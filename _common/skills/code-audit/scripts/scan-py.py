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
        # 有可见输出的降级不算「吞没」。
        #
        # 为什么必须区分：本规则原先只要「宽泛 except 且没 re-raise」就报，
        # 于是 `except Exception as e: print(警告); return []` 这种**有提示的
        # 降级**也被报成 P1，文案还写「异常静默，调用方看不到失败」——
        # 与事实相反。实测扫本技能自己的 scripts/：29 条命中里 24 条是这种
        # 有 print / 有告警收集 的降级，只有 5 条是真静默。
        # 报 29 条里 24 条是狼来了，工具就会被忽略。
        if _reports_error(n):
            continue
        level = "P0" if only_pass else "P1"
        tag = "except: pass 完全吞没" if only_pass else "宽泛 except 未重新抛出"
        out.append((n.lineno, f"{tag}（异常静默，调用方看不到失败）"))
    return out


def _reports_error(handler):
    """except 体里有没有把错误**暴露出去**。

    三条通道，任一成立即视为「没有吞没」：
      ① 打印 / 记日志：print / stderr.write / logging.warning ...
      ② 收集进告警列表：warns.append(str(e))
      ③ **把异常信息返回给调用方**：return 3, str(e) / return False, None, '异常：%s' % e

    ③ 为什么必须算：本规则第一版只认 ①，于是
    `return 3, '', str(e)`（错误码 + 错误信息都交给了调用方）被报成
    「异常静默，调用方看不到失败」—— 与事实完全相反。实测扫 scripts/
    又多出 3 条这类误报（audit / rule-registry / cocos-godot 的读取失败告警）。

    只看「有没有」，不看「做得好不好」—— 后者是人工精审的事。
    """
    # 捕获到的异常变量名（except Exception as e → 'e'）
    ename = handler.name if isinstance(handler.name, str) else None

    for node in ast.walk(handler):
        # ① 打印 / 记日志
        if isinstance(node, ast.Call):
            fname = node_name(node.func) or ''
            if any(k in fname for k in ('print', 'write', 'warning', 'warn',
                                        'error', 'exception', 'debug', 'info',
                                        'log', 'add', 'append', 'collect',
                                        'report')):
                return True
        # ② 收集进告警列表
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ('append', 'add', 'error', 'warning')):
            return True
        # ③ 把异常信息返回给调用方
        if isinstance(node, ast.Return) and node.value is not None:
            if ename:
                used = {n.id for n in ast.walk(node.value)
                        if isinstance(n, ast.Name)}
                if ename in used:
                    return True
            # 返回字面量里带「失败/异常/错误」等字样也算（如 return [{"rule": "读取失败"...}]）
            for n in ast.walk(node.value):
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    if any(k in n.value for k in ('失败', '异常', '错误', 'error',
                                                  'fail', 'invalid')):
                        return True
    return False


def _in_function_scope(tree, node):
    """该赋值语句是否在函数/方法体内（True=局部变量，False=模块级/类级）。"""
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(parent):
                if child is node:
                    return True
    return False



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
            # 锁是特例：模块级 / 类级的**共享锁**生命周期与宿主同长，
            # 本来就不该用 with（用了反而每次都新建一把，失去互斥意义）。
            # 只有函数内临时创建的锁才可能是「忘了释放」。
            # 不区分的话，`lock = threading.Lock()` 这种最标准的写法会被一律误报。
            if kind == 'lock' and not _in_function_scope(tree, n):
                continue
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



def py_path_codec_asym(tree, lines, path):
    """PY-19 (P1) 非 subprocess 出口的路径编解码不对称

    与 PY-15 的分界：PY-15 判的是 `subprocess.run(input=...)` 的 `errors=`，
    本条不涉及 subprocess —— 是 os.readlink / 落盘往返上的编解码方向。

    - 编码侧：`.encode()` 未带 `surrogateescape` → 含非法字节的路径直接
      UnicodeEncodeError 崩溃（POSIX 文件名允许除 `/` 和 NUL 外的任意字节）
    - 解码侧：`.decode(..., "replace")` → 非法字节被永久换成 U+FFFD，
      再写回去就**不是同一个文件**了，且这个损坏不可逆
    """
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        nm = node_name(n.func)
        if nm not in {"encode", "decode"}:
            continue
        if has_pragma(lines, n.lineno):
            continue
        # 只判路径类表达式，避免把普通字符串编解码全报一遍（会变噪音源）
        # 被编解码的对象要"像路径"：os.readlink(p) 是 Call，node_name 取不到
        # 名字（返回空串），所以改用源码文本判断。
        owner = ""
        f = n.func
        if isinstance(f, ast.Attribute):
            try:
                owner = ast.unparse(f.value).lower()
            # audit: ignore —— 反解析失败退回 node_name()，是降精度不是吞异常
            except Exception:
                owner = (node_name(f.value) or "").lower()
        if not any(k in owner for k in ("readlink", "path", "name", "target", "entry")):
            continue
        if nm == "encode":
            # errors 既可能是关键字参数，也可能是第 2 个位置参数
            # （`.encode("utf-8", "surrogateescape")`）—— 只看 keyword
            # 会把正确写法判成缺 errors，正是本条要避免的误报方向。
            has_esc = any(
                kw.arg == "errors" and isinstance(kw.value, ast.Constant)
                and "surrogateescape" in str(kw.value.value)
                for kw in n.keywords)
            has_esc = has_esc or any(
                isinstance(a, ast.Constant) and isinstance(a.value, str)
                and "surrogateescape" in a.value for a in n.args)
            if not has_esc:
                out.append((n.lineno,
                            "路径类字符串 .encode() 未带 errors='surrogateescape'"
                            " —— 含非法字节的文件名会 UnicodeEncodeError 崩溃"))
        else:
            bad = any(isinstance(a, ast.Constant) and str(a.value) == "replace"
                      for a in n.args)
            bad = bad or any(
                kw.arg == "errors" and isinstance(kw.value, ast.Constant)
                and str(kw.value.value) == "replace" for kw in n.keywords)
            if bad:
                out.append((n.lineno,
                            "路径类字符串 .decode(..., 'replace') —— 非法字节被永久"
                            "换成 U+FFFD，写回后指向的不是同一个文件（不可逆）"))
    return out


def py_path_list_newline_join(tree, lines, path):
    """K-43 (P2) 路径列表用换行符拼接后跨进程传递

    POSIX 文件名只排除 `/` 和 NUL —— **允许含换行**。用 `"\n".join(paths)`
    喂 `--stdin-paths` / 管道，含换行的路径会被拆成两条，条目数对不上。

    只在「同文件别处已用 NUL 分隔」时报：那说明作者知道这个坑，此处是漏网
    （判据原文的确认手法就是两种写法做差集）。否则批量拼接未必是路径列表，
    报了就是噪音。
    """
    src = "\n".join(lines)
    if not re.search(r'-z\b|--pathspec-file-nul|--null|-print0', src):
        return []
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or node_name(n.func) != "join":
            continue
        sep = None
        if n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str):
            sep, joined = n.args[0].value, n.args[1] if len(n.args) > 1 else None
        elif isinstance(n.func, ast.Attribute) \
                and isinstance(n.func.value, ast.Constant) \
                and isinstance(n.func.value.value, str):
            # `"\n".join(paths)` —— 分隔符在 func.value，不是 args[0]
            sep, joined = n.func.value.value, n.args[0] if n.args else None
        if sep not in ("\n", "\r\n") or joined is None:
            continue
        nm = (node_name(joined) or "").lower()
        if not any(k in nm for k in ("path", "rel", "file", "name", "sha", "entry")):
            continue
        if has_pragma(lines, n.lineno):
            continue
        out.append((n.lineno,
                    "路径列表用 %r 拼接后跨进程传递 —— 同文件别处已用 NUL 分隔"
                    "（-z/--pathspec-file-nul），此处是漏网；含换行的路径会被拆成"
                    "两条" % sep))
    return out



# 必须**整体**是测试数据表的名字。不能裸 search「test」：
# `latest` 里就含 t-e-s-t，裸匹配会把普通变量当数据表排除掉。
# 用 ^ / _ 锚定词首，SELF_TEST_CASES 这类才能命中而 latest 不会。
_TESTDATA_NAME_RX = re.compile(
    r'(?i)^(?:self[-_]?test|test[-_]?(?:cases?|data|s?)|fixtures?|samples?)'
    r'|(?:^|_)(?:tests?|cases?|fixtures?|samples?)$')


def _non_code_lines(lines, tree):
    """返回「不该被行扫描规则当真代码」的行号集合（1-based）。

    两类：
      · 注释行 —— 用 tokenize 判（引号里的 # 不算注释）
      · docstring 行 —— 用 AST 取每个函数/类/模块的文档字符串范围

    为什么需要：scan-py 的两条行扫描规则（K-44 / AR-05）原先直接扫原文，
    于是**描述规则的文字本身会被自己的规则命中**：
      · K-44 扫到 K-44 注释里的 `user.name=xxx` 示例
      · AR-05 扫到 AR-05 文档字符串里的 `ALL PASS` / `mod.X = ...` 说明
    实测（scan-py 扫自己的 scripts/）：注释化测试显示 116 组 TP 里
    有 2 条规则在代码被整段注释后仍命中，就是这两条。

    AST 驱动的规则天然不受影响（注释进不了 AST），只有行扫描的这两条要过滤。
    """
    bad = set()
    import io as _io
    import tokenize as _tk
    src = '\n'.join(lines)
    code = set()
    try:
        for tok in _tk.generate_tokens(_io.StringIO(src).readline):
            if tok.type in (_tk.COMMENT, _tk.NL, _tk.NEWLINE, _tk.INDENT,
                            _tk.DEDENT, _tk.ENCODING, _tk.ENDMARKER):
                continue
            if not tok.string.strip():
                continue
            for ln in range(tok.start[0], tok.end[0] + 1):
                code.add(ln)
        bad |= {i for i in range(1, len(lines) + 1) if i not in code}
    except (_tk.TokenError, IndentationError, SyntaxError):
        pass                      # 解析失败就不过滤，宁可多报也不静默漏

    try:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            body = getattr(node, 'body', None)
            if not body:
                continue
            first = body[0]
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                for ln in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                    bad.add(ln)
    # audit: ignore —— 解析失败就不过滤（宁可多报也不静默漏），理由见函数文档
    except Exception:
        pass

    # ③ 内嵌测试数据表：SELF_TEST / TEST_CASES / FIXTURES 这类常量里
    #    存的是**被检样本的内容**，不是执行路径上的代码。
    #    不排除的话规则会扫到自己定义的样本 —— 实测 AR-05 扫 scan-py.py
    #    时命中 `("AR-05", "mod.ROOT='/tmp/x'...print('ALL PASS')", True)`
    #    那一行：样本内容被当成真实输出；K-44 同理会命中样本里的 user.name。
    #    自检时样本是单独喂给规则的（不在表范围内），排除表本身不影响自检。
    try:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if not isinstance(t, ast.Name):
                    continue
                if not _TESTDATA_NAME_RX.search(t.id):
                    continue
                end = getattr(node, 'end_lineno', None) or node.lineno
                for ln in range(node.lineno, end + 1):
                    bad.add(ln)
    # audit: ignore —— 测试数据表识别失败就不过滤，宁可多报也不静默漏（同上）
    except Exception:
        pass
    return bad


def py_git_hardcoded_identity(tree, lines, path):
    """K-44 (P2) 工具代用户做提交 / 签名时硬编码自身身份

    `git -c user.name=... -c user.email=...` / `--author=` / `GIT_AUTHOR_*`
    的值是工具作者自己的身份 → 会写进用户仓库的历史与贡献归属；
    出问题时 `git blame` 指向工具作者而不是使用者。

    只报**硬编码字面量**：从 `git config` / 环境变量读出来的不算。
    """
    out = []
    # 命令行常写成 `["git", "-c", "user.name=xxx"]` —— -c 与 user.name 之间
    # 隔着 `", "`，不能用 `-c\s*user\.` 直接连。
    pat = re.compile(
        r'user\.(?:name|email)\s*["\']?\s*[=:]\s*["\']?'
        r'([A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+|[A-Za-z][A-Za-z0-9 _.-]{1,40})')
    ctx = re.compile(r'--author|GIT_AUTHOR_(?:NAME|EMAIL)|["\']-c["\']')
    skip = _non_code_lines(lines, tree)
    for i, l in enumerate(lines, 1):
        if i in skip or has_pragma(lines, i):
            continue
        low = l[:max(0, l.lower().find('user.'))]
        if re.search(r'\b(?:config|getenv|environ|\.get\(|argv|argparse|input\()', low):
            continue
        if not ctx.search(l):
            continue
        m = pat.search(l)
        if not m:
            continue
        val = m.group(1).strip()
        if val.startswith(("{", "$", "%", "<")) or val.lower() in {
                "none", "self", "user", "name", "email", "true", "false",
                "default", "value", "identity"}:
            continue
        tail = l[m.end():m.end() + 3]
        if not re.match(r'["\']?\s*[,)\]]|["\']\s*$|["\']\s*,', tail):
            continue
        out.append((i, "硬编码了提交者身份 %r —— 会写进用户仓库历史与贡献归属；"
                       "应优先读已有 git config，回退时才用默认值并告知用户" % val))
    return out
# ---------------------------------------------------------------- 架构可演进性
# 这四条判的不是「运行时行为对不对」，而是「下一次改动会不会出错」。
# 完整判据见 references/s-architecture.md（AR-01 ~ AR-05）。

_JUDGE_NAME_RX = re.compile(
    r'^(?:check|validate|verify|ensure|guard|is|can|should)_?', re.I)

# 换成 pytest / unittest 之后不该再命中
_TEST_FRAMEWORK_RX = re.compile(r'^\s*(?:import|from)\s+(?:pytest|unittest)\b', re.M)

_CLI_FILES = {'cli.py', 'main.py', '__main__.py', 'run_all.py'}

# 状态类常量：命中即说明「状态存在哪」是写死的
_STATE_CONST_NAMES = {'STATE_PATH', 'STATE_FILE', 'DB_PATH', 'CACHE_PATH'}
# 目标类常量：命中即说明「操作谁」是写死的
_TARGET_CONST_NAMES = {'OWNER', 'REPO', 'ROOT', 'BASE_DIR', 'WORKDIR'}


def _assigned_names(node):
    """展开 `A, B = 1, 2` 这类元组赋值，返回被赋值的名字集合。"""
    names = set()
    stack = list(node.targets)
    while stack:
        t = stack.pop()
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            stack.extend(t.elts)
    return names


_SELFTEST_NAME_RX = re.compile(
    r'(?:^|_)(?:self[-_]?test|run[-_]?tests?|run[-_]?checks?|_selftest)$'
    r'|^self_test$|^_self_test$')


def ar_judge_output_coupled(tree, lines, path):
    """AR-01 (P1) 判定逻辑与输出 / 副作用耦合

    两条独立信号，命中任一即报：
      · 非 CLI 层直接 `raise SystemExit` —— 判定结论无法结构化复用
      · `check*` / `validate*` / `is*` 这类**判定函数内部直接 print** —— 输出焊在实现上

    降级：CLI 入口文件（cli.py / main.py）本来就该终止进程与打印，跳过。
    """
    if os.path.basename(path) in _CLI_FILES:
        return []
    # 入口 / 自检函数本来就该终止进程与打印，不算耦合。
    #
    # 两处修正（实测扫 scripts/ 的 6 条命中全部落在这些范围里，无一真问题）：
    #   ① 不只查 tree.body —— `main` 可能在类里或嵌套；自检里常定义
    #      内层 `def check(cond, msg)`，按顶层查不到，于是 self_test 的
    #      逐条输出被当成「判定函数内部 print」
    #   ② 范围用**行号区间**而不是只看直接父函数 —— 自检函数内部嵌套的
    #      check / report 都该跟着豁免
    _entry_names = {'main', 'cli', 'cli_main', 'run', 'cmd_main'}
    entry_ranges = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.FunctionDef):
            continue
        if n.name in _entry_names or _SELFTEST_NAME_RX.search(n.name):
            entry_ranges.append((n.lineno, n.end_lineno or n.lineno))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) \
                and getattr(n.exc.func, 'id', None) == 'SystemExit':
            if any(a <= n.lineno <= b for a, b in entry_ranges):
                continue
            if has_pragma(lines, n.lineno):
                continue
            out.append((n.lineno,
                        '非 CLI 层 raise SystemExit —— 判定结论无法结构化复用'
                        '（改一处文案就要改测试，见 s-architecture AR-01）'))
            break
    for n in ast.walk(tree):
        if not isinstance(n, ast.FunctionDef):
            continue
        # 信号 B（不依赖命名）：函数既 `return True/False` 又 print ——
        # 它显然在「判定」，却把结论同时写进了 stdout。
        # 只靠 check*/validate* 这类名字白名单会漏掉全部自定义命名的判定函数
        # （实测同类教训：TS-O02 白名单内 5/5 命中、白名单外 0/8）。
        returns_bool = any(
            isinstance(x, ast.Return) and isinstance(x.value, ast.Constant)
            and isinstance(x.value.value, bool) for x in ast.walk(n))
        named_judge = bool(_JUDGE_NAME_RX.match(n.name))
        if not (named_judge or returns_bool):
            continue
        # 自检函数（self_test / run_tests …）本来就该「既判定又展示」：
        # 它 return 的是通过与否（给退出码用），print 的是逐条结果（给人看）。
        # 强行拆开只会让它更难读，且没有任何调用方需要它的返回值当库用。
        # 实测扫 scripts/：6 条命中里 4 条是 self_test 的进度输出。
        if _SELFTEST_NAME_RX.search(n.name):
            continue
        for x in ast.walk(n):
            if isinstance(x, ast.Call) and getattr(x.func, 'id', None) == 'print':
                if any(a <= x.lineno <= b for a, b in entry_ranges):
                    continue
                if has_pragma(lines, x.lineno):
                    continue
                out.append((x.lineno,
                            f'判定函数 {n.name}() 内部直接 print —— '
                            '判定与输出耦合，无法 --json / 无法当库调用（AR-01）'))
                break
    return out


def ar_cross_instance_state(tree, lines, path):
    """AR-03 (P1) 跨实例 / 跨仓库状态串档

    两条信号：
      · 状态类常量是**仓库外的绝对路径** → 多实例共用同一份
      · 目标类常量（OWNER / REPO / ROOT）硬编码 → 换目标只能改源码

    降级：值是 `os.path.join(...)` 等表达式时不报（说明已参数化，不是写死的）。
    """
    out = []
    for n in tree.body:
        if not isinstance(n, ast.Assign):
            continue
        names = _assigned_names(n)
        # `A, B = 'x', 'y'` 时 n.value 是 Tuple：按位置取值，取不到就跳过
        vals = n.value.elts if isinstance(n.value, ast.Tuple) else None
        for nm in sorted(names):
            if vals is not None:
                v = vals[0] if len(vals) == 1 else None
                if v is None:
                    continue
            else:
                v = n.value
            if not (isinstance(v, ast.Constant) and isinstance(v.value, str)):
                continue
            if nm in _STATE_CONST_NAMES and v.value.startswith('/'):
                out.append((n.lineno,
                            f'状态路径 {nm} 是仓库外的绝对路径 '
                            f'{v.value!r} —— 多实例共用会串档（AR-03）'))
            elif nm in _TARGET_CONST_NAMES:
                out.append((n.lineno,
                            f'操作目标 {nm} 硬编码为模块级常量 '
                            f'{v.value!r} —— 换目标只能改源码（AR-03）'))
    return out


def ar_exit_code_flat(tree, lines, path):
    """AR-04 (P2) 退出码不分类（生产者侧）

    判据：退出点 ≥3 个，而用到的**数字**退出码不超过 1 种 ——
    说明「被防护拦下」与「真出错」在自动化眼里是一样的。

    降级：退出点 <3 个不报（小工具没必要分码）。
    """
    exits, codes = [], set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) \
                and getattr(n.exc.func, 'id', None) == 'SystemExit':
            exits.append(n.lineno)
            a = n.exc.args
            if a and isinstance(a[0], ast.Constant) and isinstance(a[0].value, int):
                codes.add(a[0].value)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == 'exit' \
                and getattr(n.func.value, 'id', None) == 'sys':
            exits.append(n.lineno)
            if n.args and isinstance(n.args[0], ast.Constant) \
                    and isinstance(n.args[0].value, int):
                codes.add(n.args[0].value)
    if len(exits) >= 3 and len(codes) <= 1:
        return [(exits[0],
                 f'{len(exits)} 个退出点只用了 {len(codes) or 0} 种数字退出码 —— '
                 'CI 无法区分「被拦下」与「出错」（见 s-architecture AR-04）')]
    return []



def _harness_text(line, lines=None, lineno=0):
    """把一行里「不会进 stdout 的字符串字面量」剔除，返回剩余文本。

    为什么需要：AR-05 原先按**整行原文**匹配 `ALL PASS` / `mod.X =`，
    于是把「描述这条规则的文字」也当成了被审代码。实测扫 scripts/：
    6 条命中里 5 条是这种自指 ——
      · rule-registry.py 规则说明文本里的「ALL PASS / mod.X= 打补丁」
      · scan-py.py 自己 append 告警文案里的「用 mod.X = ...」
      · scan-py.py 的 fixture 定义 ("AR-05", "mod.ROOT = '/tmp/x'...", True)
      · mutate.py 的 PASS_MARKS 常量表、route.py 的检测规则表

    与「注释」同类：注释已在 _non_code_lines 里剔除，字符串字面量是
    第二条漏网路径。区别在于——**print 的参数确实会进 stdout**，
    那正是本条规则要抓的，必须保留。

    做法：tokenize 后只保留 ①非字符串 token ②print( 括号内的字符串。
    多行 print 的续行：往上找 3 行内有未闭合的 print( 也算输出。
    """
    import io as _io
    import tokenize as _tk
    try:
        toks = list(_tk.generate_tokens(_io.StringIO(line).readline))
    except (_tk.TokenError, SyntaxError, IndentationError):
        # 单行 tokenize 遇到**跨行字符串**必然抛 TokenError ——
        # 字符串在下一行才闭合。此时原样返回会把文案当输出：
        # 实测 AR-05 仍命中自己 out.append 里跨两行的告警文案。
        # 这种行的引号内容一律是文案，直接剔除。
        return re.sub(r'''"[^"]*"|'[^']*''', ' ', line)

    cont = False
    if lines and lineno:
        for k in range(max(0, lineno - 4), lineno - 1):
            prev = lines[k] if k < len(lines) else ''
            if 'print(' in prev and prev.count('(') > prev.count(')'):
                cont = True
                break

    out = []
    pending = None
    stack = []
    for t in toks:
        if t.type == _tk.NAME:
            pending = t.string
        elif t.type == _tk.OP and t.string == '(':
            stack.append('print' if pending == 'print' else 'other')
            pending = None
        elif t.type == _tk.OP and t.string == ')':
            if stack:
                stack.pop()
            pending = None
        elif t.type == _tk.STRING:
            if 'print' in stack or cont:
                out.append(t.string)
            continue
        if t.type not in (_tk.COMMENT, _tk.NL, _tk.NEWLINE, _tk.INDENT,
                          _tk.DEDENT, _tk.ENCODING, _tk.ENDMARKER):
            out.append(t.string)
    return ' '.join(out)



def ar_test_harness_welded(tree, lines, path):
    """AR-05 (P1) 测试自建 harness，断言焊在实现与输出上

    两条信号（都要「没用测试框架」这个前提）：
      · stdout 里出现 `ALL PASS` 这类自建通过标记 → 断言焊在输出上
      · `mod.X = ...` 打补丁替换模块级全局 → 断言焊在实现上

    降级：文件里有 `import pytest` / `import unittest` 时不报（已用框架）。
    """
    src = '\n'.join(lines)
    if _TEST_FRAMEWORK_RX.search(src):
        return []
    skip = _non_code_lines(lines, tree)
    out = []
    for i, line in enumerate(lines, 1):
        if i in skip:
            continue
        # 只匹配「会进 stdout 的部分」：规则说明、样本定义、检测目标这些
        # 字符串字面量不算（见 _harness_text）
        text = _harness_text(line, lines, i)
        if 'ALL PASS' in text:
            out.append((i, '以 stdout 里的 ALL PASS 判定通过 —— '
                           '改一句提示文案测试就红（AR-05）'))
        elif re.search(r'\b(?:mod|m|module)\.[A-Z]\w*\s*=', text):
            out.append((i, '用 mod.X = ... 打补丁替换模块级全局 —— '
                           '重构动一处全局就要全量改测试（AR-05）'))
    return out[:3]


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
    ("PY-19", "P1", "路径编解码不对称（非 subprocess 出口）",
     py_path_codec_asym),
    ("K-43", "P2", "路径列表用换行拼接后跨进程传递（同文件别处已用 NUL 分隔）",
     py_path_list_newline_join),
    ("K-44", "P2", "工具代用户提交时硬编码自身身份",
     py_git_hardcoded_identity),
    # ---- 架构可演进性（s-architecture）----
    ("AR-01", "P1", "判定与输出 / 副作用耦合（改不动）", ar_judge_output_coupled),
    ("AR-03", "P1", "跨实例 / 跨仓库状态串档（改不动）", ar_cross_instance_state),
    ("AR-04", "P2", "退出码不分类，自动化无法分流", ar_exit_code_flat),
    ("AR-05", "P1", "测试 harness 焊死实现与输出（债务放大器）",
     ar_test_harness_welded),
]

SCENE = {
    "PY-01": "p-python", "PY-02": "p-python", "PY-03": "p-python",
    "PY-04": "s-concurrency", "PY-05": "s-backend", "PY-06": "s-sandbox",
    "PY-07": "s-concurrency", "PY-08": "p-python", "PY-09": "p-python",
    "PY-10": "s-backend", "PY-11": "p-python", "PY-12": "p-python",
    "PY-13": "s-atomicity",
    "PY-18": "p-python",
    "PY-19": "p-python",
    "K-43": "s-backend",
    "K-44": "s-backend",
    # 架构可演进性：判据在 references/s-architecture.md
    "AR-01": "s-architecture",
    "AR-03": "s-architecture",
    "AR-04": "s-architecture",
    "AR-05": "s-architecture",
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
    # ---- 架构可演进性（AR）----
    ("AR-01", "def validate_state(s):\n    if not s:\n"
              "        raise SystemExit('bad')\n    print('ok')\n"
              "    return True\n", True),
    ("AR-01", "def validate_state(s):\n    return bool(s)\n", False),       # 纯返回，无耦合
    ("AR-01", "def main():\n    raise SystemExit(0)\n", False),            # CLI 入口允许
    # 白名单外命名：audit_repo_state 不在 check*/validate* 里，靠 return bool 命中
    ("AR-01", "def audit_repo_state(s):\n    print('checking')\n"
              "    return True\n", True),
    ("AR-01", "def audit_repo_state(s):\n    return bool(s)\n", False),
    ("AR-03", "STATE_PATH = '/data/workspace/.push-sync.json'\n"
              "OWNER, REPO = 'a', 'b'\n", True),
    ("AR-03", "import os\nSTATE_PATH = os.path.join(root, '.state.json')\n",
     False),                                                                # 已参数化
    ("AR-04", "def a():\n    raise SystemExit('x')\n"
              "def b():\n    raise SystemExit('y')\n"
              "def c():\n    raise SystemExit(1)\n", True),
    ("AR-04", "def a():\n    raise SystemExit(2)\n"
              "def b():\n    raise SystemExit(3)\n", False),               # 有分类
    ("AR-05", "mod.ROOT = '/tmp/x'\nprint('ALL PASS')\n", True),
    ("AR-05", "import pytest\nmod.ROOT = '/tmp/x'\n", False),              # 已用框架
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
