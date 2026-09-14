#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cocos Creator 脚本审核扫描器 (cocos_audit.py)

静态扫描 TypeScript 脚本，找出 Cocos 项目里最常见的四类问题：
内存泄漏（P0）、性能陷阱（P1）、代码质量（P2）、生命周期误用（P1）。

**只出报告，不改写任何文件。**

用法：
    python3 scripts/cocos_audit.py <路径>             扫描目录或文件
    python3 scripts/cocos_audit.py <路径> --level P0   只看阻塞级
    python3 scripts/cocos_audit.py <路径> --json      输出 JSON
    python3 scripts/cocos_audit.py <路径> --top 20     只显示前 N 条

退出码：发现 P0 返回 1（可用于 CI 卡口），否则 0

注意：静态扫描只能抓"模式明显"的问题。漏报和误报都会存在——
它用来缩小人工审查范围，不是替代人工判断。
"""

import re
import sys
import json
import argparse
from pathlib import Path

# 排除目录：构建产物与依赖，扫它们没意义
EXCLUDE_DIRS = {"node_modules", "library", "build", "temp", ".git",
                "dist", "assets/scripts/editor", ".creator"}

LEVEL_DESC = {
    "P0": "阻塞（内存泄漏，线上会累积）",
    "P1": "严重（性能或生命周期误用）",
    "P2": "建议（代码质量）",
}

# ---------- 检测规则 ----------

# 成对关系：注册了就必须有对应的清理
PAIRS = [
    # (注册模式, 清理模式, 说明, 级别)
    (r"\.\s*on\s*\(", r"\.\s*(off|targetOff)\s*\(",
     "注册了事件监听但未找到对应的 off()/targetOff()", "P0"),
    (r"\b(scheduleOnce|schedule)\s*\(", r"\bunschedule(All)?(Callbacks)?\s*\(",
     "使用了 schedule 但未找到 unschedule/unscheduleAllCallbacks", "P0"),
    (r"\bsetInterval\s*\(", r"\bclearInterval\s*\(",
     "使用了 setInterval 但未找到 clearInterval", "P0"),
    (r"\bsetTimeout\s*\(", r"\bclearTimeout\s*\(",
     "使用了 setTimeout 但未找到 clearTimeout", "P0"),
]

# 资源加载：加载了就该释放
LOAD_PAT = [r"resources\.load\s*\(", r"assetManager\.load", r"bundle\.load\s*\(",
            r"loader\.loadRes\s*\("]
RELEASE_PAT = [r"\.release(Asset)?\s*\(", r"\.decRef\s*\(",
               r"releaseUnusedAssets\s*\(", r"\.releaseAll\s*\("]

# Tween：repeatForever 切场景后驻留内存（官方文档明确点名）
TWEEN_FOREVER = r"repeatForever\s*\("
TWEEN_STOP = [r"\.stop\s*\(", r"\.clear\s*\(",
              r"Tween\.stopAll", r"stopAllByTarget\s*\(", r"stopAllByTag\s*\("]

# 2.x 遗留 API（3.x 已废弃，官方升级指南要求替换）
LEGACY_2X = [
    (r"\bcc\.loader\b", "cc.loader 在 3.x 已废弃 → 改用 assetManager / resources.load", "P1"),
    (r"\bcc\.find\s*\(", "cc.find 是 2.x 写法 → 3.x 用 import { find } from 'cc'", "P2"),
    (r"\bcc\.director\.getScheduler\s*\(",
     "getScheduler 是 2.x 写法 → 3.x 用 this.schedule/unschedule", "P1"),
    (r"\bcc\.NodePool\b", "cc.NodePool 是 2.x 写法 → 3.x 用 import { NodePool } from 'cc'", "P2"),
    (r"\bcc\.tween\s*\(", "cc.tween 是 2.x 写法 → 3.x 用 import { tween } from 'cc'", "P2"),
]

# 物理误用
PHYSICS = [
    (r"ERigidBody2DType\.Dynamic|RigidBody2DType\.Dynamic|type\s*=\s*.*Dynamic",
     "使用了 Dynamic 刚体 —— 确认是否真会移动；静态物体应为 Static（引擎对静态有优化）", "P1"),
]

# UI 性能
UI_PERF = [
    (r"\.string\s*=", "修改 Label.string —— 确认 cacheMode 是否匹配更新频率（高频用 CHAR）", "P2"),
]

# DrawCall 相关
DRAWCALL = [
    (r"Mask", "使用了 Mask —— 会产生额外 DrawCall 与 Stencil 操作，滚动列表慎用", "P2"),
]

# 规则分组：--rule 可按类扫描
RULE_GROUPS = {
    "memory": ["成对缺失", "资源未释放", "tween泄漏", "匿名回调", "空清理"],
    "perf": ["update 性能", "代码质量", "UI性能", "DrawCall"],
    "migration": ["2.x遗留"],
    "physics": ["物理"],
}

# update 内禁止的操作
UPDATE_BAN = [
    (r"\b(find|getChildByName|getChildByPath)\s*\(",
     "在 update 中查找节点，每帧开销累积 → 缓存到 onLoad/start", "P1"),
    (r"\bgetComponent\s*\(",
     "在 update 中获取组件 → 缓存引用到 onLoad/start", "P1"),
    (r"\binstantiate\s*\(",
     "在 update 中实例化节点 → 改用 NodePool 对象池", "P1"),
    (r"\bnew\s+[A-Z]\w*",
     "在 update 中 new 对象，产生 GC 压力 → 复用外部对象", "P1"),
    (r"\bdestroy\s*\(",
     "在 update 中销毁节点 → 改用对象池回收", "P1"),
]

# 代码质量
QUALITY = [
    (r"console\.(log|info|debug|warn)\s*\(",
     "存在 console 输出，生产环境应移除或包在 CC_DEBUG 内", "P2"),
    (r":\s*any\b",
     "使用了 any 类型，丧失类型检查", "P2"),
]


def iter_ts(root: Path):
    """遍历 TypeScript 文件，跳过构建产物与依赖目录。"""
    if root.is_file():
        if root.suffix == ".ts":
            yield root
        return
    for p in root.rglob("*.ts"):
        if any(x in p.parts for x in EXCLUDE_DIRS):
            continue
        if p.name.endswith(".d.ts"):
            continue
        yield p


def strip_comments(text: str) -> str:
    """去掉注释，避免注释里的示例代码造成误报。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*$", "", text, flags=re.M)
    return text


def find_method_body(lines: list, start: int) -> tuple[int, int]:
    """给定方法定义行，返回方法体的 (起始行, 结束行)（0-based，含）。

    按缩进判断：cocos 组件方法通常 4 空格缩进，方法体 >= 8 空格。
    结束于下一个仅 4 空格缩进的 `}`。
    """
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        # 顶层闭合（缩进 ≤4 的 }）→ 方法结束
        if re.match(r"^\s{0,4}\}\s*$", ln):
            return start + 1, i
        i += 1
    return start + 1, len(lines)


def scan_file(path: Path, rel: str) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        return [{"file": rel, "line": 0, "level": "P2",
                 "rule": "读取失败", "msg": str(e)}]

    text = strip_comments(raw)
    lines = text.splitlines()
    issues = []

    def add(line_no, level, rule, msg):
        issues.append({"file": rel, "line": line_no + 1,
                       "level": level, "rule": rule, "msg": msg})

    # 1) 成对检查
    anon_lines = set()
    for i, l in enumerate(lines):
        if re.search(r"\.\s*on\s*\(", l):
            chunk = l + " " + (lines[i + 1] if i + 1 < len(lines) else "")
            if re.search(r"=>|function\s*\(", chunk):
                anon_lines.add(i)

    for reg, cleanup, desc, level in PAIRS:
        hits = [(i, l) for i, l in enumerate(lines) if re.search(reg, l)]
        if hits and not re.search(cleanup, text):
            for i, l in hits:
                # 匿名回调已单独立为 P1（"无法 off"），此处不重复报 P0，
                # 让 P0 只代表「用了类方法却忘了清理」这类确凿泄漏
                if i in anon_lines:
                    continue
                add(i, level, "成对缺失", f"{desc}（第 {i+1} 行注册）")

    # 2) 资源加载未释放
    loads = []
    for pat in LOAD_PAT:
        loads += [(i, l) for i, l in enumerate(lines) if re.search(pat, l)]
    if loads and not any(re.search(p, text) for p in RELEASE_PAT):
        for i, l in loads:
            add(i, "P0", "资源未释放",
                f"动态加载了资源但未找到 release/decRef（第 {i+1} 行）")

    # 3) update 方法体内的禁令
    for i, l in enumerate(lines):
        if re.match(r"^\s+(public\s+|private\s+|protected\s+)?update\s*\(", l):
            b_start, b_end = find_method_body(lines, i)
            body = "\n".join(lines[b_start:b_end])
            for pat, msg, level in UPDATE_BAN:
                for j in range(b_start, b_end):
                    if re.search(pat, lines[j]):
                        add(j, level, "update 性能", msg)
                        break   # 同一规则在同一 update 内只报一次

    # 3.5) Tween repeatForever 未 stop（官方：切场景后驻留内存）
    if re.search(TWEEN_FOREVER, text) and not any(
            re.search(p, text) for p in TWEEN_STOP):
        for i, l in enumerate(lines):
            if re.search(TWEEN_FOREVER, l):
                add(i, "P0", "tween泄漏",
                    "repeatForever 缓动未停止 —— 切换场景后仍驻留内存，"
                    "需在 onDestroy 调 stop() 或 Tween.stopAllByTarget(this.node)")

    # 4) 匿名函数注册事件（无法 off）
    for i, l in enumerate(lines):
        if re.search(r"\.\s*on\s*\(", l):
            # 同一行或紧跟的续行里出现 => 或 function(
            chunk = l + " " + (lines[i + 1] if i + 1 < len(lines) else "")
            if re.search(r"=>|function\s*\(", chunk):
                add(i, "P1", "匿名回调",
                    "事件回调用了匿名函数，之后无法精确 off → 改为类方法")

    # 4.5) 2.x 遗留 API（同一模式在一个文件内只报首次，附注出现次数，避免刷屏）
    for pat, msg, level in LEGACY_2X:
        hits = [i for i, l in enumerate(lines) if re.search(pat, l)]
        if hits:
            extra = f"（本文件共 {len(hits)} 处）" if len(hits) > 1 else ""
            add(hits[0], level, "2.x遗留", msg + extra)

    # 4.6) 物理误用
    for pat, msg, level in PHYSICS:
        for i, l in enumerate(lines):
            if re.search(pat, l):
                add(i, level, "物理", msg)

    # 4.7) UI 性能（只提示一次，避免刷屏）
    for pat, msg, level in UI_PERF:
        if re.search(pat, text) and "cacheMode" not in text:
            for i, l in enumerate(lines):
                if re.search(pat, l):
                    add(i, level, "UI性能", msg)
                    break

    for pat, msg, level in DRAWCALL:
        for i, l in enumerate(lines):
            if re.search(pat, l):
                add(i, level, "DrawCall", msg)
                break

    # 5) 空 onDestroy（有资源/监听却没清理）
    for i, l in enumerate(lines):
        if re.match(r"^\s+onDestroy\s*\(", l):
            b_start, b_end = find_method_body(lines, i)
            body = "\n".join(lines[b_start:b_end]).strip()
            if not body or body in ("{",):
                add(i, "P1", "空清理",
                    "onDestroy 为空 —— 确认是否真无需清理（监听/定时器/资源）")

    # 6) 代码质量
    for pat, msg, level in QUALITY:
        for i, l in enumerate(lines):
            if re.search(pat, l):
                if "console." in l and "CC_DEBUG" in text:
                    continue    # 已包在 CC_DEBUG 内，不报
                add(i, level, "代码质量", msg)

    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="Cocos 项目目录或单个 .ts 文件")
    ap.add_argument("--level", default="", help="只看某级：P0 / P1 / P2")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=0, help="只显示前 N 条")
    ap.add_argument("--rule", default="", help="按类扫描：" + "/".join(RULE_GROUPS))
    ap.add_argument("--rules", action="store_true", help="列出规则分组")
    args = ap.parse_args()

    if args.rules:
        for g, rules in RULE_GROUPS.items():
            print("  %-10s %s" % (g, "、".join(rules)))
        return
    if not args.path:
        ap.error("缺少 path（或用 --rules 查看规则分组）")

    root = Path(args.path).expanduser()
    if not root.exists():
        sys.exit("路径不存在：%s" % root)

    files = list(iter_ts(root))
    if not files:
        sys.exit("未找到 .ts 文件：%s（是否路径有误或全被排除？）" % root)

    all_issues = []
    for f in files:
        try:
            rel = str(f.relative_to(root)) if f != root else f.name
        except Exception:
            rel = str(f)
        all_issues += scan_file(f, rel)

    if args.level:
        all_issues = [i for i in all_issues if i["level"] == args.level.upper()]

    if args.rule:
        key = args.rule.lower()
        if key not in RULE_GROUPS:
            sys.exit("未知规则组：%s\n可用：%s"
                     % (args.rule, "、".join(RULE_GROUPS)))
        want = set(RULE_GROUPS[key])
        all_issues = [i for i in all_issues if i["rule"] in want]

    order = {"P0": 0, "P1": 1, "P2": 2}
    all_issues.sort(key=lambda x: (order.get(x["level"], 9), x["file"], x["line"]))

    if args.json:
        print(json.dumps(all_issues, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("Cocos 脚本审核：%s" % root)
        print("扫描 %d 个 .ts 文件，发现 %d 项" % (len(files), len(all_issues)))
        print("=" * 60)
        shown = all_issues[:args.top] if args.top else all_issues
        cur_file = None
        for it in shown:
            if it["file"] != cur_file:
                cur_file = it["file"]
                print("\n── %s" % cur_file)
            print("  [%s] L%-4d %-6s %s"
                  % (it["level"], it["line"], it["rule"], it["msg"]))
        if args.top and len(all_issues) > args.top:
            print("\n… 另有 %d 项未显示（--top 调整）" % (len(all_issues) - args.top))

        print("\n" + "-" * 60)
        for lv in ("P0", "P1", "P2"):
            n = sum(1 for i in all_issues if i["level"] == lv)
            if n:
                print("  %s %-22s %d 项" % (lv, LEVEL_DESC[lv], n))
        if not all_issues:
            print("  ✓ 未发现明显问题")
        print("\n提示：静态扫描只抓模式明显的问题，人工复核仍不可省")

    if any(i["level"] == "P0" for i in all_issues):
        sys.exit(1)


if __name__ == "__main__":
    main()
