#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scan-cpp.py — C/C++ 源码缺陷模式扫描（正则 + 结构启发式）

为什么单独一个扫描器
--------------------
`scan-ts.py` / `scan-app.py` 的模式按 TS/JS 语法编写，对 C/C++ 输出 0 命中——
**不是「没问题」，是压根没看**。

正则而非 AST：目标环境不保证有 clang / libclang。
本扫描器定位是**候选发现**，重点是「正常路径测不出来」的问题：
异常路径泄漏、虚假唤醒、符号转换回绕。
**证明越界与竞争要靠 ASan / TSan，本扫描器只给线索。**

用法
----
    python3 scan-cpp.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
    python3 scan-cpp.py --self-test        # 内置用例自检（改规则后必跑）
"""
import os
import re
import sys
import json
import argparse

SRC = "."
SKIP_DIRS = {".git", "build", "out", "cmake-build-debug", "cmake-build-release",
             "node_modules", "third_party", "vendor", "_build", ".deps"}
MAX_FILE_BYTES = 3 * 1024 * 1024
CPP_EXT = (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx", ".inl")


def iter_cpp(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(CPP_EXT):
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(p) > MAX_FILE_BYTES:
                        continue
                except OSError:
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


ALLOC = r"\b(malloc|calloc|realloc|new)\b"
FREE = r"\b(free|delete|delete\[\])\b"
SMART = r"\b(unique_ptr|shared_ptr|make_unique|make_shared|scoped_ptr|auto_ptr)\b"


def cpp_resource_ownership(src, lines, path):
    """CPP-01 裸资源无释放 / 异常路径泄漏"""
    if not re.search(ALLOC, src):
        return []
    if re.search(SMART, src):
        return []
    if re.search(FREE, src):
        return []
    out = []
    for n in find_line(lines, ALLOC):
        if has_pragma(lines, n):
            continue
        kind = "malloc/calloc/realloc" if re.search(r"\b(malloc|calloc|realloc)\b", lines[n - 1]) else "new"
        out.append((n, f"{kind} 分配但文件内无 free/delete 且未用智能指针 —— 异常路径必泄漏"))
    return out


UNSAFE_MEM = ["strcpy", "strcat", "sprintf", "gets", "vsprintf", "wcscpy", "alloca"]


def cpp_unsafe_string(src, lines, path):
    """CPP-02 不安全的字符串/内存函数"""
    out = []
    for fn_name in UNSAFE_MEM:
        rx = r"\b%s\s*\(" % fn_name
        for n in find_line(lines, rx):
            if has_pragma(lines, n):
                continue
            out.append((n, f"{fn_name}() 无长度限制 —— 外部输入可溢出，改 snprintf/strncpy/std::string"))
    # memcpy/memset 长度参数检查
    for fn_name in ("memcpy", "memmove", "memset"):
        for n in find_line(lines, r"\b%s\s*\(" % fn_name):
            if has_pragma(lines, n):
                continue
            seg = lines[n - 1]
            m = re.search(r"\b%s\s*\(([^;]*)\)" % fn_name, seg)
            args = m.group(1) if m else ""
            if re.search(r"sizeof\s*\(", args):
                continue          # sizeof 是安全长度
            if re.search(r"^\s*\w+\s*,\s*[^,]+,\s*(sizeof|[\d]+)\s*$", args):
                continue
            out.append((n, f"{fn_name}() 长度参数非 sizeof/常量 —— 确认是否可被外部控制"))
    return out


def cpp_bounds_risk(src, lines, path):
    """CPP-03 循环边界 `<=` 与 size 混用"""
    out = []
    for n in find_line(lines, r"for\s*\([^;]*;\s*\w+\s*<=?\s*\w+(\s*-\s*1)?\s*;"):
        if has_pragma(lines, n):
            continue
        seg = lines[n - 1]
        if re.search(r"<=\s*\w+", seg) and re.search(r"\.(size|length)\s*\(\s*\)|\bcount\b|\bn\b", seg):
            out.append((n, "循环用 `<=` 且上界来自 size/count —— 多半多访问一个（应为 <）"))
    return out


def cpp_data_race(src, lines, path):
    """CPP-04 共享数据无同步"""
    threads = re.search(r"std::thread|pthread_create|std::async|std::async|CreateThread|"
                        r"_beginthread|std::future|detach\s*\(", src)
    if not threads:
        return []
    if re.search(r"std::mutex|std::atomic|pthread_mutex|lock_guard|unique_lock|"
                 r"scoped_lock|std::recursive_mutex|CRITICAL_SECTION", src):
        return []
    globals_ = find_line(lines, r"^\s*(?:static\s+)?(?:extern\s+)?[\w:<>\*\s]+?\w+\s*(?:=\s*[^;]+)?;\s*$")
    if not globals_:
        return []
    out = []
    for n in find_line(lines, r"std::thread|pthread_create|std::async"):
        if has_pragma(lines, n):
            continue
        out.append((n, "起线程但无 mutex/atomic —— 文件级全局变量的读写存在数据竞争（UB）"))
    return out


def cpp_condvar_if(src, lines, path):
    """CPP-05 条件变量用 if 而非 while"""
    if not re.search(r"\.\s*wait\s*\(|wait_for\s*\(|wait_until\s*\(", src):
        return []
    out = []
    # ⚠ 条件里不能用 [^)]*：`if (q.empty())` 有两个 `)`，
    # [^)]* 跨不过 empty() 的那个，回溯后整行匹配失败 → 永远 0 命中
    for n in find_line(lines, r"\bif\s*\(.*\)\s*\{?\s*$"):
        if has_pragma(lines, n):
            continue
        # 向后 6 行内是否有 wait(
        ctx = "\n".join(lines[n - 1:n + 6])
        if re.search(r"\b\w+\s*\.\s*wait\s*\(", ctx) or re.search(r"wait\s*\(\s*\w*\s*,?\s*\w*\s*\)", ctx):
            if "while" not in ctx:
                out.append((n, "条件变量用 if 判断 —— 虚假唤醒会导致条件未满足就继续（应用 while 或谓词重载）"))
    return out


def cpp_dtor_risky(src, lines, path):
    """CPP-06 析构中的危险操作"""
    out = []
    for n in find_line(lines, r"~\s*\w+\s*\("):
        if has_pragma(lines, n):
            continue
        body = "\n".join(lines[n - 1:n + 40])
        end = body.find("~")
        seg = body[end:end + 900] if end >= 0 else body[:900]
        risky_lock = re.search(r"\block\s*\(\s*\)|\bunlock\s*\(\s*\)|lock_guard|"
                               r"pthread_mutex_lock|EnterCriticalSection", seg)
        risky_io = re.search(r"\bfopen\s*\(|\bsocket\s*\(|\bsend\s*\(|\brecv\s*\(|"
                             r"\bconnect\s*\(|\bwrite\s*\(|\bread\s*\(", seg)
        if risky_lock:
            out.append((n, "析构函数中加锁 —— 可能与持锁线程互等形成死锁（P0）"))
        elif risky_io:
            out.append((n, "析构函数中做 IO —— 失败无法上报，且可能访问已销毁成员"))
    return out


def cpp_dangling(src, lines, path):
    """CPP-07 返回局部变量引用 / 悬垂"""
    out = []
    for m in re.finditer(r"[\w:<>\*&\s]+&\s+\w+\s*\([^)]*\)\s*\{", src):
        n = src[:m.start()].count("\n") + 1
        if has_pragma(lines, n):
            continue
        body = src[m.end():m.end() + 1200]
        if re.search(r"return\s+\w+\s*;", body):
            # 返回的标识符是否在函数体内声明过（局部变量）
            declared = re.search(r"(?:^|;|\{)\s*(?:[\w:<>\*]+\s+)?(\w+)\s*(?:=|;)", body)
            if declared:
                out.append((n, "函数返回局部对象的引用 —— 返回即悬垂（应按值返回）"))
    # string_view 绑定临时对象
    for n in find_line(lines, r"string_view\s+\w+\s*=\s*std::string\s*\("):
        if not has_pragma(lines, n):
            out.append((n, "string_view 绑定 std::string 临时对象 —— 语句结束即悬垂"))
    return out


def cpp_int_conversion(src, lines, path):
    """CPP-08 无符号回绕 / 有符号混用"""
    out = []
    # size() - 1 形式
    for n in find_line(lines, r"\.(size|length)\s*\(\s*\)\s*-\s*1"):
        if has_pragma(lines, n):
            continue
        out.append((n, "size() - 1 —— 容器为空时下溢成巨大无符号数"))
    # 无符号反向循环
    for n in find_line(lines, r"for\s*\(\s*\w*[:\s]*size_t\s+\w+\s*="):
        if has_pragma(lines, n):
            continue
        if re.search(r">=\s*0", lines[n - 1]):
            out.append((n, "无符号循环变量与 `>= 0` —— 条件恒真，无限循环 + 越界"))
    # int 与 size_t 比较
    for n in find_line(lines, r"\bint\s+\w+\s*[<>]+\s*\w+\.(size|length)\s*\("):
        if not has_pragma(lines, n):
            out.append((n, "int 与 size_t 比较 —— 有符号被转无符号，负数变巨值"))
    return out


def cpp_uninitialized(src, lines, path):
    """CPP-09 内置类型未初始化即使用（粗判）"""
    out = []
    for n in find_line(lines, r"^\s*(int|float|double|bool|char|short|long|unsigned)\s+\w+\s*;"):
        if has_pragma(lines, n):
            continue
        if re.search(r"=\s*[^=]", lines[n - 1]):
            continue
        out.append((n, "内置类型声明时未初始化 —— 值不确定（不是 0），调试版与发布版可能不同"))
    return out


def cpp_policy_violation(src, lines, path):
    """CPP-10 违反项目运行时策略（异常/RTTI/thread_local）"""
    out = []
    checks = [
        (r"\bthrow\s+\w+", "throw —— 确认项目是否禁用异常（如 HotSpot Style）"),
        (r"\btry\s*\{", "try —— 确认项目是否禁用异常"),
        (r"\bdynamic_cast\s*<", "dynamic_cast —— 确认项目是否禁用 RTTI"),
        (r"\btypeid\s*\(", "typeid —— 确认项目是否禁用 RTTI"),
        (r"\bthread_local\b", "thread_local —— 确认项目是否限制线程局部存储"),
    ]
    for rx, msg in checks:
        for n in find_line(lines, rx):
            if has_pragma(lines, n):
                continue
            out.append((n, msg))
    return out


PATTERNS = [
    ("CPP-01", "P0", "裸资源无释放（异常路径泄漏）", cpp_resource_ownership),
    ("CPP-02", "P0", "不安全的内存/字符串函数", cpp_unsafe_string),
    ("CPP-03", "P1", "循环边界风险（<= 与 size 混用）", cpp_bounds_risk),
    ("CPP-04", "P0", "共享数据无同步（数据竞争）", cpp_data_race),
    ("CPP-05", "P0", "条件变量用 if（虚假唤醒）", cpp_condvar_if),
    ("CPP-06", "P1", "析构中的危险操作", cpp_dtor_risky),
    ("CPP-07", "P0", "悬垂引用/生命周期错误", cpp_dangling),
    ("CPP-08", "P1", "无符号回绕 / 有符号混用", cpp_int_conversion),
    ("CPP-09", "P1", "内置类型未初始化", cpp_uninitialized),
    ("CPP-10", "P2", "违反项目运行时策略", cpp_policy_violation),
]

SCENE = {"CPP-01": "p-cpp", "CPP-02": "p-cpp", "CPP-03": "p-cpp",
         "CPP-04": "s-concurrency", "CPP-05": "s-concurrency",
         "CPP-06": "s-concurrency", "CPP-07": "p-cpp", "CPP-08": "s-numerics",
         "CPP-09": "p-cpp", "CPP-10": "p-cpp"}


def scan(src):
    rows = []
    for p in iter_cpp(src):
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
                             "detail": msg, "scanner": "scan-cpp.py",
                             "scene": SCENE.get(rid, "")})
    return rows


SELF_TEST_CASES = [
    ("CPP-01", "void f() {\n    char* p = new char[64];\n    parse(p);\n}\n", True),
    ("CPP-02", "void f(char* in) {\n    char buf[64];\n    strcpy(buf, in);\n}\n", True),
    ("CPP-03", "void f(int n) {\n    for (int i = 0; i <= n; ++i) a[i] = 0;\n}\n", True),
    ("CPP-04", "int counter = 0;\nvoid f() {\n    std::thread t(work);\n    t.detach();\n}\n", True),
    ("CPP-05", "void f() {\n    if (q.empty()) {\n        cv.wait(lk);\n    }\n}\n", True),
    ("CPP-06", "class A {\npublic:\n    ~A() { lock(); cleanup(); }\n};\n", True),
    ("CPP-07", "const std::string& f() {\n    std::string s = \"x\";\n    return s;\n}\n", True),
    ("CPP-08", "void f(std::vector<int>& v) {\n    for (size_t i = v.size() - 1; i >= 0; --i) {}\n}\n", True),
    ("CPP-09", "void f() {\n    int count;\n    count += 1;\n}\n", True),
    ("CPP-10", "void f() {\n    throw std::runtime_error(\"x\");\n}\n", True),
    # 反向
    ("CPP-01", "void f() {\n    auto p = std::make_unique<char[]>(64);\n    parse(p.get());\n}\n", False),
    ("CPP-02", "void f(char* in) {\n    char buf[64];\n    memcpy(buf, in, sizeof(buf));\n}\n", False),
    ("CPP-03", "void f(int n) {\n    for (int i = 0; i < n; ++i) a[i] = 0;\n}\n", False),
    ("CPP-04", "std::mutex mu;\nint counter = 0;\nvoid f() {\n    std::thread t(work);\n    t.detach();\n}\n", False),
    ("CPP-05", "void f() {\n    while (q.empty()) {\n        cv.wait(lk);\n    }\n}\n", False),
    ("CPP-07", "std::string f() {\n    std::string s = \"x\";\n    return s;\n}\n", False),
    ("CPP-09", "void f() {\n    int count = 0;\n    count += 1;\n}\n", False),
]


def self_test():
    global SRC
    import tempfile
    ok = fail = 0
    tmp = tempfile.mkdtemp()
    SRC = tmp
    for i, (rid, code, want) in enumerate(SELF_TEST_CASES):
        f = os.path.join(tmp, f"t{i}.cpp")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(code)
        rows = scan(tmp)
        got = any(r["id"] == rid and r["file"] == f"t{i}.cpp" for r in rows)
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
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())

    global SRC
    SRC = os.path.abspath(args.src)
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
                json.dump(build_sarif(rows, tool_name="scan-cpp.py", root=SRC),
                          f, ensure_ascii=False, indent=1)
            print(f"SARIF → {args.sarif}（{len(rows)} 条）")
        except Exception as e:
            print(f"sarif 导出失败: {e}", file=sys.stderr)
        return

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return

    print("scan-cpp · C/C++ 缺陷模式扫描")
    print(f"源码根: {SRC}   C/C++ 文件: {sum(1 for _ in iter_cpp(SRC))}   命中候选: {len(rows)}")
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
    print("\n候选 ≠ 结论：越界与竞争要用 ASan/TSan 证明，本扫描器只给线索。")


if __name__ == "__main__":
    main()
