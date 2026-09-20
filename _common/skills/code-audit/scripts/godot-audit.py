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
    # --- 网络同步 ---
    ("GD131", "P1", "传输模式", "gd",
     r'@rpc\s*\(\s*["\'](?:any_peer|authority)["\']\s*,?\s*(?:["\']call_remote["\']\s*,?\s*)?\)',
     "@rpc 只写了 mode（或 mode+call_remote）没写 transfer —— 默认是 **reliable**，高频位置同步走可靠通道会因重传越来越滞后",
     "高频同步显式写 @rpc(\"any_peer\", \"call_remote\", \"unreliable_ordered\")；只有命中/生成等关键事件用 reliable"),    ("GD106", "P1", "异步异常", "cs", r"async\s+void\b",
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
    ("GD134", "P1", "传输模式缺失", "gd", r"@rpc\s*\(",
     "文件里有 @rpc 但从未出现 unreliable —— 高频同步默认走 reliable，丢包重传会让位置越来越滞后",
     "每帧位置/输入用 unreliable_ordered（带序号）；只有关键事件用 reliable",
     r"(?<!\w)unreliable"),
    ("GD135", "P1", "插件缺tool", "gd", r"extends\s+EditorPlugin",
     "继承 EditorPlugin 但全文没有 @tool —— 脚本在编辑器里不执行，插件看起来完全没生效",
     "在脚本顶部加 @tool 注解",
     r"@tool"),
    ("GD136", "P1", "插件未注销", "gd", r"_enter_tree\s*\(",
     "_enter_tree 里注册了东西但 _exit_tree 不存在 —— 禁用插件后 UI 残留、重复启用会翻倍",
     "_exit_tree() 必须对称注销 _enter_tree() 注册的一切（控件、菜单、检视器）",
     r"_exit_tree\s*\("),

    ("GD132", "P0", "未校验发送者", "gd", r'@rpc\s*\(\s*["\']any_peer["\']',
     "any_peer 允许任何人调用，但全文没有 get_remote_sender_id() —— 等于开放作弊接口",
     "函数内先取 sender 并校验身份与合法性（不只是判断是谁，还要判断能不能做）",
     r"get_remote_sender_id"),
    ("GD133", "P1", "sender失效", "gd", r"await[\s\S]{0,200}?get_remote_sender_id\s*\(",
     "await 之后调用 get_remote_sender_id() —— 它只在 RPC 函数内有效，await 后会变回 0",
     "在 await 之前把 sender 存成局部变量，后面都用这个变量",
     None),

    # ---- 程序化生成 ----
    ("GD141", "P1", "全局随机源", "gd", r"(?<![\w.])randi\s*\(\s*\)|(?:^|[^\w.])randf\s*\(\s*\)",
     "用了全局 randi()/randf() —— 是全局状态，任何脚本或插件调用都会改变结果，生成不可复现",
     "改用 RandomNumberGenerator 实例并设 seed：rng.seed = s; rng.randi_range(a, b)",
     r"RandomNumberGenerator"),
    ("GD142", "P1", "生成改场景树", "gd", r"for[\s\S]{0,300}?add_child\s*\(",
     "循环里直接 add_child —— 每帧插几十个节点会掉帧，且生成过程与场景树耦合",
     "先在纯数据层算完布局，最后一次批量实例化；分帧生成时注意与场景树交互非线程安全",
     None),
    ("GD143", "P1", "生成未校验连通", "gd", r"(?i)(?:cellular|maze|dungeon|cave|generate_(?:map|level))",
     "做了程序化生成但全文没有连通性校验 —— 元胞自动机最容易产出到不了的区域，玩家会卡死",
     "生成后从出生点 flood fill，未访问的地板改写/连接/删除，或只保留最大连通分量",
     r"(?i)(?:flood_fill|floodfill|connected|reachab|连通)"),

    # ---- AI 感知 ----
    ("GD144", "P1", "射线旧写法", "gd", r"intersect_ray\s*\(\s*(?!.*QueryParameters)[^)]*,[^)]*\)",
     "intersect_ray 用了 3.x 的裸参数写法 —— 4.x 必须传 PhysicsRayQueryParameters3D",
     "改用 PhysicsRayQueryParameters3D.create(from, to, mask, exclude) 再 intersect_ray(query)",
     r"PhysicsRayQueryParameters3D"),
    ("GD145", "P2", "感知无记忆", "gd", r"(?i)vision|view_cone|can_see|视线|视锥",
     "做了视觉检测但全文没有最后已知位置相关逻辑 —— 目标一消失敌人立刻失忆，行为很假",
     "丢失目标后保存最后已知位置，并走搜索→放弃→返回的有限状态",
     r"(?i)(?:last_known|last_seen|最后已知)"),

    # ---- 骨骼与 IK ----
    ("GD146", "P0", "不存在的IK节点", "gd", r"PoleModifier3D|SplineIK3D",
     "引用了 PoleModifier3D 或 SplineIK3D —— 这两个节点在 Godot 4.7 **不存在**（常见错误说法）",
     "Pole 用 TwoBoneIK3D 的 pole_node/pole_direction；长链曲线用 IterateIK3D 加多目标或找插件",
     None),
    ("GD147", "P2", "两骨IK缺pole", "gd", r"TwoBoneIK3D",
     "用了 TwoBoneIK3D 但全文没设 pole —— 关节没有共面参考，膝盖/肘部会乱翻",
     "设 pole_node（构建关节共面）与 pole_direction（控制扭转方向）",
     r"(?<!\w)pole_"),

    # ---- 配表 / 数据驱动 ----
    ("GD151", "P1", "共享Resource", "gd", r"@export\s+var\s+\w+\s*:\s*Resource\b|@export\s+var\s+\w+\s*:\s*Array\s*\[",
     "@export 了 Resource 或 Resource 数组 —— 是共享引用，改一个实例会全改（Godot 4 的 #1 新手 bug）",
     "运行时实例用 duplicate_deep(Resource.DEEP_DUPLICATE_INTERNAL)，或设 resource_local_to_scene",
     r"duplicate_deep|resource_local_to_scene|duplicate\s*\(\s*true"),
    ("GD152", "P2", "配表无校验", "gd", r"(?i)(?:load_csv|parse_csv|read_csv|csv_to_|import_table)",
     "解析 CSV 配表但全文没有任何校验 —— 缺列/类型错/ID 重复会静默进包，问题在运行时以无关形式出现",
     "导入期校验主键唯一、类型、范围、外键悬空，失败要 push_error 并阻止导入",
     r"(?i)(?:validate|校验|push_error|assert)"),

    # ---- VFX / 游戏感 ----
    ("GD153", "P0", "顿帧无法恢复", "gd", r"Engine\.time_scale\s*=\s*0",
     "把 time_scale 设为 0 但恢复用的定时器没有 ignore_time_scale —— 定时器也停摆，游戏永久卡死",
     "用 create_timer(t, false, false, true) 或显式 ignore_time_scale=true 来恢复（位置参数与具名参数都要认）",
     r"ignore_time_scale|create_timer\s*\([^)]*,[^)]*,[^)]*,\s*true"),
    ("GD154", "P2", "震动写死偏移", "gd", r"(?i)(?:camera|offset)[\s\S]{0,120}?randf_range\s*\(",
     "把随机偏移直接写进相机 offset —— 多源命中互相覆盖、频谱是白噪声（像筛子不是被撞）、强度不衰减",
     "改用 trauma 模型：trauma 只衰减可叠加 cap 1，用 trauma^exponent 驱动采样噪声",
     r"(?<!\w)trauma"),

    # ---- 经济 / 长线 ----
    ("GD155", "P1", "货币用浮点", "gd", r"(?i)(?:var\s+\w*(?:gold|coin|money|currency|price|cost)\w*\s*(?::\s*float\s*)?=\s*\d+\.\d)",
     "货币/价格用了浮点字面量 —— 精度误差会累积，对不上账",
     "货币与计数一律用 int；加成计算才用浮点，两者在明确转换点相接",
     r"(?<!\w)int\s*\("),
    ("GD156", "P2", "掉落无保底持久化", "gd", r"(?i)(?:randi_weighted|rand_weighted|pick_random|drop_table)",
     "做了权重掉落但全文没有保底计数 —— 连续未中次数必须随存档持久化且与卡池绑定",
     "保底计数存进存档，按卡池分别计（不能全局共用一个计数器）",
     r"(?i)(?:pity|保底|dry_count|since_last)"),

    # ---- 输入重绑定 ----
    ("GD161", "P1", "输入3.x残留", "gd", r"get_action_list\s*\(|(?<![\w.])scancode\b",
     "用了 3.x 的 get_action_list() 或 scancode —— 4.x 是 action_get_events() 与 keycode/physical_keycode，混用会静默类型转换存错字段",
     "改用 InputMap.action_get_events()；键字段用 physical_keycode 或 keycode",
     None),
    ("GD162", "P1", "键字段重复", "gd", r"(?<!\w)keycode\s*=",
     "设置了 keycode 但同一文件也设了 physical_keycode —— 官方明确三者只能设其一，全设会导致布局变化时映射错乱",
     "只设 physical_keycode（存物理位置），keycode 仅用于当前布局显示",
     None),
    ("GD163", "P1", "振动未停止", "gd", r"start_joy_vibration\s*\(",
     "启动了手柄振动但全文没有 stop_joy_vibration —— 振动不会因退出场景/暂停/崩溃自动停止",
     "在暂停、切后台、释放场景、重映射结束时显式调用 stop_joy_vibration(device)",
     r"stop_joy_vibration"),

    # ---- 回放与确定性 ----
    ("GD164", "P2", "回放依赖墙钟", "gd", r"(?i)(?:replay|recorder|record|ghost|demo|frame_log)[\s\S]{0,600}?(?:Time\.get_unix_time_from_system|OS\.get_ticks_msec|Time\.get_ticks_msec)",
     "回放/录制代码里用了墙钟时间 —— 确定性重放必须用固定步长的 delta，墙钟会让每次结果不同",
     "用固定时间步累加的 tick 计数驱动，不读系统时间",
     None),
    ("GD165", "P2", "录制用rand", "gd", r"(?i)(?:replay|recorder|record|ghost|demo|frame_log)[\s\S]{0,600}?(?<![\w.])randi\s*\(\s*\)",
     "回放/录制路径里用了全局 randi()/randf() —— 破坏确定性，重放结果会不一致",
     "用带固定种子的 RandomNumberGenerator 实例，并把 seed 写进回放文件",
     r"(?:RandomNumberGenerator|\.seed\s*=)"),

    # ---- Mod / 存档迁移（上一轮曾被覆盖，此处重建）----
    ("GD166", "P0", "Mod路径拼接", "gd", r"(?i)(?:extract|unzip|unpack|install_mod|mod_path|mod_root|mod_dir|addon_path)[\s\S]{0,400}?(?:\+\s*[\"']|\+\s*\w*(?:name|file|entry))",
     "Mod 解压时直接拼接文件名到目标路径 —— 未校验 ../ 就是 zip-slip，可写入任意目录",
     "解压前校验规范化后的路径必须仍在目标根目录内（用 Path 规范化后比对前缀）",
     r"(?i)(?:normalize|simplify|begins_with\s*\(\s*(?:mod_root|target|dest)|\.resolve)"),
    ("GD167", "P2", "pack来源未记", "gd", r"load_resource_pack\s*\(",
     "加载了 resource pack 但全文没有记录来源 —— Mod 出问题时无法定位是哪个包引入的",
     "维护已加载 pack 的清单（路径、加载顺序、覆盖关系），便于排查与卸载",
     r"(?i)(?:loaded_packs|_pack_list|pack_manifest|记录)"),
    ("GD168", "P1", "加解密无兜底", "gd", r"open_encrypted\s*\(|open_encrypted_with_pass\s*\(",
     "调用加密存档 API 但全文没有错误处理 —— 存档损坏/密码错误会直接崩溃而不是走降级路径",
     "包在 try 里并对失败情形区分处理（损坏→提供备份恢复；密码错→提示而非静默丢档）",
     r"(?i)(?:if\s+\w+\s*==\s*(?:null|ERR_|OK)|match\s+\w*(?:err|result)|\berr\s*!=)"),
    ("GD169", "P1", "存档无版本号", "gd", r"(?i)(?:func\s+\w*save\w*\s*\(|store_var\s*\(|var_to_bytes\s*\(|FileAccess\.open)",
     "写存档但全文没有 VERSION/版本字段 —— 没有版本号的存档无法安全迁移，只能靠猜",
     "存档结构第一天就要带 VERSION 字段，并据此分派迁移路径",
     r"(?i)VERSION"),
    ("GD170", "P1", "迁移无备份", "gd", r"(?i)(?:func\s+\w*(?:migrate|upgrade_save|migrate_save)\w*)",
     "有存档迁移函数但全文没有备份动作 —— 迁移是不可逆操作，失败即丢失玩家进度",
     "迁移前先复制一份原档（.bak），失败时回滚；迁移后重算校验/HMAC",
     r"(?i)(?:backup|\.bak|copy_to|dir_copy|存档备份)"),

    # ---- 云存档 ----
    ("GD171", "P1", "云存档静默覆盖", "gd", r"(?i)(?:cloud|云存档|remote_save|sync_save)",
     "有云存档逻辑但全文没有冲突处理 —— 静默覆盖是玩家进度丢失的头号来源",
     "用单调递增的逻辑版本号判定先后，冲突时进人工选择（展示相对时间与设备，不要显示时间戳）",
     r"(?i)(?:conflict|冲突|version\s*[<>]|merged|选择)"),
    ("GD172", "P2", "时间戳判冲突", "gd", r"(?i)(?:get_mtime|modified_time|file_time)[\s\S]{0,200}?(?:>|>=|<|<=)",
     "用文件修改时间比较存档先后 —— 设备时钟可被改、跨时区、夏令时会改变字符串顺序，不能作权威判据",
     "改用每个存档槽单调递增的逻辑版本号；时间戳仅用于界面展示",
     r"(?i)(?:logic(?:al)?_?version|save_version|rev\s*\+)"),

    # ---- 调试工具 ----
    ("GD173", "P2", "作弊无标识", "gd", r"(?i)(?:var\s+\w*god\w*\s*:?=|var\s+\w*(?:invincible|invuln|cheat)\w*\s*:?=)",
     "有作弊/无敌开关但全文没有视觉标识 —— 测试者不知道自己开着无敌，测出不真实的结果",
     "作弊状态要有持久的屏幕标识，并写入带时间戳的审计日志（否则 bug 复现不了时无法归因）",
     r"(?i)(?:cheat_label|debug_label|作弊中|show_cheat|audit|log_cheat|cheat\.visible|cheat_indicator)"),
    ("GD174", "P2", "调试面板未隔离", "gd", r"Performance\.get_monitor\s*\(",
     "读取 Performance 指标但不区分构建 —— 部分监控在 release 导出包恒为 0、部分有约 1 秒延迟，会出现「面板显示 0」的假故障",
     "面板要同时显示 debug/release 标记、采样时间与更新间隔；release 预设移除或条件编译",
     r"(?i)(?:OS\.is_debug_build|debug_build|is_release|构建)"),

    # ---- 画质管线 ----
    ("GD181", "P2", "TAA非Forward+", "gd", r"(?:scaling_3d_mode|anti_aliasing)\s*=?\s*\d*[\s\S]{0,300}?(?:TAA|taa)",
     "用了 TAA 但项目可能是 Mobile/Compatibility 渲染器 —— TAA 仅在 Forward+ 可用，其他渲染器下会被静默忽略",
     "确认渲染方法为 Forward+ 再使用 TAA；否则改用 MSAA/FXAA",
     None),
    ("GD182", "P2", "超分未分层", "gd", r"(?:scaling_3d_mode\s*=|scaling_3d_scale\s*=)",
     "设置了 3D 超分缩放但 UI 未做分层 —— 文字会被连带糊掉",
     "UI 单独渲染到一个不缩放的 CanvasLayer/子视口，避免被超分影响",
     r"(?i)(?:ui_?viewport|ui_?layer|canvas_?layer|分层|不缩放)"),

    # ---- 载具 / 物理 ----
    ("GD183", "P1", "载具无自定义质心", "gd", r"(?:extends\s+VehicleBody3D|VehicleBody3D)",
     "用了 VehicleBody3D 但没有自定义质心 —— 默认按形状算质心，包围盒偏高时会「一开就翻」",
     "显式设置 center_of_mass_mode = CUSTOM 并把质心放在车身局部原点下方",
     r"(?i)(?:center_of_mass|CENTER_OF_MASS_MODE_CUSTOM)"),
    ("GD184", "P2", "高速物无CCD", "gd", r"(?:linear_velocity\s*=\s*Vector3|apply_central_impulse)\s*\(",
     "设置了高速运动但全文没有 continuous_cd —— 高速物体会穿透薄墙",
     "给高速/关键刚体启用 continuous_cd，并加厚薄墙（墙厚要覆盖单步位移）",
     r"(?:continuous_cd|continuous\s*=\s*)"),

    # ---- 角色自定义 ----
    ("GD185", "P1", "共享材质直改", "gd", r"\.albedo_color\s*=|set_shader_parameter\s*\(",
     "直接改材质属性但全文没有 duplicate —— 共享材质会让所有引用同一材质的装备一起变（染色串色）",
     "改之前用 material.duplicate() 做实例私有化；注意 duplicate(true) 仍是浅拷贝",
     r"(?:\.duplicate\s*\()"),
    ("GD186", "P2", "blendshape未判空", "gd", r"set_blend_shape_value\s*\(",
     "调用 set_blend_shape_value 但没有前置判空/判索引 —— mesh 为 null 或索引无效时会报错",
     "调用前用 get_blend_shape_count() 判空，用 find_blend_shape_by_name 取索引并校验 >= 0",
     r"(?:get_blend_shape_count|find_blend_shape_by_name)"),

    # ---- UI 进阶 ----
    ("GD191", "P1", "BBCode未转义", "gd", r"(?:append_text|push_paragraph|\.text\s*\+?=)[^\n]*?(?:玩家|昵称|name|nick|玩家名)",
     "把玩家输入（昵称/聊天）直接拼进 RichTextLabel —— 内容含 [ 会破坏排版（BBCode 注入）",
     "对用户输入调用 escape_bbcode 后再拼入；不要拼未转义的 [ ] 标记",
     r"(?:escape_bbcode)"),
    ("GD192", "P2", "海量条目无虚拟化", "gd", r"for\s+\w+\s+in\s+(?:range\s*\(|\w+\.size\s*\(|\w+)\s*[\s\S]{0,300}?(?:Button|Label|Panel|Control|TextureRect)\.new\s*\([\s\S]{0,200}?add_child",
     "循环把大量条目 add_child 进容器 —— 没有内置虚拟列表，千级节点会卡死",
     "自己写对象池化虚拟列表，只实例化可见项；Tree 也不虚拟化（70k 项约 1.21 GiB）",
     r"(?i)(?:virtual|pool|recycle|虚拟化|对象池)"),
    ("GD193", "P2", "UI缺焦点配置", "gd", r"(?:extends\s+Button|@onready\s+var\s+\w*button|Button)",
     "有按钮但没有 focus_neighbor / grab_focus 配置 —— 鼠标能点但手柄选不中",
     "设置 focus_mode 与 focus_neighbor_*，并在打开界面时显式 grab_focus()",
     r"(?:focus_neighbor|grab_focus|focus_mode)"),

    # ---- 诊断与稳定性 ----
    ("GD194", "P1", "assert含副作用", "gd", r"assert\s*\(\s*(?:\w+\.)?\w+\s*\.\s*(?:remove|erase|free|append|push_back|pop)",
     "assert 表达式里调用了会修改状态的方法 —— assert 在非 debug 构建中不被求值，release 里这些副作用根本不执行",
     "assert 参数必须是无副作用表达式；需要执行的逻辑移到 assert 之前单独调用",
     None),
    ("GD195", "P2", "资源加载未判空", "gd", r"(?:load\s*\(|preload\s*\(|ResourceLoader\.load\s*\()",
     "加载资源但全文没有 null 判断 —— 失败时返回 null，静默继续是最危险的反模式",
     "加载后立即判空并走降级/占位资源分支",
     r"(?:==\s*null|!=\s*null|if\s+not\s+\w|if\s+\w+\s*==\s*null)"),
    ("GD196", "P2", "无错误日志钩子", "gd", r"(?:func\s+_ready\s*\(|func\s+_init\s*\()",
     "项目没有注册自定义 Logger —— 未捕获的脚本错误无法被收集（GDScript 没有 try/catch）",
     "在 autoload 的 _init() 里调 OS.add_logger() 实现 Logger._log_error，尽早注册",
     r"(?:add_logger)"),

    # ---- 商业化 / 变现 ----
    ("GD201", "P0", "客户端判支付成功", "gd", r"(?:purchase|buy|pay|支付|购买)\w*\s*\([\s\S]{0,200}?(?:success|成功|completed|ok)",
     "客户端自己判定支付成功并直接发货 —— 客户端说「我付了钱」绝不能信，收据必须服务器校验",
     "客户端只发起支付；服务器校验收据（签名/证书链/bundle_id/product_id/transaction_id）后再发货",
     r"(?i)(?:server|服务器|verify_receipt|收据验证)"),
    ("GD202", "P1", "抽卡随机在客户端", "gd", r"(?:randi|randf|randf_range|RandomNumberGenerator)",
     "代码里有随机但上下文涉及抽卡/掉落 —— 随机必须在服务器端，客户端随机会被改",
     "抽奖结果由服务器计算并返回；客户端只展示结果",
     r"(?i)(?:server|服务器|rpc|remote)"),
    ("GD204", "P1", "日期用本地时区", "gd",
     r"(?:get_datetime_dict_from_system|get_date_dict_from_system)\s*\(\s*(?:false\s*)?\)|OS\.get_(?:date|time|datetime)\s*\(",
     "用本地时间做每日重置/月卡到期 —— 玩家可改时钟，跨时区/夏令时会导致缺一天或多一天",
     "所有商业计时用 UTC：get_datetime_dict_from_system(true)，不要用本地时间",
     r"(?i)(?:utc|from_system\s*\(\s*true)"),
    # ---- 投射物 / 弹道 ----
    ("GD205", "P1", "高速投射物无扫描", "gd", r"(?i)(?:bullet|projectile|子弹|投射物|弹道)",
     "高速投射物直接靠物理位移判定 —— 一帧内位移大会穿透（tunneling）；官方称 CCD「有时有效」",
     "用「上一帧位置 → 本帧位置」的射线/ShapeCast 扫描补判定",
     r"(?:intersect_ray|ShapeCast|raycast|射线)"),
    ("GD206", "P2", "预测与实弹两套公式", "gd", r"(?:func\s+\w*(?:predict|aim|trajectory)\w*\s*\(|预测|瞄准线|aim_line)",
     "有弹道预测但预测与真实弹道各写一套 —— 显示落点与实际落点不一致",
     "预测线必须复用与真实弹道相同的重力、时间步和碰撞查询，只画到首个碰撞点",
     r"(?i)(?:simulate|复用|共用|shared|same|同一)"),

    # ---- 进阶移动 ----
    ("GD211", "P1", "抓边直接赋坐标", "gd", r"(?:ledge|抓边|抓取边缘)[\s\S]{0,300}?(?:global_transform\.origin|global_position)\s*=",
     "抓边后直接把坐标赋到边缘点 —— 可能穿透薄墙或动画不匹配",
     "用 move_and_collide() 朝目标移动并设最大插值距离，分吸附/悬停/攀爬三阶段",
     r"(?:move_and_collide|move_and_slide)"),
    ("GD212", "P1", "up_direction设为零", "gd", r"up_direction\s*=\s*Vector\d?\.?\s*ZERO",
     "把 up_direction 设为 ZERO —— 官方明确不允许（它用于区分地板/墙/天花板）",
     "up_direction 必须是一个非零方向向量；可变重力场景要同步 up、相机与移动平面",
     None),
    ("GD213", "P2", "改重力未同步相机", "gd", r"(?:up_direction\s*=|gravity\s*=\s*Vector\d?\s*\()",
     "改了 up_direction 或重力向量，但没有同步相机/移动平面 —— 角色会侧着走或相机翻转",
     "改重力方向时 up、相机 basis、移动平面要一起更新（不只是改向量）",
     r"(?i)(?:camera|相机|basis|quaternion|rotate)"),

    # ---- 多人社交 ----
    ("GD214", "P1", "聊天仅客户端过滤", "gd", r"(?:chat|聊天|send_msg|消息)[\s\S]{0,300}?(?:filter|敏感词|屏蔽词|censor)",
     "聊天过滤只在客户端做 —— 改包就能绕过；UGC 必须服务器最终过滤",
     "客户端可预过滤改善体验，但服务器必须做最终过滤、限流、审计与留存",
     # absent 不能含 rpc：坏样本用 rpc 广播给客户端，并不是服务器过滤。
     # rpc 只证明"发了网络消息"，不能证明"服务器做了最终过滤"。
     r"(?i)(?:server|服务器|服务端|audit|审核|留存)"),
    ("GD215", "P2", "peer ID当玩家身份", "gd", r"(?:multiplayer\.get_unique_id|get_unique_id)\s*\(\s*\)",
     "用 peer ID 作为玩家身份 —— 重连后会变，且不是稳定账号标识（官方大厅示例也不这么做）",
     "登录后用独立会话/账号 ID；peer ID 只用于本次连接的路由",
     r"(?i)(?:account|账号|user_id|session|auth)"),
    # ---- 生存 / 角色状态 ----
    ("GD221", "P1", "死亡写成布尔", "gd", r"(?:is_dead|dead|死亡)\s*(?::=|\+=|=)\s*(?:true|false)",
     "死亡用布尔赋值表达 —— 会让 _process 反复触发；死亡是四阶段状态机（TRIGGERED/PLAYING/SETTLING/RESPAWNING）",
     "改成枚举状态机，并在死亡期间禁止输入、移动、伤害、拾取、保存",
     r"(?:enum|STATE_|DEAD_|state\s*=|set_state)"),
    ("GD222", "P1", "死亡期间仍可保存", "gd", r"(?:is_dead|dead|死亡)\s*(?::=|=)\s*true[\s\S]{0,120}?(?:save_game|save\s*\(|存档)",
     "死亡流程里调用保存 —— 会把「死亡状态」写进稳定存档，读档即死循环",
     "死亡在状态结算后才提交临时存档；进入死亡播放期间禁止保存",
     # absent 不能含 respawn：坏样本正是「死了立刻 respawn」，
     # 有 respawn 恰恰说明流程有问题，不能当作已正确处理的证据。
     r"(?i)(?:settle|结算|forbid|禁止|defer|延后)"),
    ("GD223", "P1", "上限存计算结果", "gd", r"(?:max_hp|max_health|上限)\s*(?::=|=)\s*\w+\s*[+\-*]",
     "把上限算成一个变量并直接存 —— 上限变化会造成超上限、比例回血错误、永久容量丢失",
     "存 base_value + 修饰器列表 + current，读档时重建输入再算上限，最后把 current 夹到合法区间",
     r"(?i)(?:base_value|base|modifier|recalc|重算)"),
    ("GD224", "P2", "重生未清Tween", "gd", r"(?:respawn|重生|复活)\w*\s*\(",
     "有重生流程但全文没有清理 Tween/Timer —— 跨场景引用泄漏（create_tween 不自动绑定节点）",
     "重生时快照→清场→生成→恢复→释放；清掉临时修饰器、输入缓冲、Tween、Timer、飞行投射物",
     r"(?:kill|stop|queue_free|free\s*\(|clear)"),

    # ---- 叙事 / 进程 ----
    ("GD225", "P1", "flag散落手写字符串", "gd", r"(?:set_flag|flags?\s*\[\s*\"|has_flag\s*\(\s*\")",
     "剧情 flag 用魔法字符串散落各处 —— 后期无法重构，且同类 key 会撞车",
     "集中在 StoryState；用三段式命名（global. / meta. / act1.xxx）与常量集合，避免手写字面量",
     r"(?i)(?:const|StringName|StoryState|enum)"),
    ("GD226", "P1", "结局用ifelif链", "gd", r"(?:结局|ending)\w*[\s\S]{0,400}?(?:elif\s+.+?:[\s\S]{0,200}?){2,}",
     "结局判定写成一长串 if/elif —— 很快出现优先级、重复条件、测试覆盖与策划改表问题",
     "改成数据驱动的判定表：id / priority / conditions / required_flags / incompatible_with，按优先级排序并处理冲突",
     r"(?i)(?:priority|优先级|table|判定表|sort_custom)"),

    # ---- 谜题 / 机关 ----
    ("GD231", "P1", "反射无迭代上限", "gd", r"(?:while\s+true|while\s+not\b|for\s+\w+\s+in\s+range\s*\(\s*\d{3,}\s*\))",
     "反射循环没有迭代上限 —— 两面镜子互照会无限反射并卡死主线程（这是数学问题不是调优问题）",
     "硬编码 MAX_BOUNCES（推荐 8），且每次反射用上一次命中的 RID 做 exclude",
     r"(?:MAX_BOUNCES|max_bounces|上限|limit)"),
    ("GD232", "P1", "反射用reflect非bounce", "gd", r"\.reflect\s*\(",
     "用了 Vector3.reflect() 做镜面反射 —— Godot 里 bounce = -reflect，混用会得到相反方向",
     "镜面反射方向用 Vector3.bounce(normal)；reflect 是「对法线所在平面做镜面」，语义不同",
     r"(?:\.bounce\s*\()"),
    ("GD233", "P2", "机关状态存动画进度", "gd", r"(?:current_animation_position|动画进度)\s*(?::=|=)",
     "把动画进度当机关状态存 —— 官方明确 current_animation_position 只有 getter；应存开/关状态",
     "存「门开着」这样的状态；读档时用 seek(length, true) 跳到动画终点而不是回放",
     r"(?:seek\s*\()"),
    ("GD234", "P1", "交互绑死按键", "gd", r"(?:Input\.is_action_just_pressed\s*\(\s*.?\"?(?:interact|ui_accept))",
     "交互直接绑死按键 —— 键鼠/手柄/触屏三平台会打架；触屏没有该按键",
     "把交互抽象成「意图」：触屏把屏幕坐标投影成世界射线打到 Interactable 就触发",
     r"(?:InputEventScreenTouch|screen_to_world|射线|投影|意图)"),

    # ---- 时间操控 ----
    ("GD235", "P0", "停帧计时器受缩放", "gd", r"Engine\.time_scale\s*=\s*0*(?:\.0+)?\b",
     "time_scale 设为 0（停帧）但恢复用的计时器没传 ignore_time_scale —— 计时器也停，游戏永久卡死",
     "停帧/慢动作的恢复计时器必须 create_timer(t, true)，确保不受 time_scale 影响",
     r"(?:create_timer\s*\([^)]*,\s*true|ignore_time_scale)"),
    ("GD236", "P1", "改time_scale无恢复", "gd", r"Engine\.time_scale\s*=\s*[\d.]+",
     "改了 Engine.time_scale 但全文没有恢复路径 —— 任何路径漏掉恢复都会导致游戏永久慢动作",
     "恢复必须「必然发生」：统一封装入口，用 Tween 平滑过渡并在完成时强制归位",
     # absent 不能含 time_scale = 1：坏样本 hitstop() 里就写了归位，
     # 但 slowmo() 没有任何恢复 —— 出现归位赋值不等于所有路径都有恢复。
     r"(?i)(?:TimeScale\.|time_scale_manager|ensure_reset|统一封装|封装入口)"),
    ("GD237", "P1", "暂停时UI不可交互", "gd", r"get_tree\(\)\.paused\s*=\s*true",
     "整树暂停但没给 UI 设 process_mode —— 暂停菜单自己也停了，点不动",
     "暂停菜单节点设 PROCESS_MODE_WHEN_PAUSED 或 ALWAYS；注意它与 Tween 忽略缩放是两件事",
     r"(?:PROCESS_MODE_|process_mode\s*=)"),


    # ---- 域专项补充（GD241-GD274）----
    ("GD241", "P1", "聊天仅客户端过滤", "gd", r"(?:chat|聊天|message)\w*[\s\S]{0,250}?(?:filter|过滤|replace|替换)",
     "聊天内容只在客户端过滤 —— 玩家可改客户端，过滤形同虚设；词库放客户端等于公开",
     "过滤与审计必须在服务端；客户端只做输入提示",
     r"(?i)(?:server|服务端|rpc_id|audit|留存|moderat)"),
    ("GD242", "P1", "peerID当玩家身份", "gd", r"(?=[\s\S]*(?:peer_id|get_unique_id|sender_id))(?=[\s\S]*(?:player_name|account|账号|身份))",
     "用 peer_id 当玩家身份 —— 每次连接都会变，重连后就不是同一个人",
     "用账号体系的稳定 ID 做身份，peer_id 只用于本次连接寻址",
     r"(?:account_id|user_id|stable_id|账号ID|持久ID)"),
    ("GD243", "P2", "抓边直接赋坐标", "gd", r"(?:ledge|抓边|climb|攀爬)\w*[\s\S]{0,250}?(?:global_position|position)\s*=",
     "抓边时直接赋坐标 —— 瞬移且跳过物理，容易穿墙或抖动",
     "用 Tween 或改 velocity 走 move_and_slide，不要硬赋坐标",
     r"(?:move_and_slide|tween_property|Tween\.)"),
    ("GD244", "P1", "up_direction设为零", "gd", r"up_direction\s*=\s*Vector3\.ZERO|up_direction\s*=\s*Vector3\(\s*0,\s*0,\s*0\s*\)",
     "把 up_direction 设为 ZERO —— 官方明确不能为零，否则无法区分地板/墙/天花板",
     "给明确的上方向；改重力方向时同步更新它",
     ""),
    ("GD245", "P2", "改重力未同步相机", "gd", r"(?:gravity|重力)\w*[\s\S]{0,250}?(?:rotate|旋转|翻转|flip)",
     "改了重力方向但没同步相机与输入方向 —— 看到的和操作的对不上",
     "重力、相机 up、输入映射三者要同步切换",
     r"(?:camera\w*\.\s*(?:up|rotation|global_rotation)|相机.{0,8}(?:up|旋转|同步)|\binput_map\b)"),
    ("GD246", "P1", "死亡写成布尔", "gd", r"var\s+\w*dead\w*\s*(?::\s*bool\s*)?\s*(?::=|=)\s*(?:true|false)",
     "用布尔表示死亡 —— 死亡是过程（正在死亡/已死亡/可重生），布尔只有两态",
     "用状态枚举或状态机，把「死亡中」与「已死亡」分开",
     r"(?:enum|状态机|State|DEAD|_DYING)"),
    ("GD247", "P0", "死亡期间仍可保存", "gd", r"func\s+\w*save\w*\s*\([^)]*\)",
     "保存时没有排除死亡/过场状态 —— 死亡动画中存档会存出「正在死」的状态",
     "保存前校验状态：死亡、过场、加载中不允许存档",
     r"(?:if\s+state\s*!=|can_save\(\)|state\s*==\s*State\.ALIVE|状态校验)"),
    ("GD248", "P1", "上限存计算结果", "gd", r"(?:max_hp|max_value|上限)\w*\s*(?::=|=)\s*\w+\s*\*\s*\d",
     "把计算后的最终上限存起来 —— 上限变化会连锁造成超上限、比例回血错误、容量永久丢失",
     "只存 base/additive/multipliers，上限每次现算",
     r"(?:base_value|additive|multipliers|现算|get_max)"),
    ("GD249", "P2", "重生未清Tween", "gd", r"(?:respawn|重生|revive)\w*",
     "重生时没清理旧的 Tween/Timer/信号 —— 旧补间还在跑会覆盖新状态",
     "重生时显式 kill 所有 Tween、停 Timer、断开一次性信号",
     r"(?:\bkill\s*\(|kill_all\w*|stop_all|_tween\s*=\s*null|清理|reset_tween)"),
    ("GD250", "P2", "flag散落手写字符串", "gd", r"\.has\s*\(\s*[\"'][a-z_]+[\"']\s*\)",
     "剧情 flag 用散落的字符串字面量 —— 拼错只有运行时才发现，且无法枚举所有 flag",
     "用常量表或枚举集中定义，禁止裸字符串",
     r"(?:const\s+\w*FLAG|FlagDef|enum|flag_enum)"),
    ("GD251", "P1", "结局用ifelif链", "gd", r"if\s+[\s\S]{0,80}?(?:ending|结局)[\s\S]{0,200}?elif\s+[\s\S]{0,80}?(?:ending|结局)",
     "结局判定写成 if/elif 链 —— 分支变多后优先级、重复条件、测试覆盖都会失控",
     "改成判定表（id/priority/conditions/incompatible），优先级显式配置",
     r"(?:判定表|ending_table|priority|conditions)"),
    ("GD252", "P1", "反射无上限", "gd", r"while\s+true|while\s*\(\s*true\s*\)",
     "循环没有迭代上限 —— 两面镜子互照会无限反射，主线程直接卡死",
     "设 MAX_BOUNCES 硬切断（如 8）",
     r"(?:MAX_BOUNCES|max_bounces|bounce_count\s*<\s*\d|上限)"),
    ("GD253", "P1", "用reflect非bounce", "gd", r"\.reflect\s*\(",
     "用了 reflect() —— Godot 里反射方向该用 bounce()，源码中 bounce = -reflect，混用得到相反方向",
     "改用 v.bounce(normal)",
     ""),
    ("GD254", "P2", "机关绑死按键", "gd", r"(?:interact|交互|机关)\w*[\s\S]{0,250}?is_action_pressed\s*\(\s*[\"'][^\"']+[\"']\s*\)",
     "交互绑死具体按键 —— 玩家改键位后失效，且多个机关会抢同一个键",
     "绑 Input Map 动作名，且交互走统一入口避免多机关抢输入",
     r"(?:ACTION_INTERACT|动作名|统一入口|interact_focus)"),
    ("GD255", "P0", "停帧计时器受缩放", "gd", r"Engine\.time_scale\s*=\s*0[\s\S]{0,200}?create_timer\s*\(\s*[\d.]+\s*\)",
     "time_scale=0 后用普通 create_timer —— 计时器同样被冻结，游戏永久卡死",
     "恢复计时器必须 create_timer(t, true)",
     r"(?:create_timer\s*\(\s*[\d.]+\s*,\s*true|ignore_time_scale)"),
    ("GD256", "P1", "改time_scale无恢复", "gd", r"Engine\.time_scale\s*=\s*[\d.]+",
     "改了 time_scale 但全文找不到恢复 —— 异常路径下会永久停在慢动作或卡死",
     "所有修改都要配对恢复，用 try/finally 或在统一出口恢复",
     r"(?:time_scale\s*=\s*1|恢复|restore|finally|reset_scale)"),
    ("GD257", "P2", "暂停时UI不可交互", "gd", r"get_tree\(\)\.paused\s*=\s*true",
     "设 paused=true 但没处理 UI —— 默认 process_mode 下暂停菜单自己也被暂停，点不动",
     "暂停菜单设为 PROCESS_MODE_ALWAYS / WHEN_PAUSED",
     r"(?:PROCESS_MODE|process_mode|ALWAYS|WHEN_PAUSED)"),
    ("GD258", "P0", "客户端判支付成功", "gd", r"(?:purchase|支付|buy|购买)\w*[\s\S]{0,300}?(?:success|成功|grant|发放)",
     "客户端判定支付成功并发货 —— 客户端结果不可信，可被伪造",
     "以服务端订单状态为准；客户端只发起与展示结果",
     r"(?i)(?:server_verify|服务端|order_status|receipt|订单查询)"),
    ("GD259", "P1", "抽卡随机在客户端", "gd", r"(?:gacha|抽卡|扭蛋|roll)\w*[\s\S]{0,250}?(?:randf|randi|randomize)\s*\(",
     "抽卡结果在客户端随机 —— 玩家可改内存必出 SSR",
     "抽取必须在服务端，客户端只展示结果",
     r"(?i)(?:server|服务端|rpc_id|request_draw)"),
    ("GD260", "P1", "日期用本地时区", "gd", r"(?:daily|每日|reset|重置)\w*[\s\S]{0,250}?get_datetime_dict_from_system\s*\(\s*\)",
     "每日重置用本地时间 —— 改时钟就能重复领，且跨时区/夏令时会缺一天或多一天",
     "时间源必须 UTC，关键判定以服务端时间为准",
     r"(?:utc|UTC|server_time|服务端时间|from_unix_time)"),
    ("GD261", "P1", "高速投射物无扫描", "gd", r"(?:velocity|speed)\w*[\s\S]{0,200}?(?:2000|3000|5000)",
     "高速投射物只靠碰撞体 —— 单帧位移超过墙厚会直接穿透",
     "用射线扫描补一次（上一帧到当前位置），或启用 CCD",
     r"(?:raycast|射线|intersect_ray|CCD|continuous_cd|扫描)"),
    ("GD262", "P2", "预测与实弹两套公式", "gd", r"(?:predict|预测|preview)\w*[\s\S]{0,300}?(?:gravity|重力)",
     "预测线自己写了一套简化公式 —— 显示落点和实际落点不一致",
     "预测必须复用与真实弹道相同的重力、时间步和碰撞查询",
     r"(?:simulate|复用|same_step|同一套|_step)"),
    ("GD263", "P2", "配表无校验", "gd", r"(?:load_table|parse_table|配表)\w*[\s\S]{0,300}?(?:JSON\.parse|parse_string)",
     "配表解析后没有校验 —— 缺字段/类型错只在运行时炸，且往往很后面才炸",
     "加载后立刻做 schema 校验，报错要指明哪一行哪个字段",
     r"(?:validate|校验|schema|assert|push_error)"),
    ("GD264", "P2", "输入重绑定未持久化", "gd", r"(?:remap|重绑定|改键)\w*[\s\S]{0,250}?action_erase_events|action_add_event",
     "改了键位但没保存 —— 重启后回到默认，玩家会以为游戏出 bug",
     "重绑定后立刻写存档，并在启动时应用",
     r"(?:save_keymap|持久化|write_keymap|ConfigFile)"),
    ("GD265", "P1", "技能写死硬编码", "gd", r"(?:skill|技能|ability)\w*[\s\S]{0,250}?if\s+\w+\s*==\s*[\"'][^\"']+[\"']",
     "技能逻辑写死在代码里 —— 策划改一个数值就要改代码、重新打包",
     "用 Resource 数据驱动，技能参数可配置",
     r"(?:skill|技能|ability)\w*[\s\S]{0,150}?(?:Resource|数据驱动|@export|配置|\.tres)"),
    ("GD266", "P2", "伤害计算顺序不定", "gd", r"(?:damage|伤害)\w*[\s\S]{0,300}?\*\s*\(\s*1\s*\+\s*",
     "伤害加成用连乘且顺序依赖数组 —— 同样 buff 组合，顺序不同结果不同",
     "固定叠加顺序，或按乘区分类后合并计算",
     r"(?:固定顺序|sorted|乘区|additive|multiplier)"),
    ("GD267", "P2", "命中判定在客户端", "gd", r"(?:hit|命中|判定)\w*[\s\S]{0,250}?if\s+.{0,60}(?:distance|overlap|intersect)",
     "命中判定在客户端做 —— 联网时可被改成必中",
     "有服务端时必须服务端判定，客户端只做预测与表现",
     r"(?i)(?:server|服务端|authority|@rpc)"),
    ("GD268", "P1", "资源加载未判空", "gd", r"(?:load|preload)\w*\s*\(\s*[\"']res://[^\"']+[\"']\s*\)[\s\S]{0,100}?(?:\.|\[)",
     "资源加载后直接用没判空 —— 加载失败是静默的，用到时才崩且看不出是哪个资源",
     "判 null 并给出明确错误（路径 + 原因）",
     r"(?:if\s+\w+\s*==\s*null|is_instance_valid|push_error|判空)"),
    ("GD269", "P2", "高频创建对象", "gd", r"(?:spawn|生成|create)\w*[\s\S]{0,200}?\.new\s*\(\s*\)[\s\S]{0,150}?add_child",
     "高频创建并 add_child —— 子弹/特效这类高频对象必须池化，否则内存抖动",
     "用对象池复用实例",
     r"(?:pool|池化|_pool|reuse|复用)"),
    ("GD270", "P1", "存档存运行时态", "gd", r"(?:func\s+\w*save\w*\s*\([^)]*\)|存档)[\s\S]{0,300}?[Nn]ode\W*[:,)]",
     "把 Node/Object 存进存档 —— 含引擎内部引用，反序列化会丢或崩",
     "只存可序列化数据（ID/字典/基础类型）",
     r"(?:to_dict|ID|字典|serialize|纯数据)"),
    ("GD271", "P2", "过场未禁用输入", "gd", r"(?:cutscene|过场|cinematic)\w*[\s\S]{0,300}?(?:play|start)\s*\(",
     "过场播放时没禁用玩家输入 —— 输入穿透会把机关全触发一遍",
     "过场期间切到专用状态，屏蔽玩家输入",
     r"(?:disable_input|输入锁|set_process_input\s*\(\s*false|屏蔽)"),
    ("GD272", "P2", "相机未处理遮挡", "gd", r"SpringArm\w*(?:\.new\s*\(|\s*\()",
     "用了 SpringArm 但没配碰撞 —— 相机会穿墙",
     "给 SpringArm 设碰撞掩码与碰撞体，或自己做遮挡检测",
     r"(?:collision_mask|碰撞|occlusion|遮挡|margin)"),
    ("GD273", "P2", "UI未处理安全区", "gd", r"(?:safe_area|安全区|cutout|刘海)\w*",
     "提到安全区但没实际适配 —— 刘海屏上 UI 会被挡",
     "用 DisplayServer.get_display_safe_area() 做边距适配",
     r"(?:get_display_safe_area|适配|margin|offset)"),
    ("GD274", "P1", "版本号硬编码", "gd", r"(?i)(?:version|版本)\w*\s*(?::=|=)\s*[\"']\d+\.\d+",
     "版本号硬编码在代码里 —— 改版本要改代码，且容易漏改一处",
     "版本号集中在 project.godot 或单一常量",
     r"(?:ProjectSettings|project.godot|config_version|集中)"),


    # ---- 类型专项补充（GD275-GD320）----
    ("GD275", "P1", "波次用group判空", "gd", r"get_nodes_in_group\s*\(\s*[^)]*\)\s*\.is_empty\s*\(\s*\)",
     "用 get_nodes_in_group().is_empty() 判波次清空 —— 池里休眠怪、退场怪会污染计数",
     "显式计数：spawned == killed + escaped",
     r"(?:spawned_count|killed_count|escaped_count)"),
    ("GD276", "P2", "建塔后未强制更新导航", "gd", r"set_cell\s*\([^)]*\)[\s\S]{0,300}?map_get_path\s*\(",
     "改了地图后立刻 map_get_path() —— NavigationServer 改动要下一物理帧才生效，拿到的是旧数据",
     "改完地图调 NavigationServer2D.map_force_update() 再取路径",
     r"map_force_update"),
    ("GD277", "P2", "name字符串判敌人", "gd", r"(?:body|other|area)\.name\s*==\s*[\"\']",
     "用 body.name == \"Enemy\" 做分发 —— TileMap 配了碰撞也会触发 body_entered，会误伤",
     "给敌人统一接口 take_damage()，塔只持\"可伤害\"引用",
     r"(?:take_damage|is_in_group\s*\(\s*[\"\']enemy)"),
    ("GD278", "P2", "Timer串高频刷怪", "gd", r"wait_time\s*=\s*(?:0\.0[0-9]|0\.1)\s*$",
     "用极短 wait_time 的 Timer 串高频刷怪 —— Timer 每帧最多处理一次超时，行为会依赖帧率",
     "用累加器显式结算：while acc >= interval: spawn()",
     r"(?:_acc|accumulator)\s*\+="),
    ("GD279", "P2", "塔射程用body_entered", "gd", r"(?:body_entered|area_entered)\s*\.\s*connect[\s\S]{0,200}?(?:range|射程|tower|塔)",
     "用 body_entered 做塔的射程检测 —— 20塔×200怪是信号风暴",
     "降频用 PhysicsDirectSpaceState2D.intersect_shape() 集中查询",
     r"(?:intersect_shape|PhysicsShapeQuery)"),
    ("GD280", "P2", "敌人未关物理处理", "gd", r"if\s+not\s+\w*(?:active|visible)\w*\s*:\s*return",
     "屏幕外/休眠对象用 if not active: return —— 空转仍被引擎每帧调用",
     "set_physics_process(false) 真正停掉，不是提前 return",
     r"set_physics_process\s*\(\s*false"),
    ("GD281", "P1", "每帧遍历group取单位", "gd", r"(?:_process|_physics_process)\w*[\s\S]{0,300}?get_nodes_in_group\s*\(\s*",
     "在每帧函数里 get_nodes_in_group() —— 全树扫描，单位多时明显掉帧",
     "UnitManager 持有 Array[Unit]，启停只改数组",
     ""),
    ("GD282", "P1", "camera调用不存在方法", "gd", r"\w*camera\w*\s*\.\s*screen_to_world\w*\s*\(",
     "调用 Camera2D.screen_to_world_point() —— 该方法不存在",
     "用 get_screen_transform().affine_inverse() * screen_point",
     ""),
    ("GD283", "P2", "战争迷雾用Light2D", "gd", r"(?:fog|迷雾|视野)[\s\S]{0,200}?Light2D",
     "用 Light2D 做战争迷雾 —— 那是 2D 光照阴影，不是可见性系统",
     "用独立 TileMapLayer 的 visible/explored 格子状态 + 脏区批量提交",
     r"(?:TileMapLayer|set_cell|脏区|dirty)"),
    ("GD284", "P2", "迷雾每帧set_cell", "gd", r"(?:_process|_physics_process)\w*[\s\S]{0,300}?set_cell\s*\(\s*",
     "每帧对迷雾层 set_cell —— 反复触发导航/渲染重算",
     "收集脏区，逻辑帧末尾一次性提交",
     r"(?:_dirty|脏区|flush|_flush_dirty)"),
    ("GD285", "P2", "单位全指向同目标", "gd", r"(?:for\s+\w+\s+in\s+\w*(?:units|squad|selected)\w*)[\s\S]{0,300}?target_position\s*=\s*\w+\.global_position",
     "编队内所有单位指向同一目标点 —— 会挤成一团，RVO 只是缓解且引入抖动",
     "SquadFormation 算菱形/网格偏移位，各 agent 各自寻路",
     r"(?:formation|偏移|offset)"),
    ("GD286", "P1", "Array.shuffle洗牌", "gd", r"\.\s*shuffle\s*\(\s*\)",
     "用 Array.shuffle() 洗牌 —— 走全局 RNG，无法复现也无法服务器校验",
     "用 RandomNumberGenerator 实例写 Fisher-Yates",
     ""),
    ("GD287", "P1", "混用全局随机与rng", "gd", r"(?<![.\w])(?:randi|randf|randi_range|randf_range)\s*\(\s*\)",
     "用全局随机函数 —— 与 RandomNumberGenerator 是不同状态，混用导致同种子不同结果",
     "整局只用一个 rng 实例，所有随机走 rng.randf()/rng.randi_range()",
     ""),
    ("GD288", "P2", "卡牌存档用JSON", "gd", r"(?:card|卡牌|deck|牌)[\s\S]{0,250}?(?:JSON\.stringify|JSON\.parse_string|to_json)",
     "卡牌存档用 JSON —— 无法表达 Resource 引用与 Effect 子类类型",
     "用 ResourceSaver 存 .tres/.res，或自定义二进制协议",
     r"(?:ResourceSaver|\.res|\.tres)"),
    ("GD289", "P2", "卡牌是PackedScene", "gd", r"(?:card|卡牌)\w*\s*:\s*PackedScene",
     "卡牌数据用 PackedScene —— 同一张卡在多处各一份实例，成倍耗内存",
     "数据用 Resource，只有 CardView 是场景",
     ""),
    ("GD290", "P1", "效果直接调伤害", "gd", r"\w+\.take_damage\s*\(\s*[\d\w]+\s*\)",
     "效果里直接 target.take_damage(5) —— 跳过响应链，\"受伤时\"类效果无法响应",
     "生成 DamageEvent 入栈，由栈结算并允许响应/修改/取消",
     r"(?:_stack|Event|入栈|emit)"),
    ("GD291", "P2", "洗牌同帧回抽", "gd", r"if\s+\w*deck\w*\.is_empty\s*\(\s*\)\s*:[\s\S]{0,200}?(?:shuffle|_reshuffle)",
     "牌库空了洗弃牌堆后同帧继续抽 —— 会抽到刚洗进去的同一张",
     "洗后标记 is_reshuffling，本轮该次抽牌按洗前判定处理",
     r"(?:is_reshuffling|洗前)"),
    ("GD292", "P2", "生成直接set_cell", "gd", r"(?:for\s+\w+\s+in\s+\w*(?:room|cell|tile)\w*)[\s\S]{0,300}?set_cell\s*\(\s*",
     "生成循环里逐格 set_cell —— 失败难回滚且逐格触发重算",
     "先建纯数据 Dungeon 中间表示，校验连通性后一次性提交",
     r"(?:连通性|validate_|中间表示|_commit|批量提交)"),
    ("GD293", "P2", "生成时导航开着", "gd", r"(?:generate|生成)\w*[\s\S]{0,300}?set_cell\s*\(\s*",
     "生成时开着 navigation_enabled —— 每个 set_cell 触发导航更新",
     "生成前关掉，最后一次提交后再开",
     r"navigation_enabled\s*=\s*false"),
    ("GD294", "P1", "meta只在退出时存", "gd", r"(?:_exit_tree|NOTIFICATION_WM_CLOSE_REQUEST)[\s\S]{0,300}?(?:save|ResourceSaver)",
     "只在退出时存 meta 进度 —— 崩溃/强杀会丢整局进度",
     "关键节点变化即存（过关结算后、解锁时）",
     r"(?:过关|解锁|结算后|关键节点)"),
    ("GD295", "P1", "覆盖写存档", "gd", r"ResourceSaver\.save\s*\(\s*[^)]+\)\s*$",
     "直接覆盖写存档文件 —— 崩溃会留下半截文件，存档彻底损坏",
     "先写 .tmp 再原子重命名",
     r"(?:\.tmp|rename|原子)"),
    ("GD296", "P1", "FLAG_COMPRESS当加密", "gd", r"(?:secret|key|password|付费|purchase)\w*[\s\S]{0,250}?FLAG_COMPRESS",
     "把 FLAG_COMPRESS 当加密 —— 它是 Zstandard 压缩，不是加密",
     "敏感存档要签名或服务端权威",
     r"(?:hmac|sign|签名|服务端|server)"),
    ("GD297", "P2", "道具池每次重算总权重", "gd", r"for\s+\w+\s+in\s+\w*(?:pool|items)\w*\s*:[\s\S]{0,200}?(?:total|sum)\s*\+=",
     "每次抽取遍历全池算总权重 —— O(n)，池大且高频时明显",
     "用累积权重 + bsearch 降到 O(log n)，或别名法 O(1)",
     r"(?:_cum|bsearch|累积)"),
    ("GD298", "P1", "产出delta直乘", "gd", r"(?:output|产出|produce|rate)\w*\s*\*\s*delta",
     "产出率直接乘 delta —— 帧率不同结果不同，且无法复用于离线结算",
     "固定步长 + 累加器：while acc >= STEP: tick(STEP)",
     r"(?:FIXED_STEP|_acc|accumulator)"),
    ("GD299", "P1", "离线收益简单相乘", "gd", r"(?:offline|离线)\w*[\s\S]{0,250}?(?:rate|产出)\w*\s*\*\s*\w*(?:seconds|elapsed|diff)",
     "离线收益 = 每秒产出 × 离线秒数 —— 忽略依赖链、上限、buff",
     "把离线时间切片，循环推进完整 Economy.tick() 并每步截断",
     r"(?:while\s+\w+\s*<\s*\w+|tick\s*\(\s*FIXED|循环推进)"),
    ("GD300", "P1", "离线用本地时间", "gd", r"(?:offline|离线|daily|每日)\w*[\s\S]{0,250}?get_datetime_dict_from_system\s*\(\s*\)",
     "离线/每日结算用本地系统时间 —— 改时钟就能重复领，跨时区会缺或多一天",
     "时间源用 UTC，关键判定以服务端时间为准",
     r"(?:utc|UTC|server_time|服务端时间)"),
    ("GD301", "P2", "建筑放置用Area2D", "gd", r"(?:can_place|放置|placement)\w*[\s\S]{0,250}?(?:overlaps_area|overlaps_body|get_overlapping)",
     "网格建筑放置用 Area2D 重叠检测 —— 网格放置查二维数组是 O(1)",
     "查 BuildingGrid 的二维数组；Area2D 只适合自由放置",
     r"(?:_grid|grid\s*\[|二维数组)"),
        ("GD303", "P2", "资源键用String", "gd", r"Dictionary\s*\[\s*String\s*,",
     "资源字典键用 String —— 每次哈希新字符串",
     "用 StringName 作键，且 Dictionary[Key,Value] 类型化能早报错",
     r"StringName"),
    ("GD304", "P1", "just_pressed在physics里", "gd", r"func\s+_physics_process\s*\([^)]*\)[\s\S]{0,400}?is_action_just_pressed\s*\(\s*",
     "在 _physics_process 里 is_action_just_pressed —— 渲染帧与物理帧错位时按键会被吞",
     "在 _input/_process 捕获置缓冲标志，_physics_process 消费",
     r"(?:\w*buffer\w*|jump_buffer)"),
    ("GD305", "P2", "松跳速度归零", "gd", r"velocity\.y\s*=\s*0\s*$",
     "松开跳跃键把 velocity.y 归零 —— 每次短按高度完全一致，手感发飘",
     "截断到 CUT_SPEED（如 -150），不是归零",
     r"(?:CUT_SPEED|maxf\s*\(\s*velocity\.y)"),
    ("GD306", "P1", "平台手动改position", "gd", r"(?:platform|平台)\w*\.position\s*\+=",
     "手动 position += v*delta 移动平台 —— 不产生接触速度叠加，角色不跟着走",
     "用物理移动的平台（AnimatableBody/CharacterBody），让引擎处理接触",
     r"(?:move_and_slide|AnimatableBody)"),
    ("GD307", "P2", "冲刺改碰撞形状", "gd", r"(?:dash|冲刺|slide|滑铲)\w*[\s\S]{0,250}?(?:shape\s*\.\s*radius|shape\s*\.\s*height|\.disabled\s*=)",
     "冲刺/滑铲时改碰撞形状尺寸或 disabled —— 会重建接触，容易卡墙",
     "用固定形状 + 状态分层 collision mask",
     r"(?:collision_mask|collision_layer)"),
    ("GD308", "P1", "每帧重设instance_count", "gd", r"(?:_process|_physics_process)\w*[\s\S]{0,300}?(?<!visible_)instance_count\s*=",
     "每帧设置 MultiMesh.instance_count —— 会清空并重分配整个 buffer，抵消合批收益",
     "加载时一次定到上限，运行时只改 visible_instance_count",
     ""),
    ("GD309", "P1", "子弹用Area2D", "gd", r"(?:bullet|子弹|projectile)\w*[\s\S]{0,250}?Area2D",
     "每颗子弹一个 Area2D —— 千颗子弹千个每帧回调，本类游戏最典型的死法",
     "数据层定长数组批量积分 + MultiMesh 渲染 + 只查玩家判定点",
     r"(?:MultiMesh|PackedFloat32Array|intersect_point)"),
    ("GD310", "P2", "弹幕逻辑用delta", "gd", r"(?:bullet|子弹)\w*[\s\S]{0,250}?(?:position|pos)\s*\+=\s*\w*(?:vel|velocity)\w*\s*\*\s*delta",
     "弹幕位置积分直接用 delta —— 帧率不同弹幕密度不同，且无法确定性回放",
     "固定逻辑步长（如 1/60）累加器推进",
     r"(?:LOGIC_STEP|FIXED|_acc\s*\+=\s*delta)"),
    ("GD311", "P2", "判定点用精灵中心", "gd", r"(?:hit|命中|graze|擦弹)\w*[\s\S]{0,200}?(?:global_position|position)\s*\)",
     "命中判定用精灵中心坐标 —— 判定点应明显更小并单独渲染提示",
     "判定点 2–4px 独立定义；擦弹是另一个独立半径",
     r"(?:hit_point|HIT_RADIUS|GRAZE_RADIUS)"),
    ("GD312", "P2", "intersect_point用默认上限", "gd", r"intersect_point\s*\(\s*[^,)]+\s*\)",
     "intersect_point 不传 max_results —— 默认 32，密集弹幕会被截断",
     "显式传足够大的 max_results，或先做距离粗筛",
     r"intersect_point\s*\(\s*[^,)]+\s*,\s*\d"),
    ("GD313", "P2", "ResourceSaver不判返回值", "gd", r"ResourceSaver\.save\s*\(",
     "调用 ResourceSaver.save() 不判返回值 —— 磁盘满/路径错会静默失败",
     "判返回值 != OK 并给出明确错误",
     r"(?:==\s*OK|!\s*=\s*OK|if\s+\w+\s*(?:!=|==))"),
    ("GD314", "P1", "await后未判活", "gd", r"await\s+[\s\S]{0,150}?(?:\.\s*\w+|\w+\s*\()",
     "await 之后直接使用对象 —— 等待期间节点可能已被销毁",
     "await 后用 is_instance_valid() 判活再继续",
     r"is_instance_valid"),
    ("GD315", "P1", "queue_free后仍使用", "gd", r"queue_free\s*\(\s*\)[\s\S]{0,150}?(?:self\.\w+|\w+\.\w+\s*=)",
     "queue_free() 之后仍访问节点 —— 实际释放发生在帧末，状态已不可靠",
     "释放后立即返回，不要继续使用",
     ""),
    ("GD316", "P0", "密码学用随机而非rng", "gd", r"(?:token|nonce|salt|secret)\w*\s*(?::=|=)\s*(?:randi|randf|rand_from_seed)",
     "用普通随机函数生成 token/nonce/salt —— 可预测，不是密码学安全随机",
     "敏感随机用 Crypto.generate_random_bytes()",
     r"(?:Crypto\.|generate_random_bytes)"),
    ("GD317", "P1", "断线直接销毁角色", "gd", r"(?i)(?:peer_disconnected|server_disconnected|connection_lost|断线|掉线)[\s\S]{0,400}?queue_free",
     "玩家断线就 queue_free 角色 —— 对端看到物体凭空消失、已发射抛射物变孤儿、计分不一致",
     "角色保留 + 受控 AI 托管，超时（reconnect_grace_ms）后才按模式处理",
     r"(?i)(?:retain|保留|托管|ai_control|grace|reconnect_grace|暂不销毁)"),
    ("GD318", "P1", "权威位置硬赋值", "gd", r"(?i)(?:authority|server_pos|snapshot_pos|权威)[\s\S]{0,300}?(?:global_)?position\s*=\s*\w*(?:pos|position|snapshot|state)",
     "每帧把位置直接赋成权威值 —— 表现为「走路像橡皮筋」",
     "超阈值才纠正，用临界阻尼/指数平滑朝目标移动，偏差极大才 snap",
     r"(?i)(?:lerp|smooth|阻尼|move_toward|exp\s*\(\s*-|correction)"),
    ("GD319", "P2", "观战流无延迟缓冲", "gd", r"(?i)(?:spectat\w*|观战)[\s\S]{0,400}?(?:_process|render|apply|显示|draw)[\s\S]{0,200}?(?:latest|最新|last_snapshot|直接)",
     "观战端拿到快照就实时渲染 —— 会窥屏（比选手早看到转角敌人）且 1% 丢包就卡顿",
     "维护 200-600ms 历史缓冲，按固定显示 tick 插值",
     r"(?i)(?:buffer|缓冲|history|历史|delay|延迟|interpolat)"),
    ("GD320", "P1", "模拟用渲染delta驱动", "gd", r"(?i)func\s+_process\s*\([^)]*\)[\s\S]{0,400}?(?:simulate|step|advance|tick_update)\s*\(\s*delta\s*\)",
     "用渲染帧 delta 驱动模拟 —— 144Hz 与 60Hz 结果不同、拖窗口改变回放长度",
     "固定步长累加器：const STEP := 1.0/60.0，while acc >= STEP: simulate(STEP)",
     r"(?i)(?:accumulator|_acc|STEP|FIXED_STEP|固定步长|1\.0\s*/\s*60)"),
    ("GD321", "P2", "HTTP请求无重试", "gd", r"(?i)(?:HTTPRequest|http_client|_http)\w*[\s\S]{0,500}?\.request\s*\(",
     "HTTPRequest 无内置重试/退避且单节点不可并发 —— 弱网下运营配置、登录、支付回调全部静默失败",
     "自己写重试层与请求队列：指数退避 + 超时 + 幂等键",
     r"(?i)(?:retry|重试|backoff|退避|max_attempt|重试次数)"),
    ("GD322", "P1", "JSON解析未判失败", "gd", r"JSON\.parse_string\s*\(",
     "JSON.parse_string 失败返回 null 且容忍尾逗号 —— 无法区分「内容是 null」与「解析失败」，坏配置会让整个配置表空掉",
     "用 JSON.new().parse() 走 error != OK 分支；解析失败保留旧配置不覆盖缓存",
     r"(?i)(?:JSON\.new|\.error|!\s*=\s*OK|is\s+null|==\s*null|get\(\s*[\"']|\.get\()"),
    ("GD323", "P1", "避障未接velocity_computed", "gd", r"\.set_velocity\s*\(",
     "调用 set_velocity() 却没接 velocity_computed —— 拿不到安全速度，等于没避障；且 avoidance_enabled 默认 false，不打开就是完全没启用",
     "agent.avoidance_enabled = true；连接 velocity_computed 并用 safe_velocity 自己移动父节点",
     r"(?:velocity_computed|avoidance_enabled)"),
    ("GD324", "P2", "群集全量两两比较", "gd", r"(?i)(?:boid|flock|swarm|群集|群体)\w*[\s\S]{0,400}?for\s+\w+\s+in\s+\w+(?:s|list|array|_units)\s*:[\s\S]{0,300}?for\s+\w+\s+in\s+\w+(?:s|list|array|_units)\s*:",
     "群集邻居查询嵌套两层循环全量比较 —— O(n²)，单位一多就掉帧",
     "按感知半径做网格分桶（cell_size = 感知半径），只查自身 cell 与邻域；或用 PhysicsServer shape query",
     r"(?:cell|grid|网格|分桶|neighbor_dist|半径|shape_query)"),
    ("GD325", "P1", "加速检测用系统时间", "gd", r"(?i)(?:anti_?cheat|speed_?hack|加速|变速|检测加速)\w*[\s\S]{0,400}?(?:Time\.get_unix_time_from_system|OS\.get_(?:datetime|date|time)|get_datetime_dict_from_system)",
     "加速检测用系统时间 —— 玩家改表即可绕过，检测形同虚设",
     "必须用单调时钟 Time.get_ticks_msec()（不受改表影响），与服务端同步的逻辑时间比对",
     r"(?:get_ticks_msec|get_ticks_usec|单调)"),
    ("GD326", "P0", "密钥令牌硬编码", "gd", r"(?i)(?:hmac_key|api_key|secret|app_secret|sign_key)\s*(?::=|const\s+[A-Z_]+\s*=)\s*[\"'][A-Za-z0-9_+/=]{12,}[\"']",
     "签名密钥/API 密钥写死在客户端代码里 —— 客户端必然泄露，签名层不再提供任何真实性",
     "HMAC 密钥由服务端按会话颁发；客户端只保存运行时下发的临时密钥",
     r"(?:服务端下发|server_issued|fetch_key|request_key|session_key)"),
    ("GD327", "P1", "加密用字面密码", "gd", r"save_encrypted_pass\s*\(\s*[^\n,]*,\s*[\"'][^\"']+[\"']\s*\)",
     "save_encrypted_pass 传字面密码 —— 引擎只用 MD5(password) 派生密钥（无盐无迭代），玩家拿到包就能离线批量猜",
     "密码由服务端按设备会话派生且可吊销；或自己实现带随机 salt 的 PBKDF2/Argon2",
     r"(?:pbkdf2|argon2|salt|派生|server_derived|kek)"),
    ("GD328", "P2", "客户端自封禁", "gd", r"(?i)(?:cheat|hack|外挂|作弊|tamper)\w*[\s\S]{0,300}?(?:ban|封禁|封号|kick|踢出)\w*\s*\(",
     "客户端检测到作弊后自己封禁 —— 攻击者直接 NOP 掉检测函数，封禁形同虚设",
     "客户端只上报信号，服务端累积风险分后按阈值限制或运营人工封禁",
     r"(?:report|上报|server_verdict|risk_score|风险分|服务端判定)"),
    ("GD329", "P1", "合服无备份", "gd", r"(?i)(?:merge_shard|合服|合区|cross_shard|跨服迁移)\w*[\s\S]{0,400}?(?:INSERT|UPDATE|delete|write|overwrite)",
     "合服/跨服迁移直接写数据 —— 一旦出错玩家资产不可逆丢失",
     "四步：快照 → dry-run → 幂等迁移 → 保留回滚；重名、排行榜、重复资产都要显式处理",
     r"(?:snapshot|快照|backup|备份|dry_?run|rollback|回滚)"),
    ("GD330", "P1", "补偿发放无幂等键", "gd", r"(?i)(?:compensate|补偿|grant_reward|发放奖励|send_mail|邮件附件)\w*[\s\S]{0,400}?(?:add_item|add_gold|grant|发放)\s*\(",
     "补偿/邮件附件发放没有幂等键 —— 断网重试、并发点击会重复发道具",
     "按 (player_id, compensate_id) 建幂等；先查发放日志，已发过直接返回首次结果",
     r"(?:idempot|幂等|dedup|compensate_id|grant_log|已发放|_log)"),
    # ---- 合规·装备养成（GD331-GD335）----
    ("GD331", "P0", "身份敏感信息明文持久化", "gd",
     r"(?i)(?:id_card|idcard|identity_no|id_number|身份证号?|realname_id)\w*[\s\S]{0,200}?(?:\.save|save\w*\s*\(|set_value|store|存档|持久化|config\.set|db\.insert|\.write)",
     "身份证号/实名证件号被明文写进存档或配置 —— 属敏感个人信息，泄露即合规事故，且违反最小必要原则",
     "服务端完成实名核验后只保留核验结果与不可反解的凭证引用；客户端不留存证件号原件，必须留存时先哈希/脱敏并限期删除",
     r"(?:hash|sha256|脱敏|mask|tokenize|不留存|仅校验|凭证|credential)"),
    ("GD332", "P0", "防沉迷/未成年判定用本地系统时间", "gd",
     r"(?i)(?:is_minor|未成年|minor|防沉迷|addiction)\w*[\s\S]{0,300}?(?:get_unix_time_from_system|get_datetime_from_system|get_date_dict_from_system|OS\.get_date|本地时间|系统时间)",
     "防沉迷时段用客户端系统时间判定 —— 改表即可绕过，且跨时区/夏令时会错放行或错拦截",
     "时段与时长一律由服务端按 UTC + 法定节假日日历判定；客户端只展示服务端返回的剩余时间",
     r"(?:server|服务端|utc|权威|get_unix_time_from_server|server_now)"),
    ("GD333", "P1", "注销账号直接删数据", "gd",
     r"(?i)(?:注销|delete_account|销号|删除账号|remove_account)\w*[\s\S]{0,300}?(?:DELETE\s+FROM|db\.delete|\.erase\s*\(|remove_all|drop_table)",
     "注销账号直接执行删除 —— 订单/退款/税务/安全事件等法定保留数据会被一并抹掉，且无法证明已履行删除义务",
     "做成状态机 requested→identity_verified→anonymized→pending_retention_review→purged；可识别字段立即匿名化，法定保留数据去标识化+访问隔离+到期删除标记，并同步通知第三方",
     r"(?:anonym|匿名化|purge|retention|保留期|request_id|核验|状态机|去标识)"),
    ("GD334", "P1", "装备词条存最终数值", "gd",
     r"(?i)(?:affix|词条|词缀)\w*[\s\S]{0,200}?(?:final_value|finalvalue|最终值|final_stat|显示值|cached_value)",
     "装备实例只存最终属性值 —— 策划改了词条上限后历史装备无法重算，也无法区分「故意保留的旧装备」与「Bug 装备」",
     "实例只存 affix_id + roll（0..1 原始位置）+ generation_version；最终值一律由唯一计算器现算",
     r"(?:\.roll\b|roll\s*[:=]|snapshot|快照|generation_version)"),
    ("GD335", "P1", "分解返还按模板原价", "gd",
     r"(?i)(?:分解|decompose|dismantle|熔炼|拆解|回收)\w*[\s\S]{0,300}?(?:base_cost|template_cost|base_price|原价|模板价格|def_cost)",
     "分解按模板原价返还 —— 返还 ≥ 获取成本时玩家可刷分解套利，是经济通胀的头号来源",
     "按装备当前养成状态（强化/品阶/词条）折算返还；绑定与已装备物品明确不可分解；与强化/洗练共用同一事务与审计日志",
     r"(?:current|当前|enhance|强化|折算|evaluate|按状态|state)"),
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
        # 先逐行匹配（行号精确）。
        hit_line = None
        for i, l in enumerate(lines):
            if re.search(pat, l):
                hit_line = i
                break
        if hit_line is None:
            # 跨行规则（如「await 之后用了 X」）逐行永远匹配不到，
            # 但上面的预检已确认全文能匹配 —— 直接用全文定位行号。
            # 不回退的话这类规则会「预检通过却从不 add」，
            # 表现与「规则没问题」完全一样，是最难发现的一类失效。
            m = re.search(pat, text, re.M)
            if m:
                hit_line = text[:m.start()].count("\n")
        if hit_line is not None:
            add(hit_line, rid, level, rule, msg, fix)

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

SELF_NET_BAD = '''extends Node3D

@rpc("any_peer", "call_remote")
func submit_input(data: Dictionary) -> void:
    apply_input(data)

@rpc("authority")
func sync_pos(p: Vector3) -> void:
    global_position = p

'''

SELF_AWT_BAD = '''extends Node3D

func late() -> void:
    await get_tree().process_frame
    print(multiplayer.get_remote_sender_id())
'''

SELF_AWT_CLEAN = '''extends Node3D

func on_rpc() -> void:
    var sender := multiplayer.get_remote_sender_id()
    await get_tree().process_frame
    print(sender)
'''

SELF_NET_CLEAN = '''extends Node3D

@rpc("any_peer", "call_remote", "reliable")
func submit_input(data: Dictionary) -> void:
    var sender := multiplayer.get_remote_sender_id()
    if sender == 0:
        return
    apply_input(sender, data)

@rpc("authority", "call_remote", "unreliable_ordered")
func sync_pos(p: Vector3) -> void:
    global_position = p
'''

SELF_PLG_BAD = '''extends EditorPlugin

func _enter_tree() -> void:
    add_control_to_bottom_panel($Panel, "Tool")
'''

SELF_PLG_CLEAN = '''@tool
extends EditorPlugin

var _panel: Control

func _enter_tree() -> void:
    _panel = preload("res://panel.tscn").instantiate()
    add_control_to_bottom_panel(_panel, "Tool")

func _exit_tree() -> void:
    remove_control_from_bottom_panel(_panel)
    _panel.queue_free()
    _panel = null
'''

# ---- 程序化生成 ----
SELF_PCG_BAD = '''extends Node

func generate_map() -> void:
    for x in 100:
        for y in 100:
            if randi() % 2 == 0:
                var t := Node2D.new()
                add_child(t)

func _make_cave() -> void:
    randomize()
'''

SELF_PCG_CLEAN = '''extends Node

var rng := RandomNumberGenerator.new()

func generate_map(seed_value: int) -> void:
    rng.seed = seed_value
    var layout := []
    for x in 100:
        for y in 100:
            if rng.randi_range(0, 1) == 0:
                layout.append(Vector2i(x, y))
    if _is_connected(layout):
        _instantiate_all(layout)

func _is_connected(cells: Array) -> bool:
    return true

func _instantiate_all(cells: Array) -> void:
    pass
'''

# ---- AI 感知 ----
SELF_PERC_BAD = '''extends Node3D

func can_see(target: Node3D) -> bool:
    var result := get_world_3d().direct_space_state.intersect_ray(
            global_position, target.global_position)
    return not result.is_empty()
'''

SELF_PERC_CLEAN = '''extends Node3D

var last_known_position := Vector3.ZERO

func can_see(target: Node3D) -> bool:
    var q := PhysicsRayQueryParameters3D.create(
            global_position, target.global_position, 2, [self])
    var result := get_world_3d().direct_space_state.intersect_ray(q)
    if result.is_empty():
        return false
    if result["collider"] != target:
        return false
    last_known_position = target.global_position
    return true
'''

# ---- 骨骼与 IK ----
SELF_BONE_BAD = '''extends Node3D

@onready var pole: PoleModifier3D = $Skeleton3D/PoleModifier3D
@onready var spline: SplineIK3D = $Skeleton3D/SplineIK3D

func _ready() -> void:
    pole.influence = 1.0
'''

SELF_BONE_CLEAN = '''extends Node3D

@onready var ik: TwoBoneIK3D = $Skeleton3D/ArmIK

func _ready() -> void:
    ik.pole_node = NodePath("../PoleTarget")
    ik.pole_direction = Vector3(0, 0, 1)
'''

# ---- 配表 ----
SELF_DT_BAD = '''extends Node

@export var skills: Array[Resource]

func load_csv() -> void:
    var f := FileAccess.open("res://data.csv", FileAccess.READ)
    while not f.eof_reached():
        var row := f.get_csv_line()
        _table[row[0]] = row
'''

SELF_DT_CLEAN = '''extends Node

func load_csv() -> void:
    var seen := {}
    for row in _rows:
        var id := String(row[0])
        if seen.has(id):
            push_error("duplicate id %s" % id)
            continue
        seen[id] = true
        if not _validate(row):
            push_error("invalid row %s" % id)
            continue
        _table[id] = _make(row).duplicate_deep(Resource.DEEP_DUPLICATE_INTERNAL)
'''

# ---- VFX ----
SELF_VFX_BAD = '''extends Camera2D

func hit() -> void:
    offset = Vector2(randf_range(-10, 10), randf_range(-10, 10))
    Engine.time_scale = 0.0
    await get_tree().create_timer(0.08).timeout
    Engine.time_scale = 1.0
'''

SELF_VFX_CLEAN = '''extends Camera2D

var trauma := 0.0

func hit() -> void:
    trauma = minf(trauma + 0.3, 1.0)
    Engine.time_scale = 0.0
    await get_tree().create_timer(0.08, false, false, true).timeout
    Engine.time_scale = 1.0

func _process(delta: float) -> void:
    trauma = maxf(trauma - delta, 0.0)
'''

# ---- 经济 ----
SELF_ECO_BAD = '''extends Node

var gold: float = 100.0
var price := 9.9

func roll_drop(table: Array) -> int:
    return table.pick_random()
'''

SELF_ECO_CLEAN = '''extends Node

var gold: int = 100
var pity_count: int = 0

func roll_drop(table: Array) -> int:
    var idx := _weighted_index(table)
    if idx < 0:
        pity_count += 1
    else:
        pity_count = 0
    return int(idx)
'''

# ---- 输入重绑定 ----
SELF_INP_BAD = '''extends Control

func load_keys() -> void:
    var ev := InputEventKey.new()
    ev.scancode = KEY_A
    ev.keycode = KEY_A
    ev.physical_keycode = KEY_A
    InputMap.action_add_event(&"jump", ev)
    var list := InputMap.get_action_list(&"jump")

func hit_feedback() -> void:
    Input.start_joy_vibration(0, 0.5, 0.8, 0.2)
'''

SELF_INP_CLEAN = '''extends Control

func load_keys() -> void:
    var ev := InputEventKey.new()
    ev.physical_keycode = KEY_A
    InputMap.action_add_event(&"jump", ev)
    for e in InputMap.action_get_events(&"jump"):
        print(e)

func hit_feedback() -> void:
    Input.start_joy_vibration(0, 0.5, 0.8, 0.2)

func _exit_tree() -> void:
    Input.stop_joy_vibration(0)
'''

# ---- 回放 ----
SELF_RPL_BAD = '''extends Node

func record_frame() -> void:
    _frames.append({
        "t": Time.get_unix_time_from_system(),
        "x": randi(),
    })
'''

SELF_RPL_CLEAN = '''extends Node

var rng := RandomNumberGenerator.new()
var tick := 0

func record_frame() -> void:
    _frames.append({
        "tick": tick,
        "x": rng.randi(),
    })
    tick += 1
'''

# ---- Mod / 存档迁移 ----
SELF_MOD_BAD = '''extends Node

func install_mod(zip_path: String) -> void:
    var reader := ZIPReader.open(zip_path)
    for name in reader.get_files():
        var out := "user://mods/" + name
        FileAccess.open(out, FileAccess.WRITE)
'''

SELF_MOD_CLEAN = '''extends Node

const MOD_ROOT := "user://mods/"

func install_mod(zip_path: String) -> void:
    var reader := ZIPReader.open(zip_path)
    for name in reader.get_files():
        var target := (MOD_ROOT + name).simplify_path()
        if not target.begins_with(MOD_ROOT):
            push_error("rejected path escape: %s" % name)
            continue
        FileAccess.open(target, FileAccess.WRITE)
    _loaded_packs.append(zip_path)
'''

SELF_MIG_BAD = '''extends Node

func migrate_save(data: Dictionary) -> Dictionary:
    if data.get("v") == 1:
        data["gold"] = data["money"]
    return data
'''

SELF_MIG_CLEAN = '''extends Node

const SAVE_VERSION := 2

func migrate_save(path: String, data: Dictionary) -> Dictionary:
    DirAccess.copy_absolute(path, path + ".bak")
    if data.get("VERSION", 0) < SAVE_VERSION:
        data["gold"] = data.get("money", 0)
        data["VERSION"] = SAVE_VERSION
    return data
'''

# ---- 云存档 ----
SELF_CLD_BAD = '''extends Node

func sync_cloud(remote: Dictionary, local: Dictionary) -> Dictionary:
    if remote.get("mtime") > local.get("mtime"):
        return remote
    return local
'''

SELF_CLD_CLEAN = '''extends Node

func sync_cloud(remote: Dictionary, local: Dictionary) -> Dictionary:
    if remote.get("version", 0) > local.get("version", 0):
        return remote
    if remote.get("version", 0) == local.get("version", 0):
        return local
    return _ask_player_conflict(remote, local)
'''

SELF_CLD_TS_BAD = '''extends Node

func pick(path_a: String, path_b: String) -> String:
    var ta := FileAccess.get_modified_time(path_a)
    var tb := FileAccess.get_modified_time(path_b)
    return path_a if ta > tb else path_b
'''

# ---- 调试工具 ----
SELF_DBG_BAD = '''extends Control

var god_mode := false

func _process(_d: float) -> void:
    $Fps.text = str(Performance.get_monitor(Performance.TIME_FPS))
'''

SELF_DBG_CLEAN = '''extends Control

var god_mode := false

func _process(_d: float) -> void:
    if not OS.is_debug_build():
        hide()
        return
    $Fps.text = str(Performance.get_monitor(Performance.TIME_FPS))
    $Cheat.visible = god_mode
'''

# ---- 画质管线 ----
SELF_GFX_BAD = '''extends Node

func _ready() -> void:
    get_viewport().scaling_3d_mode = Viewport.SCALING_3D_MODE_FSR2
    get_viewport().scaling_3d_scale = 0.5
    get_viewport().msaa_3d = Viewport.MSAA_4X
'''

SELF_GFX_CLEAN = '''extends Node

func _ready() -> void:
    $UIViewport.set_update_mode(SubViewport.UPDATE_ALWAYS)
    get_viewport().scaling_3d_mode = Viewport.SCALING_3D_MODE_FSR2
    get_viewport().scaling_3d_scale = 0.5
'''

SELF_TAA_BAD = '''extends Node

func _ready() -> void:
    get_viewport().scaling_3d_mode = Viewport.SCALING_3D_MODE_FSR2
'''

# ---- 载具 / 物理 ----
SELF_VEH_BAD = '''extends VehicleBody3D

@export var engine_power := 200.0

func _physics_process(_d: float) -> void:
    engine_force = Input.get_axis("brake", "accelerate") * engine_power
'''

SELF_VEH_CLEAN = '''extends VehicleBody3D

@export var engine_power := 200.0

func _ready() -> void:
    center_of_mass_mode = CENTER_OF_MASS_MODE_CUSTOM
    center_of_mass = Vector3(0, -0.5, 0)
'''

# ---- 角色自定义 ----
SELF_CHR_BAD = '''extends Node3D

func dye(part: MeshInstance3D, c: Color) -> void:
    part.get_surface_override_material(0).albedo_color = c

func set_face(v: float) -> void:
    $Head.set_blend_shape_value(0, v)
'''


# ---- UI 进阶 ----

# ---- 商业化 / 变现 ----
SELF_PAY_BAD = '''extends Node

func buy_gems(product_id: String) -> void:
    var ok := IAP.purchase(product_id)
    if ok:
        Gems.add(100)
        Save.save()

func roll_gacha() -> void:
    var r := randi() % 100
    if r < 3:
        give_five_star()
    pity_count += 1

func daily_reset() -> void:
    var d := Time.get_datetime_dict_from_system()
    if d.hour >= 5:
        refresh_shop()
'''

SELF_PAY_CLEAN = '''extends Node

func buy_gems(product_id: String) -> void:
    IAP.purchase(product_id)
    # 发货由服务器校验收据后推送，客户端不自己判定成功

func request_roll() -> void:
    rpc_id(1, "server_roll")

@rpc("any_peer", "call_local", "reliable")
func server_roll() -> void:
    var r := randi() % 100
    var result := pick(r)
    pity_count += 1
    Save.write_pity(pity_count)
    rpc("on_rolled", result)

func daily_reset() -> void:
    var d := Time.get_datetime_dict_from_system(true)
    if d.hour >= 5:
        refresh_shop()
'''

# ---- 投射物 / 弹道 ----
SELF_PROJ_BAD = '''extends RigidBody3D
class_name Bullet

func fire(dir: Vector3) -> void:
    linear_velocity = dir * 300.0

func draw_aim() -> void:
    for i in 30:
        var p := global_position + dir * i * 2.0
        p.y -= 0.5 * 9.8 * i * 0.02
        line.add_point(p)
'''

SELF_PROJ_CLEAN = '''extends Node3D

func _physics_process(delta: float) -> void:
    var next := global_position + velocity * delta
    var q := PhysicsRayQueryParameters3D.create(global_position, next)
    var hit := get_world_3d().direct_space_state.intersect_ray(q)
    if hit:
        on_hit(hit)
        return
    global_position = next

func draw_aim() -> void:
    var pts := simulate_ballistic(global_position, velocity, 30)
    for p in pts:
        line.add_point(p)
'''

# ---- 进阶移动 ----
SELF_MOVE_BAD = '''extends CharacterBody3D

func grab_ledge(edge: Vector3) -> void:
    global_transform.origin = edge

func _ready() -> void:
    up_direction = Vector3.ZERO

func set_gravity_up(up: Vector3) -> void:
    up_direction = up
    gravity = -up * 20.0
'''

SELF_MOVE_CLEAN = '''extends CharacterBody3D

func grab_ledge(edge: Vector3) -> void:
    var delta := (edge - global_position).limit_length(0.5)
    move_and_collide(delta)

func set_gravity_up(up: Vector3, cam: Camera3D) -> void:
    up_direction = up
    gravity = -up * 20.0
    cam.basis = Basis.looking_at(-up)
'''

# ---- 多人社交 ----
SELF_SOCIAL_BAD = '''extends Node

func send_chat(text: String) -> void:
    var clean := WordFilter.censor(text)
    rpc("on_chat", clean)

func who_am_i() -> int:
    return multiplayer.get_unique_id()
'''

SELF_SOCIAL_CLEAN = '''extends Node

func send_chat(text: String) -> void:
    rpc_id(1, "server_send_chat", text)

@rpc("any_peer", "call_local", "reliable")
func server_send_chat(text: String) -> void:
    var clean := WordFilter.censor(text)
    Audit.log_chat(clean)
    rpc("on_chat", clean)

func who_am_i() -> String:
    return Session.account_id
'''

# ---- 生存 / 角色状态 ----
SELF_SURV_BAD = '''extends Node

var max_hp: int = 100
var is_dead := false

func take_damage(n: int) -> void:
    is_dead = true
    save_game()
    respawn()

func upgrade() -> void:
    max_hp = max_hp + 50

func respawn() -> void:
    position = spawn_point
'''

SELF_SURV_CLEAN = '''extends Node

enum DeathState { ALIVE, TRIGGERED, PLAYING, SETTLING, RESPAWNING }
var _death_state := DeathState.ALIVE
var base_value := 100
var _modifiers: Array = []
var current := 100

func recalc_max() -> int:
    var total := base_value
    for m in _modifiers:
        total += m.amount
    return total

func _set_state(next: DeathState) -> void:
    _death_state = next
    if next == DeathState.SETTLING:
        commit_checkpoint()

func respawn() -> void:
    _tween.kill()
    _timer.stop()
    _tween = null
    current = recalc_max()
'''

# ---- 叙事 / 进程 ----
SELF_NARR_BAD = '''extends Node

func pick_ending() -> String:
    if flags["met_alice"] and gold > 100:
        return "true_ending"
    elif flags["met_alice"]:
        return "friend_ending"
    elif flags["saved_city"]:
        return "hero_ending"
    else:
        return "normal"

func mark() -> void:
    set_flag("has_key", true)
    flags["has_key"] = true
'''

SELF_NARR_CLEAN = '''extends Node

const F_GLOBAL_MET_ALICE := StringName("global.met_alice")
const F_ACT1_SAVED_CITY := StringName("act1.saved_city")

const ENDINGS: Array = [
    {"id": "true_ending", "priority": 100, "conditions": ["global.met_alice"], "incompatible_with": []},
    {"id": "hero_ending", "priority": 50, "conditions": ["act1.saved_city"], "incompatible_with": []},
]

func pick_ending() -> String:
    var ok := []
    for e in ENDINGS:
        if StoryState.all_set(e.conditions):
            ok.append(e)
    ok.sort_custom(func(a, b): return a.priority > b.priority)
    return ok[0].id if ok else "normal"

func mark() -> void:
    StoryState.set_flag(F_GLOBAL_MET_ALICE, true)
'''

# ---- 谜题 / 机关 ----
SELF_PUZ_BAD = '''extends Node3D

func trace_light(dir: Vector3) -> void:
    while true:
        var hit := cast(dir)
        if not hit:
            break
        dir = dir.reflect(hit.normal)

func save_door() -> void:
    state.current_animation_position = anim.current_animation_position

func _input(e) -> void:
    if Input.is_action_just_pressed("interact"):
        try_activate()
'''

SELF_PUZ_CLEAN = '''extends Node3D

const MAX_BOUNCES := 8

func trace_light(dir: Vector3) -> void:
    for i in MAX_BOUNCES:
        var hit := cast(dir)
        if not hit:
            break
        dir = dir.bounce(hit.normal)

func save_door() -> void:
    state.open = is_open

func load_door() -> void:
    anim.seek(anim.current_animation_length, true)

func _input(e) -> void:
    if e is InputEventScreenTouch and e.pressed:
        var ray := screen_to_world(e.position)
        try_activate(ray)
'''

# ---- 时间操控 ----
SELF_TIME_BAD = '''extends Node

func hitstop() -> void:
    Engine.time_scale = 0.0
    await get_tree().create_timer(0.08).timeout
    Engine.time_scale = 1.0

func pause() -> void:
    get_tree().paused = true
    menu.show()

func slowmo() -> void:
    Engine.time_scale = 0.3
'''

SELF_TIME_CLEAN = '''extends Node

func hitstop() -> void:
    Engine.time_scale = 0.0
    await get_tree().create_timer(0.08, true).timeout
    Engine.time_scale = 1.0

func pause() -> void:
    get_tree().paused = true
    menu.process_mode = Node.PROCESS_MODE_WHEN_PAUSED
    menu.show()

func slowmo() -> void:
    TimeScale.slow_to(0.3)
'''
# ---- 域专项重建样本（GD241-GD274）----
SELF_RB_BAD = '''extends Node3D

var is_dead = false
var max_hp = base_hp * 2
var GAME_VERSION = "1.0"

func _ready() -> void:
    chara.up_direction = Vector3.ZERO

func chat(text: String) -> void:
    var clean := text.replace("bad", "***")
    send(clean)

func on_join() -> void:
    player_name = "p" + str(multiplayer.get_unique_id())

func ledge() -> void:
    global_position = ledge_pos

func flip_gravity() -> void:
    gravity = gravity.rotated(Vector3.FORWARD, PI)

func save() -> void:
    var d := {"node": self}
    store(d)

func respawn() -> void:
    hp = max_hp

func check_flag() -> void:
    if flags.has("door_opened"):
        pass

func ending() -> void:
    if flags_a:
        ending_a()
    elif flags_b:
        ending_b()

func mirror() -> void:
    while true:
        dir = dir.reflect(n)

func interact() -> void:
    if Input.is_action_pressed("ui_accept"):
        trigger()

func hitstop() -> void:
    Engine.time_scale = 0.0
    await get_tree().create_timer(0.08).timeout

func slowmo() -> void:
    Engine.time_scale = 0.3

func pause() -> void:
    get_tree().paused = true

func purchase() -> void:
    if buy_success:
        grant_item()

func gacha() -> void:
    var r := randf()
    if r < 0.01:
        give_ssr()

func daily() -> void:
    var t := Time.get_datetime_dict_from_system()
    if t.hour == 5:
        reset_daily()

func fire() -> void:
    velocity = Vector3.FORWARD * 3000

func predict_line() -> void:
    var g := gravity
    var p := pos + vel * t + 0.5 * g * t * t

func load_table(path: String) -> void:
    var d := JSON.parse_string(read(path))

func remap() -> void:
    InputMap.action_erase_events("jump")

func cast_skill(name: String) -> void:
    if name == "fireball":
        do_fire()

func damage_calc(d: float) -> float:
    return d * (1 + buff_a) * (1 + buff_b)

func hit_check() -> void:
    if distance_to(target) < 2.0:
        apply_damage()

func load_res() -> void:
    var r := load("res://x.tres")
    r.use()

func spawn_enemy() -> void:
    var e := Enemy.new()
    add_child(e)

func cutscene() -> void:
    player.play("intro")

func setup_camera() -> void:
    var arm := SpringArm3D.new()

func safe_ui() -> void:
    var area := safe_area

func shoot() -> void:
    bullet.velocity = dir * 3000
'''

SELF_RB_CLEAN = '''extends Node3D

enum State { ALIVE, DYING, DEAD }
var state: State = State.ALIVE
var base_value := 100.0
var additive := 0.0
var multipliers: Array = []

func _ready() -> void:
    chara.up_direction = Vector3.UP

func chat(text: String) -> void:
    request_server_filter.rpc_id(1, text)

func on_join() -> void:
    player_name = account_id

func ledge() -> void:
    var tw := create_tween()
    tw.tween_property(self, "position", ledge_pos, 0.2)

func flip_gravity() -> void:
    gravity = gravity.rotated(Vector3.FORWARD, PI)
    camera.up_direction = gravity_normal
    input_map.swap()

func save() -> void:
    if state != State.ALIVE:
        return
    var d := to_dict()
    store(d)

func respawn() -> void:
    kill_all_tweens()
    hp = get_max_hp()

func check_flag() -> void:
    if flags.has(FlagDef.DOOR_OPENED):
        pass

func ending() -> void:
    var e := ending_table.pick(conditions)
    e.apply()

func mirror() -> void:
    for i in range(MAX_BOUNCES):
        dir = dir.bounce(n)

func interact() -> void:
    if Input.is_action_pressed(ACTION_INTERACT):
        trigger()

func hitstop() -> void:
    Engine.time_scale = 0.0
    await get_tree().create_timer(0.08, true).timeout
    Engine.time_scale = 1.0

func slowmo() -> void:
    Engine.time_scale = 0.3
    await get_tree().create_timer(1.0, true).timeout
    Engine.time_scale = 1.0

func pause() -> void:
    get_tree().paused = true
    menu.process_mode = Node.PROCESS_MODE_ALWAYS

func purchase() -> void:
    var st := await server_verify_order(order_id)
    if st == "paid":
        grant_item()

func gacha() -> void:
    var r := await request_draw.rpc_id(1)

func daily() -> void:
    var t := Time.get_datetime_dict_from_unix_time(server_time_utc)
    if t.hour == 5:
        reset_daily()

func fire() -> void:
    bullet.velocity = Vector3.FORWARD * 3000
    raycast_scan(prev_pos, bullet.global_position)

func predict_line() -> void:
    var p := simulate_ballistic(pos, vel)

func load_table(path: String) -> void:
    var d := JSON.parse_string(read(path))
    validate_schema(d)

func remap() -> void:
    InputMap.action_erase_events("jump")
    save_keymap()

func cast_skill(res: SkillResource) -> void:
    res.execute()

func damage_calc(d: float) -> float:
    return d * (1.0 + additive_total()) * multiplier_total()

func hit_check() -> void:
    request_hit.rpc_id(1, target_id)

func load_res() -> void:
    var r := load("res://x.tres")
    if r == null:
        push_error("load failed")
        return
    r.use()

func spawn_enemy() -> void:
    var e := pool.acquire()
    add_child(e)

func cutscene() -> void:
    disable_input()
    player.play("intro")

func setup_camera() -> void:
    var arm := SpringArm3D.new()
    arm.collision_mask = 1

func safe_ui() -> void:
    var area := DisplayServer.get_display_safe_area()
'''

SELF_GTD_GD = '''extends Node2D

func wave_clear() -> bool:
    return get_nodes_in_group("enemies").is_empty()

func build_tower() -> void:
    tile.set_cell(Vector2i(1, 1), 0, Vector2i(0, 0))
    var p := NavigationServer2D.map_get_path(m, a, b, true, 1)

func on_body_entered(body: Node) -> void:
    if body.name == "Enemy":
        body.queue_free()

func spawn_timer() -> void:
    t.wait_time = 0.05

func tower_range() -> void:
    body_entered.connect(_on_tower_range)

func enemy_tick() -> void:
    if not active:
        return
'''

SELF_GRTS_GD = '''extends Node2D

func _process(delta: float) -> void:
    var units := get_nodes_in_group("units")

func pick(p: Vector2) -> Vector2:
    return camera.screen_to_world_point(p)

var fog_light: Light2D

func move_squad() -> void:
    for u in units:
        u.target_position = leader.global_position
'''

SELF_GRTS2_GD = '''extends Node2D

func _physics_process(delta: float) -> void:
    fog.set_cell(Vector2i(0, 0), 1, Vector2i(0, 0))
'''

SELF_GCARD_GD = '''extends Node2D

func shuffle_deck() -> void:
    deck.shuffle()

func draw_one() -> void:
    var r := randf()

func persist() -> void:
    var card_json := JSON.stringify(deck)

var card: PackedScene

func play(e) -> void:
    e.take_damage(5)

func draw_more() -> void:
    if deck.is_empty():
        _reshuffle()
'''

SELF_GROGUE_GD = '''extends Node2D

func build() -> void:
    for room in rooms:
        tile.set_cell(room.cell, 0, Vector2i(0, 0))

func generate_map() -> void:
    ground.set_cell(Vector2i(2, 2), 0, Vector2i(0, 0))

func _exit_tree() -> void:
    ResourceSaver.save(meta, "user://meta.res")

func quick_save() -> void:
    ResourceSaver.save(state, "user://s.res")

func save_purchase() -> void:
    ResourceSaver.save(purchase_data, "user://p.res", ResourceSaver.FLAG_COMPRESS)

func roll_item() -> int:
    for it in item_pool:
        total += it.weight
    return 0
'''

SELF_GIDLE_GD = '''extends Node2D

func _process(delta: float) -> void:
    var v := output_rate * delta

func settle() -> float:
    var offline_gain = offline_rate * elapsed
    return offline_gain

func daily_reset() -> void:
    var t := Time.get_datetime_dict_from_system()

func can_place(c: Vector2i) -> bool:
    return not area.get_overlapping_bodies().is_empty()

var amounts: Dictionary[String, float] = {}
'''

SELF_GPLAT_GD = '''extends Node2D

func _physics_process(_d: float) -> void:
    if Input.is_action_just_pressed("jump"):
        jump()

func release_jump() -> void:
    velocity.y = 0

func move_platform(delta: float) -> void:
    platform.position += Vector2.RIGHT * 200.0 * delta

func dash() -> void:
    shape.radius = 0.5
'''

SELF_GBULLET_GD = '''extends Node2D

func _process(delta: float) -> void:
    mm.instance_count = live_count

var bullet_area: Area2D

func step(delta: float) -> void:
    bullet.position += bullet_vel * delta

func hit_check() -> bool:
    return dist(bullet.global_position)
'''

SELF_GBULLET2_GD = '''extends Node2D

func collide() -> void:
    var hits := get_world_2d().direct_space_state.intersect_point(q)
'''

SELF_GMISC_GD = '''extends Node2D

func persist() -> void:
    ResourceSaver.save(state, "user://s.res")

func wait_done() -> void:
    await get_tree().create_timer(1.0).timeout
    refresh()

func die() -> void:
    queue_free()
    self.hp = 0

func make_token() -> int:
    var token := randi()
    return token
'''

SELF_GTDOK_GD = '''extends Node2D

var spawned_count := 0
var killed_count := 0
var escaped_count := 0

func wave_clear() -> bool:
    return spawned_count == killed_count + escaped_count

func build_tower() -> void:
    tile.set_cell(Vector2i(1, 1), 0, Vector2i(0, 0))
    NavigationServer2D.map_force_update()

func on_body_entered(body: Node) -> void:
    if body.has_method("take_damage"):
        body.take_damage(10.0, 0)

func spawn_timer(delta: float) -> void:
    _acc += delta

func tower_range() -> void:
    var hits := get_world_2d().direct_space_state.intersect_shape(q, 32)

func enemy_idle() -> void:
    set_physics_process(false)
'''

SELF_GRTSOK_GD = '''extends Node2D

var _units: Array = []

func _process(delta: float) -> void:
    tick(_units)

func pick(p: Vector2) -> Vector2:
    return get_screen_transform().affine_inverse() * p

func move_squad() -> void:
    for i in _units.size():
        _units[i].target_position = leader.global_position + formation_offset(i)
'''

SELF_GRTS2OK_GD = '''extends Node2D

var _dirty: Array = []

func _physics_process(delta: float) -> void:
    _collect(_dirty)

func flush() -> void:
    for c in _dirty:
        fog.set_cell(c, 1, Vector2i(0, 0))
    _dirty.clear()
'''

SELF_GCARDOK_GD = '''extends Node2D

var rng := RandomNumberGenerator.new()

func shuffle_deck() -> void:
    for i in range(deck.size() - 1, 0, -1):
        var j := rng.randi_range(0, i)
        var t = deck[i]
        deck[i] = deck[j]
        deck[j] = t

func draw_one() -> void:
    var r := rng.randf()

func persist() -> void:
    var err := ResourceSaver.save(deck_state, "user://deck.res.tmp")
    if err != OK:
        push_error("deck save failed")
        return
    DirAccess.rename_absolute("user://deck.res.tmp", "user://deck.res")

var card_data: CardData

func play(e) -> void:
    _stack.push_back(DamageEvent.new(self, e, 5))

func draw_more() -> void:
    if is_reshuffling:
        return
    if deck.is_empty():
        _reshuffle()
'''

SELF_GROGUEOK_GD = '''extends Node2D

func build() -> void:
    var d := build_layout()
    if not validate_connectivity(d):
        return
    ground.navigation_enabled = false
    for room in rooms:
        ground.set_cell(room.cell, 0, Vector2i(0, 0))
    ground.navigation_enabled = true

func generate_map() -> void:
    ground.navigation_enabled = false
    ground.set_cell(Vector2i(2, 2), 0, Vector2i(0, 0))
    ground.navigation_enabled = true

func on_clear() -> void:
    save_meta()

func save_meta() -> void:
    var e1 := ResourceSaver.save(meta, "user://meta.res.tmp")
    if e1 != OK:
        push_error("meta save failed")
        return
    DirAccess.rename_absolute("user://meta.res.tmp", "user://meta.res")

func quick_save() -> void:
    var e2 := ResourceSaver.save(state, "user://s.res.tmp")
    if e2 != OK:
        push_error("state save failed")
        return
    DirAccess.rename_absolute("user://s.res.tmp", "user://s.res")

func save_purchase() -> void:
    var sig := hmac(purchase_data)
    var e3 := ResourceSaver.save(purchase_data, "user://p.res")
    if e3 != OK:
        push_error("purchase save failed")

func roll_item() -> int:
    return _cum.bsearch(rng.randf() * _cum[-1])
'''

SELF_GIDLEOK_GD = '''extends RefCounted

const FIXED_STEP := 0.25
var _acc := 0.0

func advance(delta: float) -> void:
    _acc += delta
    while _acc >= FIXED_STEP:
        tick(FIXED_STEP)
        _acc -= FIXED_STEP

func settle(seconds: float) -> float:
    var t := 0.0
    while t < seconds:
        tick(FIXED_STEP)
        t += FIXED_STEP
    return t

func daily_reset() -> void:
    var t := Time.get_unix_time_from_utc()

func can_place(c: Vector2i) -> bool:
    return _grid[c.y][c.x] == null

var amounts: Dictionary[StringName, float] = {}
'''

SELF_GPLATOK_GD = '''extends CharacterBody2D

var jump_buffer_timer := 0.0

func _input(event: InputEvent) -> void:
    if event.is_action_pressed("jump"):
        jump_buffer_timer = 0.15

func _physics_process(_d: float) -> void:
    if jump_buffer_timer > 0.0 and is_on_floor():
        jump_buffer_timer = 0.0

func release_jump() -> void:
    velocity.y = maxf(velocity.y, -150.0)

func move_platform(delta: float) -> void:
    platform.move_and_slide()

func dash() -> void:
    collision_mask = DASH_MASK
'''

SELF_GBULLETOK_GD = '''extends Node2D

const LOGIC_STEP := 1.0 / 60.0
var _acc := 0.0

func _process(delta: float) -> void:
    _acc += delta
    while _acc >= LOGIC_STEP:
        step(LOGIC_STEP)
        _acc -= LOGIC_STEP

func flush() -> void:
    mm.visible_instance_count = live_count

func step(dt: float) -> void:
    for i in live_count:
        _pos[i] += _vel[i] * dt

func hit_check() -> bool:
    return dist(hit_point) < HIT_RADIUS
'''

SELF_GBULLET2OK_GD = '''extends Node2D

func collide() -> void:
    var hits := get_world_2d().direct_space_state.intersect_point(q, 64)
'''

SELF_GMISCOK_GD = '''extends Node2D

func persist() -> void:
    var err := ResourceSaver.save(state, "user://s.res.tmp")
    if err != OK:
        push_error("save failed")
        return
    DirAccess.rename_absolute("user://s.res.tmp", "user://s.res")

func wait_done() -> void:
    await get_tree().create_timer(1.0).timeout
    if is_instance_valid(self):
        refresh()

func die() -> void:
    queue_free()
    return

func make_token() -> PackedByteArray:
    return Crypto.new().generate_random_bytes(16)
'''

SELF_NETOPS_BAD = '''extends Node2D

var _http: HTTPRequest

func _on_peer_disconnected(id: int) -> void:
    get_node("Player").queue_free()

func apply_authority_snapshot(server_pos: Vector2) -> void:
    global_position = server_pos

func spectate_render() -> void:
    sprite.position = latest_snapshot.pos

func _process(delta: float) -> void:
    simulate(delta)

func fetch() -> void:
    _http.request("https://api.example.com/cfg")

func load_cfg(t: String) -> void:
    var d = JSON.parse_string(t)
    hp = d.hp
'''

SELF_NETOPS_CLEAN = '''extends Node2D

var _http: HTTPRequest
var _acc := 0.0
const STEP := 1.0 / 60.0

func _on_peer_disconnected(id: int) -> void:
    retain_and_ai_control(id, reconnect_grace_ms)

func sync_pos(target: Vector2) -> void:
    global_position = global_position.lerp(target, 0.2)

func spectate_render() -> void:
    var f := _history.sample(_display_tick)
    sprite.position = f.pos

func _process(delta: float) -> void:
    _acc += delta
    while _acc >= STEP:
        simulate(STEP)
        _acc -= STEP

func fetch() -> void:
    _http.request("https://api.example.com/cfg", [], HTTPClient.METHOD_GET, "", _retry_with_backoff())

func load_cfg(t: String) -> void:
    var j := JSON.new()
    if j.parse(t) != OK:
        push_error("bad cfg")
        return
    hp = j.data.get("hp", 100)
'''

SELF_OPS2_BAD = '''extends Node2D

var _agent: NavigationAgent3D
var _boids: Array

func move() -> void:
    _agent.set_velocity(vel)

func flock_step() -> void:
    for a in _boids:
        for b in _boids:
            pass

func check_speed_hack() -> bool:
    var t := Time.get_unix_time_from_system()
    return t > limit

const HMAC_KEY := "aB3dEf7hIjKlMnOp"

func save_state() -> void:
    cf.save_encrypted_pass("user://s.enc", "mysecret123")

func on_cheat() -> void:
    ban_player(uid)

func merge_shards() -> void:
    db.update("players", data)

func compensate(pid: int) -> void:
    add_item(pid, 1001, 5)
'''

SELF_OPS2_CLEAN = '''extends Node2D

var _agent: NavigationAgent3D
var _boids: Array
var _grid := {}

func _ready() -> void:
    _agent.avoidance_enabled = true
    _agent.velocity_computed.connect(_on_safe)

func _on_safe(v: Vector3) -> void:
    velocity = v

func move() -> void:
    _agent.set_velocity(vel)

func flock_step() -> void:
    for a in _boids:
        for n in _grid.neighbors(a.cell):
            pass

func check_speed_hack() -> bool:
    var t := Time.get_ticks_msec()
    return t > limit

var _hmac_key: PackedByteArray

func save_state() -> void:
    cf.save_encrypted("user://s.enc", derive_pbkdf2(dev_kek, salt))

func on_cheat() -> void:
    report_risk_score(uid, 80)

func merge_shards() -> void:
    take_snapshot()
    if not dry_run(data):
        return
    migrate_idempotent(data)

func compensate(pid: int, cid: int) -> void:
    if grant_log.has(cid):
        return
    add_item(pid, 1001, 5)
'''

SELF_OPS3_BAD = '''extends Node2D

var id_card: String

func submit_realname(name: String, id: String) -> void:
    id_card = id
    save_profile()

func can_play() -> bool:
    if is_minor:
        var t := Time.get_unix_time_from_system()
        return t < limit
    return true

func delete_account(uid: int) -> void:
    db.DELETE FROM players WHERE uid = uid

func roll_affix(inst) -> void:
    inst.affix.final_value = calc(inst)

func decompose(inst) -> int:
    return inst.base_cost
'''

SELF_OPS3_CLEAN = '''extends Node2D

var _verify_credential: String

func submit_realname(name: String, id: String) -> void:
    var h := id.sha256_text()
    _verify_credential = h
    save_profile()

func can_play() -> bool:
    if is_minor:
        var t := server_now_utc()
        return t < limit
    return true

func delete_account(uid: int) -> void:
    var st := load_state(uid)
    if st != "identity_verified":
        return
    anonymize_pii(uid)
    mark_retention_review(uid)

func roll_affix(inst) -> void:
    inst.affix.roll = randf()

func decompose(inst) -> int:
    return evaluate_current_value(inst)
'''





SELF_UI_BAD = '''extends RichTextLabel

func say(nick: String, msg: String) -> void:
    append_text("[color=red]" + nick + "[/color]: " + msg)

func build_list(items: Array) -> void:
    for it in items:
        var b := Button.new()
        b.text = str(it)
        $VBox.add_child(b)
'''

SELF_UI_CLEAN = '''extends RichTextLabel

func say(nick: String, msg: String) -> void:
    append_text("[color=red]" + nick.escape_bbcode() + "[/color]: " + msg.escape_bbcode())

func build_list(items: Array) -> void:
    $VirtualList.recycle(items)
'''

# ---- 诊断 ----
SELF_DIAG_BAD = '''extends Node

func _ready() -> void:
    var res := load("res://data/cfg.tres")
    res.apply()

func check(inv: Array, item: String) -> void:
    assert(inv.erase(item))
'''

SELF_DIAG_CLEAN = '''extends Node

class DiagLogger extends RefCounted:
    func _log_error(_f, _fl, _l, _c, _r, _t, _s) -> void:
        pass

func _init() -> void:
    OS.add_logger(DiagLogger.new())

func _ready() -> void:
    var res := load("res://data/cfg.tres")
    if res == null:
        push_error("配置加载失败，走兜底")
        return
    res.apply()
'''
SELF_CHR_CLEAN = '''extends Node3D

func dye(part: MeshInstance3D, c: Color) -> void:
    var mat := part.get_surface_override_material(0).duplicate()
    mat.albedo_color = c
    part.set_surface_override_material(0, mat)

func set_face(name_: String, v: float) -> void:
    var idx := $Head.find_blend_shape_by_name(name_)
    if $Head.mesh == null or idx < 0:
        return
    $Head.set_blend_shape_value(idx, v)
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
            'rb.gd': SELF_RB_BAD, 'rbok.gd': SELF_RB_CLEAN,
            'gtd.gd': SELF_GTD_GD,
            'grts.gd': SELF_GRTS_GD,
            'grts2.gd': SELF_GRTS2_GD,
            'gcard.gd': SELF_GCARD_GD,
            'grogue.gd': SELF_GROGUE_GD,
            'gidle.gd': SELF_GIDLE_GD,
            'gplat.gd': SELF_GPLAT_GD,
            'gbullet.gd': SELF_GBULLET_GD,
            'gbullet2.gd': SELF_GBULLET2_GD,
            'gmisc.gd': SELF_GMISC_GD,
            'gtdok.gd': SELF_GTDOK_GD,
            'grtsok.gd': SELF_GRTSOK_GD,
            'grts2ok.gd': SELF_GRTS2OK_GD,
            'gcardok.gd': SELF_GCARDOK_GD,
            'grogueok.gd': SELF_GROGUEOK_GD,
            'gidleok.gd': SELF_GIDLEOK_GD,
            'gplatok.gd': SELF_GPLATOK_GD,
            'gbulletok.gd': SELF_GBULLETOK_GD,
            'gbullet2ok.gd': SELF_GBULLET2OK_GD,
            'gmiscok.gd': SELF_GMISCOK_GD,
            'dbg.gd': SELF_DEBUG_BAD, 'dbgok.gd': SELF_DEBUG_CLEAN,
            'sh.gdshader': SELF_SHADER_BAD, 'shok.gdshader': SELF_SHADER_CLEAN,
            'misc.gd': SELF_MISC_BAD, 'miscok.gd': SELF_MISC_CLEAN,
            'netops.gd': SELF_NETOPS_BAD, 'netopsok.gd': SELF_NETOPS_CLEAN,
            'ops2.gd': SELF_OPS2_BAD, 'ops2ok.gd': SELF_OPS2_CLEAN, 'ops3.gd': SELF_OPS3_BAD, 'ops3ok.gd': SELF_OPS3_CLEAN,
            'v47.gd': SELF_V47_BAD, 'v47ok.gd': SELF_V47_CLEAN,
            'net.gd': SELF_NET_BAD, 'netok.gd': SELF_NET_CLEAN,
            'awt.gd': SELF_AWT_BAD, 'awtok.gd': SELF_AWT_CLEAN,
            'plg.gd': SELF_PLG_BAD, 'plgok.gd': SELF_PLG_CLEAN,
            'asy.cs': SELF_CS_ASYNC_BAD, 'asyok.cs': SELF_CS_ASYNC_CLEAN,
            'pcg.gd': SELF_PCG_BAD, 'pcgok.gd': SELF_PCG_CLEAN,
            'perc.gd': SELF_PERC_BAD, 'percok.gd': SELF_PERC_CLEAN,
            'bone.gd': SELF_BONE_BAD, 'boneok.gd': SELF_BONE_CLEAN,
            'dt.gd': SELF_DT_BAD, 'dtok.gd': SELF_DT_CLEAN,
            'vfx.gd': SELF_VFX_BAD, 'vfxok.gd': SELF_VFX_CLEAN,
            'eco.gd': SELF_ECO_BAD, 'ecook.gd': SELF_ECO_CLEAN,
            'inp.gd': SELF_INP_BAD, 'inpok.gd': SELF_INP_CLEAN,
            'rpl.gd': SELF_RPL_BAD, 'rplok.gd': SELF_RPL_CLEAN,
            'mod.gd': SELF_MOD_BAD, 'modok.gd': SELF_MOD_CLEAN,
            'mig.gd': SELF_MIG_BAD, 'migok.gd': SELF_MIG_CLEAN,
            'cld.gd': SELF_CLD_BAD, 'cldok.gd': SELF_CLD_CLEAN, 'cldts.gd': SELF_CLD_TS_BAD,
            'dev.gd': SELF_DBG_BAD, 'devok.gd': SELF_DBG_CLEAN,
            'gfx.gd': SELF_GFX_BAD, 'gfxok.gd': SELF_GFX_CLEAN, 'taa.gd': SELF_TAA_BAD,
            'veh.gd': SELF_VEH_BAD, 'vehok.gd': SELF_VEH_CLEAN,
            'chr.gd': SELF_CHR_BAD, 'chrok.gd': SELF_CHR_CLEAN,
            'ui2.gd': SELF_UI_BAD, 'ui2ok.gd': SELF_UI_CLEAN,
            'diag.gd': SELF_DIAG_BAD, 'diagok.gd': SELF_DIAG_CLEAN,
            'pay.gd': SELF_PAY_BAD, 'payok.gd': SELF_PAY_CLEAN,
            'proj.gd': SELF_PROJ_BAD, 'projok.gd': SELF_PROJ_CLEAN,
            'mv.gd': SELF_MOVE_BAD, 'mvok.gd': SELF_MOVE_CLEAN,
            'soc.gd': SELF_SOCIAL_BAD, 'socok.gd': SELF_SOCIAL_CLEAN,
            'surv.gd': SELF_SURV_BAD, 'survok.gd': SELF_SURV_CLEAN,
            'narr.gd': SELF_NARR_BAD, 'narrok.gd': SELF_NARR_CLEAN,
            'puz.gd': SELF_PUZ_BAD, 'puzok.gd': SELF_PUZ_CLEAN,
            'time.gd': SELF_TIME_BAD, 'timeok.gd': SELF_TIME_CLEAN,
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
        # --- GD13x 网络同步 / 插件 ---
        for rid in ('GD131', 'GD132', 'GD134'):
            check(rid in ids('net.gd'), 'net.gd 命中 %s' % rid)
        for rid in ('GD131', 'GD132', 'GD133', 'GD134'):
            check(rid not in ids('netok.gd'), 'netok.gd 不报 %s（干净样本）' % rid)
        # GD133 跨行：单独样本（net.gd 里有 sender 校验会掩盖它）
        check('GD133' in ids('awt.gd'), 'awt.gd 命中 GD133（await 后用 sender）')
        check('GD133' not in ids('awtok.gd'), 'awtok.gd 不报 GD133（先存局部变量）')
        for rid in ('GD135', 'GD136'):
            check(rid in ids('plg.gd'), 'plg.gd 命中 %s' % rid)

        for rid in ('GD141', 'GD142', 'GD143'):
            check(rid in ids('pcg.gd'), 'pcg.gd 命中 %s' % rid)
        for rid in ('GD141', 'GD142', 'GD143'):
            check(rid not in ids('pcgok.gd'), 'pcgok.gd 不误报 %s' % rid)
        for rid in ('GD144', 'GD145'):
            check(rid in ids('perc.gd'), 'perc.gd 命中 %s' % rid)
        for rid in ('GD144', 'GD145'):
            check(rid not in ids('percok.gd'), 'percok.gd 不误报 %s' % rid)
        for rid in ('GD241', 'GD242', 'GD243', 'GD244', 'GD245', 'GD246', 'GD247', 'GD248', 'GD249', 'GD250', 'GD251', 'GD252', 'GD253', 'GD254', 'GD255', 'GD256', 'GD257', 'GD258', 'GD259', 'GD260', 'GD261', 'GD262', 'GD263', 'GD264', 'GD265', 'GD266', 'GD267', 'GD268', 'GD269', 'GD270', 'GD271', 'GD272', 'GD273', 'GD274'):
            check(rid in ids('rb.gd'), 'rb.gd 命中 %s' % rid)

        # ---- 类型专项（GD275-GD316）样本断言 ----
        for rid in ('GD275', 'GD276', 'GD277', 'GD278', 'GD279', 'GD280'):
            check(rid in ids('gtd.gd'), 'td.gd 命中 %s' % rid)
        for rid in ('GD275', 'GD276', 'GD277', 'GD278', 'GD279', 'GD280'):
            check(rid not in ids('gtdok.gd'), 'tdok.gd 不报 %s' % rid)
        for rid in ('GD281', 'GD282', 'GD283', 'GD285'):
            check(rid in ids('grts.gd'), 'rts.gd 命中 %s' % rid)
        for rid in ('GD281', 'GD282', 'GD283', 'GD285'):
            check(rid not in ids('grtsok.gd'), 'rtsok.gd 不报 %s' % rid)
        for rid in ('GD284',):
            check(rid in ids('grts2.gd'), 'rts2.gd 命中 %s' % rid)
        for rid in ('GD284',):
            check(rid not in ids('grts2ok.gd'), 'rts2ok.gd 不报 %s' % rid)
        for rid in ('GD286', 'GD287', 'GD288', 'GD289', 'GD290', 'GD291'):
            check(rid in ids('gcard.gd'), 'card.gd 命中 %s' % rid)
        for rid in ('GD286', 'GD287', 'GD288', 'GD289', 'GD290', 'GD291'):
            check(rid not in ids('gcardok.gd'), 'cardok.gd 不报 %s' % rid)
        for rid in ('GD292', 'GD293', 'GD294', 'GD295', 'GD296', 'GD297'):
            check(rid in ids('grogue.gd'), 'rogue.gd 命中 %s' % rid)
        for rid in ('GD292', 'GD293', 'GD294', 'GD295', 'GD296', 'GD297'):
            check(rid not in ids('grogueok.gd'), 'rogueok.gd 不报 %s' % rid)
        for rid in ('GD298', 'GD299', 'GD300', 'GD301', 'GD303'):
            check(rid in ids('gidle.gd'), 'idle.gd 命中 %s' % rid)
        for rid in ('GD298', 'GD299', 'GD300', 'GD301', 'GD303'):
            check(rid not in ids('gidleok.gd'), 'idleok.gd 不报 %s' % rid)
        for rid in ('GD304', 'GD305', 'GD306', 'GD307'):
            check(rid in ids('gplat.gd'), 'plat.gd 命中 %s' % rid)
        for rid in ('GD304', 'GD305', 'GD306', 'GD307'):
            check(rid not in ids('gplatok.gd'), 'platok.gd 不报 %s' % rid)
        for rid in ('GD308', 'GD309', 'GD310', 'GD311'):
            check(rid in ids('gbullet.gd'), 'bullet.gd 命中 %s' % rid)
        for rid in ('GD308', 'GD309', 'GD310', 'GD311'):
            check(rid not in ids('gbulletok.gd'), 'bulletok.gd 不报 %s' % rid)
        for rid in ('GD312',):
            check(rid in ids('gbullet2.gd'), 'bullet2.gd 命中 %s' % rid)
        for rid in ('GD312',):
            check(rid not in ids('gbullet2ok.gd'), 'bullet2ok.gd 不报 %s' % rid)
        for rid in ('GD313', 'GD314', 'GD315', 'GD316'):
            check(rid in ids('gmisc.gd'), 'misc.gd 命中 %s' % rid)
        for rid in ('GD313', 'GD314', 'GD315', 'GD316'):
            check(rid not in ids('gmiscok.gd'), 'miscok.gd 不报 %s' % rid)
        for rid in ('GD241', 'GD242', 'GD243', 'GD244', 'GD245', 'GD246', 'GD247', 'GD248', 'GD249', 'GD250', 'GD251', 'GD252', 'GD253', 'GD254', 'GD255', 'GD256', 'GD257', 'GD258', 'GD259', 'GD260', 'GD261', 'GD262', 'GD263', 'GD264', 'GD265', 'GD266', 'GD267', 'GD268', 'GD269', 'GD270', 'GD271', 'GD272', 'GD273', 'GD274'):
            check(rid not in ids('rbok.gd'), 'rbok.gd 不误报 %s' % rid)
        check('GD146' in ids('bone.gd'), 'bone.gd 命中 GD146（不存在的 IK 节点）')
        check('GD146' not in ids('boneok.gd'), 'boneok.gd 不误报 GD146')
        # ---- 观战/重连/运营（GD317-GD322）----
        for rid in ('GD317', 'GD318', 'GD319', 'GD320', 'GD321', 'GD322'):
            check(rid in ids('netops.gd'), 'netops.gd 命中 %s' % rid)
        for rid in ('GD317', 'GD318', 'GD319', 'GD320', 'GD321', 'GD322'):
            check(rid not in ids('netopsok.gd'), 'netopsok.gd 不报 %s' % rid)
        # ---- 群集/避障·分服·账号反外挂（GD323-GD330）----
        for rid in ('GD323', 'GD324', 'GD325', 'GD326', 'GD327', 'GD328', 'GD329', 'GD330'):
            check(rid in ids('ops2.gd'), 'ops2.gd 命中 %s' % rid)
        for rid in ('GD323', 'GD324', 'GD325', 'GD326', 'GD327', 'GD328', 'GD329', 'GD330'):
            check(rid not in ids('ops2ok.gd'), 'ops2ok.gd 不报 %s' % rid)
        # ---- 合规·装备养成（GD331-GD335）----
        for rid in ('GD331', 'GD332', 'GD333', 'GD334', 'GD335'):
            check(rid in ids('ops3.gd'), 'ops3.gd 命中 %s' % rid)
        for rid in ('GD331', 'GD332', 'GD333', 'GD334', 'GD335'):
            check(rid not in ids('ops3ok.gd'), 'ops3ok.gd 不报 %s' % rid)



        for rid in ('GD151', 'GD152'):
            check(rid in ids('dt.gd'), 'dt.gd 命中 %s' % rid)
        for rid in ('GD151', 'GD152'):
            check(rid not in ids('dtok.gd'), 'dtok.gd 不误报 %s' % rid)
        for rid in ('GD153', 'GD154'):
            check(rid in ids('vfx.gd'), 'vfx.gd 命中 %s' % rid)
        for rid in ('GD153', 'GD154'):
            check(rid not in ids('vfxok.gd'), 'vfxok.gd 不误报 %s' % rid)
        for rid in ('GD155', 'GD156'):
            check(rid in ids('eco.gd'), 'eco.gd 命中 %s' % rid)
        for rid in ('GD155', 'GD156'):
            check(rid not in ids('ecook.gd'), 'ecook.gd 不误报 %s' % rid)

        for rid in ('GD161', 'GD162', 'GD163'):
            check(rid in ids('inp.gd'), 'inp.gd 命中 %s' % rid)
        for rid in ('GD161', 'GD162', 'GD163'):
            check(rid not in ids('inpok.gd'), 'inpok.gd 不误报 %s' % rid)
        for rid in ('GD164', 'GD165'):
            check(rid in ids('rpl.gd'), 'rpl.gd 命中 %s' % rid)
        for rid in ('GD164', 'GD165'):
            check(rid not in ids('rplok.gd'), 'rplok.gd 不误报 %s' % rid)
        check('GD166' in ids('mod.gd'), 'mod.gd 命中 GD166（zip-slip 路径拼接）')
        check('GD166' not in ids('modok.gd'), 'modok.gd 不误报 GD166')
        for rid in ('GD169', 'GD170'):
            check(rid in ids('mig.gd'), 'mig.gd 命中 %s' % rid)
        for rid in ('GD169', 'GD170'):
            check(rid not in ids('migok.gd'), 'migok.gd 不误报 %s' % rid)

        check('GD171' in ids('cld.gd'), 'cld.gd 命中 GD171（云存档无冲突处理）')
        check('GD171' not in ids('cldok.gd'), 'cldok.gd 不误报 GD171')
        check('GD172' in ids('cldts.gd'), 'cldts.gd 命中 GD172（时间戳判冲突）')
        for rid in ('GD173', 'GD174'):
            check(rid in ids('dev.gd'), 'dev.gd 命中 %s' % rid)
        for rid in ('GD173', 'GD174'):
            check(rid not in ids('devok.gd'), 'devok.gd 不误报 %s' % rid)

        check('GD182' in ids('gfx.gd'), 'gfx.gd 命中 GD182（超分未分层）')
        check('GD182' not in ids('gfxok.gd'), 'gfxok.gd 不误报 GD182')
        check('GD183' in ids('veh.gd'), 'veh.gd 命中 GD183（载具无自定义质心）')
        check('GD183' not in ids('vehok.gd'), 'vehok.gd 不误报 GD183')
        for rid in ('GD185', 'GD186'):
            check(rid in ids('chr.gd'), 'chr.gd 命中 %s' % rid)
        for rid in ('GD185', 'GD186'):
            check(rid not in ids('chrok.gd'), 'chrok.gd 不误报 %s' % rid)

        for rid in ('GD191', 'GD192'):
            check(rid in ids('ui2.gd'), 'ui2.gd 命中 %s' % rid)
        for rid in ('GD191', 'GD192'):
            check(rid not in ids('ui2ok.gd'), 'ui2ok.gd 不误报 %s' % rid)
        check('GD194' in ids('diag.gd'), 'diag.gd 命中 GD194（assert 含副作用）')
        check('GD195' in ids('diag.gd'), 'diag.gd 命中 GD195（资源加载未判空）')
        check('GD195' not in ids('diagok.gd'), 'diagok.gd 不误报 GD195')
        check('GD196' not in ids('diagok.gd'), 'diagok.gd 不误报 GD196（已注册 logger）')

        check('GD201' in ids('pay.gd'), 'pay.gd 命中 GD201（客户端判支付成功）')
        check('GD202' in ids('pay.gd'), 'pay.gd 命中 GD202（抽卡随机在客户端）')
        check('GD204' in ids('pay.gd'), 'pay.gd 命中 GD204（日期用本地时区）')
        for rid in ('GD201', 'GD202', 'GD204'):
            check(rid not in ids('payok.gd'), 'payok.gd 不误报 %s' % rid)
        check('GD205' in ids('proj.gd'), 'proj.gd 命中 GD205（高速投射物无扫描）')
        check('GD206' in ids('proj.gd'), 'proj.gd 命中 GD206（预测与实弹两套公式）')
        for rid in ('GD205', 'GD206'):
            check(rid not in ids('projok.gd'), 'projok.gd 不误报 %s' % rid)

        check('GD211' in ids('mv.gd'), 'mv.gd 命中 GD211（抓边直接赋坐标）')
        check('GD212' in ids('mv.gd'), 'mv.gd 命中 GD212（up_direction 设为零）')
        check('GD213' in ids('mv.gd'), 'mv.gd 命中 GD213（改重力未同步相机）')
        for rid in ('GD211', 'GD212', 'GD213'):
            check(rid not in ids('mvok.gd'), 'mvok.gd 不误报 %s' % rid)
        check('GD214' in ids('soc.gd'), 'soc.gd 命中 GD214（聊天仅客户端过滤）')
        check('GD215' in ids('soc.gd'), 'soc.gd 命中 GD215（peer ID 当玩家身份）')
        for rid in ('GD214', 'GD215'):
            check(rid not in ids('socok.gd'), 'socok.gd 不误报 %s' % rid)

        for rid in ('GD221', 'GD222', 'GD223', 'GD224'):
            check(rid in ids('surv.gd'), 'surv.gd 命中 %s' % rid)
        for rid in ('GD221', 'GD222', 'GD223', 'GD224'):
            check(rid not in ids('survok.gd'), 'survok.gd 不误报 %s' % rid)
        for rid in ('GD225', 'GD226'):
            check(rid in ids('narr.gd'), 'narr.gd 命中 %s' % rid)
        for rid in ('GD225', 'GD226'):
            check(rid not in ids('narrok.gd'), 'narrok.gd 不误报 %s' % rid)

        for rid in ('GD231', 'GD232', 'GD233', 'GD234'):
            check(rid in ids('puz.gd'), 'puz.gd 命中 %s' % rid)
        for rid in ('GD231', 'GD232', 'GD233', 'GD234'):
            check(rid not in ids('puzok.gd'), 'puzok.gd 不误报 %s' % rid)
        for rid in ('GD235', 'GD236', 'GD237'):
            check(rid in ids('time.gd'), 'time.gd 命中 %s' % rid)
        for rid in ('GD235', 'GD236', 'GD237'):
            check(rid not in ids('timeok.gd'), 'timeok.gd 不误报 %s' % rid)
        for rid in ('GD135', 'GD136'):
            check(rid not in ids('plgok.gd'), 'plgok.gd 不报 %s（干净样本）' % rid)
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
