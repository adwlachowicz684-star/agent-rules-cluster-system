# Godot 4.x 弹幕射击（Bullet Hell / SHMUP）

弹幕的核心是**"数据化弹幕 + 批量更新 + GPU 合批"**，
不是 `RigidBody2D`，更不是"每颗子弹一个脚本"。

## 0. 四层分离

| 层 | 职责 |
|---|---|
| **数据层** | `BulletData`：pos / vel / accel / radius / lifetime |
| **世界层** | `BulletWorld` 定长数组 + 活跃索引 |
| **图案层** | `BulletPattern` Resource + `PatternRunner` 时间轴 |
| **碰撞层** | 只查玩家判定点；擦弹独立算 |

⚠ **每颗子弹都挂 `Area2D` 是本类游戏最典型的死法** ——
千颗子弹千个 `Area2D` = 千个每物理帧回调 + 碰撞形状管理。

## 1. MultiMesh 定容量，运行时只改可见数

```gdscript
var mm := MultiMesh.new()
mm.transform_format = MultiMesh.TRANSFORM_2D
mm.mesh = _quad_mesh
mm.instance_count = MAX_BULLETS      # 加载时一次定
mm.visible_instance_count = 0        # 运行时只改这个
```

⚠ **`instance_count` 设置会清空并重分配整个 buffer** ——
每帧 `instance_count = n` 完全抵消合批收益。
**正确**：加载时一次定到上限，运行时只改 `visible_instance_count`
与每实例 transform，并维护空闲链表做对象池。

```gdscript
func spawn(pos: Vector2, vel: Vector2) -> void:
    var i := _free_list.pop_back()
    _pos[i] = pos; _vel[i] = vel
    _active.append(i)

func flush() -> void:
    mm.visible_instance_count = _active.size()
    for k in _active.size():
        var t := Transform2D(0.0, _pos[k])
        # ⛔ transform_format 为 TRANSFORM_2D 时要用 set_instance_transform_2d()，
        #    传 Transform2D 给 set_instance_transform()（3D 版）是类型错。
        mm.set_instance_transform_2d(k, t)
```

## 2. 碰撞只查玩家判定点

```gdscript
func _physics_process(_d: float) -> void:
    var q := PhysicsPointQueryParameters2D.new()
    q.position = player.hit_point        # 判定点，不是精灵中心
    q.collision_mask = BULLET_LAYER
    var hits := get_world_2d().direct_space_state.intersect_point(q, 64)
```

⚠ **不要用玩家 `Area2D` 检测每颗子弹进入** ——
几千次 enter/exit 信号分发 + 每颗一颗的碰撞形状是双重浪费。

⚠ **`intersect_point` 默认 `max_results = 32`** ——
密集弹幕下会被截断。要么提高上限，要么先用距离批量粗筛再精查。

⚠ **参与判定的形状必须是 solid shape** ——
官方明确：**Segments build mode 的 `CollisionPolygon2D`** 与
**`ConcavePolygonShape2D`** 都不是 solid shape，
`intersect_point` 不会检测到它们。
⛔ 表现为"子弹明明在判定点上却永远判定不到"，
而形状在编辑器里看得到、面积也正确，⛔ 排查时不会怀疑形状类型。
弹幕一律用 `CircleShape2D` / `RectangleShape2D` 这类实心形状。

## 3. 判定点与擦弹是两个半径

```gdscript
const HIT_RADIUS := 3.0     # 判定点很小，要单独渲染/发光提示
const GRAZE_RADIUS := 24.0  # 擦弹，过一次记一次
```

⚠ **判定点不等于精灵中心/视觉中心** ——
常见 2–4 px，玩家要能看见它。擦弹与命中不可混。

## 4. 弹幕逻辑用固定步长，不是 delta

```gdscript
const LOGIC_STEP := 1.0 / 60.0
var _acc := 0.0

func _process(delta: float) -> void:
    _acc += delta
    while _acc >= LOGIC_STEP:
        _step(LOGIC_STEP)
        _acc -= LOGIC_STEP
```

⚠ **不要写在 `_physics_process` 里用 `delta`** ——
弹幕图案对帧率敏感且要求确定性回放。
否则"60Hz 与 144Hz 下弹幕密度不同"。

## 5. 图案是数据，不是代码

```gdscript
# bullet_pattern.gd
class_name BulletPattern extends Resource

@export var emitters: Array[EmitterSpec] = []
@export var timeline: Array[EmitCommand] = []   # time / emitter_id / params
```

⚠ **`PatternRunner` 按时间表驱动发射器** ——
图案可复用、可调参、可做编辑器预览，不要写成一串 `for` 循环。

## 6. 性能三档

| 规模 | 方案 |
|---|---|
| 数百–千余颗 | GDScript + `PackedFloat32Array` + `@onready` 缓存 + 固定步长 |
| 千–数千颗 | C# `BulletWorld` 值类型数组/结构体 |
| 数千–上万颗 | GDExtension，SoA 布局 + 分块 SIMD |

⚠ **GDScript 里每帧遍历 3000 颗子弹更新 `Vector2` 数组通常撑不住** ——
先用 `PackedFloat32Array` 扁平存（x,y,vx,vy 交错），避免对象开销。

## 7. 渲染与重绘

⚠ **每帧改 `set_instance_color` 仍要走缓冲区** ——
同屏单色弹幕用一张纹理 + shader 参数，按发射器分组，避免逐实例刷。

⚠ **CanvasItem 不需要每帧 `queue_redraw()`** ——
把背景、UI、玩家、子弹分到独立 CanvasLayer，只让需要的节点重绘。

## 8. ⛔ 官方口径：定容量与插值的三条硬约束

**① `use_colors` / `use_custom_data` 只能在 `instance_count` 为 0 时设置。**
官方原话：*"Can only be set when instance_count is 0 or less."*
⛔ 先定 `instance_count = MAX_BULLETS` 再开 `use_colors = true` ——
逐实例颜色**静默不生效**，不报错，只是所有子弹都是同一个颜色。

**② `visible_instance_count` 默认是 `-1`，含义是"画出全部实例"。**
⛔ 定容量后忘记显式设为 `0` —— 屏幕上会立刻出现
`MAX_BULLETS` 个 transform 未初始化的实例，**全部堆在原点**，
而 `instance_count`、`mesh`、纹理全都检查无误。

**③ 子弹必须用"移动起始"三步，顺序不能颠倒**（官方原文举的例子就是 bullet）：

1. 设置初始 transform
2. 调 `reset_instance_physics_interpolation()`
3. **立即**设置第一个 tick 之后的 transform

官方明确：*"Make sure you set the transform and call reset_physics_interpolation()
in the correct order as shown above, otherwise you will see unwanted streaking."*

⛔ 对象池复用槽位时这条尤其致命 —— 该槽位上一帧还在屏幕另一头，
插值会让它从那里滑过来，表现为"子弹凭空拖一条线"。

## 9. ⛔ 固定步长累加器必须有上限

`Engine.max_physics_steps_per_frame` 默认 `8`，官方说明它的存在就是为了
避免 *"spiral of death"*（昂贵的物理模拟触发更多模拟，无限循环）。

⛔ 自写累加器若不设上限，卡顿一次后会越追越慢、直至卡死；
表现为"偶尔掉一次帧后游戏就再也回不到正常速度"。

配套：官方建议 `physics_ticks_per_second` **不要超过 240** ——
超过之后渲染帧率一旦低于 30 FPS，游戏会**整体变慢**
（即使物理计算里一直正确地使用 `delta`）。

## 10. 流程：按什么顺序做

> → `flow/godot/bullethell/00-域流程总览.md`

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-bullet-hell.md`
