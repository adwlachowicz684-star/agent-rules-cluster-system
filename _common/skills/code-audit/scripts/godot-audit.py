#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Godot 4.x 脚本审核扫描器 (godot-audit.py)

静态扫描 GDScript (.gd) 与 C# (.cs)，找出 Godot 项目里最常见的三类问题：
所有权/泄漏（P0）、3.x 迁移残留与生命周期误用（P1）、性能提示（P2）。

**只出报告，不改写任何文件。**

用法：
    python3 scripts/godot-audit.py <路径>              扫描目录或文件
    python3 scripts/godot-audit.py <路径> --level P0    只看阻塞级
    python3 scripts/godot-audit.py <路径> --lang gd     只看 GDScript（gd/cs）
    python3 scripts/godot-audit.py <路径> --json        输出 JSON
    python3 scripts/godot-audit.py --rules              列出规则
    python3 scripts/godot-audit.py --self-test          自检（改规则后必跑）

退出码：发现 P0 返回 1（可用于 CI 卡口），否则 0

边界（重要）：
静态检查只能证明**所有权关系可疑**，不能证明运行时一定泄漏。
Godot 的信号自动断开、Tween 绑定、C# lambda 捕获、Resource 缓存都依赖
运行期对象关系，命中后必须人工确认。本脚本的输出是**候选**，不是结论。
"""

import re
import sys
import json
import argparse
import tempfile
import shutil
from pathlib import Path

# 构建产物与引擎缓存，扫它们没意义。
# C# 侧要额外排除 bin/obj/.mono —— Godot 的 C# 构建产物，
# 里面是 MSBuild 生成代码，扫进去全是噪声。
EXCLUDE_PARTS = {".git", ".godot", ".mono", "build", "builds", "dist",
                 "bin", "obj", "node_modules", ".vs", ".idea"}
EXCLUDE_SUFFIX = (".g.cs", ".designer.cs", ".generated.cs")

LEVEL_DESC = {
    "P0": "阻塞（所有权/泄漏，跨场景会累积）",
    "P1": "严重（迁移残留或生命周期误用）",
    "P2": "建议（性能提示）",
}

GD_EXT = (".gd",)
CS_EXT = (".cs",)

# 帧回调（规范化名：去下划线转小写）
FRAME_METHODS = {"process", "physicsprocess"}
# 清理回调
CLEANUP_METHODS = {"exittree", "notification"}

# ---------- 规则表 ----------
# scope: file=全文逐行 / frame=仅帧回调内 / special=需上下文判断

LINE_RULES = [
    # --- 3.x 迁移残留（P1）---
    ("GD04", "P1", "旧式信号", "gd", r"\.connect\s*\(\s*[\"'][^\"']+[\"']",
     "GDScript 旧式字符串信号 connect —— 4.x 用 signal.connect(callable)",
     "改为 `button.pressed.connect(_on_pressed)`；断开前先 `is_connected()` 判断"),
    ("GD04", "P1", "旧式信号", "cs", r"\.Connect\s*\(\s*[\"'][^\"']+[\"']",
     "C# 旧式字符串信号 Connect —— 4.x 优先事件 `+=` 或 SignalName",
     "改为 `button.Pressed += OnPressed;`；GDScript 自定义信号要保存 delegate 才能 `-=`"),
    ("GD05", "P1", "旧式注解", "gd", r"^\s*(export|onready)\s",
     "GDScript 3.x 注解 —— 4.x 为 @export / @onready",
     "加 @ 前缀：`@export var speed := 10.0`"),
    ("GD06", "P1", "旧式协程", "gd", r"\byield\s*\(",
     "yield 在 4.x 已移除 —— 改用 await",
     "`yield(get_tree(), \"idle_frame\")` → `await get_tree().process_frame`；`yield(sig, \"completed\")` → `await sig`"),
    ("GD07", "P1", "旧类名", "any",
     r"\b(KinematicBody2D|KinematicBody3D|KinematicBody|Spatial|Position3D)\b",
     "Godot 3.x 节点类名 —— 4.x 已更名",
     "KinematicBody2D/3D → CharacterBody2D/3D；Spatial → Node3D；Position3D → Marker3D"),
    ("GD08", "P1", "旧式实例化", "gd", r"\.instance\s*\(",
     "PackedScene.instance() 在 4.x 已改名",
     "改用 `instantiate()`"),
    ("GD08", "P1", "旧式实例化", "cs", r"\.Instance\s*\(",
     "PackedScene.Instance() 在 4.x 已改名",
     "改用 `Instantiate()`"),
    ("GD09", "P1", "旧式移动", "gd", r"move_and_slide\s*\([^)\s]",
     "move_and_slide 在 4.x 无参 —— 速度/朝向改为属性",
     "设 `velocity` / `up_direction` 属性后调用 `move_and_slide()`"),
    ("GD09", "P1", "旧式移动", "cs", r"MoveAndSlide\s*\([^)\s]",
     "MoveAndSlide 在 4.x 无参 —— 速度/朝向改为属性",
     "设 `Velocity` / `UpDirection` 属性后调用 `MoveAndSlide()`"),
    ("GD10", "P1", "闭包连接", "cs",
     r"(\+=|-=)\s*(?:\([^)]*\)\s*=>|delegate|[A-Za-z_]\w*\s*=>)",
     "信号用 lambda 订阅 —— 之后无法精确 -=（委托身份不保留）",
     "改为具名方法订阅并保存引用，退出树时 `-=`"),
]

FRAME_RULES = [
    ("GD11", "P1", "帧内查找", "gd", r"(get_node\s*\(|find_child\s*\(|get_nodes_in_group\s*\(|get_node_or_null\s*\()",
     "在 _process/_physics_process 中查找节点 —— 每帧遍历，应缓存",
     "在 `_ready` 或 `@onready` 缓存引用"),
    ("GD11", "P1", "帧内查找", "cs", r"(GetNode\s*[<(]|FindChild\s*\(|GetNodesInGroup\s*\()",
     "在 _Process/_PhysicsProcess 中查找节点 —— 每帧遍历，应缓存",
     "在 `_Ready` 缓存引用"),
    ("GD12", "P1", "帧内实例化", "gd", r"(instantiate\s*\(|\.new\s*\()",
     "在帧回调中实例化/新建对象 —— 产生 GC 压力，应考虑对象池",
     "预先实例化并复用，或改用节点池"),
    ("GD12", "P1", "帧内实例化", "cs", r"(Instantiate\s*\(|new\s+[A-Z]\w*)",
     "在帧回调中实例化/新建对象 —— 产生 GC 压力，应考虑对象池",
     "预先实例化并复用，或改用节点池"),
    ("GD13", "P2", "帧内文本", "gd", r"\.text\s*=(?!=)",
     "在帧回调中赋值 Label.text —— 每帧触发重排，仅值变化时赋值",
     "先比较再赋值：`if label.text != s: label.text = s`"),
    ("GD13", "P2", "帧内文本", "cs", r"\.Text\s*=(?!=)",
     "在帧回调中赋值 Label.Text —— 每帧触发重排，仅值变化时赋值",
     "先比较再赋值：`if (label.Text != s) label.Text = s;`"),
]

# _process 里做物理移动：速率与权威状态不一致
PROCESS_PHYSICS_GD = r"(move_and_slide|move_and_collide|apply_central_force|apply_force|apply_impulse)"
PROCESS_PHYSICS_CS = r"(MoveAndSlide|MoveAndCollide|ApplyCentralForce|ApplyForce|ApplyImpulse)"

# ---------- 领域规则（GD2x 物理 / GD3x UI / GD4x IO / GD5x 输入·音频·动画）----------
# 来源：references/godot-api/ 四份 API 查表文档（physics / ui / io / anim）。
#
# 收录原则：只收**有明确源码特征**的条目。需要跨文件或运行时对象关系
# 才能判的（如"StaticBody 被移动当平台"）不进扫描器，留在文档里人工看。
# 否则会造出一批"看着有道理但天天误报"的规则，把真正的 P0 淹掉。
#
# 字段：(ID, 级别, 类别, 语言, 正则, 说明, 修法, 反例豁免正则 or "")
#   need_absent：若该正则在整个文件里出现，则本条不报（用于"改了 X 却没调 Y"）
DOMAIN_RULES = [
    # --- GD2x 物理 ---
    ("GD21", "P1", "物理", "gd", r"velocity\s*\*=\s*delta",
     "velocity *= delta 后调 move_and_slide() —— 引擎内部已做时间积分，再乘是二次积分",
     "重力按 delta 累加到 velocity.y（`velocity.y += g * delta`），不要整体乘 delta",
     ""),
    ("GD22", "P1", "物理", "gd", r"apply_impulse\s*\(",
     "apply_impulse 出现在帧/物理回调里 —— impulse 是一次性冲击，每帧施加应改 apply_force",
     "持续力用 apply_force/apply_central_force；一次性冲击才用 apply_impulse",
     ""),
    ("GD23", "P1", "物理", "gd", r"target_position\s*=",
     "改了 RayCast.target_position —— 同帧读取仍是旧缓存，需 force_raycast_update()",
     "改完立刻 `ray.force_raycast_update()` 再 is_colliding()/get_collider()",
     r"force_raycast_update"),
    ("GD23", "P1", "物理", "cs", r"TargetPosition\s*=",
     "改了 RayCast.TargetPosition —— 同帧读取仍是旧缓存，需 ForceRaycastUpdate()",
     "改完立刻 `ray.ForceRaycastUpdate()` 再 IsColliding()/GetCollider()",
     r"ForceRaycastUpdate"),
    ("GD24", "P1", "物理", "any",
     r"intersect_ray\s*\(\s*(?:Vector[23]|to\b|from\b|self\.|position|\$)",
     "intersect_ray 用了位置参数 —— 4.x 只收参数对象（3.x 写法残留）",
     "`state.intersect_ray(PhysicsRayQueryParameters3D.create(from, to))`",
     ""),
    ("GD26", "P1", "物理", "gd", r"body_entered|body_exited",
     "连了 body_entered/body_exited —— 需 RigidBody.contact_monitor=true 且 max_contacts_reported>0，否则永不触发",
     "设 `contact_monitor = true` 与 `max_contacts_reported = 4+`",
     r"contact_monitor"),
    ("GD26", "P1", "物理", "cs", r"BodyEntered|BodyExited",
     "订阅了 BodyEntered/BodyExited —— 需 ContactMonitor=true 且 MaxContactsReported>0",
     "设 `ContactMonitor = true` 与 `MaxContactsReported = 4+`",
     r"ContactMonitor"),

    # --- GD3x UI / 2D 渲染 ---
    ("GD31", "P1", "UI", "any", r"ShaderMaterial\s*\.\s*new\s*\(|new\s+ShaderMaterial\s*\(",
     "帧回调里 new ShaderMaterial —— 材质状态碎片化，打断合批",
     "共享材质实例，只 `set_shader_parameter()` 改参数",
     ""),
    ("GD32", "P1", "UI", "any", r"CanvasGroup",
     "用了 CanvasGroup —— 它不能与 clip_children 嵌套，且每次都要读 backbuffer（fit_margin/use_mipmaps 有代价）",
     "确认未嵌套裁剪；fit_margin 与 use_mipmaps 按需开",
     ""),
    ("GD33", "P1", "UI", "any", r"set_cell\s*\(\s*\d",
     "set_cell 第一个参数是数字 —— 4.3+ 已改为坐标优先，层号优先是旧签名（deprecated）",
     "迁移到 TileMapLayer：`.set_cell(coords, source_id, atlas_coords)`",
     ""),
    ("GD34", "P1", "UI", "any", r"\bLight2D\b",
     "Light2D 是 3.x 类名 —— 4.x 已拆为 PointLight2D / DirectionalLight2D / SpotLight2D",
     "按用途换成 PointLight2D / DirectionalLight2D / SpotLight2D",
     ""),

    # --- GD4x 资源 / IO / 网络 ---
    ("GD41", "P1", "IO", "gd", r"FileAccess\s*\.\s*open\s*\(",
     "FileAccess.open() 后未见 close() —— 句柄泄漏，导出后文件被占用",
     "用完后 `f.close()`，或用 `using`/defer 模式确保成对",
     r"\.\s*close\s*\("),
    ("GD41", "P1", "IO", "cs", r"FileAccess\s*\.\s*Open\s*\(",
     "FileAccess.Open() 后未见 Close() —— 句柄泄漏",
     "用完后 `f.Close()`，或用 `using` 块",
     r"\.\s*Close\s*\("),
    ("GD43", "P1", "IO", "any", r"FileAccess\s*\.\s*[Oo]pen\s*\(\s*[\"']res://",
     "往 res:// 写文件 —— 导出后该路径只读，写盘会静默失败",
     "存档/用户数据一律写 `user://`",
     ""),
    ("GD45", "P0", "IO", "any", r"bytes_to_var\s*\(|str_to_var\s*\(",
     "反序列化不可信数据 —— 可构造任意对象，等同任意代码执行边界",
     "只反序列化自己写过的、签名/版本校验过的数据；优先 JSON/ConfigFile",
     ""),
    ("GD46", "P1", "IO", "gd", r"\.instantiate\s*\(",
     "instantiate() 后未见 add_child() —— 节点不在树里，不触发 _ready 也不渲染",
     "实例化后 `add_child(node)`",
     r"add_child\s*\("),
    ("GD46", "P1", "IO", "cs", r"\.Instantiate\s*\(",
     "Instantiate() 后未见 AddChild() —— 节点不在树里",
     "实例化后 `AddChild(node)`",
     r"AddChild\s*\("),
    ("GD47", "P1", "IO", "any", r"HTTPRequest",
     "用了 HTTPRequest 但未见 add_child —— 不进树就不会处理请求",
     "`add_child(http)` 后再 `request(...)`",
     r"add_child\s*\(|AddChild\s*\("),
    ("GD48", "P1", "IO", "any", r"\b(File|Directory)\s*\.\s*new\s*\(",
     "File.new()/Directory.new() 是 3.x 写法 —— 4.x 改为 FileAccess.open()/DirAccess.open()",
     "`FileAccess.open(path, FileAccess.READ)`（失败返回 null）",
     ""),

    # --- GD5x 输入 / 音频 / 动画 ---
    ("GD51", "P1", "输入", "gd",
     r"Input\s*\.\s*is_action_just_(?:pressed|released)\s*\(",
     "Input.is_action_just_* 在非输入回调里 —— 一帧内多次调用/掉帧会漏输入",
     "放 `_unhandled_input(event)`，或在固定步里一次性采样成 bool 字段",
     ""),
    ("GD51", "P1", "输入", "cs",
     r"Input\s*\.\s*IsActionJust(?:Pressed|Released)\s*\(",
     "Input.IsActionJust* 在非输入回调里 —— 掉帧会漏输入",
     "放 `_UnhandledInput(InputEvent e)`，或固定步里采样一次",
     ""),
    ("GD52", "P0", "音频", "gd", r"AudioStreamPlayer\w*\s*\.\s*new\s*\(",
     "动态 new AudioStreamPlayer —— 不 queue_free 会在树里累积（每个都是 Node）",
     "播完 `queue_free()`，或预建固定数量复用；`max_polyphony` 只限声部不限节点",
     r"queue_free"),
    ("GD52", "P0", "音频", "cs", r"new\s+AudioStreamPlayer\w*",
     "动态 new AudioStreamPlayer —— 不 QueueFree 会累积",
     "播完 `QueueFree()`，或预建复用",
     r"QueueFree"),
    ("GD53", "P2", "动画", "any", r"[\"']parameters/",
     "AnimationTree 参数路径用字面量 —— 拼错**静默失效**（不报错也不生效）",
     "集中成常量并加断言；或启动时校验 get(\"parameters/...\") 非 null",
     ""),
    ("GD54", "P2", "动画", "any", r"\.play\s*\(\s*[\"'][^\"']+[\"']",
     "动画名用字面量 —— 动画重命名后不报错也不播放",
     "动画名集中为常量；或启动时 has_animation() 校验",
     ""),
]


def lang_of(path: Path) -> str:
    s = path.suffix.lower()
    if s in GD_EXT:
        return "gd"
    if s in CS_EXT:
        return "cs"
    return ""


def excluded(path: Path, root: Path) -> bool:
    if set(path.parts) & EXCLUDE_PARTS:
        return True
    name = path.name
    return any(name.endswith(x) for x in EXCLUDE_SUFFIX)


def iter_scripts(root: Path):
    if root.is_file():
        if lang_of(root):
            yield root
        return
    for p in sorted(root.rglob("*")):
        if not p.is_file() or not lang_of(p):
            continue
        if excluded(p, root):
            continue
        yield p


def strip_comments(src: str, lang: str) -> str:
    """剥离注释，**保持行数与每行长度守恒**（行号才不会错位）。

    GDScript 用 `#`；C# 用 `//` 与 `/* */`。
    两者都必须识别字符串，否则：
      - GDScript `var url = "http://x"` 里的 // 会被当注释
      - C# 同理，且还有 `@"..."` 逐字字符串
    游戏代码里 URL / 资源路径常量极常见，踩中率很高。

    行数不守恒的后果：报告行号与真实行号错开，用户按行号去找看到的是别的行。
    """
    line_cmt = "#" if lang == "gd" else "//"
    out, i, n = [], 0, len(src)
    while i < n:
        if lang == "gd" and src.startswith('"""', i):
            j = src.find('"""', i + 3)
            j = n if j < 0 else j + 3
            out.append('\n' * src.count('\n', i, j))
            i = j
        elif lang == "cs" and src.startswith('/*', i):
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append('\n' * src.count('\n', i, j))
            i = j
        elif src.startswith(line_cmt, i):
            j = src.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif src[i] in '"\'' or (lang == "cs" and src[i] == '@'
                                 and i + 1 < n and src[i + 1] == '"'):
            if src[i] == '@':
                q, k = '"', i + 2
            else:
                q, k = src[i], i + 1
            while k < n:
                if src[k] == '\\':
                    k += 2
                    continue
                # C# 逐字字符串的转义是双写引号
                if src[i] == '@' and src[k] == '"':
                    if k + 1 < n and src[k + 1] == '"':
                        k += 2
                        continue
                    k += 1
                    break
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


def norm_name(name: str) -> str:
    return name.replace("_", "").lower()


def method_bodies(lines: list, lang: str) -> list[tuple[str, int, int]]:
    """提取方法 (规范化名, body起始行, body结束行)，0-based 半开区间。

    GDScript 按**缩进**界定；C# 按**大括号配平**界定。
    两者混用彼此的规则会完全失效——这是同时支持两种语言最容易写错的地方。
    """
    out = []
    if lang == "gd":
        for i, l in enumerate(lines):
            m = re.match(r"^(\s*)func\s+(\w+)\s*\(", l)
            if not m:
                continue
            indent = len(m.group(1))
            j = i + 1
            while j < len(lines):
                s = lines[j]
                if s.strip() and (len(s) - len(s.lstrip())) <= indent:
                    break
                j += 1
            out.append((norm_name(m.group(2)), i + 1, j))
    else:
        for i, l in enumerate(lines):
            # 只认 Godot 的 C# 回调（_Ready / _Process / _ExitTree …）。
            # 不写「任意标识符 + (」：那会把 `if (x)`、`for (...)` 也当成方法，
            # 于是 remove_child 的查找范围被缩到 if 块内，
            # 块外的 queue_free 看不见 → 干净代码被误报成泄漏。
            m = re.search(r"\b(_[A-Z]\w*)\s*\(", l)
            if not m:
                continue
            name = m.group(1)
            depth, j, started = 0, i, False
            while j < len(lines) and j < i + 400:
                depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j]:
                    started = True
                j += 1
                if started and depth <= 0:
                    break
            # 单行空方法 `public void _Ready() { }`
            if j == i + 1 and "{" in l and "}" in l:
                out.append((norm_name(name), i + 1, i + 1))
            else:
                out.append((norm_name(name), i + 1, j))
    return out


def span_of(methods, idx: int):
    for name, s, e in methods:
        if s <= idx < e:
            return name, s, e
    return None, -1, -1


def scan_file(path: Path, rel: str) -> list[dict]:
    lang = lang_of(path)
    if not lang:
        return []
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        return [{"file": rel, "line": 0, "level": "P2",
                 "rule": "读取失败", "msg": str(e)}]

    text = strip_comments(raw, lang)
    lines = text.splitlines()
    methods = method_bodies(lines, lang)
    issues = []

    def add(line_no, rid, level, rule, msg, fix=""):
        issues.append({"file": rel, "line": line_no + 1, "id": rid,
                       "level": level, "rule": rule, "msg": msg, "fix": fix})

    # ---- 1) 全文逐行规则（迁移残留等）----
    for rid, level, rule, rlang, pat, msg, fix in LINE_RULES:
        if rlang not in ("any", lang):
            continue
        seen = set()
        for i, l in enumerate(lines):
            if not re.search(pat, l):
                continue
            # 同一规则同一文件只报首次，附注次数，避免刷屏
            if rid in seen:
                continue
            seen.add(rid)
            add(i, rid, level, rule, msg, fix)

    # ---- 2) 帧回调内规则（性能）----
    for name, s, e in methods:
        if name not in FRAME_METHODS:
            continue
        for rid, level, rule, rlang, pat, msg, fix in FRAME_RULES:
            if rlang not in ("any", lang):
                continue
            for j in range(s, e):
                if re.search(pat, lines[j]):
                    add(j, rid, level, rule, msg, fix)
                    break      # 同一规则在同一帧回调内只报一次

    # ---- 3) _process 内做物理移动 ----
    for name, s, e in methods:
        if name != "process":
            continue
        pat = PROCESS_PHYSICS_GD if lang == "gd" else PROCESS_PHYSICS_CS
        for j in range(s, e):
            if re.search(pat, lines[j]):
                add(j, "GD14", "P1", "物理时机",
                    "在 _process 中做物理移动 —— _process 随渲染帧率变化，"
                    "低帧率时步长为变值，应放 _physics_process",
                    "把移动/受力逻辑移到 `_physics_process`")
                break

    # ---- 4) remove_child 后无释放（Godot 最经典的泄漏）----
    # Godot 里 remove_child 只解除父子关系，**不等于释放**。
    # 节点、脚本字段、信号连接、闭包引用都还活着。
    rm_pat = r"remove_child\s*\(" if lang == "gd" else r"RemoveChild\s*\("
    rel_pat = (r"(queue_free|free\s*\()" if lang == "gd"
               else r"(QueueFree|Free\s*\()")
    add_pat = r"add_child\s*\(" if lang == "gd" else r"AddChild\s*\("
    for i, l in enumerate(lines):
        if not re.search(rm_pat, l):
            continue
        name, s, e = span_of(methods, i)
        # 找不到所属方法就看后续 30 行（顶层脚本）；仍按可疑报
        lo = s if e > s else i + 1
        hi = e if e > s else min(len(lines), i + 30)
        after = "\n".join(lines[max(lo, i + 1):hi])
        if re.search(rel_pat, after) or re.search(add_pat, after):
            continue
        add(i, "GD01", "P0", "孤儿节点",
            "remove_child 后未见 queue_free/free 或重新 add_child —— "
            "remove_child 只解除父子关系，节点与它的信号/闭包引用仍在内存中",
            "确认去向：要销毁就 `queue_free()`；要复用就重新 `add_child()` 或交对象池保管")

    # ---- 5) create_tween 返回值未保存 ----
    # 官方：绑定的 Tween 随绑定对象释放而销毁；但**未保存引用**的
    # create_tween() 无法 kill，重复触发时旧 Tween 仍持有属性写入权。
    tw_pat = r"(create_tween|CreateTween)\s*\("
    kill_pat = r"(\.kill\s*\(|\.Kill\s*\(|bind_node\s*\(|BindNode\s*\()"
    for i, l in enumerate(lines):
        m = re.search(tw_pat, l)
        if not m:
            continue
        # 赋值语句（前面有 = ）视为已保存
        if "=" in l[:m.start()]:
            continue
        # await 场景：await ToSignal(...) 里的 CreateTimer 不在此列，
        # 但 create_tween 返回值被 await 的情况罕见，仍按未保存处理
        name, s, e = span_of(methods, i)
        lo = s if e > s else max(0, i - 5)
        hi = e if e > s else min(len(lines), i + 10)
        ctx = "\n".join(lines[lo:hi])
        if re.search(kill_pat, ctx):
            continue
        add(i, "GD02", "P0", "tween泄漏",
            "create_tween() 返回值未保存且未见 kill/bind_node —— "
            "重复触发时旧 Tween 仍持有属性写入权，且无法主动停止",
            "保存引用：`_tween = create_tween()`；重启前 `_tween.kill()`")

    # ---- 6) create_timer 返回值丢弃且非 await ----
    # SceneTreeTimer 是 RefCounted，不持有引用就失去控制（不能 stop）。
    tm_pat = r"(create_timer|CreateTimer)\s*\("
    for i, l in enumerate(lines):
        m = re.search(tm_pat, l)
        if not m:
            continue
        before = l[:m.start()]
        # 已赋值给变量 / 紧跟 await / 在 ToSignal 里 → 视为有持有者
        if "=" in before or "await" in before or "ToSignal" in before:
            continue
        add(i, "GD03", "P1", "timer失控",
            "create_timer() 返回值未保存 —— SceneTreeTimer 是 RefCounted，"
            "不持有引用就没法 stop，只能等它自然到点",
            "需要停止/复用就保存引用，或改用 Timer 节点（有 start/stop）")

    # ---- 6.5) 领域规则（物理 / UI / IO / 输入·音频·动画）----
    # 只在文件里能找到该 API 时才逐条查，避免对不相关的文件空转。
    for rid, level, rule, rlang, pat, msg, fix, absent in DOMAIN_RULES:
        if rlang not in ("any", lang):
            continue
        if not re.search(pat, text):
            continue
        # 「改了 X 却没调 Y」类：Y 在文件里出现过就不报
        if absent and re.search(absent, text):
            continue
        frame_only = rid in ("GD22", "GD31")
        if frame_only:
            hit = None
            for name, s, e in methods:
                if name not in FRAME_METHODS:
                    continue
                for j in range(s, e):
                    if re.search(pat, lines[j]):
                        hit = j
                        break
                if hit is not None:
                    break
            if hit is not None:
                add(hit, rid, level, rule, msg, fix)
            continue
        for i, l in enumerate(lines):
            if re.search(pat, l):
                add(i, rid, level, rule, msg, fix)
                break      # 同一规则同文件只报首次

    # ---- 7) 信号连接但清理回调里没有断开（跨生命周期）----
    # 只在「有 connect 且文件里有 _exit_tree 但其中没有 disconnect」时报，
    # 避免误伤同树父子连接（那种任一方释放会自动断开）。
    conn_pat = r"\.connect\s*\(" if lang == "gd" else r"(\.Connect\s*\(|\+=)"
    disc_pat = r"\.disconnect\s*\(" if lang == "gd" else r"(\.Disconnect\s*\(|-=)"
    has_conn = any(re.search(conn_pat, l) for l in lines)
    if has_conn:
        cleanups = [(s, e) for name, s, e in methods if name in CLEANUP_METHODS]
        cleaned = any(any(re.search(disc_pat, ln) for ln in lines[s:e])
                      for s, e in cleanups)
        has_cleanup = bool(cleanups)
        if has_cleanup and not cleaned:
            for i, l in enumerate(lines):
                if re.search(conn_pat, l):
                    add(i, "GD15", "P1", "信号未断",
                        "有信号连接，但 _exit_tree/_ExitTree 里未见 disconnect -= —— "
                        "跨场景/Autoload 连接不会随本节点释放自动断开",
                        "在 `_exit_tree` 中断开，先 `is_connected()` 判断；"
                        "同树父子连接可忽略本条")
                    break

    return issues


# ---------- 自检 ----------
# 其余 8 个扫描器都有 --self-test。没有自检的扫描器改了规则无法判断
# 是改好还是改坏——「永远 0 命中」与「真没问题」在输出上完全一样。

SELF_GD_BAD = '''extends Node2D

# 块注释占 3 行，用来验证行号不会错位
# 下面这行是示例代码，不应被当成真实代码：
# get_node("Fake")
var _url = "http://example.com/a"

export var speed := 10.0
onready var label = $Label

func _ready():
    some_bus.signal_name.connect("pressed", self, "_on_pressed")
    get_tree().create_timer(1.0)
    create_tween().tween_property(self, "modulate", Color.WHITE, 0.2)
    yield(get_tree(), "idle_frame")

func _process(delta):
    var n = get_node("Player")
    label.text = "x"
    move_and_slide(velocity, Vector2.UP)

func remove_self():
    get_parent().remove_child(self)

func _exit_tree():
    pass
'''

SELF_GD_CLEAN = '''extends CharacterBody2D

@export var speed := 10.0
@onready var _label: Label = $Label
var _tween: Tween
var _timer: Timer

func _ready():
    _label.text = "ready"

func _physics_process(delta):
    velocity = Vector2.ZERO
    move_and_slide()

func flash() -> void:
    if _tween != null and _tween.is_running():
        _tween.kill()
    _tween = create_tween()
    _tween.tween_property(self, "modulate", Color.WHITE, 0.2)

func despawn() -> void:
    get_parent().remove_child(self)
    queue_free()

func wait_a_bit() -> void:
    # await 持有 SceneTreeTimer 引用，属于正确用法，不应报 GD03
    await get_tree().create_timer(1.0).timeout

func _exit_tree():
    if some_bus.signal_name.is_connected(_on_pressed):
        some_bus.signal_name.disconnect(_on_pressed)

func _on_pressed() -> void:
    pass
'''

SELF_CS_BAD = '''using Godot;

public partial class Bad : Node2D
{
    public override void _Ready()
    {
        GetTree().CreateTimer(1.0f);
        CreateTween().TweenProperty(this, "modulate", Colors.White, 0.2f);
        button.Pressed += (s, e) => DoThing();
    }

    public override void _Process(double delta)
    {
        var n = GetNode<Node2D>("Player");
        label.Text = "x";
    }

    public override void _ExitTree()
    {
    }
}
'''

SELF_DOMAIN_BAD = '''extends Node2D

func _physics_process(delta):
    velocity *= delta
    $Body.apply_impulse(Vector2.UP * 10)
    var m = ShaderMaterial.new()

func scan():
    $Ray.target_position = Vector2(100, 0)
    if $Ray.is_colliding(): pass

func q():
    var r = get_world_2d().direct_space_state.intersect_ray($A.position, $B.position)
    return r

func save():
    var f = FileAccess.open("res://save.dat", FileAccess.WRITE)
    f.store_string("x")

func load_it():
    var o = bytes_to_var(f.get_buffer(8))
    var n = preload("res://e.tscn").instantiate()
    var h = HTTPRequest.new()
    h.request("http://x")
    var old = File.new()

func anim():
    $Tree.set("parameters/conditions/run", true)
    $Player.play("run")

func sfx():
    var p = AudioStreamPlayer.new()
    p.play()
'''

SELF_DOMAIN_CLEAN = '''extends Node2D

func _physics_process(delta):
    velocity.y += 980 * delta
    $Body.apply_force(Vector2.UP * 10)
    $Ray.target_position = Vector2(100, 0)
    $Ray.force_raycast_update()
    if $Ray.is_colliding(): pass

func q():
    var p = PhysicsRayQueryParameters2D.create($A.position, $B.position)
    return get_world_2d().direct_space_state.intersect_ray(p)

func save():
    var f = FileAccess.open("user://save.dat", FileAccess.WRITE)
    if f == null: return
    f.store_string("x")
    f.close()

func load_it():
    var n = preload("res://e.tscn").instantiate()
    add_child(n)
    var h = HTTPRequest.new()
    add_child(h)
    h.request("http://x")

func sfx():
    var p = AudioStreamPlayer.new()
    add_child(p)
    p.play()
    p.finished.connect(p.queue_free)
'''

SELF_CS_CLEAN = '''using Godot;

public partial class Good : CharacterBody2D
{
    [Export] public float Speed { get; set; } = 10.0f;
    private Label _label;
    private Tween _tween;

    public override void _Ready()
    {
        _label = GetNode<Label>("Label");
        _label.Text = "ready";
    }

    public override void _PhysicsProcess(double delta)
    {
        Velocity = Vector2.Zero;
        MoveAndSlide();
    }

    public override void _ExitTree()
    {
        button.Pressed -= OnPressed;
    }

    private void OnPressed() { }
}
'''


def self_test() -> int:
    tmp = tempfile.mkdtemp(prefix='godot-audit-self-')
    ok, fail = 0, []

    def check(cond, label):
        nonlocal ok
        if cond:
            ok += 1
            print('  ✓ %s' % label)
        else:
            fail.append(label)
            print('  ✗ %s' % label)

    try:
        cases = {
            'bad.gd': SELF_GD_BAD, 'clean.gd': SELF_GD_CLEAN,
            'bad.cs': SELF_CS_BAD, 'clean.cs': SELF_CS_CLEAN,
            'dom.gd': SELF_DOMAIN_BAD, 'domok.gd': SELF_DOMAIN_CLEAN,
        }
        res = {}
        for name, src in cases.items():
            p = Path(tmp) / name
            p.write_text(src, encoding='utf-8')
            res[name] = scan_file(p, name)

        def ids(name):
            return {i['id'] for i in res[name]}

        def rule_lines(name, rid):
            return [i['line'] for i in res[name] if i['id'] == rid]

        # --- GDScript 缺陷样本：迁移类应全中 ---
        for rid, label in (('GD04', '旧式字符串信号'), ('GD05', 'export/onready 无 @'),
                           ('GD06', 'yield'), ('GD09', 'move_and_slide 带参')):
            check(rid in ids('bad.gd'), 'bad.gd 命中 %s（%s）' % (rid, label))
        check('GD01' in ids('bad.gd'), 'bad.gd 命中 GD01（remove_child 无释放）')
        check('GD02' in ids('bad.gd'), 'bad.gd 命中 GD02（create_tween 未保存）')
        check('GD03' in ids('bad.gd'), 'bad.gd 命中 GD03（create_timer 未保存）')
        check('GD11' in ids('bad.gd'), 'bad.gd 命中 GD11（帧内 get_node）')
        check('GD13' in ids('bad.gd'), 'bad.gd 命中 GD13（帧内 text 赋值）')
        check('GD14' in ids('bad.gd'), 'bad.gd 命中 GD14（_process 内物理移动）')

        # --- 行号守恒：get_node 真实在第 16 行 ---
        real = next(i + 1 for i, l in enumerate(SELF_GD_BAD.splitlines())
                    if 'var n = get_node' in l)
        got = rule_lines('bad.gd', 'GD11')
        check(bool(got) and got[0] == real,
              '行号守恒：报 L%s，实际 L%s（注释未致错位）'
              % (got[0] if got else '?', real))

        # --- 字符串里的 // 不得吞掉代码（URL 那行下面仍正常解析）---
        check(not any('http' in i['msg'] for i in res['bad.gd']),
              '字符串里的 // 未被误当注释')

        # --- GDScript 干净样本 ---
        check(not [i for i in res['clean.gd'] if i['level'] == 'P0'],
              'clean.gd 无 P0（已正确配对的不误报）')
        check('GD01' not in ids('clean.gd'),
              'clean.gd 不报 GD01（remove_child 后有 queue_free）')
        check('GD02' not in ids('clean.gd'),
              'clean.gd 不报 GD02（tween 已保存并 kill）')
        check('GD05' not in ids('clean.gd'),
              'clean.gd 不报 GD05（@export/@onready 正确）')

        # --- C# 缺陷样本 ---
        check('GD03' in ids('bad.cs'), 'bad.cs 命中 GD03（CreateTimer 未保存）')
        check('GD02' in ids('bad.cs'), 'bad.cs 命中 GD02（CreateTween 未保存）')
        check('GD10' in ids('bad.cs'), 'bad.cs 命中 GD10（lambda 订阅信号）')
        check('GD11' in ids('bad.cs'), 'bad.cs 命中 GD11（_Process 内 GetNode）')

        # --- C# 干净样本 ---
        check(not [i for i in res['clean.cs'] if i['level'] == 'P0'],
              'clean.cs 无 P0')
        check('GD07' not in ids('clean.cs'),
              'clean.cs 不报 GD07（CharacterBody2D 是 4.x 正确类名）')
        check('GD11' not in ids('clean.cs'),
              'clean.cs 不报 GD11（_Ready 里 GetNode 是正常用法）')

        # --- 领域规则（GD2x 物理 / GD3x UI / GD4x IO / GD5x 输入·音频·动画）---
        for rid, label in (('GD21', 'velocity *= delta 二次积分'),
                           ('GD22', '帧内 apply_impulse'),
                           ('GD23', '改 target_position 未 force_raycast_update'),
                           ('GD24', 'intersect_ray 位置参数'),
                           ('GD31', '帧内 new ShaderMaterial'),
                           ('GD43', '写 res://'),
                           ('GD45', 'bytes_to_var 反序列化'),
                           ('GD46', 'instantiate 未 add_child'),
                           ('GD47', 'HTTPRequest 未 add_child'),
                           ('GD48', 'File.new() 3.x 写法'),
                           ('GD52', '动态 AudioStreamPlayer 未 queue_free'),
                           ('GD53', 'AnimationTree 参数路径字面量'),
                           ('GD54', '动画名字面量')):
            check(rid in ids('dom.gd'), 'dom.gd 命中 %s（%s）' % (rid, label))

        for rid, label in (('GD21', 'velocity.y += g*delta 是正确写法'),
                           ('GD22', '用 apply_force 不是 impulse'),
                           ('GD23', '已调 force_raycast_update'),
                           ('GD24', '用 PhysicsRayQueryParameters'),
                           ('GD41', 'FileAccess 已 close'),
                           ('GD43', '写 user://'),
                           ('GD46', 'instantiate 后 add_child'),
                           ('GD47', 'HTTPRequest 已 add_child'),
                           ('GD52', 'AudioStreamPlayer 有 queue_free')):
            check(rid not in ids('domok.gd'), 'domok.gd 不报 %s（%s）' % (rid, label))

        print('\n自检：%d 通过 / %d 失败' % (ok, len(fail)))
        for f in fail:
            print('  失败：%s' % f)
        return 1 if fail else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="Godot 项目目录或单个 .gd/.cs 文件")
    # --src= 是编排器 audit.py 的调用约定（所有扫描器统一）。
    # 不加这个参数，编排器调过来会因为参数不识别而失败——
    # 它把「调用失败」当成「0 条候选」，报告显示"无候选"，
    # 看起来像"代码没问题"，实际扫描器压根没跑。
    ap.add_argument("--src", default="", help="同 path，供 audit.py 编排器调用")
    ap.add_argument("--level", default="", help="只看某级：P0 / P1 / P2")
    ap.add_argument("--lang", default="", help="只看某语言：gd / cs")
    ap.add_argument("--rule", default="", help="按规则名过滤，如 GD01")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=0, help="只显示前 N 条")
    ap.add_argument("--rules", action="store_true", help="列出规则")
    ap.add_argument("--self-test", action="store_true", help="跑自检")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    if args.rules:
        print("  %-6s %-4s %-8s %s" % ("ID", "级别", "类别", "说明"))
        seen = set()
        for rid, level, rule, rlang, pat, msg, fix in LINE_RULES:
            if rid in seen:
                continue
            seen.add(rid)
            print("  %-6s %-4s %-8s %s" % (rid, level, rule, msg[:46]))
        for rid, level, rule, rlang, pat, msg, fix in FRAME_RULES:
            if rid in seen:
                continue
            seen.add(rid)
            print("  %-6s %-4s %-8s %s" % (rid, level, rule, msg[:46]))
        for rid, level, rule, msg in (("GD01", "P0", "孤儿节点", "remove_child 后无释放"),
                                      ("GD02", "P0", "tween泄漏", "create_tween 未保存"),
                                      ("GD03", "P1", "timer失控", "create_timer 未保存"),
                                      ("GD14", "P1", "物理时机", "_process 内做物理移动"),
                                      ("GD15", "P1", "信号未断", "清理回调里未 disconnect")):
            print("  %-6s %-4s %-8s %s" % (rid, level, rule, msg))
        return

    target = args.path or args.src
    if not target:
        ap.error("缺少 path / --src（或用 --rules / --self-test）")

    root = Path(target).expanduser()
    if not root.exists():
        sys.exit("路径不存在：%s" % root)

    files = list(iter_scripts(root))
    if not files:
        sys.exit("未找到 .gd / .cs 文件：%s（路径有误或全被排除？）" % root)

    all_issues = []
    for f in files:
        if args.lang and lang_of(f) != args.lang:
            continue
        try:
            rel = str(f.relative_to(root)) if f != root else f.name
        # audit: ignore —— 相对路径计算失败退回绝对路径，只影响报告里的显示
        except Exception:
            rel = str(f)
        all_issues += scan_file(f, rel)

    if args.level:
        all_issues = [i for i in all_issues if i["level"] == args.level.upper()]
    if args.rule:
        all_issues = [i for i in all_issues if i["id"] == args.rule.upper()]

    # 按文件分组（其次级别、行号）。
    # 不按级别全局排序：那样同一文件的条目会被别的文件的 P1 打断，
    # 读报告时来回跳。同一文件内仍是 P0 → P1 → P2。
    order = {"P0": 0, "P1": 1, "P2": 2}
    all_issues.sort(key=lambda x: (x["file"], order.get(x["level"], 9), x["line"]))

    if args.json:
        print(json.dumps(all_issues, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("Godot 脚本审核：%s" % root)
        print("扫描 %d 个脚本，发现 %d 项" % (len(files), len(all_issues)))
        print("=" * 60)
        shown = all_issues[:args.top] if args.top else all_issues
        cur = None
        for it in shown:
            if it["file"] != cur:
                cur = it["file"]
                print("\n── %s" % cur)
            print("  [%s] L%-4d %-5s %s" % (it["level"], it["line"], it["id"], it["msg"]))
            if it.get("fix"):
                print("        修：%s" % it["fix"])
        if args.top and len(all_issues) > args.top:
            print("\n… 另有 %d 项未显示（--top 调整）" % (len(all_issues) - args.top))
        print("\n" + "-" * 60)
        for lv in ("P0", "P1", "P2"):
            n = sum(1 for i in all_issues if i["level"] == lv)
            if n:
                print("  %s %-30s %d 项" % (lv, LEVEL_DESC[lv], n))
        if not all_issues:
            print("  ✓ 未发现明显问题")
        print("\n提示：静态扫描只证明「所有权关系可疑」，不证明运行时一定泄漏")
        print("      命中项需人工确认，或用 Performance.OBJECT_COUNT 做前后对比")

    if any(i["level"] == "P0" for i in all_issues):
        sys.exit(1)


if __name__ == "__main__":
    main()
