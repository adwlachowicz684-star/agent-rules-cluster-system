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
        mm.set_instance_transform(k, t)
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

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-bullet-hell.md`
