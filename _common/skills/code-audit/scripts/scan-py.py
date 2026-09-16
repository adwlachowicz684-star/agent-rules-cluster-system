#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan-py.py — Python 源码缺陷模式扫描（AST 驱动）

为什么单独一个扫描器
--------------------
`scan-ts.py` / `scan-app.py` 的模式全部按 TS/JS 语法编写，
对 Python 输出 `文件: 0  候选: 0` —— **这不是「没问题」，是压根没看**。
（该陷阱已记入 `references/route.md` 末节。）

本扫描器用 `ast` 而非正则：Python 的可变默认参数、异常隔离、
资源配对这类问题，正则扫不出来。

用法
----
    python3 scan-py.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
    python3 scan-py.py --self-test        # 内置用例自检（改规则后必跑）

输出与其他扫描器同构（`id` / `level` / `file` / `line` / `snippet`），
可直接喂 `sarif.py` 与 `rule-registry.py`。

只出候选，不是结论 —— 每条都要人工过三关（读注释 / 读调用上下文 / 想清后果）。
"""
import ast
import os
import sys
import json
import argparse
import re

SRC = "."
# 测试与 fixture 样本默认排除：它们是**缺陷的示范代码**，扫进去只会污染结果
# （实测：扫本仓库时 5 条候选全部来自 rules/fixtures/*/tp.*）。
# 要连测试一起审时显式加 --include-tests。
TEST_FILE = re.compile(
    r'(?:^|/)(?:test_|.+[._](?:test|spec|fixture)|.+_test)\.[A-Za-z]+$|'
    r'(?:^|/)conftest\.py$')
INCLUDE_TESTS = False  # 由 --include-tests 打开

# --include-tests 同时放开**目录级**排除：否则开关只影响文件名匹配，
# fixtures/ 目录仍被跳过，开关看着像失灵。
TEST_SKIP_DIRS = {'fixtures', '__fixtures__', 'tests', 'test', '__tests__', 'testdata'}


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", ".mypy_cache", ".pytest_cache", "site-packages",
             "fixtures", "__fixtures__", "tests", "test"}
MAX_FILE_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------- 工具

EXCLUDES = []


def _excluded(p, root):
    """排除路径（--exclude）。

    为什么需要：fixture 的 tp.* 是**故意写成有缺陷**的，扫它们必然命中，
    属于预期噪声；生成代码、vendor 目录同理。

    抑制必须**显式写在命令行上**（可见、可审计、可复现）。
    藏在隐藏配置里的抑制等于没有抑制——没人看得见，也就没人复核。
    """
    if not EXCLUDES:
        return False
    try:
        rp = os.path.relpath(p, root).replace(os.sep, '/')
    except ValueError:
        return False
    for e in EXCLUDES:
        e = (e or '').strip().rstrip('/')
        if not e:
            continue
        if rp == e or rp.startswith(e + '/'):
            return True
    return False


def iter_py(root):
    """遍历 .py 文件。扁平结构（根下直接是 .py）也能扫。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py") and (INCLUDE_TESTS or not TEST_FILE.search(fn)):
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(p) > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if _excluded(p, root):
                    continue
                yield p


def parse(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        return ast.parse(src), src.splitlines()
    except (SyntaxError, ValueError, OSError):
        return None, []


def rel(p):
    return os.path.relpath(p, SRC)


def snip(lines, n):
    if 1 <= n <= len(lines):
        return lines[n - 1].strip()[:120]
    return ""


def node_name(n):
    """取节点的点号全名：a.b.c → 'a.b.c'"""
    parts = []
    while isinstance(n, ast.Attribute):
        parts.append(n.attr)
        n = n.value
    if isinstance(n, ast.Name):
        parts.append(n.id)
    return ".".join(reversed(parts))


def has_pragma(lines, lineno, keyword="audit"):
    """上一行或本行是否带 `# audit: ignore` 类豁免注释"""
    for i in (lineno - 2, lineno - 1):
        if 0 <= i < len(lines) and f"# {keyword}" in lines[i] and "ignore" in lines[i]:
            return True
    return False


# ---------------------------------------------------------------- 模式

MUTATING_METHODS = {"append", "extend", "insert", "pop", "remove", "clear",
                    "update", "setdefault", "add", "discard", "sort"}

RESOURCE_FACTORIES = {
    "open": "file", "io.open": "file",
    "socket.socket": "socket", "socket.create_connection": "socket",
    "threading.Lock": "lock", "threading.RLock": "lock",
    "multiprocessing.Lock": "lock",
    "subprocess.Popen": "process",
    "tarfile.open": "file", "zipfile.ZipFile": "file",
    "sqlite3.connect": "db", "psycopg2.connect": "db",
}

UNSAFE_DESERIALIZE = {"pickle.loads", "pickle.load", "cPickle.loads",
                      "marshal.loads", "yaml.load", "yaml.unsafe_load",
                      "shelve.open", "dill.loads"}

SENSITIVE_LOG_HINTS = {"password", "passwd", "pwd", "secret", "token", "api_key",
                       "apikey", "access_key", "private_key", "credential",
                       "authorization", "auth", "session_id", "ssn", "id_card",
                       "idcard", "phone", "mobile", "email", "身份证", "密码"}

SYNC_PRIMITIVES = {"threading.Lock", "threading.RLock", "multiprocessing.Lock",
                   "queue.Queue", "Queue", "threading.Semaphore",
                   "threading.Condition", "threading.Event", "asyncio.Lock",
                   "asyncio.Queue", "Lock", "RLock"}

THREAD_SPAWN = {"Thread", "threading.Thread", "multiprocessing.Process",
                "Process", "ThreadPoolExecutor", "ProcessPoolExecutor",
                "create_task", "asyncio.create_task", "ensure_future",
                "asyncio.ensure_future"}


def _walks_body(fn_node, pred, depth=0):
    """深度遍历函数体，任一节点满足 pred 即 True"""
    if depth > 12:
        return False
    for n in ast.walk(fn_node):
        if pred(n):
            return True
    return False


def py_mutable_default(tree, lines, path):
    """PY-01 (P0) 可变默认参数：def f(x=[]) / ={} 且在函数体内被修改"""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        defaults = list(n.args.defaults) + [d for d in n.args.kw_defaults if d]
        for d in defaults:
            if isinstance(d, (ast.List, ast.Dict, ast.Set, ast.ListComp)):
                if has_pragma(lines, n.lineno):
                    continue
                mutated = _walks_body(n, lambda x: isinstance(x, ast.Call)
                                      and isinstance(x.func, ast.Attribute)
                                      and x.func.attr in MUTATING_METHODS)
                level = "P0" if mutated else "P1"
                why = "函数体内有修改 → 跨调用累积" if mutated else "潜在（未检出修改，需人工确认）"
                out.append((n.lineno, f"{n.name}(): 可变默认参数（{why}）"))
                break
    return out


def py_broad_except(tree, lines, path):
    """PY-02 (P0) 宽泛异常吞没：except: / except Exception 后不 re-raise 也无隔离说明"""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        if has_pragma(lines, n.lineno):
            continue
        broad = n.type is None
        if not broad:
            t = node_name(n.type)
            broad = t in ("Exception", "BaseException", "StandardError")
        if not broad:
            continue
        body = n.body
        only_pass = len(body) == 1 and isinstance(body[0], ast.Pass)
        reraises = _walks_body(n, lambda x: isinstance(x, ast.Raise), depth=3) \
            if not isinstance(n, ast.Module) else False
        # 在 handler 子树里找 raise
        reraises = any(isinstance(x, ast.Raise) for x in ast.walk(n))
        if reraises:
            continue
        level = "P0" if only_pass else "P1"
        tag = "except: pass 完全吞没" if only_pass else "宽泛 except 未重新抛出"
        out.append((n.lineno, f"{tag}（异常静默，调用方看不到失败）"))
    return out


def py_resource_no_with(tree, lines, path):
    """PY-03 (P1) 资源未用 with：open()/socket()/Lock() 直接赋值给变量"""
    out = []
    withs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                for x in ast.walk(item.context_expr):
                    if isinstance(x, ast.Call):
                        withs.add(id(x))
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call):
            continue
        if id(n.value) in withs:
            continue
        name = node_name(n.value.func)
        if name in RESOURCE_FACTORIES and not has_pragma(lines, n.lineno):
            kind = RESOURCE_FACTORIES[name]
            out.append((n.lineno, f"{name}() 未用 with（{kind} 可能未关闭/未释放）"))
    return out


def py_thread_shared_state(tree, lines, path):
    """PY-04 (P0) 起线程/任务但全文件无同步原语 → 共享状态缺保护"""
    src_uses_sync = any(node_name(n) in SYNC_PRIMITIVES
                        for n in ast.walk(tree)
                        if isinstance(n, (ast.Attribute, ast.Name)))
    out = []
    if src_uses_sync:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            nm = node_name(n.func)
            if nm in THREAD_SPAWN and not has_pragma(lines, n.lineno):
                out.append((n.lineno, f"{nm}() 起并发，但文件内无 Lock/Queue 等同步证据"))
    return out


def py_unsafe_deserialize(tree, lines, path):
    """PY-05 (P0) 不安全反序列化：pickle.loads / yaml.load 无 SafeLoader"""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        nm = node_name(n.func)
        if nm not in UNSAFE_DESERIALIZE:
            continue
        if has_pragma(lines, n.lineno):
            continue
        safe = False
        if nm.startswith("yaml"):
            for kw in n.keywords:
                if kw.arg == "Loader" and "Safe" in node_name(kw.value):
                    safe = True
        if not safe:
            out.append((n.lineno, f"{nm}() 反序列化不可信数据 → 任意代码执行"))
    return out


def py_sensitive_log(tree, lines, path):
    """PY-06 (P0) 敏感数据进日志：log/print 调用参数名含敏感词"""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        nm = node_name(n.func)
        if not any(k in nm for k in ("log", "print", "logger", "logging",
                                     "warn", "error", "info", "debug")):
            continue
        if has_pragma(lines, n.lineno):
            continue
        names = []
        for a in n.args:
            if isinstance(a, ast.Name):
                names.append(a.id)
            elif isinstance(a, ast.Constant) and isinstance(a.value, str):
                names.append(a.value)
            elif isinstance(a, ast.JoinedStr):
                for v in a.values:
                    if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name):
                        names.append(v.value.id)
        for kw in n.keywords:
            # 关键字名本身也要查（password=pw 的敏感信息在 arg 上，不在 value 上）
            if kw.arg:
                names.append(kw.arg)
            if isinstance(kw.value, ast.Name):
                names.append(kw.value.id)
            # extra={'password': pw} —— 敏感词藏在 Dict 的 key 里
            if isinstance(kw.value, ast.Dict):
                for k in kw.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        names.append(k.value)
        # 位置参数里的字典字面量：log("x", {"token": t})
        for a in n.args:
            if isinstance(a, ast.Dict):
                for k in a.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        names.append(k.value)
        hit = [x for x in names if any(s in x.lower() for s in SENSITIVE_LOG_HINTS)]
        if hit:
            out.append((n.lineno, f"日志可能含敏感字段 {hit[:3]}（密码/token/PII 落盘即泄露）"))
    return out


def py_del_risky(tree, lines, path):
    """PY-07 (P1) __del__ 中执行锁/IO/跨线程 → 解释器退出期行为不可靠"""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "__del__":
            risky = _walks_body(n, lambda x: isinstance(x, ast.Call)
                                and node_name(x.func) in
                                {"open", "socket.socket", "requests.get",
                                 "requests.post", "threading.Lock", "acquire"})
            if risky and not has_pragma(lines, n.lineno):
                out.append((n.lineno, "__del__ 中执行 IO/加锁 —— 解释器退出期不保证执行"))
    return out


def py_mutable_global(tree, lines, path):
    """PY-08 (P1) 模块级可变全局状态 —— **且确实被修改**

    降级（实测 68 条里 67 条是误报，必须加）：
      全文件找不到对该名字的 mutate 调用 → 只读常量（EXCLUDE_DIRS / SCENE_SCRIPTS），
      无竞态也无泄漏风险，跳过。

    ⚠ 不要额外按「全大写就跳过」降级：名为常量、实际被修改的全局（CACHE[k] = v）
    恰恰最危险——名字暗示不可变，读代码的人不会加锁。判据只看「有没有被改」。
    """
    out = []
    mutated_names = set()
    for x in ast.walk(tree):
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) \
                and x.func.attr in MUTATING_METHODS and isinstance(x.func.value, ast.Name):
            mutated_names.add(x.func.value.id)
        # 就地下标/属性赋值：CACHE[k] = v
        if isinstance(x, ast.Assign):
            for t in x.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                    mutated_names.add(t.value.id)
    for n in tree.body:
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if not (isinstance(t, ast.Name) and isinstance(n.value, (ast.List, ast.Dict, ast.Set))):
                continue
            if has_pragma(lines, n.lineno):
                continue
            if t.id not in mutated_names:   # 只读常量，无风险
                continue
            out.append((n.lineno, f"模块级可变全局 {t.id} 且被修改 —— 跨调用/跨线程共享"))
    return out


def py_assert_validation(tree, lines, path):
    """PY-09 (P1) 用 assert 做运行时校验（python -O 会被移除）"""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Assert):
            continue
        if has_pragma(lines, n.lineno):
            continue
        test = ast.dump(n.test)
        risky = any(k in test for k in ("isinstance", "len(", "is not None",
                                        "is None", "in ", ">=", "<="))
        if risky:
            out.append((n.lineno, "assert 做运行时校验 —— python -O 下被移除，校验失效"))
    return out


def py_shell_true(tree, lines, path):
    """PY-10 (P0) subprocess(shell=True)：外部输入进 shell 即命令注入"""
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if node_name(n.func) not in {"subprocess.run", "subprocess.call",
                                     "subprocess.Popen", "subprocess.check_output",
                                     "os.system", "os.popen"}:
            continue
        if has_pragma(lines, n.lineno):
            continue
        if node_name(n.func) in {"os.system", "os.popen"}:
            out.append((n.lineno, f"{node_name(n.func)}() 直接走 shell —— 外部输入即命令注入"))
            continue
        for kw in n.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                out.append((n.lineno, "subprocess(shell=True) —— 外部输入可被 shell 二次解析"))
    return out


def py_bare_except_pass(tree, lines, path):
    """PY-11 (P0) 裸 except（不指定异常类型）"""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler) and n.type is None:
            if has_pragma(lines, n.lineno):
                continue
            out.append((n.lineno, "裸 except: 会吞掉 KeyboardInterrupt/SystemExit"))
    return out


# 清理 / 回滚动作的特征名：handler 体里出现这些调用，就认定这是清理代码。
# 只看名字不看上下文，是候选不是结论 —— 报出来后仍要人工判断。
_CLEANUP_CALLS = {
    "close", "unlink", "remove", "rmtree", "rollback", "cleanup",
    "delete", "restore", "release", "unlock", "abort", "teardown",
}
# 名字里含这些子串也算（如 delete_branch / _cleanup_failed_branch / rollback_tx）
_CLEANUP_SUBSTR = ("cleanup", "clean_up", "rollback", "roll_back", "delete",
                   "remove", "unlink", "restore", "release", "abort")


def _is_cleanup(body):
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if not isinstance(n, ast.Call):
            continue
        nm = node_name(n.func)
        if not nm:
            continue
        tail = nm.split(".")[-1].lower()
        if tail in _CLEANUP_CALLS:
            return True
        low = nm.lower()
        if any(s in low for s in _CLEANUP_SUBSTR):
            return True
    return False


def py_cleanup_except_exception(tree, lines, path):
    """PY-13 (P1) 清理/回滚用 except Exception —— 抓不到 KeyboardInterrupt

    KeyboardInterrupt / SystemExit 是 BaseException 子类，
    不走 except Exception。清理代码写在这里，用户 Ctrl-C 时就不执行，
    留下远端/磁盘上的孤儿（s-atomicity A-18 / A-19）。

    与 PY-11（裸 except）的区别：本条**指定了类型、看起来很规范**，
    只是类型不对。finally 里的清理在中断时也会执行，不算。
    """
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        if n.type is None:
            continue                       # 裸 except 归 PY-11，不重复报
        if node_name(n.type) != "Exception":
            continue                       # 具体类型 / BaseException → 不算
        if has_pragma(lines, n.lineno):
            continue
        if _is_cleanup(n.body):
            out.append((n.lineno,
                        "清理/回滚用 except Exception —— Ctrl-C 时不执行，"
                        "改用 except BaseException（清理后 raise）或 finally"))
    return out



def py_dead_docstring(tree, lines, path):
    """PY-18 (P2) 文档字符串不在函数体首位 → 变成无效果的死表达式

    Python 只把**函数体第一条语句**位置的字符串字面量当作 `__doc__`。
    若 `def` 之后先写了别的语句（哪怕只是一行调用），后面再写三引号字符串，
    它就只是一个被求值后丢弃的表达式：`help(f)` / `pydoc` / Sphinx autodoc
    全部拿不到，而代码读起来"明明写了文档"。

    与 C-01（死代码）的分界：C-01 是"定义了没人引用"；
    本条是"写在了正确的地方之外"，语法合法、linter 多数不报。
    """
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(n, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(getattr(first, "value", None), ast.Constant)
                and isinstance(first.value.value, str)):
            continue                                  # 正常 docstring
        for st in body:
            if (isinstance(st, ast.Expr)
                    and isinstance(getattr(st, "value", None), ast.Constant)
                    and isinstance(st.value.value, str)):
                if has_pragma(lines, st.lineno):
                    break
                out.append((st.lineno,
                            f"{n.name}() 的文档字符串不在函数体首位 —— "
                            f"只是被求值后丢弃的死表达式，help()/pydoc 取不到；"
                            f"把它移到 def 之后的第一行"))
                break
    return out


def py_naive_datetime(tree, lines, path):
    """PY-12 (P2) 无时区的 datetime.now() —— 跨时区/跨机器比较出错"""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            nm = node_name(n.func)
            if nm in {"datetime.now", "datetime.utcnow", "datetime.fromtimestamp"}:
                if has_pragma(lines, n.lineno):
                    continue
                has_tz = any(kw.arg in ("tz", "tzinfo") for kw in n.keywords)
                if not has_tz:
                    out.append((n.lineno, f"{nm}() 无 tz —— 跨时区比较/存储易错"))
    return out


PATTERNS = [
    ("PY-01", "P0", "可变默认参数（跨调用累积）", py_mutable_default),
    ("PY-02", "P0", "宽泛异常吞没（未重新抛出）", py_broad_except),
    ("PY-03", "P1", "资源未用 with（可能未释放）", py_resource_no_with),
    ("PY-04", "P0", "并发无同步证据（共享状态缺保护）", py_thread_shared_state),
    ("PY-05", "P0", "不安全反序列化（任意代码执行）", py_unsafe_deserialize),
    ("PY-06", "P0", "敏感数据进日志", py_sensitive_log),
    ("PY-07", "P1", "__del__ 中执行 IO/加锁", py_del_risky),
    ("PY-08", "P1", "模块级可变全局状态", py_mutable_global),
    ("PY-09", "P1", "assert 做运行时校验（-O 下失效）", py_assert_validation),
    ("PY-10", "P0", "subprocess shell=True / os.system（命令注入）", py_shell_true),
    ("PY-11", "P0", "裸 except（吞掉 KeyboardInterrupt）", py_bare_except_pass),
    ("PY-12", "P2", "naive datetime（无时区）", py_naive_datetime),
    ("PY-13", "P1", "清理/回滚用 except Exception（Ctrl-C 时不执行）",
     py_cleanup_except_exception),
    ("PY-18", "P2", "文档字符串不在函数体首位（变成死表达式）",
     py_dead_docstring),
]

SCENE = {
    "PY-01": "p-python", "PY-02": "p-python", "PY-03": "p-python",
    "PY-04": "s-concurrency", "PY-05": "s-backend", "PY-06": "s-sandbox",
    "PY-07": "s-concurrency", "PY-08": "p-python", "PY-09": "p-python",
    "PY-10": "s-backend", "PY-11": "p-python", "PY-12": "p-python",
    "PY-13": "s-atomicity",
    "PY-18": "p-python",
}


# ---------------------------------------------------------------- 扫描

def scan(src):
    rows = []
    for p in iter_py(src):
        tree, lines = parse(p)
        if tree is None:
            continue
        for rid, level, name, fn in PATTERNS:
            try:
                hits = fn(tree, lines, p)
            except Exception as e:      # 单条规则异常不能拖垮整体
                print(f"[warn] {rid} 在 {rel(p)} 异常: {e}", file=sys.stderr)
                continue
            for lineno, msg in hits:
                rows.append({"id": rid, "level": level, "name": name,
                             "file": rel(p), "line": lineno,
                             "snippet": snip(lines, lineno),
                             "detail": msg, "scanner": "scan-py.py",
                             "scene": SCENE.get(rid, "")})
    return rows


# ---------------------------------------------------------------- 自检
# 每条规则至少一组 TP（必须命中）。改规则后必跑：
# 永远 0 命中的检查等于没有检查。

SELF_TEST_CASES = [
    ("PY-01", "def f(x=[]):\n    x.append(1)\n    return x\n", True),
    ("PY-02", "try:\n    a()\nexcept Exception:\n    pass\n", True),
    ("PY-03", "f = open('a.txt')\ndata = f.read()\n", True),
    ("PY-04", "import threading\nt = threading.Thread(target=work)\nt.start()\n", True),
    ("PY-05", "import pickle\nd = pickle.loads(raw)\n", True),
    ("PY-06", "logger.info('login', password=pw)\n", True),
    ("PY-07", "class A:\n    def __del__(self):\n        open('/tmp/x','w').write('a')\n", True),
    ("PY-08", "CACHE = {}\ndef add(k, v):\n    CACHE[k] = v\n", True),
    ("PY-09", "assert isinstance(x, int)\n", True),
    ("PY-10", "import subprocess\nsubprocess.run(cmd, shell=True)\n", True),
    ("PY-11", "try:\n    a()\nexcept:\n    pass\n", True),
    ("PY-12", "from datetime import datetime\nn = datetime.now()\n", True),
    ("PY-13", "try:\n    commit()\nexcept Exception:\n    cleanup()\n    raise\n", True),
    # cleanup 藏在自定义函数名里也要算（实测的正是这种形态）
    ("PY-13", "try:\n    commit()\nexcept Exception:\n"
              "    _cleanup_failed_branch(b)\n    raise\n", True),
    # 反向：不该命中的
    ("PY-01", "def f(x=None):\n    x = x or []\n    return x\n", False),
    ("PY-05", "import yaml\nd = yaml.load(f, Loader=yaml.SafeLoader)\n", False),
    ("PY-10", "import subprocess\nsubprocess.run(['ls','-l'])\n", False),
    ("PY-03", "with open('a.txt') as f:\n    data = f.read()\n", False),
    ("PY-02", "try:\n    a()\nexcept ValueError:\n    handle()\n", False),
    ("PY-12", "from datetime import datetime, timezone\nn = datetime.now(tz=timezone.utc)\n", False),
    ("PY-08", "EXCLUDE_DIRS = ['a', 'b']\n", False),          # 常量约定
    ("PY-08", "LOOKUP = {'a': 1}\ndef get(k):\n    return LOOKUP.get(k)\n", False),  # 只读
    ("PY-13", "try:\n    commit()\nfinally:\n    cleanup()\n", False),      # finally 不算
    ("PY-13", "try:\n    commit()\nexcept BaseException:\n    cleanup()\n"
              "    raise\n", False),                          # BaseException 正确
    ("PY-13", "try:\n    commit()\nexcept TimeoutError:\n    cleanup()\n", False),  # 具体类型
    ("PY-13", "try:\n    commit()\nexcept Exception:\n"
              "    logger.error(e)\n", False),                # 只记日志不是清理
    # PY-18：文档字符串写在了第一条语句之后
    ("PY-18", "def prune(state):\n    _report()\n    \"\"\"只报告，不删除。\"\"\"\n", True),
    ("PY-18", "def load(s):\n    \"\"\"读基线。\"\"\"\n    return s\n", False),   # 正常位置
    ("PY-18", "def f(x):\n    return x + 1\n", False),                      # 没有文档字符串
]


def self_test():
    global SRC
    import tempfile
    ok = fail = 0
    tmp = tempfile.mkdtemp()
    SRC = tmp          # rel() 依赖全局 SRC；不设会得到相对 cwd 的路径，导致全部判为不命中
    for i, (rid, code, want_hit) in enumerate(SELF_TEST_CASES):
        f = os.path.join(tmp, f"t{i}.py")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(code)
        rows = scan(tmp)
        got = any(r["id"] == rid and r["file"] == f"t{i}.py" for r in rows)
        mark = "✓" if got == want_hit else "✗"
        if got == want_hit:
            ok += 1
        else:
            fail += 1
        exp = "命中" if want_hit else "不命中"
        got_s = "命中" if got else "不命中"
        print(f"  {mark} {rid} 期望{exp} 实际{got_s}")
    print()
    print(f"自检：{ok} 通过 / {fail} 失败（共 {len(SELF_TEST_CASES)} 组）")
    if fail == 0:
        print("结论：全部模式按预期工作")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=".")
    ap.add_argument("--p0", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--include-tests", action="store_true",
                    help="连测试与 fixture 样本一起扫（默认排除）")
    ap.add_argument("--sarif", default="")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--pattern", default="", help="只跑某条规则（rule-registry --test 用）")
    ap.add_argument("--exclude", action="append", default=[],
                    help="排除路径（可重复/逗号分隔），跳过 fixtures 与生成代码")
    args = ap.parse_args()

    global INCLUDE_TESTS
    INCLUDE_TESTS = args.include_tests
    if INCLUDE_TESTS:
        global SKIP_DIRS
        SKIP_DIRS = SKIP_DIRS - TEST_SKIP_DIRS

    if args.self_test:
        sys.exit(self_test())

    global SRC, EXCLUDES
    SRC = os.path.abspath(args.src)
    EXCLUDES = [x.strip() for a in (args.exclude or []) for x in a.split(",") if x.strip()]
    rows = scan(SRC)
    if args.pattern:
        rows = [r for r in rows if r["id"] == args.pattern]
    if args.p0:
        rows = [r for r in rows if r["level"] == "P0"]

    if args.sarif:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from sarif import build_sarif
            doc = build_sarif(rows, tool_name="scan-py.py", root=SRC)
            with open(args.sarif, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
            print(f"SARIF → {args.sarif}（{len(rows)} 条）")
        except Exception as e:
            print(f"sarif 导出失败: {e}", file=sys.stderr)
        return

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print("scan-py · Python 缺陷模式扫描")
    print(f"源码根: {SRC}   Python 文件: {sum(1 for _ in iter_py(SRC))}   命中候选: {len(rows)}")
    if EXCLUDES:
        print("排除路径: " + ", ".join(EXCLUDES) + "（抑制已显式声明，可审计）")
    print()
    if not rows:
        print("（无命中）")
        return
    by = {}
    for r in rows:
        by.setdefault(r["id"], []).append(r)
    for rid, level, name, _ in PATTERNS:
        if rid in by:
            print(f"  {rid} ({level}) {name}  ×{len(by[rid])}")
            for r in by[rid][:5]:
                print(f"      {r['file']}:{r['line']}  {r['detail']}")
            if len(by[rid]) > 5:
                print(f"      … 其余 {len(by[rid]) - 5} 条")
    print("\n候选 ≠ 结论：每条都要人工确认（读注释 / 读调用上下文 / 想清后果）。")


if __name__ == "__main__":
    main()
