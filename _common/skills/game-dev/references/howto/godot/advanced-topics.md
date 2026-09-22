# Godot 4.x 高级主题：程序化生成 / 编辑器工具 / 资源管线 / XR

四个相对独立的大型项目主题。

## 一、程序化生成

### 确定性先于"随机感"

**只存一个整数种子是不够的。** 生成结果取决于四层：

```
算法实现 + 输入配置 + 随机数状态 + 外部数据版本
```

只存种子，改了 `FastNoiseLite` 参数、换了模板库、升了 Godot 版本 —— 同一"种子"产出完全不同。
所以要把**生成请求整体**序列化成不可变 manifest。

```gdscript
class_name SeedManager
extends RefCounted

const PROTOCOL_VERSION := 1

var protocol_version := PROTOCOL_VERSION
var seed: int
var source_hash := ""          # 模板/配置资源校验和
var generator_version := ""    # 语义化版本或 git commit
var parameters: Dictionary = {}
var created_at: int

static func make(p_seed: int, params: Dictionary,
                 gen_ver: String, src_hash: String) -> SeedManager:
    var sm := SeedManager.new()
    sm.seed = p_seed
    sm.parameters = params.duplicate(true)
    sm.generator_version = gen_ver
    sm.source_hash = src_hash
    sm.created_at = Time.get_unix_time_from_system()
    return sm

func bind(rng: RandomNumberGenerator) -> void:
    rand_from_seed(seed)             # 用固定种子重置
```

⚠ **别用 `Time.get_unix_time_from_system()` 当种子然后指望复现** —— 那是每次都变的。

⚠ GDScript 的 `RandomNumberGenerator.seed` 对负值有引擎特定的转换规则。
跨平台复现时别自己做位运算/浮点变换后再当"同一输入"。

⚠ 生成产物要**记录生成参数、版本、校验和**，否则出 bug 时无法复现那一次。

### 分层噪声

`FastNoiseLite` 基础类型：`TYPE_SIMPLEX` / `TYPE_SIMPLEX_SMOOTH` / `TYPE_PERLIN` / `TYPE_VALUE` / `TYPE_VALUE_CUBIC` / `TYPE_CELLULAR`
分形类型：`FRACTAL_NONE` / `FRACTAL_FBM` / `FRACTAL_RIDGED` / `FRACTAL_PING_PONG`

| 场景 | 推荐 | 要验证 |
|---|---|---|
| 大陆/丘陵高度场 | Simplex + FBM | 极点/边界、海平面后验统计 |
| 高度图/凹凸贴图 | ValueCubic | 梯度过大与接缝 |
| 裂缝/山脊 | Ridged FBM | 值域漂移、过度锐化 |
| 生物群系斑块 | Cellular + domain warp | 输出**可能超过 1** |
| 河流/道路扰动 | 低频噪声做 domain warp | warp 幅度与坐标尺度一致 |

⚠ **多数噪声输出在 `[-1,1]`，但某些 cellular 算法会超过 1**。
做阈值判断、颜色映射前必须 clamp 或归一化。

⚠ `fractal_octaves` 默认 5、`gain` 默认 0.5、`lacunarity` 默认 2.0 ——
这些是引擎默认，**不是你项目的生产值**，要按效果调。

### BSP 房间生成（可直接抄）

```gdscript
class_name BspDungeon
extends RefCounted

class Rect2i:
    var x: int
    var y: int
    var w: int
    var h: int
    func _init(px: int, py: int, pw: int, ph: int) -> void:
        x = px; y = py; w = pw; h = ph
    func center() -> Vector2i:
        return Vector2i(x + w / 2, y + h / 2)

var _rng := RandomNumberGenerator.new()
var _rooms: Array[Rect2i] = []
var _corridors: Array = []

func generate(seed_val: int, size: Vector2i, min_room: int, depth: int) -> void:
    _rng.seed = seed_val & 0xFFFFFFFF
    _rooms = []
    _corridors = []
    _split(Rect2i.new(1, 1, size.x - 2, size.y - 2), depth, min_room)

func _split(r: Rect2i, depth: int, min_room: int) -> void:
    if depth <= 0 or (r.w < min_room * 2 and r.h < min_room * 2):
        # 叶子：在区域内随机放一个房间
        var rw: int = _rng.randi_range(min_room, maxi(min_room, r.w - 2))
        var rh: int = _rng.randi_range(min_room, maxi(min_room, r.h - 2))
        var rx: int = r.x + _rng.randi_range(0, maxi(0, r.w - rw - 1))
        var ry: int = r.y + _rng.randi_range(0, maxi(0, r.h - rh - 1))
        _rooms.push_back(Rect2i.new(rx, ry, rw, rh))
        return
    var horizontal: bool = _rng.randf() < 0.5 if r.w < r.h else false
    if horizontal:
        var cut: int = _rng.randi_range(min_room, r.h - min_room)
        _split(Rect2i.new(r.x, r.y, r.w, cut), depth - 1, min_room)
        _split(Rect2i.new(r.x, r.y + cut, r.w, r.h - cut), depth - 1, min_room)
    else:
        var cut: int = _rng.randi_range(min_room, r.w - min_room)
        _split(Rect2i.new(r.x, r.y, cut, r.h), depth - 1, min_room)
        _split(Rect2i.new(r.x + cut, r.y, r.w - cut, r.h), depth - 1, min_room)

## 连通性校验：生成完必须跑
func is_connected() -> bool:
    if _rooms.is_empty():
        return false
    # 用走廊连接相邻房间后做并查集
    var parent: Array = []
    parent.resize(_rooms.size())
    for i in _rooms.size():
        parent[i] = i
    for c in _corridors:
        _union(parent, int(c[0]), int(c[1]))
    var root: int = _find(parent, 0)
    for i in _rooms.size():
        if _find(parent, i) != root:
            return false
    return true

func _find(parent: Array, x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x

func _union(parent: Array, a: int, b: int) -> void:
    var ra: int = _find(parent, a)
    var rb: int = _find(parent, b)
    if ra != rb:
        parent[ra] = rb
```

⚠ **必须做连通性校验**。BSP 分割可能产生无法到达的房间，
测试时没抽到不代表上线不会抽到。

⚠ 生成失败要**重试 + 降级**，不能直接给玩家一个不可通关的关卡。

### 分 pass 与统计输出

```
pass 1: 地形高度
pass 2: 房间/区域划分
pass 3: 连通性
pass 4: 资源/怪物布点
pass 5: 校验（可达性 / 出口存在 / 无死路）
```

每 pass 输出统计：房间数、路径长度、死路数、资源密度、不可解情况。
这些数字异常时通常意味着生成参数错了。

⚠ 不要把生成结果存成**不可追踪的二进制或一次性场景** ——
那样出问题时无法复现也无法测试。

## 二、编辑器插件

### `@tool` vs `EditorPlugin`

| | 用途 |
|---|---|
| `@tool` | 让脚本在编辑器里执行。适合自定义节点预览、轻量校验 |
| `EditorPlugin` | 插件生命周期（`_enter_tree`/`_exit_tree`）。注册 dock、菜单、导入器、Inspector |

| 需求 | 机制 |
|---|---|
| 视口实时预览 | `@tool` + `Engine.is_editor_hint()` |
| 菜单/面板/扩展点 | `EditorPlugin` |
| 新文件类型导入 | `EditorImportPlugin` |
| 导入场景后批量改 | `EditorScenePostImport` |
| 自定义属性 UI | `EditorInspectorPlugin` |
| 编辑器撤销 | `EditorUndoRedoManager` |

### 最小可用插件

```ini
; res://addons/my_tool/plugin.cfg
[plugin]
name="My Tool"
description="..."
author="..."
version="0.1.0"
script="my_tool_plugin.gd"
```

```gdscript
# my_tool_plugin.gd
@tool
extends EditorPlugin

var _dock: Control

func _enter_tree() -> void:
    _dock = preload("res://addons/my_tool/dock.tscn").instantiate()
    add_control_to_dock(EditorPlugin.DOCK_SLOT_BOTTOM, _dock)

func _exit_tree() -> void:
    if _dock:
        remove_control_from_docks(_dock)
        _dock.queue_free()
        _dock = null
```

⚠ **进入与退出必须镜像对称**。忘记 `remove_control_from_docks` + `queue_free` 会泄漏。

⚠ `plugin.cfg` 的 `enabled` 建议默认 `false` —— 别让团队打开项目就自动执行未知编辑器逻辑。

⚠ Inspector 插件禁用时要 `remove_inspector_plugin()`。

⚠ **插件不能污染场景文件**。`@tool` 脚本里在 `_ready`/`_process` 改节点，
改动会被存进 `.tscn`。用 `Engine.is_editor_hint()` 严格隔离。

### 撤销/重做

```gdscript
var _undo := get_undo_redo()

func do_change(obj: Object, prop: String, from, to) -> void:
    _undo.create_action("修改属性")
    _undo.add_do_property(obj, prop, to)
    _undo.add_undo_property(obj, prop, from)
    _undo.commit_action()
```

⚠ 编辑器里改东西**必须走 UndoRedo**，否则用户 Ctrl+Z 无效 —— 这是插件最常见的差评来源。

## 三、资源导入管线

**三层隔离**：

```
原始文件（.blend/.psd/.wav）  ← 进版本库
      ↓ 导入规则
导入产物（.import / .godot/）  ← 不进版本库
      ↓
运行时资源                     ← 被引擎加载
```

### 统一规则

| 类型 | 规则 |
|---|---|
| 纹理 | 尺寸、压缩（VRAM Compressed）、mipmaps、法线检测 |
| 模型 | 单位、朝向、缩放、骨骼命名、碰撞生成 |
| 动画 | 烘焙、循环、压缩 |
| 音频 | 采样率、位深、循环点 |

### 第三方资源入库前检查

```gdscript
# 检查器：拒绝超大尺寸 / 重复 / 未知脚本
func check_asset(path: String) -> Array[String]:
    var problems: Array[String] = []
    var img := Image.new()
    if img.load(path) == OK:
        if img.get_width() > 4096 or img.get_height() > 4096:
            problems.push_back("纹理超过 4096，会吃大量显存")
    if path.get_extension() == "gd" and _has_unknown_script(path):
        problems.push_back("含未知脚本，需人工审查")
    return problems
```

⚠ **第三方资源是最大的安全与体积风险来源**。
未知脚本会随场景一起执行，超大资源会撑爆包体和显存。

⚠ 许可证要记录。用了不能商用的素材等于项目定时炸弹。

## 四、XR / VR

⚠ **本节部分内容版本敏感**，标注"待核对"的必须在目标 Godot 版本和头显上实测。

### 节点拓扑

```
XROrigin3D              ← 游戏空间中心（追踪锚点）
├── XRCamera3D          ← 头显立体相机
├── LeftController      ← XRController3D
└── RightController     ← XRController3D
```

```gdscript
func _ready() -> void:
    if Engine.is_editor_hint():
        return
    var xr := XRServer.find_interface("OpenXR")
    if xr == null:
        push_error("未找到 OpenXR 接口")
        return
    if not xr.is_initialized():
        if not xr.initialize():
            push_error("OpenXR 初始化失败")
            return
```

⚠ 项目设置里也要启用 XR > OpenXR，**代码不替代项目配置**。

⚠ 相机的很多属性在立体渲染下会被头显覆盖（只有近/远裁剪面较可靠）。
**不要把角色逻辑挂在头显上**。

⚠ 追踪线程的延迟会让脚本读到的相机位置略旧 —— 别用它做精确的碰撞判定。

### 性能是硬约束

VR **必须稳定 90fps**（或设备刷新率），掉帧直接导致晕动症。

| 预算项 | 目标 |
|---|---|
| 帧时间 | ≤ 11ms（90fps） |
| DrawCall | 远低于桌面，通常 ≤ 几百 |
| 双眼渲染 | 所有开销 ×2 |

- 分辨率/渲染缩放是最大的性能杠杆
- MSAA、Foveation（若平台支持）要按目标头显调
- 兼容性渲染器 vs Forward+ 的差异要实测

⚠ **先满足刷新率，再谈画质**。在 VR 里"好看但晕"是负分。

### 移动与舒适度

| 方式 | 优点 | 风险 |
|---|---|---|
| 瞬移 | 几乎不晕 | 破坏沉浸感 |
| 平滑移动 | 沉浸 | 高晕动风险，要加隧道视野（vignette） |

⚠ 至少提供一种"无晕"选项。晕动症不是玩家能"适应"的东西。

⚠ UI 要放在**舒适阅读距离**（约 1-3 米），不能贴在脸上或太远。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/advanced-topics.md`

