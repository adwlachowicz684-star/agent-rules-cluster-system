#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan-java.py — Java 源码缺陷模式扫描（正则 + 结构启发式）

为什么单独一个扫描器
--------------------
`scan-ts.py` / `scan-app.py` 的模式按 TS/JS 语法编写，对 Java 输出 0 命中——
**不是「没问题」，是压根没看**。

正则而非 AST：目标环境不保证有 JDK / javaparser。
本扫描器定位是**候选发现**，重点抓那些"编译通过、运行正常、只在特定条件下出错"的：
中断被吞、线程池不关、异常静默。

用法
----
    python3 scan-java.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
    python3 scan-java.py --self-test        # 内置用例自检（改规则后必跑）
"""
import os
import re
import sys
import json
import argparse

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


SKIP_DIRS = {".git", "target", "build", "out", ".gradle", ".idea",
             "node_modules", "generated", "gen",
             "fixtures", "__fixtures__", "test", "tests"}
MAX_FILE_BYTES = 2 * 1024 * 1024
JAVA_EXT = (".java",)


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


def iter_java(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(JAVA_EXT) and (INCLUDE_TESTS or not TEST_FILE.search(fn)):
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(p) > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if _excluded(p, root):
                    continue
                yield p


def rel(p):
    return os.path.relpath(p, SRC)


def find_line(lines, rx):
    return [i for i, l in enumerate(lines, 1) if re.search(rx, l)]


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def has_pragma(lines, n):
    for i in (n - 2, n - 1):
        if 0 <= i < len(lines) and "// audit" in lines[i] and "ignore" in lines[i]:
            return True
    return False


CLOSEABLE = r"(FileInputStream|FileOutputStream|BufferedReader|BufferedWriter|" \
            r"FileReader|FileWriter|InputStream|OutputStream|Reader|Writer|" \
            r"Connection|Statement|PreparedStatement|ResultSet|Socket|ServerSocket|" \
            r"ZipFile|JarFile|Scanner|PrintWriter|Channel|HttpClient)"


def java_no_try_with_resources(src, lines, path):
    """JAVA-01 Closeable 裸创建，无 try-with-resources"""
    out = []
    for n in find_line(lines, r"new\s+" + CLOSEABLE + r"[\s<\(]"):
        if has_pragma(lines, n):
            continue
        seg = lines[n - 1]
        if re.search(r"try\s*\(", seg):
            continue
        # 同文件/同 try 块里有 finally close 视为已处理（粗判：文件内出现 finally + close）
        if re.search(r"finally\s*\{[\s\S]{0,400}?\.close\s*\(", src):
            continue
        if re.search(r"\breturn\s+new\s+" + CLOSEABLE, seg):
            continue       # 直接返回给调用方，由调用方负责
        out.append((n, "Closeable 裸创建，未用 try-with-resources —— 异常路径不释放"))
    return out


def java_executor_no_shutdown(src, lines, path):
    """JAVA-02 线程池未 shutdown"""
    created = find_line(lines, r"Executors\.new(?:Fixed|Cached|Single|Scheduled|WorkStealing)"
                               r"(?:Thread|Task)?Pool|new\s+ThreadPoolTaskExecutor|"
                               r"new\s+ThreadPoolExecutor")
    if not created:
        return []
    if re.search(r"\.shutdown\s*\(\)|\.shutdownNow\s*\(\)|@PreDestroy|@Bean\s*\(\s*destroyMethod", src):
        return []
    out = []
    for n in created:
        if has_pragma(lines, n):
            continue
        out.append((n, "线程池创建后无 shutdown —— 线程不回收，JVM 不退出"))
    return out


def java_interrupted_swallowed(src, lines, path):
    """JAVA-03 InterruptedException 被吞（未恢复中断标志）"""
    if "InterruptedException" not in src:
        return []
    out = []
    for n in find_line(lines, r"catch\s*\(\s*(?:final\s+)?InterruptedException"):
        if has_pragma(lines, n):
            continue
        # 取 catch 块（向后 800 字符）
        block = "\n".join(lines[n - 1:n + 30])
        m = re.search(r"catch\s*\(\s*(?:final\s+)?InterruptedException[^)]*\)\s*\{", block)
        body = block[m.end():m.end() + 800] if m else block[:800]
        if re.search(r"currentThread\s*\(\s*\)\s*\.\s*interrupt\s*\(\s*\)", body):
            continue
        if re.search(r"throw\s+", body):
            continue
        out.append((n, "InterruptedException 被吞且未恢复中断标志 —— 上层取消永远不生效"))
    return out


def java_unsafe_collection(src, lines, path):
    """JAVA-04 并发场景下的非线程安全集合"""
    concurrent_ctx = re.search(r"\bThread\b|ExecutorService|CompletableFuture|@Async|"
                               r"Runnable|Callable|parallelStream|newFixedThreadPool|"
                               r"newCachedThreadPool", src)
    if not concurrent_ctx:
        return []
    out = []
    for n in find_line(lines, r"new\s+(HashMap|HashSet|ArrayList|LinkedList|TreeMap|StringBuilder)\s*[<\(]"):
        if has_pragma(lines, n):
            continue
        cls = re.search(r"new\s+(HashMap|HashSet|ArrayList|LinkedList|TreeMap|StringBuilder)",
                        lines[n - 1]).group(1)
        out.append((n, f"并发上下文里用 {cls} —— 并发写可能丢数据或死循环（JDK7 HashMap 扩容）"))
    return out


def java_threadlocal(src, lines, path):
    """JAVA-05 ThreadLocal 未 remove"""
    if not re.search(r"ThreadLocal|InheritableThreadLocal", src):
        return []
    if re.search(r"\.remove\s*\(\s*\)", src):
        return []
    out = []
    for n in find_line(lines, r"\b(?:Inheritable)?ThreadLocal\b"):
        if has_pragma(lines, n):
            continue
        out.append((n, "ThreadLocal 声明但无 remove —— 线程池复用会跨请求串数据"))
    return out


def java_sync_on_shared(src, lines, path):
    """JAVA-06 synchronized 锁在共享对象上 / 同步块内做 IO"""
    out = []
    for n in find_line(lines, r"synchronized\s*\("):
        if has_pragma(lines, n):
            continue
        seg = lines[n - 1]
        m = re.search(r"synchronized\s*\(\s*([^)]+)\)", seg)
        if m:
            target = m.group(1).strip()
            if re.match(r'^"', target) or re.match(r'^\w+\.class$', target) \
                    or target in ("this", "Integer", "String", "Boolean", "Long"):
                out.append((n, f"synchronized 锁在 {target} 上 —— 会被 intern/缓存，导致意外互斥"))
    # 同步块内 IO
    for m in re.finditer(r"synchronized\s*[\({]", src):
        n = src[:m.start()].count("\n") + 1
        block = src[m.start():m.start() + 1500]
        if re.search(r"\.(get|post|execute|query|update|read|write|flush)\s*\(", block) \
                and re.search(r"http|jdbc|rest|client|template|socket", block, re.I):
            if not has_pragma(lines, n):
                out.append((n, "同步块内做 IO/远程调用 —— 粒度过粗，所有线程串行等网络"))
    return out


def java_equals_hashcode(src, lines, path):
    """JAVA-07 equals 与 hashCode 不配对"""
    has_eq = bool(re.search(r"public\s+boolean\s+equals\s*\(", src))
    has_hc = bool(re.search(r"public\s+int\s+hashCode\s*\(", src))
    # ⚠ 必须转 bool 再比较：两个 Match 对象（或 None）直接 == 永远不等，
    # 会让「equals/hashCode 都写了」的正常类被误报
    if has_eq == has_hc:      # 都有或都没有 → 不报
        return []
    out = []
    n = find_line(lines, r"public\s+boolean\s+equals\s*\(") or find_line(lines, r"public\s+int\s+hashCode\s*\(")
    if n and not has_pragma(lines, n[0]):
        missing = "hashCode" if has_eq else "equals"
        out.append((n[0], f"重写了 equals/hashCode 但缺 {missing} —— 放进 HashMap 会查不到"))
    return out


def java_static_mutable(src, lines, path):
    """JAVA-08 static 可变共享状态"""
    out = []
    for n in find_line(lines, r"\bstatic\s+(?!final\b)[\w<>\[\],\s]*?\b(Map|List|Set|Collection|"
                              r"StringBuilder|StringBuffer|Date|Calendar|Atomic\w+)\b"):
        if has_pragma(lines, n):
            continue
        seg = lines[n - 1].strip()
        out.append((n, f"static 非 final 可变字段 —— {seg[:60]} 跨线程共享，有竞态且无法回收"))
    return out


def java_exception_swallowed(src, lines, path):
    """JAVA-09 异常吞没"""
    out = []
    for n in find_line(lines, r"catch\s*\(\s*(?:final\s+)?(Exception|Throwable)\b"):
        if has_pragma(lines, n):
            continue
        block = "\n".join(lines[n - 1:n + 25])
        m = re.search(r"catch\s*\(\s*(?:final\s+)?(?:Exception|Throwable)[^)]*\)\s*\{", block)
        if not m:
            continue
        # 取 catch 块**第一个 } 之前**的内容：单行 `catch (Exception e) { } }`
        # 后面还跟着外层方法的 }，整体 strip 不会为空，必须截断到块尾
        body = block[m.end():m.end() + 600]
        end = body.find("}")
        if end >= 0:
            body = body[:end]
        stripped = re.sub(r"//[^\n]*", "", body)
        stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S).strip()
        if re.search(r"\bthrow\b", stripped):
            continue
        if re.search(r"log(ger)?\s*\.\s*\w+|System\.err|printStackTrace", stripped):
            continue          # 至少留了痕，不报
        if not stripped:
            out.append((n, "catch 块为空 —— 异常完全静默，调用方按成功继续"))
    return out


def java_unsafe_dateformat(src, lines, path):
    """JAVA-10 非线程安全的格式化对象被共享"""
    out = []
    for n in find_line(lines, r"(?:static|private|protected|public)[^;=]*\b"
                              r"(SimpleDateFormat|DecimalFormat|DateFormat)\b"):
        if has_pragma(lines, n):
            continue
        if re.search(r"static\s+final", lines[n - 1]):
            out.append((n, "SimpleDateFormat 声明为共享字段 —— 非线程安全，并发会产出错误日期"))
            continue
        out.append((n, "SimpleDateFormat 作为字段共享 —— 若被多线程使用会产出错误日期"))
    return out


PATTERNS = [
    ("JAVA-01", "P0", "Closeable 未用 try-with-resources", java_no_try_with_resources),
    ("JAVA-02", "P0", "线程池未 shutdown", java_executor_no_shutdown),
    ("JAVA-03", "P0", "InterruptedException 被吞（取消失效）", java_interrupted_swallowed),
    ("JAVA-04", "P0", "并发上下文用非线程安全集合", java_unsafe_collection),
    ("JAVA-05", "P1", "ThreadLocal 未 remove（跨请求串扰）", java_threadlocal),
    ("JAVA-06", "P1", "synchronized 锁共享对象/块内 IO", java_sync_on_shared),
    ("JAVA-07", "P2", "equals 与 hashCode 不配对", java_equals_hashcode),
    ("JAVA-08", "P1", "static 可变共享状态", java_static_mutable),
    ("JAVA-09", "P0", "异常吞没（catch 块为空）", java_exception_swallowed),
    ("JAVA-10", "P1", "非线程安全的格式化对象被共享", java_unsafe_dateformat),
]

SCENE = {"JAVA-01": "p-java", "JAVA-02": "s-concurrency", "JAVA-03": "s-concurrency",
         "JAVA-04": "s-concurrency", "JAVA-05": "s-concurrency", "JAVA-06": "s-concurrency",
         "JAVA-07": "p-java", "JAVA-08": "p-java", "JAVA-09": "p-java",
         "JAVA-10": "s-concurrency"}


def scan(src):
    rows = []
    for p in iter_java(src):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            continue
        code = strip_comments(raw)
        lines = raw.splitlines()
        for rid, level, name, fn in PATTERNS:
            try:
                hits = fn(code, lines, p)
            except Exception as e:
                print(f"[warn] {rid} 在 {rel(p)} 异常: {e}", file=sys.stderr)
                continue
            for n, msg in hits:
                rows.append({"id": rid, "level": level, "name": name,
                             "file": rel(p), "line": n,
                             "snippet": lines[n - 1].strip()[:120] if 1 <= n <= len(lines) else "",
                             "detail": msg, "scanner": "scan-java.py",
                             "scene": SCENE.get(rid, "")})
    return rows


SELF_TEST_CASES = [
    ("JAVA-01", "class A {\n  void f() throws Exception {\n    FileInputStream in = new FileInputStream(\"a\");\n    int b = in.read();\n  }\n}\n", True),
    ("JAVA-02", "class A {\n  void f() {\n    ExecutorService es = Executors.newFixedThreadPool(4);\n    es.submit(() -> {});\n  }\n}\n", True),
    ("JAVA-03", "class A {\n  void f() {\n    try { Thread.sleep(100); }\n    catch (InterruptedException e) { log.warn(\"x\"); }\n  }\n}\n", True),
    ("JAVA-04", "class A {\n  Map<String,String> m = new HashMap<>();\n  void f() { new Thread(() -> m.put(\"a\",\"b\")).start(); }\n}\n", True),
    ("JAVA-05", "class A {\n  private ThreadLocal<User> u = new ThreadLocal<>();\n}\n", True),
    ("JAVA-06", "class A {\n  void f() { synchronized (\"LOCK\") { doWork(); } }\n}\n", True),
    ("JAVA-07", "class A {\n  public boolean equals(Object o) { return true; }\n}\n", True),
    ("JAVA-08", "class A {\n  static Map<String,String> cache = new HashMap<>();\n}\n", True),
    ("JAVA-09", "class A {\n  void f() { try { g(); } catch (Exception e) { } }\n}\n", True),
    ("JAVA-10", "class A {\n  private static final SimpleDateFormat F = new SimpleDateFormat(\"yyyy\");\n}\n", True),
    # 反向
    ("JAVA-01", "class A {\n  void f() throws Exception {\n    try (FileInputStream in = new FileInputStream(\"a\")) { int b = in.read(); }\n  }\n}\n", False),
    ("JAVA-02", "class A {\n  ExecutorService es = Executors.newFixedThreadPool(4);\n  void close() { es.shutdown(); }\n}\n", False),
    ("JAVA-03", "class A {\n  void f() {\n    try { Thread.sleep(100); }\n    catch (InterruptedException e) { Thread.currentThread().interrupt(); }\n  }\n}\n", False),
    ("JAVA-04", "class A {\n  Map<String,String> m = new ConcurrentHashMap<>();\n  void f() { new Thread(() -> m.put(\"a\",\"b\")).start(); }\n}\n", False),
    ("JAVA-09", "class A {\n  void f() { try { g(); } catch (Exception e) { throw new RuntimeException(e); } }\n}\n", False),
    ("JAVA-07", "class A {\n  public boolean equals(Object o) { return true; }\n  public int hashCode() { return 1; }\n}\n", False),
]


def self_test():
    global SRC
    import tempfile
    ok = fail = 0
    tmp = tempfile.mkdtemp()
    SRC = tmp
    for i, (rid, code, want) in enumerate(SELF_TEST_CASES):
        f = os.path.join(tmp, f"T{i}.java")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(code)
        rows = scan(tmp)
        got = any(r["id"] == rid and r["file"] == f"T{i}.java" for r in rows)
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
                json.dump(build_sarif(rows, tool_name="scan-java.py", root=SRC),
                          f, ensure_ascii=False, indent=1)
            print(f"SARIF → {args.sarif}（{len(rows)} 条）")
        except Exception as e:
            print(f"sarif 导出失败: {e}", file=sys.stderr)
        return

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print("scan-java · Java 缺陷模式扫描")
    print(f"源码根: {SRC}   Java 文件: {sum(1 for _ in iter_java(SRC))}   命中候选: {len(rows)}")
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
