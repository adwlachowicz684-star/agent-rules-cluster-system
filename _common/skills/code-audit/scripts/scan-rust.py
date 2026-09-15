#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan-rust.py — Rust 源码缺陷模式扫描（正则 + 结构启发式）

为什么单独一个扫描器
--------------------
`scan-ts.py` / `scan-app.py` 的模式按 TS/JS 语法编写，对 `.rs` 只能命中
目录/文件名层面的弱信号（APP-* 族），**Rust 语义特有的缺陷一条都看不到**。

正则而非 AST：Rust 有 `syn`/`rust-analyzer`，但要求目标环境装 cargo 且能编译。
本扫描器定位是**候选发现**——在没装 Rust 工具链的环境里也能给出线索。
**证明 UB 要靠 `cargo miri`，证明溢出要靠 `-C overflow-checks=on` 重编译**。

用法
----
    python3 scan-rust.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
    python3 scan-rust.py --self-test        # 内置用例自检（改规则后必跑）

输出与其他扫描器同构，可直接喂 `sarif.py` 与 `rule-registry.py`。
"""
import os
import re
import sys
import json
import argparse

SRC = "."
# 测试与 fixture 样本默认排除：它们是**缺陷的示范代码**，扫进去只会污染结果。
TEST_FILE = re.compile(
    r'(?:^|/)(?:test_|.+[._](?:test|spec|fixture)|.+_test)\.[A-Za-z]+$')
INCLUDE_TESTS = False  # 由 --include-tests 打开

# --include-tests 同时放开**目录级**排除：否则开关只影响文件名匹配，
# fixtures/ 目录仍被跳过，开关看着像失灵。
TEST_SKIP_DIRS = {'fixtures', '__fixtures__', 'tests', 'test', '__tests__', 'testdata'}


SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build",
             "target",           # Rust 构建产物，可能含巨量生成代码
             "testdata", ".idea", "third_party",
             "fixtures", "__fixtures__"}
MAX_FILE_BYTES = 2 * 1024 * 1024
RS_EXT = (".rs",)

EXCLUDES = []


def _excluded(p, root):
    """排除路径（--exclude）。

    为什么需要：fixture 的 tp.* 是**故意写成有缺陷**的，扫它们必然命中，
    属于预期噪声；生成代码、vendor / target 目录同理。

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


def iter_rs(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(RS_EXT) and (INCLUDE_TESTS or not TEST_FILE.search(fn)):
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(p) > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if _excluded(p, root):
                    continue
                yield p


def lines_of(src):
    return src.splitlines()


def rel(p):
    return os.path.relpath(p, SRC)


def find_line(lines, rx):
    out = []
    for i, l in enumerate(lines, 1):
        if re.search(rx, l):
            out.append(i)
    return out


def strip_comments(src):
    """去注释，避免注释里的示例代码触发误报。

    Rust 还有原始字符串 `r#"..."#`，里面可能含示例代码。
    先把它挖掉再剥注释——否则 r#" 里的 // 会被当注释起点，
    后面的真实代码被整段吞掉（静默漏报，最难查的那种）。
    """
    src = re.sub(r'r#*"[\s\S]*?"#', '""', src)
    src = re.sub(r'/\*[\s\S]*?\*/', "", src)
    return re.sub(r'//[^\n]*', "", src)


def has_pragma(lines, n):
    for i in (n - 2, n - 1):
        if 0 <= i < len(lines) and "// audit" in lines[i] and "ignore" in lines[i]:
            return True
    return False


def in_test_fn(lines, n):
    """该行是否位于 #[cfg(test)] / #[test] 函数内（向上回溯 40 行）。"""
    for i in range(max(0, n - 40), n):
        if re.search(r'#\[cfg\(test\)\]|#\[test\]', lines[i]):
            return True
    return False


# ---------------------------------------------------------------- 模式

def rs_unwrap_in_command(src, lines, path):
    """RS-01 unwrap/expect 在命令或外部输入路径上"""
    if not re.search(r"\.unwrap\s*\(\s*\)|\.expect\s*\(", src):
        return []
    # 命令入口 / 公共处理函数的强信号
    is_entry = re.search(r"#\[tauri::command\]|#\[command\]|pub\s+async\s+fn|pub\s+fn\s+\w*\s*\([^)]*(?:String|PathBuf|Value|Json)", src)
    out = []
    for n in find_line(lines, r"\.unwrap\s*\(\s*\)|\.expect\s*\("):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        if is_entry:
            out.append((n, "命令/公共入口内 unwrap —— panic 会让前端只拿到模糊错误，用户看到「点了没反应」"))
        else:
            # 非入口处也报，但信息不同：需要人工确认是否外部输入
            out.append((n, "unwrap/expect —— 确认此处失败是否是外部输入导致的；是则 panic 会静默化"))
    return out


def rs_int_overflow(src, lines, path):
    """RS-02 整数窄化转换 / 未保护的算术"""
    out = []
    # as 窄化：u64/usize -> u32/u16/u8
    for n in find_line(lines, r"\bas\s+(u8|u16|u32|i8|i16|i32)\b"):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        out.append((n, "as 窄化转换 —— 溢出时高位静默截断，release 不 panic"))
    # 循环内累加未用 checked_*
    has_loop = re.search(r"\b(?:while|for|loop)\b", src)
    if has_loop and re.search(r"\w+\s*\+=\s*\w+|\w+\s*\*=\s*\w+", src):
        if not re.search(r"checked_\w+|saturating_\w+|wrapping_\w+", src):
            for n in find_line(lines, r"\w+\s*\+=\s*\w+"):
                if has_pragma(lines, n) or in_test_fn(lines, n):
                    continue
                out.append((n, "循环内累加未用 checked_*/saturating_* —— release 下溢出静默回绕"))
                break
    return out


def rs_unsafe_no_safety(src, lines, path):
    """RS-03 unsafe 无 SAFETY 注释"""
    if not re.search(r"\bunsafe\b", src):
        return []
    out = []
    for n in find_line(lines, r"\bunsafe\s*(?:\{|\bfn\b)"):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        # 上方 2 行内找 SAFETY
        ctx = "\n".join(lines[max(0, n - 3):n - 1])
        if not re.search(r"SAFETY\s*:|Safety\s*:", ctx):
            out.append((n, "unsafe 块上方无 // SAFETY: 注释 —— 安全契约无法复核，下次改动必然踩"))
    return out


def rs_lock_across_await(src, lines, path):
    """RS-04 std 同步锁守卫跨 await

    判据是 `.lock()` 后面跟 `.unwrap()`/`.expect(` —— 那是 **std** 的锁
    （返回 Result，需要 unwrap）。tokio 的锁写法是 `.lock().await`
    （返回 Future），本身就允许跨 await，不是缺陷。

    光看 `tokio::sync` 字样不可靠：真实代码里类型名可能是 `SharedState`
    这类别名，文本里根本没有 tokio 三个字，只按关键字排除会漏报。
    """
    if ".await" not in src:
        return []
    # std 锁的强信号：lock 后接 unwrap/expect
    std_lock_rx = r"\.lock\s*\(\s*\)\s*\.\s*(?:unwrap|expect)|" \
                  r"\.(?:read|write)\s*\(\s*\)\s*\.\s*(?:unwrap|expect)"
    locks = find_line(lines, std_lock_rx)
    awaits = find_line(lines, r"\.await\b")
    if not locks or not awaits:
        return []
    out = []
    for ln in locks:
        later = [a for a in awaits if a > ln]
        if not later:
            continue
        if has_pragma(lines, ln) or in_test_fn(lines, ln):
            continue
        out.append((ln, "std 同步锁（.lock().unwrap()）在 .await 之前取得 —— "
                        "MutexGuard 非 Send，跨 await 持有会死锁，"
                        "或用 block_on/unsafe 绕过编译器保护"))
        break
    return out


def rs_command_unvalidated(src, lines, path):
    """RS-05 Tauri 命令参数未校验直接用于路径/命令"""
    if not re.search(r"#\[tauri::command\]|#\[command\]", src):
        return []
    out = []
    has_check = re.search(r"canonicalize|starts_with|whitelist|allowlist|is_relative|strip_prefix", src)
    for n in find_line(lines, r"fs::(read|write|remove|create|copy)|Command::new\s*\(|std::process::Command"):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        if has_check:
            continue
        out.append((n, "命令内直接使用路径/命令执行且无 canonicalize/白名单校验 —— "
                       "前端校验不算数，invoke 可被直接调用（路径穿越）"))
    return out


def rs_unbounded_alloc(src, lines, path):
    """RS-06 外部输入驱动的无界分配"""
    out = []
    for n in find_line(lines, r"Vec::with_capacity\s*\("):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        seg = lines[n - 1]
        # 容量来自字面量常量 → 安全
        if re.search(r"with_capacity\s*\(\s*\d+\s*\)", seg):
            continue
        out.append((n, "Vec::with_capacity 容量来自变量 —— 若来自外部输入可触发 OOM，需设上限"))
    for n in find_line(lines, r"read_to_end\s*\(|read_to_string\s*\("):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        if re.search(r"take\s*\(", src):
            continue
        out.append((n, "read_to_end/String 无 take() 限制 —— 超大输入会一次性读入内存"))
    return out


def rs_error_swallowed(src, lines, path):
    """RS-07 错误被 unwrap_or_default / let _ 掩盖"""
    out = []
    for n in find_line(lines, r"\.unwrap_or_default\s*\(\s*\)|\.unwrap_or\s*\(\s*0\s*\)"):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        out.append((n, "unwrap_or_default/0 —— 错误被转成零值继续跑，失败不可见"))
    for n in find_line(lines, r"\blet\s+_\s*=\s*\w+"):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        out.append((n, "let _ = 丢弃 Result —— 错误被显式吞掉"))
    return out


def rs_arc_cycle(src, lines, path):
    """RS-08 Arc 循环引用 / Rc 跨线程

    `Rc` 的检出要同时认 `Rc<...>` 和 `Rc::new(...)`：
    只写 `Rc\s*<` 会漏掉 `Rc::new` 这种最常见的构造写法——
    而恰恰是构造点才说明这里真的产生了一个 Rc。
    """
    out = []
    if re.search(r"\bthread::spawn|tokio::spawn|std::thread", src):
        for n in find_line(lines, r"\bRc\s*(?:<|::)"):
            if has_pragma(lines, n) or in_test_fn(lines, n):
                continue
            out.append((n, "Rc 出现在 spawn 上下文 —— Rc 非 Send，跨线程是 UB"))
    # 双向 Arc<Mutex<>>（同一文件内出现两个结构体互持）
    arcs = find_line(lines, r"Arc\s*<\s*(?:Mutex|RwLock)\s*<")
    if len(arcs) >= 2 and re.search(r"Weak\s*<", src) is None:
        n = arcs[0]
        if not has_pragma(lines, n) and not in_test_fn(lines, n):
            out.append((n, "多个 Arc<Mutex<..>> 且无 Weak —— 双向持有可能形成引用环，计数永不归零"))
    return out


def rs_raw_ptr(src, lines, path):
    """RS-09 裸指针 / transmute"""
    out = []
    for n in find_line(lines, r"mem::transmute|std::mem::transmute"):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        out.append((n, "transmute —— 绕过类型系统，需 SAFETY 注释与长度/对齐断言"))
    for n in find_line(lines, r"\bas\s+\*const|\bas\s+\*mut"):
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        out.append((n, "裸指针转换 —— 应封装进单一 unsafe 小函数，业务代码不直接出现"))
    return out


def rs_secret_log(src, lines, path):
    """RS-10 敏感信息进日志"""
    SECRET = r"(?i)(password|passwd|secret|token|api_key|apikey|private_key|credential)"
    if not re.search(SECRET, src):
        return []
    out = []
    for n in find_line(lines, r"\b(?:println|eprintln|format|log::\w+|info|warn|error|debug)\s*!"):
        seg = lines[n - 1]
        if not re.search(SECRET, seg):
            continue
        if has_pragma(lines, n) or in_test_fn(lines, n):
            continue
        out.append((n, "日志/格式化里出现敏感字段名 —— 日志被采集即等同泄露"))
    return out


PATTERNS = [
    ("RS-01", "P0", "unwrap/expect 在命令入口（panic 静默化）", rs_unwrap_in_command),
    ("RS-02", "P0", "整数溢出（release 静默回绕）", rs_int_overflow),
    ("RS-03", "P0", "unsafe 无 SAFETY 注释（契约不可复核）", rs_unsafe_no_safety),
    ("RS-04", "P0", "std 同步锁跨 await（死锁/Send 违反）", rs_lock_across_await),
    ("RS-05", "P0", "Tauri 命令入参未校验（路径穿越/注入）", rs_command_unvalidated),
    ("RS-06", "P0", "外部输入驱动的无界分配（OOM）", rs_unbounded_alloc),
    ("RS-07", "P1", "错误被 unwrap_or_default / let _ 掩盖", rs_error_swallowed),
    ("RS-08", "P1", "Arc 循环引用 / Rc 跨线程", rs_arc_cycle),
    ("RS-09", "P1", "裸指针 / transmute 未隔离", rs_raw_ptr),
    ("RS-10", "P1", "敏感信息进日志", rs_secret_log),
]

SCENE = {"RS-01": "p-rust", "RS-02": "s-numerics", "RS-03": "p-rust",
         "RS-04": "s-concurrency", "RS-05": "s-backend", "RS-06": "s-backend",
         "RS-07": "p-rust", "RS-08": "p-rust", "RS-09": "p-rust",
         "RS-10": "s-sandbox"}


def scan(src):
    rows = []
    for p in iter_rs(src):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            continue
        code = strip_comments(raw)
        lines = lines_of(raw)
        for rid, level, name, fn in PATTERNS:
            try:
                hits = fn(code, lines, p)
            except Exception as e:
                print(f"[warn] {rid} 在 {rel(p)} 异常: {e}", file=sys.stderr)
                continue
            for n, msg in hits:
                snip = lines[n - 1].strip()[:120] if 1 <= n <= len(lines) else ""
                rows.append({"id": rid, "level": level, "name": name,
                             "file": rel(p), "line": n, "snippet": snip,
                             "detail": msg, "scanner": "scan-rust.py",
                             "scene": SCENE.get(rid, "")})
    return rows


SELF_TEST_CASES = [
    # ---- 正向：必须命中 ----
    ("RS-01", '#[tauri::command]\nfn load(p: String) -> Result<String, String> {\n'
              '    let v: Value = serde_json::from_str(&p).unwrap();\n    Ok(s)\n}\n', True),
    ("RS-02", 'fn f(items: &[u8]) -> u32 {\n    let n = items.len() as u32;\n    n\n}\n', True),
    ("RS-03", 'fn f(p: *const u8) -> u8 {\n    unsafe { *p }\n}\n', True),
    ("RS-04", 'async fn f(s: &State) {\n    let g = s.lock().unwrap();\n    do_async(&g).await;\n}\n', True),
    ("RS-05", '#[tauri::command]\nfn read(name: String) -> String {\n'
              '    fs::read_to_string(format!("{}/{}", base, name)).unwrap()\n}\n', True),
    ("RS-06", 'fn f(n: usize) -> Vec<u8> {\n    let mut v = Vec::with_capacity(n);\n    v\n}\n', True),
    ("RS-07", 'fn f(s: &str) -> u32 {\n    let n: u32 = s.parse().unwrap_or_default();\n    n\n}\n', True),
    ("RS-08", 'use std::rc::Rc;\nfn f() {\n    let a = Rc::new(1);\n'
              '    thread::spawn(move || { let b = a; });\n}\n', True),
    ("RS-09", 'fn f(x: u32) -> i32 {\n    let y = unsafe { std::mem::transmute::<u32, i32>(x) };\n    y\n}\n', True),
    ("RS-10", 'fn f(token: &str) {\n    println!("login with {}", token);\n}\n', True),
    # ---- 反向：必须不命中 ----
    ("RS-01", '#[tauri::command]\nfn load(p: String) -> Result<String, String> {\n'
              '    let v: Value = serde_json::from_str(&p)?;\n    Ok(s)\n}\n', False),
    ("RS-02", 'fn f(items: &[u8]) -> u32 {\n    let n: u32 = items.len().try_into().map_err(|_| "too big")?;\n    n\n}\n', False),
    ("RS-03", 'fn f(p: *const u8) -> u8 {\n    // SAFETY: caller guarantees p is valid and aligned\n    unsafe { *p }\n}\n', False),
    ("RS-04", 'async fn f(s: &TokioState) {\n    let g = s.lock().await;\n    do_async(&g).await;\n}\n', False),
    ("RS-05", '#[tauri::command]\nfn read(name: String) -> String {\n'
              '    let p = std::fs::canonicalize(&name)?;\n'
              '    if !p.starts_with(&base) { return Err("deny".into()) }\n'
              '    fs::read_to_string(p).unwrap_or_default()\n}\n', False),
    ("RS-06", 'fn f() -> Vec<u8> {\n    let mut v = Vec::with_capacity(1024);\n    v\n}\n', False),
    ("RS-07", 'fn f(s: &str) -> Result<u32, E> {\n    let n: u32 = s.parse()?;\n    Ok(n)\n}\n', False),
    ("RS-08", 'use std::sync::{Arc, Weak};\nstruct A { b: Weak<Mutex<B>> }\n', False),
    ("RS-09", 'fn f(x: u32) -> u64 {\n    let y = x as u64;\n    y\n}\n', False),
    ("RS-10", 'fn f(name: &str) {\n    println!("hello {}", name);\n}\n', False),
]


def self_test():
    global SRC
    import tempfile
    ok = fail = 0
    tmp = tempfile.mkdtemp()
    SRC = tmp
    for i, (rid, code, want) in enumerate(SELF_TEST_CASES):
        f = os.path.join(tmp, f"t{i}.rs")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(code)
        rows = scan(tmp)
        got = any(r["id"] == rid and r["file"] == f"t{i}.rs" for r in rows)
        mark = "✓" if got == want else "✗"
        ok += got == want
        fail += got != want
        print(f"  {mark} {rid} 期望{'命中' if want else '不命中'} 实际{'命中' if got else '不命中'}")
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
    ap.add_argument("--pattern", default="")
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
            with open(args.sarif, "w", encoding="utf-8") as f:
                json.dump(build_sarif(rows, tool_name="scan-rust.py", root=SRC),
                          f, ensure_ascii=False, indent=1)
            print(f"SARIF → {args.sarif}（{len(rows)} 条）")
        except Exception as e:
            print(f"sarif 导出失败: {e}", file=sys.stderr)
        return

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print("scan-rust · Rust 缺陷模式扫描")
    print(f"源码根: {SRC}   Rust 文件: {sum(1 for _ in iter_rs(SRC))}   命中候选: {len(rows)}")
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
    print("\n候选 ≠ 结论：UB 用 `cargo miri` 证明，溢出加 `-C overflow-checks=on` 重编译验证。")


if __name__ == "__main__":
    main()
