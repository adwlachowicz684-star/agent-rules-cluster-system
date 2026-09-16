#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cocos Creator 脚本审核扫描器 (cocos-audit.py)

静态扫描 TypeScript 脚本，找出 Cocos 项目里最常见的四类问题：
内存泄漏（P0）、性能陷阱（P1）、代码质量（P2）、生命周期误用（P1）。

**只出报告，不改写任何文件。**

用法：
    python3 scripts/cocos-audit.py <路径>             扫描目录或文件
    python3 scripts/cocos-audit.py <路径> --level P0   只看阻塞级
    python3 scripts/cocos-audit.py <路径> --json      输出 JSON
    python3 scripts/cocos-audit.py <路径> --top 20     只显示前 N 条
    python3 scripts/cocos-audit.py --self-test        自检（改规则后必跑）

退出码：发现 P0 返回 1（可用于 CI 卡口），否则 0

注意：静态扫描只能抓"模式明显"的问题。漏报和误报都会存在——
它用来缩小人工审查范围，不是替代人工判断。
"""

import re
import sys
import json
import argparse
import tempfile
import shutil
from pathlib import Path

# 排除目录：构建产物与依赖，扫它们没意义。
# 分两类写：EXCLUDE_PARTS 按路径分段精确匹配；EXCLUDE_SUBSTR 按相对路径子串匹配。
#
# 为什么分两类：原先只写 {"...", "assets/scripts/editor"}，而 p.parts 是
# 单个分段（'assets','scripts','editor'），永远不会有分段等于含斜杠的
# "assets/scripts/editor" —— 这条排除**从未生效**，编辑器插件一直被扫进来。
# 写进了配置却不生效，比不写更危险：读代码的人以为已经排除了。
EXCLUDE_PARTS = {"node_modules", "library", "build", "temp", ".git",
                 "dist", ".creator"}
EXCLUDE_SUBSTR = ("assets/scripts/editor",)

LEVEL_DESC = {
    "P0": "阻塞（内存泄漏，线上会累积）",
    "P1": "严重（性能或生命周期误用）",
    "P2": "建议（代码质量）",
}

# 清理应当出现在哪些生命周期方法里
CLEANUP_METHODS = ("ondestroy", "ondisable")

# ---------- 检测规则 ----------

# 成对关系：注册了就必须有对应的清理
# (注册模式, 清理模式, 说明, 级别)
PAIRS = [
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
    (r"(ERigidBody2DType|RigidBody2DType)\.Dynamic",
     "使用了 Dynamic 刚体 —— 确认是否真会移动；静态物体应为 Static（引擎对静态有优化）", "P1"),
]

# UI 性能
UI_PERF = [
    (r"\.string\s*=", "修改 Label.string —— 确认 cacheMode 是否匹配更新频率（高频用 CHAR）", "P2"),
]

# DrawCall 相关。
# 只认「实际挂到节点上」的写法：import 语句里的 `Mask` 类型、变量名里的
# `_isMasked` / `maskLayer` 都不是组件使用，裸词 `Mask` 会让它们全部误报。
DRAWCALL = [
    (r"(addComponent|getComponent|getComponentInChildren)\s*\(\s*Mask\b",
     "挂载/获取了 Mask —— 会产生额外 DrawCall 与 Stencil 操作，滚动列表慎用", "P2"),
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


def excluded(path: Path, root: Path) -> bool:
    """是否应跳过该文件。"""
    if set(path.parts) & EXCLUDE_PARTS:
        return True
    try:
        rel = path.relative_to(root).as_posix()
    except Exception:
        rel = path.as_posix()
    return any(s in rel for s in EXCLUDE_SUBSTR)


def iter_ts(root: Path):
    """遍历 TypeScript 文件，跳过构建产物与依赖目录。"""
    if root.is_file():
        if root.suffix == ".ts":
            yield root
        return
    for p in root.rglob("*.ts"):
        if excluded(p, root):
            continue
        if p.name.endswith(".d.ts"):
            continue
        yield p


def strip_comments(src: str) -> str:
    """剥离 // 与 /* */，保持行数与每行长度守恒（行号才不会错位）。

    为什么要守恒：原先直接用 re.sub 删注释，多行块注释被整段删掉后
    后续所有行号**前移**——实测真实注册在第 12 行，报告写 L7（偏移正好
    等于被删的注释行数）。用户按行号去找，看到的是注释里的示例代码。

    为什么必须识别字符串：`const u = 'http://x.com'; this.node.on(...)`
    这一行里的 // 不是注释，按注释删会把后面的真实注册一起吞掉 → 漏报。
    游戏代码里 URL 常量极常见，这个坑踩中率很高。
    """
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith('/*', i):
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append('\n' * src.count('\n', i, j))   # 用换行补齐，保持行数
            i = j
        elif src.startswith('//', i):
            j = src.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))                  # 用空格补齐，保持列位
            i = j
        elif src[i] in '"\'`':
            q, k = src[i], i + 1
            while k < n:
                if src[k] == '\\':
                    k += 2
                    continue
                if src[k] == q:
                    k += 1
                    break
                if src[k] == '\n' and q != '`':
                    break
                k += 1
            out.append(src[i:k])
            i = k
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def find_method_body(lines: list, start: int) -> tuple[int, int, str | None]:
    """给定方法定义行，返回 (起始行, 结束行, 单行体文本)。

    按缩进判断：cocos 组件方法通常 4 空格缩进，方法体 >= 8 空格。
    结束于下一个仅 4 空格缩进的 `}`。

    第三个返回值：单行写法时返回 `{` 与 `}` 之间的内容（可能为 ''）；
    多行写法返回 None，此时调用方用 lines[b_start:b_end]。

    必须处理**单行写法**，且不只是空实现：
      `onDestroy() {}`                 ← 单行空（最常见的空写法）
      `onEnable() { input.on(...); }`  ← 单行有内容
    原实现只认空实现，遇到单行有内容的会把**后续所有方法**当成它的 body —
    实测 `onEnable(){...}` / `onDisable(){}` / `onDestroy(){...}` 连写时，
    onEnable 的 body 一路吞到类末尾，作用域判定全错。
    """
    head = lines[start]
    stripped = head.rstrip()
    # 单行写法：同一行内既有 { 又有 }，且 } 在 { 之后
    o, c = stripped.rfind('{'), stripped.rfind('}')
    if o >= 0 and c > o:
        return start, start, stripped[o + 1:c].strip()
    i = start + 1
    while i < len(lines):
        if re.match(r"^\s{0,4}\}\s*$", lines[i]):
            return start + 1, i, None
        i += 1
    return start + 1, len(lines), None


def body_text(lines: list, span) -> str:
    """取方法体文本。span = (name, b_start, b_end, inline)。"""
    _, s, e, inline = span
    return inline if inline is not None else "\n".join(lines[s:e])


def method_spans(lines: list) -> list[tuple[str, int, int, str | None]]:
    """提取类里所有方法的 (名字, 起始行, 结束行, 单行体)。用于按作用域判定清理。"""
    spans = []
    for i, l in enumerate(lines):
        m = re.match(r"^\s{1,8}(?:public\s+|private\s+|protected\s+)?"
                     r"(onLoad|onEnable|start|update|lateUpdate|onDisable|onDestroy"
                     r"|[a-zA-Z_]\w*)\s*\(", l)
        if not m:
            continue
        b_start, b_end, inline = find_method_body(lines, i)
        spans.append((m.group(1).lower(), b_start, b_end, inline))
    return spans


def call_span(lines: list, i: int) -> str:
    """从 lines[i] 起，取到该语句结束（括号配平或分号），用于判断匿名回调。

    原实现只看「当前行 + 下一行」，跨行书写的匿名回调
    （`on(EVT, (a, b) => {...})` 写成多行）一律漏检。
    """
    buf, depth, j = [], 0, i
    while j < len(lines) and j < i + 12:
        buf.append(lines[j])
        depth += lines[j].count('(') - lines[j].count(')')
        if depth <= 0 and (';' in lines[j] or ')' in lines[j]):
            break
        j += 1
    return ' '.join(buf)


def scan_file(path: Path, rel: str) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        return [{"file": rel, "line": 0, "level": "P2",
                 "rule": "读取失败", "msg": str(e)}]

    text = strip_comments(raw)
    lines = text.splitlines()
    issues = []
    spans = method_spans(lines)

    def add(line_no, level, rule, msg):
        issues.append({"file": rel, "line": line_no + 1,
                       "level": level, "rule": rule, "msg": msg})

    def method_of(idx: int) -> str:
        """判断某行落在哪个方法体内。单行写法的方法，body 就是它自己那一行。"""
        for name, s, e, inline in spans:
            if inline is not None:
                if s <= idx <= e:
                    return name
            elif s <= idx < e:
                return name
        return ""

    # 1) 成对检查（按作用域，见下方说明）
    anon_lines = set()
    for i, l in enumerate(lines):
        if re.search(r"\.\s*on\s*\(", l):
            if re.search(r"=>|function\s*\(", call_span(lines, i)):
                anon_lines.add(i)

    # 清理是否出现在「清理类方法」体内。
    #
    # 原实现是 `not re.search(cleanup, text)` —— **全文**搜一次就算已清理。
    # 实测后果：一个文件里 3 处 on() 全都没 off，但只要别的方法里出现过
    # 一次 off()，这 3 处全部不报。真实泄漏被当成已处理，属于最危险的一类
    # 漏报（报告说没问题，实际有问题）。
    for reg, cleanup, desc, level in PAIRS:
        hits = [(i, l) for i, l in enumerate(lines) if re.search(reg, l)]
        if not hits:
            continue
        for i, l in hits:
            # 匿名回调已单独立为 P1（"无法 off"），此处不重复报 P0
            if i in anon_lines:
                continue
            where = method_of(i)
            # 注册点的**位置**决定清理点必须在哪。
            #
            # onEnable 里注册的（全局/输入监听）必须由 onDisable 清理：
            # 只在 onDestroy 里 off 的话，节点 setActive(false) 期间监听仍然
            # 生效——隐藏的节点继续被事件驱动。这是 p-cocos.md「已知坑」里
            # 明写的一条，但原实现把 onDestroy/onDisable 一视同仁，
            # 「onEnable 注册 + onDisable 空 + onDestroy 有 off」完全不报。
            #
            # 注意这与「引擎是否对重复注册去重」无关：即便去重，
            # 禁用期间监听仍在生效本身就是缺陷。
            need = ("ondisable",) if where == "onenable" else CLEANUP_METHODS
            cleaned = any(name in need and re.search(cleanup, body_text(lines, sp))
                          for sp in spans
                          for name in (sp[0],))
            if cleaned:
                continue
            tail = f"（在 {where}() 内注册）" if where else ""
            if where == "onenable":
                desc2 = (f"onEnable 注册的监听未在 onDisable 注销 —— "
                         f"节点禁用期间监听仍生效，需配 onDisable")
            else:
                desc2 = desc
            add(i, level, "成对缺失", f"{desc2}（第 {i+1} 行{tail}）")

    # 2) 资源加载未释放
    loads = []
    for pat in LOAD_PAT:
        loads += [(i, l) for i, l in enumerate(lines) if re.search(pat, l)]
    if loads:
        released = False
        for sp in spans:
            if sp[0] not in CLEANUP_METHODS:
                continue
            if any(re.search(p, body_text(lines, sp)) for p in RELEASE_PAT):
                released = True
                break
        if not released:
            for i, l in loads:
                add(i, "P0", "资源未释放",
                    f"动态加载了资源但未找到 release/decRef（第 {i+1} 行）")

    # 3) update 方法体内的禁令
    for i, l in enumerate(lines):
        if re.match(r"^\s+(public\s+|private\s+|protected\s+)?update\s*\(", l):
            b_start, b_end, inline = find_method_body(lines, i)
            scan_lines = [i] if inline is not None else range(b_start, b_end)
            scan_text = inline if inline is not None else None
            for pat, msg, level in UPDATE_BAN:
                if scan_text is not None:
                    if re.search(pat, scan_text):
                        add(i, level, "update 性能", msg)
                    continue
                for j in scan_lines:
                    if re.search(pat, lines[j]):
                        add(j, level, "update 性能", msg)
                        break   # 同一规则在同一 update 内只报一次

    # 3.5) Tween repeatForever 未 stop（官方：切场景后驻留内存）
    if re.search(TWEEN_FOREVER, text):
        stopped = any(
            any(re.search(p, body_text(lines, sp)) for p in TWEEN_STOP)
            for sp in spans if sp[0] in CLEANUP_METHODS
        )
        if not stopped:
            for i, l in enumerate(lines):
                if re.search(TWEEN_FOREVER, l):
                    add(i, "P0", "tween泄漏",
                        "repeatForever 缓动未停止 —— 切换场景后仍驻留内存，"
                        "需在 onDestroy 调 stop() 或 Tween.stopAllByTarget(this.node)")

    # 4) 匿名函数注册事件（无法 off）
    for i in sorted(anon_lines):
        add(i, "P1", "匿名回调",
            "事件回调用了匿名函数，之后无法精确 off → 改为类方法")

    # 4.5) 2.x 遗留 API（同一模式在一个文件内只报首次，附注出现次数）
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
            b_start, b_end, inline = find_method_body(lines, i)
            body = (inline if inline is not None
                    else "\n".join(lines[b_start:b_end])).strip()
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


# ---------- 自检 ----------
# 为什么必须有：本技能自己的规则写明「永远 0 命中的检查等于没有检查」。
# 其余 7 个扫描器（scan-ts/app/py/go/java/cpp/rust）都带 --self-test，
# cocos-audit.py 是唯一没有的——改规则后无从判断改好还是改坏。

SELF_LEAK = """import { _decorator, Component, Node, Tween, tween, resources, SpriteFrame } from 'cc';
const { ccclass } = _decorator;
/*
 * 块注释 3 行，用来验证行号不会错位
 * 下面这行是示例代码，不应被当成真实注册：
 * this.node.on('fake', cb);
 */
@ccclass('Leak')
export class Leak extends Component {
    private _sp: SpriteFrame = null!;
    onLoad() {
        this.node.on(Node.EventType.TOUCH_START, this.onTouch, this);
        this.schedule(this.tick, 1);
        setInterval(() => {}, 1000);
        tween(this.node).repeatForever(tween().to(1, { angle: 360 })).start();
        resources.load('bg/spriteFrame', SpriteFrame, (err, sp) => { this._sp = sp; });
    }
    onDestroy() {}
    private onTouch() {}
    private tick() {}
    update(dt: number) {
        const n = find('Canvas');
        this.getComponent(Node);
    }
}
"""

SELF_CLEAN = """import { _decorator, Component, Node, Tween } from 'cc';
const { ccclass } = _decorator;
@ccclass('Clean')
export class Clean extends Component {
    private _t: Tween<Node> = null!;
    onLoad() {
        this.node.on('e', this.h, this);
        this.schedule(this.tick, 1);
        this._t = tween(this.node).repeatForever(tween().to(1, {})).start();
    }
    onDestroy() {
        this.node.off('e', this.h, this);
        this.unscheduleAllCallbacks();
        this._t.stop();
    }
    private h() {}
    private tick() {}
}
"""

SELF_FALSE_CLEANUP = """import { _decorator, Component } from 'cc';
const { ccclass } = _decorator;
@ccclass('FakeClean')
export class FakeClean extends Component {
    onLoad() {
        this.node.on('e1', this.h1, this);
        this.node.on('e2', this.h2, this);
    }
    private other() { someNode.off('x', this.h1, this); }
    private h1() {}
    private h2() {}
}
"""

SELF_URL = """import { _decorator, Component } from 'cc';
const { ccclass } = _decorator;
const API = 'http://x.com/a';
@ccclass('U')
export class U extends Component {
    onLoad() { this.node.on('e', this.h, this); }
    private h() {}
}
"""

# onEnable 注册 + onDisable 空 + onDestroy 有 off
# → 节点禁用期间监听仍生效，必须报（原实现不报）
SELF_ENABLE = """import { _decorator, Component, input, Input } from 'cc';
const { ccclass } = _decorator;
@ccclass('En')
export class En extends Component {
    onEnable() { input.on(Input.EventType.TOUCH_MOVE, this.onMove, this); }
    onDisable() {}
    onDestroy() { input.off(Input.EventType.TOUCH_MOVE, this.onMove, this); }
    private onMove() {}
}
"""

# 同一个类里 onEnable/onDisable 正确配对 → 不该报
SELF_ENABLE_OK = """import { _decorator, Component, input, Input } from 'cc';
const { ccclass } = _decorator;
@ccclass('EnOk')
export class EnOk extends Component {
    onEnable() { input.on(Input.EventType.TOUCH_MOVE, this.onMove, this); }
    onDisable() { input.off(Input.EventType.TOUCH_MOVE, this.onMove, this); }
    private onMove() {}
}
"""


def self_test() -> int:
    tmp = tempfile.mkdtemp(prefix='cocos-audit-self-')
    try:
        cases = {
            'leak.ts': SELF_LEAK,
            'clean.ts': SELF_CLEAN,
            'fake.ts': SELF_FALSE_CLEANUP,
            'url.ts': SELF_URL,
            'en.ts': SELF_ENABLE,
            'enok.ts': SELF_ENABLE_OK,
        }
        res = {}
        for name, src in cases.items():
            p = Path(tmp) / name
            p.write_text(src, encoding='utf-8')
            res[name] = scan_file(p, name)

        ok, fail = 0, []

        def check(cond, label):
            nonlocal ok
            if cond:
                ok += 1
                print('  ✓ %s' % label)
            else:
                fail.append(label)
                print('  ✗ %s' % label)

        def rules(name, lv=None):
            return {i['rule'] for i in res[name]
                    if lv is None or i['level'] == lv}

        # 1) 泄漏样本：五类 P0 都要命中
        p0 = rules('leak.ts', 'P0')
        for r in ('成对缺失', 'tween泄漏', '资源未释放'):
            check(r in p0, 'leak.ts 命中 %s（P0）' % r)
        check('update 性能' in rules('leak.ts', 'P1'),
              'leak.ts 命中 update 性能（P1）')
        check('空清理' in rules('leak.ts'),
              'leak.ts 命中 空清理（onDestroy(){} 单行空实现）')

        # 2) 行号守恒：真实注册在第 11 行，块注释不得让行号前移
        on_hits = [i['line'] for i in res['leak.ts']
                   if i['rule'] == '成对缺失' and '事件监听' in i['msg']]
        real = next(i + 1 for i, l in enumerate(SELF_LEAK.splitlines())
                    if 'this.node.on(Node.EventType' in l)
        check(bool(on_hits) and on_hits[0] == real,
              '行号守恒：报 L%s，实际 L%s（块注释未致错位）'
              % (on_hits[0] if on_hits else '?', real))

        # 3) 干净样本：不该有 P0
        check(not [i for i in res['clean.ts'] if i['level'] == 'P0'],
              'clean.ts 无 P0（已配对清理的不误报）')

        # 4) 伪清理：别处有 off 但不在 onDestroy/onDisable → 仍要报
        check('成对缺失' in rules('fake.ts'),
              'fake.ts 仍报 成对缺失（清理不在 onDestroy/onDisable 不算数）')

        # 5) URL 里的 // 不得吞掉真实注册
        check('成对缺失' in rules('url.ts'),
              'url.ts 仍报 成对缺失（字符串里的 // 未被误当注释）')

        # 6) 注释里的示例代码不得被当成真实注册
        check(all('fake' not in i['msg'] for i in res['leak.ts']),
              '块注释里的示例代码未被计入')

        # 7) onEnable 注册必须配 onDisable（只在 onDestroy off 不算）
        check('成对缺失' in rules('en.ts'),
              'en.ts 报 成对缺失（onEnable 注册 + onDisable 空 + onDestroy 有 off）')
        check(any('onEnable' in i['msg'] for i in res['en.ts']),
              'en.ts 的报文明示是 onEnable/onDisable 不配对')
        check(not [i for i in res['enok.ts'] if i['level'] == 'P0'],
              'enok.ts 无 P0（onEnable/onDisable 正确配对不误报）')

        print('\n自检：%d 通过 / %d 失败' % (ok, len(fail)))
        if fail:
            for f in fail:
                print('  失败：%s' % f)
            return 1
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="Cocos 项目目录或单个 .ts 文件")
    ap.add_argument("--level", default="", help="只看某级：P0 / P1 / P2")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=0, help="只显示前 N 条")
    ap.add_argument("--rule", default="", help="按类扫描：" + "/".join(RULE_GROUPS))
    ap.add_argument("--rules", action="store_true", help="列出规则分组")
    ap.add_argument("--self-test", action="store_true", help="跑自检")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    if args.rules:
        for g, rules in RULE_GROUPS.items():
            print("  %-10s %s" % (g, "、".join(rules)))
        return
    if not args.path:
        ap.error("缺少 path（或用 --rules 查看规则分组 / --self-test 自检）")

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
