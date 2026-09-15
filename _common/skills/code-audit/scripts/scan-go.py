#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan-go.py — Go 源码缺陷模式扫描（正则 + 结构启发式）

为什么单独一个扫描器
--------------------
`scan-ts.py` / `scan-app.py` 的模式按 TS/JS 语法编写，对 Go 输出 0 命中——
**不是「没问题」，是压根没看**。

正则而非 AST：Go 有 `go/parser`，但那要求目标环境装 Go 且能编译。
本扫描器定位是**候选发现**——在没装 Go 工具链的环境里也能给出线索。
**证明竞态要靠 `go test -race`，本扫描器只负责指出「这里该去看一眼」**。

用法
----
    python3 scan-go.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
    python3 scan-go.py --self-test        # 内置用例自检（改规则后必跑）

输出与其他扫描器同构，可直接喂 `sarif.py` 与 `rule-registry.py`。
"""
import os
import re
import sys
import json
import argparse

SRC = "."
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "testdata",
             ".idea", "third_party", "Godeps"}
MAX_FILE_BYTES = 2 * 1024 * 1024
GO_EXT = (".go",)


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


def iter_go(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(GO_EXT) and not fn.endswith("_test.go"):
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(p) > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                if _excluded(p, root):
                    continue
                yield p


def read(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read(), f.read().splitlines() if False else None
    except OSError:
        return "", None


def lines_of(src):
    return src.splitlines()


def rel(p):
    return os.path.relpath(p, SRC)


def find_line(lines, rx):
    """返回所有匹配行号"""
    out = []
    for i, l in enumerate(lines, 1):
        if re.search(rx, l):
            out.append(i)
    return out


def strip_comments(src):
    """去行注释与块注释，避免注释里的示例代码触发误报"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def has_pragma(lines, n):
    for i in (n - 2, n - 1):
        if 0 <= i < len(lines) and "// audit" in lines[i] and "ignore" in lines[i]:
            return True
    return False


# ---------------------------------------------------------------- 模式

def go_goroutine_leak(src, lines, path):
    """GO-01 goroutine 无退出机制"""
    if not re.search(r"\bgo\s+(func\s*\(|[\w\.]+\s*\()", src):
        return []
    has_exit = re.search(r"\bcontext\b|\bWaitGroup\b|sync\.|ctx\.Done\(\)|done\s+chan|quit\s+chan", src)
    if has_exit:
        return []
    out = []
    for n in find_line(lines, r"\bgo\s+(func\s*\(|[\w\.]+\s*\()"):
        if has_pragma(lines, n):
            continue
        # main 包且函数名为 main 时生命周期等同进程，降级提示
        out.append((n, "go 语句启动 goroutine，但文件内无 context/WaitGroup/done channel —— 可能永久挂住"))
    return out


def go_ctx_not_propagated(src, lines, path):
    """GO-02 函数接收 ctx 但阻塞调用没传"""
    if not re.search(r"ctx\s+context\.Context|context\.Context", src):
        return []
    out = []
    blocking = [
        (r"http\.Get\s*\(", "http.Get 未用 NewRequestWithContext"),
        (r"http\.Post\s*\(", "http.Post 未带 ctx"),
        (r"http\.NewRequest\s*\(", "http.NewRequest 改用 NewRequestWithContext"),
        (r"db\.Query\s*\(", "db.Query 未用 QueryContext"),
        (r"db\.Exec\s*\(", "db.Exec 未用 ExecContext"),
        (r"time\.After\s*\(", "time.After 不受 ctx 取消影响，定时器不释放"),
    ]
    for rx, msg in blocking:
        for n in find_line(lines, rx):
            if has_pragma(lines, n):
                continue
            out.append((n, msg))
    return out


def go_channel_misuse(src, lines, path):
    """GO-03 channel 关闭位置/无缓冲风险"""
    out = []
    # 无缓冲 channel
    for n in find_line(lines, r"make\s*\(\s*chan\s+[^,)]+\s*\)"):
        if has_pragma(lines, n):
            continue
        out.append((n, "无缓冲 channel —— 无接收方时发送永久阻塞"))
    # 重复 close
    closes = find_line(lines, r"\bclose\s*\(")
    if len(closes) > 1:
        for n in closes[1:]:
            if not has_pragma(lines, n):
                out.append((n, f"第 {len(closes)} 处 close —— 重复关闭会 panic，应由发送方唯一关闭"))
    # range channel 但无 close
    if re.search(r"for\s+[\w,\s]*:=\s*range\s+\w+", src) and re.search(r"range\s+[\w\.]+\s*\{", src):
        if not closes and re.search(r"make\s*\(\s*chan", src):
            for n in find_line(lines, r"for\s+[\w,\s]*:=\s*range\s+[\w\.]+"):
                if has_pragma(lines, n):
                    continue
                out.append((n, "for range channel 但文件内无 close —— 接收方永不退出"))
    return out


def go_map_concurrent(src, lines, path):
    """GO-04 map 并发写无同步"""
    if not re.search(r"\bmap\s*\[[^\]]+\]", src):
        return []
    if not re.search(r"\bgo\s+(func|\w)", src):
        return []
    if re.search(r"sync\.(Mutex|RWMutex|Map)|\block\.Lock\(\)|sync\.Map", src):
        return []
    out = []
    for n in find_line(lines, r"\bmap\s*\[[^\]]+\]"):
        if has_pragma(lines, n):
            continue
        out.append((n, "map 与 go 语句同文件且无 mutex —— 并发写会 fatal error 崩溃"))
        break
    return out


def go_mutex_copy(src, lines, path):
    """GO-05 mutex 值传递

    只报「按值出现在 func 签名里」（参数或返回值）——那必然是一次拷贝。
    `var mu sync.Mutex` / 结构体字段是**正常用法**，不报：
    值声明本身不是拷贝，只有当持有它的对象被拷贝时才出问题，那需要数据流分析，
    交给 `go vet` 的 copylocks 更合适。
    """
    out = []
    for n in find_line(lines, r"\bfunc\b"):
        seg = lines[n - 1]
        if not re.search(r"\bsync\.(Mutex|RWMutex)\b", seg):
            continue
        if re.search(r"\*\s*sync\.(Mutex|RWMutex)", seg):
            continue            # 指针传递，正是正确写法
        if has_pragma(lines, n):
            continue
        out.append((n, "func 签名里 sync.Mutex 按值（非指针）—— 参数/返回值拷贝后保护失效"))
    return out


def go_err_dropped(src, lines, path):
    """GO-06 错误被丢弃"""
    out = []
    # _, _ = / _, err := 形式中 err 被 _
    for n in find_line(lines, r",\s*_\s*(:?=|=)\s*\w+\."):
        if has_pragma(lines, n):
            continue
        out.append((n, "错误返回值被 _ 丢弃 —— 失败静默，调用方按成功继续"))
    # err 声明但从未判断
    if re.search(r"err\s+:?=", src) and not re.search(r"err\s*!=\s*nil|\berr\b\s*==\s*nil", src):
        for n in find_line(lines, r"\berr\s+:?=[^=]"):
            if has_pragma(lines, n):
                continue
            out.append((n, "err 声明后从未判断 —— 失败被吞"))
            break
    return out


def go_waitgroup_mismatch(src, lines, path):
    """GO-07 WaitGroup 计数不匹配"""
    if not re.search(r"\.Add\s*\(", src):
        return []
    out = []
    if not re.search(r"\.Done\s*\(\)", src):
        for n in find_line(lines, r"\.Add\s*\("):
            if has_pragma(lines, n):
                continue
            out.append((n, "有 Add 无 Done —— Wait() 永久阻塞"))
    # Add 在 goroutine 内部
    for n in find_line(lines, r"go\s+func[\s\S]{0,200}?\.Add\s*\("):
        if not has_pragma(lines, n):
            out.append((n, "Add 在 goroutine 内部调用 —— Wait() 可能提前返回"))
    if re.search(r"go\s+func", src) and re.search(r"\.Add\s*\(", src):
        lines_join = "\n".join(lines)
        m = re.search(r"go\s+func[\s\S]{0,300}?\.Add\s*\(", lines_join)
        if m:
            n = lines_join[:m.start()].count("\n") + 1
            if not has_pragma(lines, n) and (n, "Add 在 goroutine 内部调用 —— Wait() 可能提前返回") not in out:
                out.append((n, "Add 在 goroutine 内部调用 —— Wait() 可能提前返回"))
    return out


def go_defer_in_loop(src, lines, path):
    """GO-08 循环里 defer"""
    out = []
    for m in re.finditer(r"\bfor\b[^\n{]*\{", src):
        start = src[:m.start()].count("\n")
        seg = src[m.start():m.start() + 3000]
        for dm in re.finditer(r"\bdefer\s+", seg):
            n = start + seg[:dm.start()].count("\n") + 1
            if has_pragma(lines, n):
                continue
            # for 与 defer 之间若出现 func 字面量 → defer 属于**内层函数**，
            # 每次迭代内层函数返回时就会执行，不会累积（这是标准修法，不是缺陷）
            between = seg[:dm.start()]
            if re.search(r"\bfunc\s*[({]", between):
                continue
            out.append((n, "循环体内 defer —— 累积到函数返回才执行，句柄/锁会堆积"))
    return out


def go_select_no_exit(src, lines, path):
    """GO-09 select 无退出路径"""
    if "select {" not in src and "select{" not in src:
        return []
    out = []
    for m in re.finditer(r"\bselect\s*\{", src):
        start = src[:m.start()].count("\n")
        # 粗略取 select 块
        depth, i = 0, m.start()
        while i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = src[m.start():i + 1]
        n = start + 1
        if "ctx.Done()" not in block and "default:" not in block \
                and "case <-done" not in block and "time.After" not in block:
            if not has_pragma(lines, n):
                out.append((n, "select 无 ctx.Done/default/超时分支 —— 所有 case 不活跃时永久阻塞"))
    return out


def go_no_recover(src, lines, path):
    """GO-10 goroutine 内无 recover"""
    if not re.search(r"\bgo\s+func", src):
        return []
    if "recover()" in src:
        return []
    out = []
    for m in re.finditer(r"\bgo\s+func", src):
        n = src[:m.start()].count("\n") + 1
        if has_pragma(lines, n):
            continue
        out.append((n, "go func 内无 recover —— 该 goroutine panic 会导致整个进程退出"))
        break
    return out


PATTERNS = [
    ("GO-01", "P0", "goroutine 泄漏（无退出机制）", go_goroutine_leak),
    ("GO-02", "P0", "context 未传播到阻塞调用", go_ctx_not_propagated),
    ("GO-03", "P0", "channel 使用不当（无缓冲/重复关闭/无人关）", go_channel_misuse),
    ("GO-04", "P0", "map 并发写无同步", go_map_concurrent),
    ("GO-05", "P1", "mutex 值拷贝（保护失效）", go_mutex_copy),
    ("GO-06", "P0", "错误返回值被丢弃", go_err_dropped),
    ("GO-07", "P1", "WaitGroup 计数不匹配", go_waitgroup_mismatch),
    ("GO-08", "P1", "循环内 defer（资源累积）", go_defer_in_loop),
    ("GO-09", "P1", "select 无退出路径", go_select_no_exit),
    ("GO-10", "P1", "goroutine 内无 recover", go_no_recover),
]

SCENE = {"GO-01": "s-concurrency", "GO-02": "s-concurrency", "GO-03": "s-concurrency",
         "GO-04": "s-concurrency", "GO-05": "s-concurrency", "GO-06": "p-go",
         "GO-07": "s-concurrency", "GO-08": "p-go", "GO-09": "s-concurrency",
         "GO-10": "p-go"}


def scan(src):
    rows = []
    for p in iter_go(src):
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
                             "detail": msg, "scanner": "scan-go.py",
                             "scene": SCENE.get(rid, "")})
    return rows


SELF_TEST_CASES = [
    ("GO-01", "package main\nfunc main() {\n    go func() { work() }()\n}\n", True),
    ("GO-02", "func f(ctx context.Context) {\n    resp, _ := http.Get(url)\n}\n", True),
    ("GO-03", "c := make(chan int)\ngo func() { c <- 1 }()\n", True),
    ("GO-04", "var m = map[string]int{}\nfunc f() { go func() { m[\"a\"] = 1 }() }\n", True),
    ("GO-05", "func f(l sync.Mutex) { l.Lock() }\n", True),
    ("GO-06", "v, _ := strconv.Atoi(s)\n", True),
    ("GO-07", "var wg sync.WaitGroup\nwg.Add(1)\ngo work()\nwg.Wait()\n", True),
    ("GO-08", "for _, f := range files {\n    fh, _ := os.Open(f)\n    defer fh.Close()\n}\n", True),
    ("GO-09", "select {\ncase v := <-ch:\n    handle(v)\n}\n", True),
    ("GO-10", "go func() {\n    doRisky()\n}()\n", True),
    # 反向
    ("GO-01", "func f(ctx context.Context) {\n    go func() { <-ctx.Done() }()\n}\n", False),
    ("GO-03", "c := make(chan int, 10)\n", False),
    ("GO-04", "var mu sync.Mutex\nvar m = map[string]int{}\nfunc f() { go func() { mu.Lock(); m[\"a\"]=1; mu.Unlock() }() }\n", False),
    ("GO-06", "v, err := strconv.Atoi(s)\nif err != nil { return err }\n", False),
    ("GO-08", "func run() {\n    fh, _ := os.Open(\"a\")\n    defer fh.Close()\n}\n", False),
]


def self_test():
    global SRC
    import tempfile
    ok = fail = 0
    tmp = tempfile.mkdtemp()
    SRC = tmp
    for i, (rid, code, want) in enumerate(SELF_TEST_CASES):
        f = os.path.join(tmp, f"t{i}.go")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(code)
        rows = scan(tmp)
        got = any(r["id"] == rid and r["file"] == f"t{i}.go" for r in rows)
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
    ap.add_argument("--sarif", default="")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--pattern", default="")
    ap.add_argument("--exclude", action="append", default=[],
                    help="排除路径（可重复/逗号分隔），跳过 fixtures 与生成代码")
    args = ap.parse_args()
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
                json.dump(build_sarif(rows, tool_name="scan-go.py", root=SRC),
                          f, ensure_ascii=False, indent=1)
            print(f"SARIF → {args.sarif}（{len(rows)} 条）")
        except Exception as e:
            print(f"sarif 导出失败: {e}", file=sys.stderr)
        return

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print("scan-go · Go 缺陷模式扫描")
    print(f"源码根: {SRC}   Go 文件: {sum(1 for _ in iter_go(SRC))}   命中候选: {len(rows)}")
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
    print("\n候选 ≠ 结论：竞态要用 `go test -race` 证明，本扫描器只给线索。")


if __name__ == "__main__":
    main()
