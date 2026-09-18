# Godot 4.x 渲染进阶：XR 交互 / LOD / 着色器预热

⚠ **本节大量内容版本敏感**。标注"待核对"的必须在目标 Godot 版本和设备上实测。
写进生产代码前先验证节点名和属性是否存在。

## 一、XR 进阶交互

### 手部追踪（4.4）

```
XRHandTracker     继承 XRPositionalTracker < XRTracker < RefCounted < Object
                  保存手部骨骼、半径、关节标志、跟踪源
XRHandModifier3D  继承 SkeletonModifier3D，驱动 Skeleton3D
                  hand_tracker 默认 /user/hand_tracker/left
                  bone_update: BONE_UPDATE_FULL 或 BONE_UPDATE_ROTATION_ONLY
```

常用查询（4.4）：

```gdscript
tracker.get_hand_joint_transform(joint)
tracker.get_hand_joint_linear_velocity(joint)
tracker.get_hand_joint_angular_velocity(joint)
tracker.has_tracking_data          # 只说明"当前有数据"，不表示每根手指都高精度
```

⚠ **4.3 的 `OpenXRHand` 已弃用**，新代码用 `XRHandModifier3D`。

⚠ `has_tracking_data` 为真**不代表手指精度够**。
`HAND_TRACKING_SOURCE_CONTROLLER` 意味着关节是从控制器**推断**的，不是真实光学追踪。

⚠ **有 `get_hand_joint_linear_velocity()` 不等于设备真会返回速度**。
Quest / Vision / SteamVR 各运行时行为不同。要同时维护
「追踪器速度 / 关节速度 / 差分位置速度」三套，任一有效才用。

**状态机要拆两层**：

```
TRACKER_ABSENT → TRACKER_PRESENT → HAND_VALID → GRASP_STABLE
```

⚠ tracker 可能先存在、之后才拿到光学手数据。
**手部模型不要一出现就吸附到抓取点** —— 会看到模型乱飞。

手势识别（pinch / poke / aim / grasp）走官方"手部交互配置文件"扩展，
**不要自己拟合手指夹角**。是否生效取决于运行时，需要实测。

### 抓握：Area3D + 6DOF 约束 + 速度估计

稳妥结构：

```
XRController3D
└── GrabArea (Area3D)        ← 抓取体积，维护候选列表
```

抓握确认后用 `Generic6DOFJoint3D` 把 `RigidBody3D` 约束到控制器抓取锚点。
**抓取瞬间冻结物理速度、释放时写入速度** —— 否则刚体会"锁在世界坐标"乱飞。

⚠ **`XRController3D` 没有官方速度 API**。
它只有 `get_float()` / `get_vector2()` / `is_button_pressed()` 等输入便利方法。
要自己缓存上一物理帧的世界变换来估计速度。

```gdscript
extends XRController3D
class_name GrabController

signal grabbed(body: RigidBody3D)
signal released(body: RigidBody3D)

@export var grab_action: StringName = &"grab"
@export var grab_anchor: Node3D
@export var sample_count: int = 6

var _held: RigidBody3D
var _joint: Generic6DOFJoint3D
var _prev_transform := Transform3D()
var _has_prev := false
var _vel_samples: Array[Vector3] = []
var _angular_samples: Array[Vector3] = []
var _candidates: Array[RigidBody3D] = []

@onready var _area: Area3D = $GrabArea

func _physics_process(delta: float) -> void:
    if delta > 0.0:
        _sample_velocity(delta)

## 用最近 N 个样本平均估计速度，避免抖动尖峰
func _sample_velocity(delta: float) -> void:
    var now := global_transform
    if _has_prev:
        var dp := now.origin - _prev_transform.origin
        _vel_samples.push_back(dp / delta)
        if _vel_samples.size() > sample_count:
            _vel_samples.pop_front()
    _prev_transform = now
    _has_prev = true

func _linear_velocity() -> Vector3:
    if _vel_samples.is_empty():
        return Vector3.ZERO
    var sum := Vector3.ZERO
    for v in _vel_samples:
        sum += v
    return sum / _vel_samples.size()

func grab() -> void:
    if _held or _candidates.is_empty():
        return
    var body := _candidates[0]
    # 冻结物理，避免约束建立瞬间弹飞
    body.linear_velocity = Vector3.ZERO
    body.angular_velocity = Vector3.ZERO
    _joint = Generic6DOFJoint3D.new()
    get_tree().current_scene.add_child(_joint)
    _joint.global_transform = grab_anchor.global_transform
    _joint.node_a = _joint.get_path_to(self)
    _joint.node_b = body.get_path()
    _held = body
    grabbed.emit(body)

func release() -> void:
    if not _held:
        return
    var body := _held
    if _joint:
        _joint.queue_free()
        _joint = null
    _held = null
    # 释放时把估计的速度写回去
    body.linear_velocity = _linear_velocity()
    released.emit(body)
```

⚠ **直接每帧 `global_transform.origin - prev.origin` 会产生尖峰**
（大抖动、重投影、120Hz 头显）。必须对最近若干样本做平均或时间衰减。

⚠ 抓握不要只改 `owner` —— 物理所有权、父子关系、约束是三件事。

### 世界空间 UI

把 Control 挂到 3D 空间要用 `SubViewport` + `SubViewportContainer`，
注意分辨率和可读性：

- UI 放在**舒适阅读距离**（约 1–3 米），不能贴脸也不能太远
- `SubViewport` 尺寸要够，否则文字糊
- 更新模式按需（`UPDATE_ALWAYS` 很贵）

⚠ 世界空间 UI 是**每帧渲染的额外视口**，会显著增加开销。

### 传送移动

抛物线射线指示落点。⚠ 待核对：是否存在 `ArcCast3D` 节点 · 验证：4.7.2 编辑器节点搜索框输入 ArcCast3D
若无，用多段 `RayCast3D` 或自己算抛物线采样点。

⚠ **至少提供一种无晕选项**（传送）。只有平滑移动会让部分玩家无法游玩。

### 性能是硬约束

VR **必须稳定 90fps**（或设备刷新率）。掉帧直接导致晕动症。

| 预算项 | 目标 |
|---|---|
| 帧时间 | ≤ 11ms（90fps） |
| 双眼渲染 | 所有开销 ×2 |
| 分辨率/渲染缩放 | 最大的性能杠杆 |

⚠ **先满足刷新率，再谈画质**。VR 里"好看但晕"是负分。
性能预算**没有官方统一 draw call / 三角形上限**，必须按目标头显实测。

## 二、LOD 分层

### 三种 LOD 是互补的，不是选一个

| 机制 | 核心 | 适用 |
|---|---|---|
| 导入期自动网格 LOD | Import 设置 + meshoptimizer | 大量外部资产、植被、静态道具 |
| 自动选择 | `mesh_lod_threshold` / `lod_bias` | 不想逐对象写距离逻辑 |
| 手动 HLOD | `visibility_range_begin/end/margin/fade_mode` | 美术做近中远模型、LOD 簇 |
| 灯光 LOD | `distance_fade_begin/length/shadow` | 大量点光/聚光及阴影 |

**自动网格 LOD**（导入时生成）：
glTF / `.blend` / Collada / FBX 默认自动生成简化网格；
**OBJ 作为单个网格导入时不会自动生成**（需改 Import As 为 Scene 并重新导入）。

⚠ **自动 LOD 不是"开一次全局有效"**：OBJ 默认不生成，复杂蒙皮网格可能异常，
生成占用导入时间。出问题的资产应在 Import dock 禁用 LOD 生成，
**不是删运行时节点**。

⚠ 自动 LOD 选择基于**屏幕空间覆盖度**（考虑 FOV 和分辨率），
不是简单距离。远处小资产可能因为屏幕占比高而保持高细节 ——
**不能按"远 30 米切一级"估算收益**。

⚠ 切换 LOD 可能改变材质批次（不同 LOD 用不同材质/表面数），
**不能只看面数下降**。

⚠ 自动 LOD 会生成阴影网格，但 HLOD 每层是独立 `GeometryInstance3D`，
**阴影代理要单独管理**。

### 手动 HLOD 用可见范围

`GeometryInstance3D` 的属性（官方确认）：

```gdscript
visibility_range_begin          # 相机比这更近时隐藏
visibility_range_begin_margin   # 滞后 / 过渡距离
visibility_range_end            # 相机比这更远时隐藏
visibility_range_end_margin
visibility_range_fade_mode      # 淡入淡出模式
```

⚠ **AABB 会欺骗距离判断**。用引擎内置的 `visibility_range_*`
比自己每帧算"相机到 AABB 中心距离"更可靠。

⚠ `mesh_lod_threshold` > 1.0 更早切低细节；
`lod_bias` > 1.0 延后切换（更高质量 / 更低性能），< 1.0 更早切换。
`ReflectionProbe` 有自己的阈值，对 "Always" 更新模式很重要。

### 大世界分块

```gdscript
# 按玩家位置加载/卸载 chunk
class_name ChunkStreamer
extends Node3D

@export var chunk_size := 64.0
@export var view_distance := 3          # 半径几个 chunk
var _loaded: Dictionary = {}            # Vector2i -> Node

func _process(_d: float) -> void:
    var c := _chunk_of(global_position)
    var want := {}
    for dx in range(-view_distance, view_distance + 1):
        for dz in range(-view_distance, view_distance + 1):
            want[Vector2i(c.x + dx, c.y + dz)] = true
    for k in _loaded.keys():
        if not want.has(k):
            _loaded[k].queue_free()
            _loaded.erase(k)
    for k in want:
        if not _loaded.has(k):
            _loaded[k] = _load_chunk(k)

func _chunk_of(pos: Vector3) -> Vector2i:
    return Vector2i(int(pos.x / chunk_size), int(pos.z / chunk_size))

func _load_chunk(c: Vector2i) -> Node:
    var path := "res://chunks/chunk_%d_%d.tscn" % [c.x, c.y]
    if not ResourceLoader.exists(path):
        return Node.new()
    return load(path).instantiate()
```

⚠ 远处 chunk 要**关阴影投射** —— 阴影是距离无关的大开销。

## 三、着色器变体预热

### 卡顿来自管线，不只是 shader 文本

管线 = 着色器代码 + 光照 + 阴影 + 渲染功能 + 后端状态的组合。
**一个 shader 可能对应许多管线**。驱动可能缓存，但驱动更新会清空缓存。

传统路径：对象首次进入视野才创建所需管线 → **首次出现卡顿**。

4.4 起用 ubershader（运行时可切换特化常量的通用版本），
先预编译它，后台再生成更优化的专用版本。

⚠ **加载 `.tres` 材质 ≠ 完成管线编译**。
资源进内存与 GPU 管线生成是两个阶段。**不能把 `load()` 返回当预热完成**。

⚠ **本次核对未找到** `RenderingServer.warm_up_shaders()` /
`create_shader()` / `precompile_all_pipelines()` 这类公开 API。
**这些名字都不要用** —— 标待核对。

### 稳妥的预热策略

最可靠的做法是**让 RenderingServer 真的看见**网格 + 材质 + 光照组合：

```gdscript
extends Node
class_name ShaderWarmupManager

signal progress(loaded: int, total: int)
signal completed

@export var material_resources: Array[Material] = []
@export var scene_paths: Array[String] = []
@export var warmup_frames := 4

var _root: Node3D
var _done := false

func start() -> void:
    _root = Node3D.new()
    _root.visible = true
    add_child(_root)
    var total := material_resources.size() + scene_paths.size()
    var n := 0
    # 1) 实例化代表性场景（要真的加入场景树）
    for p in scene_paths:
        if ResourceLoader.exists(p):
            var inst := load(p).instantiate()
            _root.add_child(inst)
        n += 1
        progress.emit(n, total)
    # 2) 把材质贴到可见的 MeshInstance3D 上
    for m in material_resources:
        var mi := MeshInstance3D.new()
        mi.mesh = SphereMesh.new()
        mi.material_override = m
        _root.add_child(mi)
        n += 1
        progress.emit(n, total)
    # 3) 至少渲染若干帧，让后端生成管线
    for i in warmup_frames:
        await get_tree().process_frame
    _finish()

func _finish() -> void:
    _done = true
    # 预热根可以保留但隐藏，或释放
    if is_instance_valid(_root):
        _root.visible = false
    completed.emit()
```

⚠ **隐藏 ≠ 提供编译证据**。
`visibility_range` 外、不可见图层、camera cull mask 排除的对象
**不提供完整编译证据**。对动态添加的效果，保留隐藏版本让它被看见。

⚠ **别依赖固定帧数**。后台编译线程、GPU 队列、驱动异步都会影响。
没有公开编译回调时，用保守帧数（2–4 帧）并持续报告进度。

⚠ 动态生成/加载的资源（玩家自定义皮肤、DLC 材质）
**必须单独预热**，它们不在启动清单里。

## 常见漏写

| 域 | 漏写 | 后果 |
|---|---|---|
| XR | 手部模型一出现就吸附 | 模型乱飞 |
| XR | 用单帧差分算控制器速度 | 抖动尖峰，抓取物乱飞 |
| XR | 抓握只改 owner | 刚体锁死世界坐标 |
| XR | 只有平滑移动 | 部分玩家晕到无法游玩 |
| XR | 掉帧 | 晕动症，比难看严重得多 |
| LOD | 以为 OBJ 也有自动 LOD | 该资产从不降面 |
| LOD | 只按距离估算收益 | 实际收益与预期不符 |
| LOD | HLOD 不关远处阴影 | 阴影开销没降 |
| LOD | 大世界不分块 | 内存爆、加载卡顿 |
| Shader | `load()` 当预热完成 | 首次出现仍卡顿 |
| Shader | 只 instantiate 不渲染 | 不触发管线生成 |
| Shader | 动态资源不预热 | 玩家换皮肤时卡一下 |

## 上线前检查

- [ ] 手部追踪在目标设备上实测过，有降级路径
- [ ] 抓握速度估计用了多样本平均
- [ ] 至少有一种无晕移动方式
- [ ] 目标头显上实测帧时间达标（不是桌面猜的）
- [ ] 大世界分块且远处关阴影
- [ ] 所有动态材质有预热路径
- [ ] 预热期间有进度反馈，不是黑屏
- [ ] 所有"待核对"项已在目标版本上验证
