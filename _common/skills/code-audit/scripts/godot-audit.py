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

import os
import re
import sys
import json
import argparse
import tempfile
import shutil
from pathlib import Path

# AR-04 退出码码表（与其它扫描器一致：0/1/2/3/4）
# 集成它的原因：工具只返回「成功/失败」时，自动化无法分流
# 「照提示做即可」与「真出错」——把被防护拦下当错误会导致重试或放弃，两种反应都错。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exitcode import help_text, OK, ERR, USAGE, ENV, BLOCKED, die  # noqa: E402

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
# .gdshader 此前完全不被识别 —— shader 文件在整个审查里是隐形的。
# 表现是"扫到 0 个 shader 问题"，看起来像没问题，实际是压根没看。
SHADER_EXT = (".gdshader",)

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

    # --- 调试与交付类（GD101+）：这些不报错，只是"看起来正常" ---
    ("GD101", "P1", "调试残留", "gd", r"^\s*breakpoint\s*$",
     "`breakpoint` 遗留在代码中 —— 发布版命中会暂停（且它在版本控制里，全团队共享）",
     "确认是临时调试就删掉；确需保留的条件断点要写注释说明"),
    ("GD102", "P1", "断言校验", "gd",
     r"(?<![A-Za-z_])assert\s*\(",
     "`assert` 在 release 导出后**被完全剥离** —— 用它做运行时校验等于没校验",
     "运行时校验改为 `push_error` + 明确降级；assert 只用于开发期不变式"),
    ("GD103", "P1", "动态路径", "gd",
     r"(?:load|preload|ResourceLoader\.load|FileAccess\.open)\s*\([^)\n]*(?:\+|\s%\s|\.format\(|\$\{)",
     "资源/文件路径是运行时拼接 —— 导出依赖分析是静态扫描，拼出来的路径扫不到，导出后找不到",
     "改用常量路径；或在导出过滤里显式包含；运行时用 `ResourceLoader.exists()` 兜底"),
    ("GD104", "P1", "绝对路径", "gd",
     r'["\'](?:[A-Za-z]:[\\/]|/(?:Users|home|root|mnt|var)/)',
     "硬编码操作系统绝对路径 —— 换机器/换平台必然失效，且 CI 上必挂",
     "改用 `res://` / `user://` 或 `ProjectSettings.globalize_path()`"),
    ("GD105", "P1", "命令拼接", "gd",
     r"OS\.(?:execute|create_process)\s*\([^)\n]*(?:\+|\s%\s|\.format\()",
     "系统命令含拼接 —— 路径/参数可控时是命令注入；Godot 导出后路径不可控也是故障源",
     "用数组参数形式而非拼接字符串；外部输入一律白名单校验"),
    # --- 动画 / 音频 / 大世界 / XR ---
    ("GD113", "P1", "节点未入树", "gd",
     r"AudioStreamPlayer3D\.new\(\)",
     "3D 音频节点创建后未 add_child —— 不在场景树里就没有空间效果，退化成普通播放器",
     "创建后 add_child 到场景树；或用 @onready 在编辑器里挂好"),    ("GD115", "P1", "坐标累积", "gd",
     r"global_position\s*\+=\s*\w*(?:world|World)\w*",
     "直接累加世界坐标 —— 大世界下远离原点会累积单精度误差（小项目测不出来）",
     "用局部坐标 + 原点重置（见 openworld.md）；或评估双精度构建"),
    ("GD116", "P1", "相机越权", "gd",
     r"(?:\$XRCamera|XRCamera3D)[\w/]*\.\s*(?:position|global_position|transform)\s*(?:\+=|=)",
     "直接改 XRCamera3D 的位置 —— 它每帧被头显覆盖，改了无效且是晕动症头号成因",
     "移动 XROrigin3D；相机位置永远由头显驱动"),
    ("GD117", "P1", "无速度传递", "gd",
     r"(?:linear_velocity|velocity)\s*=\s*Vector3\.ZERO",
     "释放抓取物时把速度清零 —— 物体掉在手里，VR 手感极假（XRController3D 没有速度 API，需自己算）",
     "用多样本速度追踪器把控制器速度传给刚体（见 xr.md）"),
    # --- 4.7 迁移（这些 API/语义在 4.7 变了，旧写法静默出错）---
    ("GD121", "P1", "设备ID", "gd",
     r"(?<!\w)device\s*==\s*0\b",
     "4.7 起鼠标/键盘的 device 不再是 0（某些手柄的 device 也可能是 0）—— 判断鼠标会误判成手柄",
     "改用 InputEvent.DEVICE_ID_MOUSE / DEVICE_ID_KEYBOARD；或按事件类型判断"),
    ("GD122", "P1", "已移除API", "gd",
     r"(?<!\w)tap_back_pos\b",
     "4.7 已从 AudioEffectSpectrumAnalyzer 移除 tap_back_pos —— 音频可视化代码会失效",
     "改用 4.7 提供的替代方式；查阅 4.7 迁移指南的 Audio 章节"),
    ("GD123", "P2", "旧发布方式", "gd",
     r"(?i)(?:google\s*play\s*)?\bobb\b",
     "4.7 起 Android 移除 Google Play OBB 支持 —— 旧发布流程会失效",
     "改用 GABE / AAB 等 4.7 支持的方式"),
    ("GD106", "P1", "异步异常", "cs", r"async\s+void\b",
     "`async void` —— 异常会逃离 Godot 调用栈（无法被上层捕获），且生命周期不可控",
     "改为 `async Task`；入口处若必须 void 也要包 try/catch"),
]

FRAME_RULES = [
    ("GD107", "P1", "热帧打印", "gd", r"(?<![A-Za-z_.])print\s*\(",
     "在 _process/_physics_process 中 print —— 每帧输出，发布版仍在打，并让 Profiler 数据失真",
     "改 `push_error`（带栈帧、立即刷新）或分级日志，发布版可关"),
    ("GD107", "P1", "热帧打印", "cs", r"(?<![A-Za-z_.])(?:GD\.Print|Console\.Write)\s*\(",
     "在 _Process/_PhysicsProcess 中打印 —— 每帧输出，发布版仍在打",
     "改 `GD.PushError` 或分级日志"),
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

    # --- GD9x 热路径（方向来自 godot-correctness-mcp / gdstyle，正则为本仓库实测）---
    ("GD91", "P0", "热帧加载", "gd", r"(?<!\w)load\s*\(",
     "在帧回调中同步 load() —— 每帧磁盘 I/O，卡主线程造成掉帧",
     "改用 preload（路径为常量）或提前加载缓存引用"),
    ("GD91", "P0", "热帧加载", "cs", r"(?<!\w)(?:GD\.Load|ResourceLoader\.Load)\s*[<(]",
     "在帧回调中同步 Load() —— 每帧磁盘 I/O，卡主线程造成掉帧",
     "提前加载并缓存引用"),

    ("GD92", "P1", "热帧字符串", "gd", r'is_action_(?:pressed|just_pressed|just_released)\s*\(\s*"',
     "帧回调内用字符串字面量查输入动作 —— 每次逐字符比较，热路径应改用 StringName",
     '改用 StringName 字面量：`Input.is_action_pressed(&"jump")`'),
    ("GD92", "P1", "热帧字符串", "cs", r'IsAction(?:Pressed|JustPressed)\s*\(\s*"',
     "帧回调内用字符串字面量查输入动作 —— 每次逐字符比较，热路径应改用 StringName",
     'C# 用常量 StringName 字段缓存，避免每帧新建字符串'),
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
# --- Shader 规则（.gdshader）：3.x 残留与颜色空间是最常见的静默错误 ---
SHADER_RULES = [
    ("GDS01", "P1", "旧提示", "shader", r"hint_(?:albedo|color)\b",
     "3.x 的 hint_albedo/hint_color —— 4.x 改为 source_color，不改颜色会偏",
     "改为 `source_color`；项目内全局替换，不只改这一处"),
    ("GDS02", "P1", "旧提示", "shader", r"hint_(?:white|black)\b",
     "3.x 的 hint_white/hint_black —— 4.x 改为 hint_default_white/default_black",
     "改为 `hint_default_white` / `hint_default_black`"),
    ("GDS03", "P1", "旧全局量", "shader", r"(?<![A-Za-z_])SCREEN_TEXTURE\b",
     "4.x 没有全局 SCREEN_TEXTURE —— 3.x 写法直接编译失败",
     "声明 `uniform sampler2D u_screen : hint_screen_texture;` 再用 texture(u_screen, SCREEN_UV)"),
    ("GDS04", "P1", "旧光照", "shader", r"(?<![A-Za-z_])AT_LIGHT_PASS\b",
     "4.x CanvasItem 改为单 pass 光照，AT_LIGHT_PASS 恒为 false —— 3.x 的光照分支在 4.x 失效",
     "删除 pass 判断，改用 render_mode unshaded / light_only 并重写 light()"),
    ("GDS05", "P1", "颜色空间", "shader",
     r"uniform\s+sampler2D\s+\w*(?:albedo|tex|color|colour|diffuse|base)\w*\s*(?!:)\s*;",
     "名字暗示是颜色纹理但没有 source_color —— Forward+/Mobile 下会发白（这是颜色空间语义，不只是 UI 控件）",
     "颜色纹理加 `source_color`；法线/粗糙度/金属度/高度**不加**"),
    ("GDS06", "P2", "粒子旧式", "shader",
     r"shader_type\s+particles[^]*]*\}[^]*]*\bvertex\s*\(",
     "3.x 粒子 shader 用 vertex() —— 4.x 改为 start() / process()",
     "改写为 `void start()` 与 `void process()`"),
    ("GDS07", "P2", "移动端丢弃", "shader", r"(?<![A-Za-z_])discard\s*;",
     "discard 会阻止有效利用深度 prepass —— 顶点阶段仍执行，不比不渲染更便宜",
     "优先 alpha scissor；只在确实需要硬孔时用 discard"),
    ("GDS08", "P2", "精度", "shader",
     r"varying\s+(?:lowp|mediump)\s+\w+\s+\w*(?:world|pos|screen|depth)\w*\s*;",
     "世界坐标/屏幕 UV/深度用低精度 varying —— 桌面正常，真机远处闪烁",
     "世界坐标、屏幕 UV、TIME、深度重建用 `highp`"),
]

# --- 动画 / 音频 / 大世界：这几条是「有 A 却没 B」型，用 absent 表达 ---
# 放在 LINE_RULES 里做不到（那边没有 absent），只能放这里。
EXTRA_DOMAIN_RULES = [
    ("GD111", "P1", "动画未激活", "gd", r"AnimationTree",
     "引用了 AnimationTree 但全文没有 active=true —— 配置全对却无任何输出（最常见的没反应）",
     "在 _ready 里 `animation_tree.active = true`，并用 playback.start() 初始化状态",
     r"active\s*=\s*true"),
    ("GD112", "P1", "音量单位", "gd", r"set_bus_volume_db\s*\(",
     "set_bus_volume_db 收的是**分贝**，全文没有 linear_to_db 说明很可能直接传了 0–1 —— 音量曲线完全不对",
     "用 `linear_to_db(v)`；静音用 -80 dB 或 set_bus_mute，不是 0 dB",
     r"linear_to_db"),
    ("GD114", "P1", "边界抖动", "gd", r"(?i)(?:load|view|stream)_radius\s*[:=]",
     "只有加载半径、全文没有卸载半径 —— 玩家在 chunk 边界来回走会抖动式加载卸载（周期性卡顿）",
     "unload_radius 必须 > load_radius，并加卸载延迟（滞回）",
     r"(?i)unload_radius"),
    ("GD124", "P1", "朝向基准", "gd", r"LookAtModifier3D",
     "用了 LookAtModifier3D 但全文没设 relative —— 4.7 起默认从 true 变 false（基于 rest pose 而非当前 pose），头部朝向会变",
     "显式设 relative=true 恢复 4.6 行为；或按 4.7 新默认重调角度限制基准",
     r"(?<!\w)relative\s*="),
    ("GD125", "P2", "摇杆自制", "gd", r"class_name\s+VirtualJoystick|TouchScreenButton",
     "自己实现虚拟摇杆 —— 4.7 起引擎内置 VirtualJoystick 节点（Fixed/Dynamic/Following 三模式 + action_* 直连）",
     "优先用内置 VirtualJoystick；仅在需完全自定义外观时才保留自制实现",
     r"(?<!\w)VirtualJoystick\b(?!\s*\.)"),
]

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

    # --- GD6x 3D / 渲染 ---
    # 只收有明确源码特征、且不依赖运行时对象关系的条目。
    # 「共享材质被改」这类需要比对 Resource 身份，静态做不到，留在 3d.md 人工看。
    ("GD61", "P2", "3D", "gd", r"global_position\s*=",
     "直接赋值 global_position —— 它只是全局变换链的计算结果，"
     "下一帧可能被物理步/父节点变换/插值覆盖回局部值",
     "要持续定位就写局部 position，或设 top_level=true；瞬时传送可用 global_position",
     ""),
    ("GD61", "P2", "3D", "cs", r"GlobalPosition\s*=",
     "直接赋值 GlobalPosition —— 会被物理步/父变换/插值覆盖",
     "写局部 Position，或设 TopLevel=true",
     ""),
    ("GD62", "P2", "3D", "any", r"spot_angle\s*=\s*(?:[9]\d|1\d\d|\d{3,})",
     "SpotLight3D.spot_angle 超过 89° —— 超出范围会不生效或产生异常阴影",
     "保持在 89° 以内；需要更大范围改用 OmniLight3D",
     ""),
    ("GD63", "P1", "3D", "any", r"editor_only\s*=\s*true",
     "editor_only=true —— 若忘了关，导出后光照/效果仍在但白占性能预算",
     "确认导出前关闭，或明确这是仅编辑器用途",
     ""),
    ("GD64", "P2", "3D", "any", r"set_shader_parameter\s*\(\s*[\"'][^\"']+[\"']",
     "set_shader_parameter 用字面量名 —— 与 shader 里的 uniform 名不一致时"
     "**静默失效**（不报错也不生效）",
     "uniform 名集中为常量；或启动时校验返回值非 null",
     ""),
    ("GD65", "P2", "3D", "any", r"visibility_aabb",
     "用了 GPUParticles3D.visibility_aabb —— 包围盒不足时粒子会被整体剔除，"
     "**不报错**，表现为粒子在屏幕边缘突然消失",
     "包围盒要覆盖粒子可能的运动范围；移动发射器注意 local_coords",
     ""),

    # --- GD7x 语言 / 工程 / 调试 ---
    ("GD71", "P1", "语言", "gd", r"\bassert\s*\(",
     "用 assert 做运行时校验 —— release 导出模板下 assert 不被求值，校验会整段消失",
     "运行时校验改用 if + push_error()；assert 只用于开发期内部不变量",
     ""),
    ("GD72", "P2", "语言", "gd", r"emit_signal\s*\(",
     "emit_signal() 是 3.x 写法 —— 4.x 用 `signal_name.emit()`",
     "改为 `my_signal.emit(args)`",
     ""),
    ("GD73", "P1", "语言", "gd", r"\.duplicate\s*\(\s*\)",
     "duplicate() 无参 —— Array/Dictionary/Resource 默认是**浅拷贝**，"
     "嵌套结构仍共享引用，改一个影响另一个",
     "需要独立副本用 `duplicate(true)`（深拷贝）",
     r"duplicate\s*\(\s*true\s*\)"),
    ("GD74", "P2", "语言", "any", r"\bprint\s*\(",
     "用 print() 输出调试信息 —— release 包里仍会执行，有 I/O 开销且可能泄露信息",
     "调试用 print_debug()（release 自动剥离），错误用 push_error()",
     ""),
    ("GD75", "P1", "语言", "gd", r"await\s+.+\.timeout",
     "await 期间节点可能已被 queue_free —— 协程恢复时访问已释放对象",
     "await 后先 `if not is_instance_valid(self): return`；或用 Timer 节点信号",
     r"is_instance_valid"),

    # --- GD8x 存档安全 / 防作弊 ---

    # --- GD9x 性能与热路径（来源：godot-correctness-mcp / gdstyle 方向，
    #      正则按本仓库实测收敛，只收低误报的）---
    ("GD93", "P1", "浮点比较", "any",
     r"(?:\b(?:position|global_position|rotation|rotation_degrees|scale"
     r"|velocity|linear_velocity)\s*==\s*)|(?:==\s*-?\d+\.\d+)",
     "浮点值直接用 == 比较 —— 浮点有精度误差，相等的判断几乎永不成立",
     "改用距离/范围判断：`if abs(a - b) < 0.001` 或 `is_equal_approx(a, b)`",
     ""),

    ("GD94", "P1", "距离比较", "any",
     r"\bdistance_to\s*\([^)]*\)\s*(?:<=|>=|==|<|>)\s*[\d.]+",
     "distance_to() 用于阈值比较 —— 内部要开方，热路径每秒算几百次是浪费",
     "比较改用 distance_squared_to()，阈值取平方"
     "（如 100 米 -> 10000）；真需要实际距离时才用 distance_to()",
     ""),

    ("GD95", "P0", "共享资源", "gd",
     r"@export\s+var\s+\w+\s*:\s*\w*(?:Resource|Data)\b",
     "@export 的 Resource 未在 _ready 内 duplicate —— 所有实例共享同一份，"
     "改一个实例的数值会让全部实例一起变（Godot 4 最常见的 #1 新手 bug）",
     "在 _ready 里 `x = x.duplicate()`；嵌套 Resource 要 `duplicate(true)` 深拷贝",
     r"duplicate\s*\("),

    ("GD97", "P2", "空函数", "gd",
     r"\bfunc\s+\w+\s*\([^)]*\)[^:]*:\s*pass\s*$",
     "函数体只有 pass —— 若是占位应标记 TODO，若是回调则可删（引擎不要求空实现）",
     "删除空回调，或补上实现；确需占位就写明 TODO 原因",
     ""),

    ("GD98", "P2", "自引用", "any",
     r"(?<![.\w])([a-z_]\w*)\s*(?:=|==)\s*\1\s*(?:#.*)?$",
     "自赋值或自比较 —— 通常是笔误（如想写 self.x = x 却写成 x = x），"
     "逻辑上永远是恒等/no-op",
     "检查是否笔误；GDScript 里成员赋值应写 `self.x = x` 或改参数名",
     ""),

    # 只收有明确源码特征的。像"密钥在客户端所以不安全"这类是架构判断，
    # 静态扫不出来，留在 p-godot.md 里人工看。
    ("GD81", "P1", "安全", "any", r"open_encrypted(?:_with_pass)?\s*\(",
     "用了加密存档但未见任何签名/校验 —— AES-CBC 无认证，"
     "可被比特翻转攻击：不改密钥就能改数值，且解密不报错",
     "加密之外必须加 HMAC 签名，且**先验签再解密**；比对用 constant_time_compare",
     r"hmac|verify|constant_time_compare|signature|校验"),
    ("GD82", "P1", "安全", "gd",
     r"(?:KEY|SECRET|PASSWORD)\s*[:=]+\s*['\"\w]{8,}",
     "密钥/口令以明文字符串写在脚本里 —— PCK 可解包、.gdc 可反编译，等于没加密",
     "主密钥分段藏在不同位置运行时拼接；真要防逆向放 GDExtension",
     ""),    ("GD83", "P1", "安全", "gd", r"get_unix_time_from_system\s*\(",
     "用系统时间做时间判定 —— 玩家改系统时钟即可绕过（每日奖励、冷却、签到）",
     "纯玩内计时改 Time.get_ticks_msec()；跨会话的每日奖励必须用服务端时间",
     ""),
    ("GD84", "P2", "安全", "any", r"(?:hmac|mac|sign|digest)\w*\s*==\s*|==\s*\w*(?:hmac|mac|sign|digest)",
     "用 == 比对 HMAC/签名 —— 提前退出会泄露「前几字节对上了」的信息（时序侧信道）",
     "改用 Crypto.constant_time_compare()",
     ""),
    ("GD85", "P1", "安全", "gd", r"(?:is_debug_build|is_editor_hint)\s*\(",
     "用 debug 构建检测做安全门禁 —— 仅能挡住最基础的尝试，"
     "且若检测到就直接崩溃/弹窗，等于帮攻击者定位检查点",
     "检测到后静默处理（标记/回滚/上报），不要给攻击者任何可观测反馈",
     ""),

]


def lang_of(path: Path) -> str:
    s = path.suffix.lower()
    if s in GD_EXT:
        return "gd"
    if s in CS_EXT:
        return "cs"
    if s in SHADER_EXT:
        return "shader"
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

    GDScript 用 `#`；C# 与 GDShader 用 `//` 与 `/* */`。
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
        elif lang in ("cs", "shader") and src.startswith('/*', i):
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

    # ---- 1.5) Shader 规则（.gdshader）----
    # 此前 .gdshader 完全不被识别，shader 在审查里是隐形的。
    if lang == "shader":
        for rid, level, rule, rlang, pat, msg, fix in SHADER_RULES:
            seen = set()
            for i, l in enumerate(lines):
                if not re.search(pat, l):
                    continue
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

    # ---- 2.5) _physics_process 内 await（协程挂起会跳过物理帧）----
    for name, s0, e0 in methods:
        if name != "physicsprocess":
            continue
        for j in range(s0, e0):
            if re.search(r"\bawait\b", lines[j]):
                add(j, "GD96", "P0", "物理帧挂起",
                    "在 _physics_process 中 await —— 协程挂起会跳过物理帧，"
                    "恢复后 delta 与物体状态都已不可信",
                    "改用状态机或 Timer 节点，不要在固定步里 await")
                break

    # ---- 2.6) 函数体过长（职责过多的信号）----
    MAX_FUNC_LINES = 80
    for name, s0, e0 in methods:
        n = e0 - s0
        if n > MAX_FUNC_LINES:
            add(s0, "GD99", "P2", "函数过长",
                "函数体 %d 行，超过 %d 行 —— 通常意味着职责过多，"
                "出问题时难以定位" % (n, MAX_FUNC_LINES),
                "按职责拆成多个私有方法，或把独立职责抽成组件节点")

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
    for rid, level, rule, rlang, pat, msg, fix, absent in (DOMAIN_RULES + EXTRA_DOMAIN_RULES):
        if rlang not in ("any", lang):
            continue
        # MULTILINE 必需：pat 里可能带 $ 锚点
        # （如 GD97 空函数、GD98 自赋值），无 M 时 $ 只匹配全文末尾
        if not re.search(pat, text, re.M):
            continue
        # 「改了 X 却没调 Y」类：Y 在文件里出现过就不报
        if absent and re.search(absent, text, re.M):
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

SELF_EXTRA_BAD = '''extends Node3D

@export var spd := 1.0

func _ready():
    $Mesh.global_position = Vector3(1, 2, 3)
    $Spot.spot_angle = 120
    $Light.editor_only = true
    $Mat.set_shader_parameter("u_color", Color.RED)
    $Par.visibility_aabb = AABB(Vector3.ZERO, Vector3.ONE)
    assert(spd > 0, "spd must be positive")
    emit_signal("ready_done")
    var a = other.duplicate()
    print("dbg")
    await get_tree().create_timer(1.0).timeout
    do_next()
'''

SELF_EXTRA_CLEAN = '''extends Node3D

const U_COLOR := "u_color"
@export var spd := 1.0

func _ready():
    $Mesh.position = Vector3(1, 2, 3)
    $Spot.spot_angle = 45
    $Mat.set_shader_parameter(U_COLOR, Color.RED)
    if spd <= 0:
        push_error("spd must be positive")
        return
    ready_done.emit()
    var a = other.duplicate(true)
    print_debug("dbg")
    await get_tree().create_timer(1.0).timeout
    if not is_instance_valid(self):
        return
    do_next()
'''

SELF_HOT_BAD = '''extends Node

@export var weapon: WeaponData

func _process(delta):
    var s = load("res://x.tres")
    if Input.is_action_pressed("jump"):
        pass
    if position == Vector2.ZERO:
        pass
    if global_position.distance_to(_target) < 100.0:
        pass
    var hp = 10
    hp = hp

func _physics_process(delta):
    await get_tree().create_timer(0.1).timeout

func empty_one() -> void: pass
'''

SELF_HOT_CLEAN = '''extends Node

@export var weapon: WeaponData
var _target: Node2D
var _cached: Resource

func _ready():
    weapon = weapon.duplicate() as WeaponData
    _cached = preload("res://x.tres")

func _process(delta):
    if Input.is_action_pressed(&"jump"):
        pass
    if global_position.distance_squared_to(_target.global_position) < 10000.0:
        pass
    if is_equal_approx(position.x, 0.0):
        pass

func _physics_process(delta):
    velocity = Vector2.ZERO
'''

SELF_V47_BAD = '''extends Node3D

@onready var look: LookAtModifier3D = $LookAt
@onready var touch: TouchScreenButton = $Jump

func _input(event: InputEvent) -> void:
    if event.device == 0:
        print("mouse")

func _ready() -> void:
    var fx = AudioEffectSpectrumAnalyzer.new()
    fx.tap_back_pos = 0.5
    var obb_path := "main.obb"
    print(obb_path)
'''

SELF_V47_CLEAN = '''extends Node3D

@onready var look: LookAtModifier3D = $LookAt
@onready var joystick: VirtualJoystick = $UI/VirtualJoystick

func _ready() -> void:
    look.relative = true

func _input(event: InputEvent) -> void:
    if event.device == InputEvent.DEVICE_ID_MOUSE:
        print("mouse")
'''

SELF_MISC_BAD = '''extends Node3D

@onready var tree: AnimationTree = $AnimationTree

const LOAD_RADIUS := 200.0
# 缺 UNLOAD_RADIUS —— 玩家在边界来回走会抖动式加载

func _ready() -> void:
    AudioServer.set_bus_volume_db(1, $Slider.value)
    var p3d = AudioStreamPlayer3D.new()
    p3d.stream = load("res://a.ogg")
    $XRCamera3D.global_position += Vector3(1, 0, 0)

    var held = $Held
    held.linear_velocity = Vector3.ZERO

func move(world_delta: Vector3) -> void:
    global_position += world_delta
'''

SELF_MISC_CLEAN = '''extends Node3D

@onready var tree: AnimationTree = $AnimationTree
@onready var p3d: AudioStreamPlayer3D = $Sfx3D

func _ready() -> void:
    tree.active = true
    AudioServer.set_bus_volume_db(1, linear_to_db($Slider.value))

func move(local_delta: Vector3) -> void:
    position += local_delta
'''

SELF_SHADER_BAD = '''shader_type canvas_item;

uniform sampler2D albedo_tex;
uniform sampler2D u_old : hint_albedo;
uniform sampler2D u_bw : hint_white;
uniform vec4 u_c : hint_color;

varying mediump vec3 v_world_position;

void fragment() {
    if (AT_LIGHT_PASS) {
        COLOR = vec4(1.0);
    }
    vec4 c = texture(SCREEN_TEXTURE, SCREEN_UV);
    discard;
}

void vertex() {
    COLOR = texture(albedo_tex, UV);
}
'''

SELF_SHADER_CLEAN = '''shader_type canvas_item;
render_mode unshaded;

uniform sampler2D u_tex : source_color;
uniform sampler2D u_normal : hint_normal;
uniform sampler2D u_screen : hint_screen_texture, filter_linear_mipmap;
uniform vec4 u_tint : source_color = vec4(1.0);

varying highp vec3 v_world_position;

void fragment() {
    vec4 c = texture(u_tex, UV);
    COLOR = c * u_tint;
}
'''

SELF_DEBUG_BAD = '''extends Node

func _process(delta):
    print("tick")
    var p = load("res://items/" + name + ".tres")
    var f = FileAccess.open("/Users/me/save.dat", FileAccess.READ)
    assert(p != null, "must exist")
    OS.execute("sh", ["-c", "rm " + path])
    breakpoint

func ok_one() -> void:
    var r = preload("res://fixed.tres")
'''

SELF_DEBUG_CLEAN = '''extends Node

const HERO := "res://hero.tres"

var _cached: Resource

func _ready() -> void:
    _cached = load(HERO)

func _process(delta):
    pass

func check(p: Resource) -> void:
    if p == null:
        push_error("资源缺失")
'''

SELF_CS_ASYNC_BAD = '''using Godot;

public partial class Loader : Node
{
    async void LoadAsync()
    {
        await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
    }
}
'''

SELF_CS_ASYNC_CLEAN = '''using Godot;

public partial class Loader : Node
{
    async System.Threading.Tasks.Task LoadAsync()
    {
        await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
        if (!IsInstanceValid(this)) return;
    }
}
'''

SELF_LONG_BAD = '''extends Node

func too_long() -> void:
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1
    var a = 1

    return
'''

SELF_SEC_BAD = '''extends Node

const API_KEY := "supersecret12345678"

func save():
    var f = FileAccess.open_encrypted_with_pass("user://s.dat", FileAccess.WRITE, "pw123456")
    f.store_string("x")
    f.close()

func check_daily():
    return Time.get_unix_time_from_system() - last > 86400

func check_mac(mac):
    return mac == computed_mac

func guard():
    if OS.is_debug_build():
        get_tree().quit()
'''

SELF_SEC_CLEAN = '''extends Node

const _A := "7f3a"
var _key: PackedByteArray

func _ready():
    _key = (_A + _load_blob()).sha256_text().hex_decode()

func save():
    var mac = Crypto.new().hmac_digest(HashingContext.HASH_SHA256, _key, payload)
    var f = FileAccess.open_encrypted_with_pass("user://s.dat", FileAccess.WRITE, "pw123456")
    f.store_buffer(payload)
    f.close()

func check_daily():
    return Time.get_ticks_msec() - last_mono > 86400000

func check_mac(mac):
    return Crypto.new().constant_time_compare(mac, computed_mac)
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
            'ex.gd': SELF_EXTRA_BAD, 'exok.gd': SELF_EXTRA_CLEAN,
            'sec.gd': SELF_SEC_BAD, 'secok.gd': SELF_SEC_CLEAN,
            'hot.gd': SELF_HOT_BAD, 'hotok.gd': SELF_HOT_CLEAN,
            'long.gd': SELF_LONG_BAD,
            'dbg.gd': SELF_DEBUG_BAD, 'dbgok.gd': SELF_DEBUG_CLEAN,
            'sh.gdshader': SELF_SHADER_BAD, 'shok.gdshader': SELF_SHADER_CLEAN,
            'misc.gd': SELF_MISC_BAD, 'miscok.gd': SELF_MISC_CLEAN,
            'v47.gd': SELF_V47_BAD, 'v47ok.gd': SELF_V47_CLEAN,
            'asy.cs': SELF_CS_ASYNC_BAD, 'asyok.cs': SELF_CS_ASYNC_CLEAN,
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

        # --- GD6x 3D/渲染 与 GD7x 语言/工程/调试 ---
        for rid, label in (('GD61', '直接赋值 global_position'),
                           ('GD62', 'spot_angle 超 89'),
                           ('GD63', 'editor_only=true'),
                           ('GD64', 'set_shader_parameter 字面量名'),
                           ('GD65', 'visibility_aabb'),
                           ('GD71', 'assert 做运行时校验'),
                           ('GD72', 'emit_signal 3.x 写法'),
                           ('GD73', 'duplicate() 浅拷贝'),
                           ('GD74', 'print() 调试输出'),
                           ('GD75', 'await 后未判 is_instance_valid')):
            check(rid in ids('ex.gd'), 'ex.gd 命中 %s（%s）' % (rid, label))

        for rid, label in (('GD61', '写局部 position'),
                           ('GD62', 'spot_angle 在范围内'),
                           ('GD63', '未设 editor_only'),
                           ('GD71', '改用 push_error'),
                           ('GD72', '用 .emit()'),
                           ('GD73', 'duplicate(true) 深拷贝'),
                           ('GD74', '用 print_debug'),
                           ('GD75', 'await 后判 is_instance_valid')):
            check(rid not in ids('exok.gd'), 'exok.gd 不报 %s（%s）' % (rid, label))

        # --- GD9x 性能与热路径 ---
        for rid, label in (('GD91', '热帧内同步 load'),
                           ('GD92', '热帧内字符串动作查询'),
                           ('GD93', '浮点相等比较'),
                           ('GD94', 'distance_to 阈值比较'),
                           ('GD95', 'Resource 未 duplicate'),
                           ('GD96', 'physics_process 内 await'),
                           ('GD97', '空函数体'),
                           ('GD98', '自赋值')):
            check(rid in ids('hot.gd'), 'hot.gd 命中 %s（%s）' % (rid, label))

        check('GD99' in ids('long.gd'), 'long.gd 命中 GD99（函数体超 80 行）')

        for rid in ('GD91', 'GD92', 'GD93', 'GD94', 'GD95',
                    'GD96', 'GD97', 'GD98', 'GD99'):
            # hotok.gd 是干净样本：preload 在 _ready、&"jump"、
            # distance_squared_to、有 duplicate
            check(rid not in ids('hotok.gd'), 'hotok.gd 不报 %s（干净样本）' % rid)

        # --- GD101+ 调试与交付类 ---
        for rid in ('GD101', 'GD102', 'GD103', 'GD104', 'GD105', 'GD107'):
            check(rid in ids('dbg.gd'), 'dbg.gd 命中 %s' % rid)
        check('GD106' in ids('asy.cs'), 'asy.cs 命中 GD106（async void）')

        # --- GDS0x shader 规则 ---
        for rid in ('GDS01', 'GDS02', 'GDS03', 'GDS04', 'GDS05',
                    'GDS07', 'GDS08'):
            check(rid in ids('sh.gdshader'), 'sh.gdshader 命中 %s' % rid)
        for rid in ('GDS01', 'GDS02', 'GDS03', 'GDS04', 'GDS05',
                    'GDS07', 'GDS08'):
            check(rid not in ids('shok.gdshader'), 'shok.gdshader 不报 %s（干净样本）' % rid)
        # --- GD12x 4.7 迁移 ---
        for rid in ('GD121', 'GD122', 'GD123', 'GD124', 'GD125'):
            check(rid in ids('v47.gd'), 'v47.gd 命中 %s' % rid)
        for rid in ('GD121', 'GD122', 'GD123', 'GD124', 'GD125'):
            check(rid not in ids('v47ok.gd'), 'v47ok.gd 不报 %s（干净样本）' % rid)
        # --- GD11x 动画/音频/大世界/XR ---
        for rid in ('GD111', 'GD112', 'GD113', 'GD114', 'GD115',
                    'GD116', 'GD117'):
            check(rid in ids('misc.gd'), 'misc.gd 命中 %s' % rid)
        for rid in ('GD111', 'GD112', 'GD113', 'GD114', 'GD115',
                    'GD116', 'GD117'):
            check(rid not in ids('miscok.gd'), 'miscok.gd 不报 %s（干净样本）' % rid)
        # .gdshader 必须被识别（此前完全不识别，shader 在审查里是隐形的）
        check(any(i['id'].startswith('GDS') for i in res['sh.gdshader']),
              '.gdshader 被识别并产生结果（扩展名已接入）')

        # 干净样本：常量路径、push_error、Task
        for rid in ('GD101', 'GD102', 'GD103', 'GD104', 'GD105', 'GD107'):
            check(rid not in ids('dbgok.gd'), 'dbgok.gd 不报 %s（干净样本）' % rid)
        check('GD106' not in ids('asyok.cs'), 'asyok.cs 不报 GD106（async Task）')


        # --- GD8x 存档安全 / 防作弊 ---
        for rid, label in (('GD81', '加密但未签名'),
                           ('GD82', '明文密钥写在脚本里'),
                           ('GD83', '用系统时间做每日奖励'),
                           ('GD84', '用 == 比 HMAC'),
                           ('GD85', 'debug 检测后直接退出')):
            check(rid in ids('sec.gd'), 'sec.gd 命中 %s（%s）' % (rid, label))

        # GD81 有 absent 模式：出现签名相关代码就不该报
        check('GD81' not in ids('secok.gd'), 'secok.gd 不报 GD81（有 HMAC 签名）')
        for rid, label in (('GD83', '改用 get_ticks_msec'),
                           ('GD84', '改用 constant_time_compare')):
            check(rid not in ids('secok.gd'), 'secok.gd 不报 %s（%s）' % (rid, label))

        # --rules 必须列出全部规则 ID。
        # 踩过的坑：加了 DOMAIN_RULES 却没更新 --rules，用户查表只看到 15 条，
        # 以为 GD21+ 不存在（是 game-dev 交叉引用时才发现的）。
        # 这种"文档比实现旧"不会报错，只能靠断言钉住。
        import subprocess
        _r = subprocess.run([sys.executable,
                             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          'godot-audit.py'), '--rules'],
                            capture_output=True, text=True)
        # \d{2} 匹配不到三位数编号：加 GD101+ 后这条检查会误报"全部遗漏"。
        listed = set(re.findall(r'\bGD\d{2,3}\b', _r.stdout))
        defined = set()
        for tbl in (LINE_RULES, FRAME_RULES):
            defined.update(x[0] for x in tbl)
        defined.update(x[0] for x in DOMAIN_RULES)
        # GD96/GD99 走方法体检测，不在 DOMAIN_RULES 里，需显式补
        defined.update(('GD96', 'GD99'))
        defined.update(('GD01', 'GD02', 'GD03', 'GD14', 'GD15'))
        missing = sorted(defined - listed)
        check(not missing,
              '--rules 列出全部 %d 条规则（漏: %s）' % (len(defined), missing or '无'))

        print('\n自检：%d 通过 / %d 失败' % (ok, len(fail)))
        for f in fail:
            print('  失败：%s' % f)
        return 1 if fail else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=help_text())
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
        for rid, level, rule, rlang, pat, msg, fix in SHADER_RULES:
            if rid in seen:
                continue
            seen.add(rid)
            print("  %-6s %-4s %-8s %s" % (rid, level, rule, msg[:46]))
        for rid, level, rule, msg in (("GD01", "P0", "孤儿节点", "remove_child 后无释放"),
                                      ("GD02", "P0", "tween泄漏", "create_tween 未保存"),
                                      ("GD03", "P1", "timer失控", "create_timer 未保存"),
                                      ("GD14", "P1", "物理时机", "_process 内做物理移动"),
                                      ("GD96", "P0", "物理帧挂起", "_physics_process 内 await"),
                                      ("GD99", "P2", "函数过长", "函数体超 80 行"),
                                      ("GD15", "P1", "信号未断", "清理回调里未 disconnect")):
            print("  %-6s %-4s %-8s %s" % (rid, level, rule, msg))
        # 领域规则此前没列进来：`--rules` 只显示 15 条，而实际有 44 条，
        # 用户查规则表会以为 GD21+ 不存在（game-dev 交叉引用时才发现）。
        print()
        print("  领域规则（GD2x 物理 / GD3x UI / GD4x IO / GD5x 其他 /"
              " GD6x 3D / GD7x 语言）：")
        for rid, level, rule, rlang, pat, msg, fix, absent in (DOMAIN_RULES + EXTRA_DOMAIN_RULES):
            if rid in seen:
                continue
            seen.add(rid)
            print("  %-6s %-4s %-8s %s" % (rid, level, rule, msg[:52]))
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
