#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境探测 (env.py)

技能会因环境而异——Python 3.8 与 3.12 的写法不同、Windows 与 Linux 的命令不同、
有 rg 和没 rg 的做法不同。**这些不是冲突，是版本分化**，两条都要留。

职责：
  1. 探测当前环境（Python 版本、操作系统、可用工具）
  2. 解析技能的 `applies_to` 约束表达式
  3. 判断某技能是否适用于当前环境

用法：
    python3 scripts/env.py                      打印当前环境
    python3 scripts/env.py --check "python>=3.9"  检查约束是否满足
    python3 scripts/env.py --json               输出 JSON（供其他脚本调用）
"""

import os
import re
import sys
import json
import shutil
import argparse
import subprocess

# 常用工具：探测到就可在技能里放心使用
TOOLS = ["rg", "git", "zip", "unzip", "jq", "curl", "wget", "sed", "awk",
         "tar", "ffmpeg", "pandoc", "node", "npm", "docker", "make"]


def _run(cmd: list) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except Exception:
        return ""


def detect() -> dict:
    """探测当前环境。失败时返回保守值，不让探测失败阻塞主流程。"""
    py = _run([sys.executable, "-c",
               "import sys;print('%d.%d.%d'%sys.version_info[:3])"]) or \
         f"{sys.version_info.major}.{sys.version_info.minor}.0"
    tools = {t: bool(shutil.which(t)) for t in TOOLS}
    return {
        "python": py,
        "python_major_minor": ".".join(py.split(".")[:2]),
        "os": "windows" if os.name == "nt" else "posix",
        "platform": sys.platform,          # linux / darwin / win32
        "shell": "cmd" if os.name == "nt" else "bash",
        "tools": tools,
        "available_tools": [t for t, ok in tools.items() if ok],
    }


def _ver_tuple(s: str):
    parts = re.findall(r"\d+", s or "")
    return tuple(int(p) for p in (parts + ["0", "0", "0"])[:3])


def matches(spec: str, env: dict = None) -> bool:
    """判断 applies_to 约束是否满足当前环境。

    支持的写法（逗号/分号分隔，全部满足才算匹配）：
        python>=3.8        python<3.12       python==3.10
        os:windows         os:linux          os:darwin
        shell:bash         shell:cmd
        rg / !rg           有(无)某工具
        py>=3.9            简写，等同 python>=3.9
    空约束 → 视为通用，恒匹配。
    """
    if not spec or not spec.strip() or spec.strip() in ("*", "all", "-"):
        return True
    env = env or detect()

    for clause in re.split(r"[,;]", spec):
        c = clause.strip()
        if not c:
            continue
        low = c.lower()

        # 工具存在性：rg / !rg
        m = re.fullmatch(r"(!)?([a-zA-Z_][\w-]*)", c)
        if m and (m.group(2).lower() in [t.lower() for t in TOOLS]):
            has = bool(shutil.which(m.group(2)))
            if m.group(1) and has:
                return False
            if not m.group(1) and not has:
                return False
            continue

        # 版本比较：python>=3.8 / py<3.12 / python==3.10
        m = re.fullmatch(r"(?:python|py)\s*(>=|<=|==|!=|>|<)\s*([\d.]+)", low)
        if m:
            op, want = m.group(1), _ver_tuple(m.group(2))
            cur = _ver_tuple(env.get("python", "0"))
            if op == ">=" and not cur >= want: return False
            if op == "<=" and not cur <= want: return False
            if op == ">" and not cur > want: return False
            if op == "<" and not cur < want: return False
            if op == "==" and not cur == want: return False
            if op == "!=" and not cur != want: return False
            continue

        # 操作系统
        m = re.fullmatch(r"os\s*:\s*(\w+)", low)
        if m:
            want = m.group(1)
            plat = env.get("platform", "")
            ok = (want == env.get("os")) or plat.startswith(want[:5])
            if not ok:
                return False
            continue

        # Shell
        m = re.fullmatch(r"shell\s*:\s*(\w+)", low)
        if m:
            if m.group(1) != env.get("shell"):
                return False
            continue

        # 无法识别的子句：保守放行，不因为解析不了就屏蔽技能
    return True


INF = (999, 999, 999)
ZERO = (0, 0, 0)


def _ver_range(spec: str):
    """把版本约束解析成半开区间 [lo, hi)，hi 为排他上界。

    例：python>=3.9        → [(3,9,0), INF)
        python<3.9         → [ZERO, (3,9,0))
        python>=3.8,py<4   → [(3,8,0), (4,0,0))
    """
    lo, hi = ZERO, INF
    for op, v in re.findall(r"(?:python|py)\s*(>=|<=|==|!=|>|<)\s*([\d.]+)", spec.lower()):
        t = _ver_tuple(v)
        if op in (">=", ">"):
            lo = max(lo, t)
        elif op in ("<=", "<"):
            hi = min(hi, t)
        elif op == "==":
            lo, hi = max(lo, t), min(hi, t)
    return lo, hi


def overlap(a: str, b: str) -> bool:
    """判断两条约束的适用环境是否重叠。

    重叠   → 可能是真冲突（同一环境下两种做法）
    不重叠 → **版本分化**，两条都要留，不是谁对谁错

    判定偏保守：宁可判为「不重叠」而多留两条，也不误判为冲突删掉一条。
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b or a in ("*", "-") or b in ("*", "-"):
        return True                      # 有一方通用 → 环境可能重叠

    va = re.search(r"(?:python|py)\s*(?:>=|<=|==|!=|>|<)\s*\d", a.lower())
    vb = re.search(r"(?:python|py)\s*(?:>=|<=|==|!=|>|<)\s*\d", b.lower())
    if va and vb:
        lo_a, hi_a = _ver_range(a)
        lo_b, hi_b = _ver_range(b)
        # 半开区间相交：需两端都严格小于对方的排他上界
        if not (lo_a < hi_b and lo_b < hi_a):
            return False

    oa = re.search(r"os\s*:\s*(\w+)", a.lower())
    ob = re.search(r"os\s*:\s*(\w+)", b.lower())
    if oa and ob and oa.group(1) != ob.group(1):
        return False                     # 系统互斥 → 不重叠

    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="约束", help="检查约束是否满足当前环境")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    env = detect()
    if args.check:
        ok = matches(args.check, env)
        print(f"{'✓ 适用' if ok else '✗ 不适用'}：{args.check}  （当前 {env['python']} / {env['platform']}）")
        sys.exit(0 if ok else 1)
    if args.json:
        print(json.dumps(env, ensure_ascii=False, indent=2))
        return
    print(f"Python  : {env['python']}  ({env['platform']})")
    print(f"OS      : {env['os']}    Shell: {env['shell']}")
    print(f"可用工具: {', '.join(env['available_tools']) or '（无）'}")


if __name__ == "__main__":
    main()
