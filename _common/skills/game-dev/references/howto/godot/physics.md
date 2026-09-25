# Godot 4.x 物理进阶

角色移动的基础在 `character.md`。本文件覆盖碰撞检测、射线、区域触发、刚体施力、移动平台。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/physics.md`
> **流程层（按什么顺序做）** → `flow/godot/physics/`

## 0. 先定：物理引擎与刻度

⚠ **这一节要在写任何物理代码之前定完。** 后面所有参数（质量、力、速度）
都在这个刻度上才有意义；⛔ 刻度没定就调参，等于在流动的沙上量尺寸。

### 0.1 ⚠ 3D 物理引擎：4.6 起新项目默认 Jolt

官方口径：Jolt 在 4.4 加入作为替代引擎，**4.6 起新创建的项目默认使用 Jolt**
（变更见 `physics/3d/physics_engine`）。

⛔ **切换后必须点 Save & Restart** —— 只保存不重启，
编辑器里预览和运行时**仍在用旧引擎**。

⚠ 现有项目切换引擎**会改变物理行为**，
官方建议先在分支里测，⛔ 不要在主干直接切。

### 0.2 ⛔ Jolt 与 Godot Physics 的三处语义差异

切换引擎后"参数没变但表现变了"，基本都在这三条里：

**① 单体关节的 `node_a` / `node_b` 语义相反。**

两个 body 的关节可以只指定一个（另一个视为"世界"）。
Godot Physics 一律当作你填的是 `node_a`，而 **Jolt 当作 `node_b`**、用 `node_a` 表示世界。

⛔ 后果是**限位被反转**（inverted limits），
表现为关节转到奇怪的角度卡住，而参数面板上看着完全正确。

兼容开关：`Physics > Jolt Physics 3D > Joints > World Node`。

**② 碰撞边距（convex radius）语义不同。**

Godot Physics **根本不用** `Shape3D.margin`。
Jolt 则是**先缩小形状、再加壳**——轮廓同样被磨圆，但尺寸不增大。

⚠ 小形状用默认 margin 会有问题，官方为此给了
`Physics > Jolt Physics 3D > Collisions > Collision Margin Fraction`
（乘以形状 AABB 最短轴算出实际 margin，原 `margin` 退化为上限）。

ⓘ 官方提示：调太小（含 0.0）也会导致奇怪碰撞结果，一般不建议。

**③ Baumgarte 稳定化只作用于位置。**

Godot Physics 里它像弹簧——物体会**加速并过冲**，彻底分离。
Jolt 只修正位置、不修正速度。

ⓘ 表现为"堆叠抖动"在两个引擎下的**观感完全不同**，
调参经验不能平移。

另外：Jolt 不支持部分关节的 soft limit 属性，
设成非默认值会**发 warning**（`PinJoint3D.bias/damping/impulse_clamp`、
`HingeJoint3D.bias/softness/relaxation` 等）。

### 0.3 物理 tick rate

默认 60。官方建议提高时取 **60 的倍数**（120 / 180 / 240），
这样在大多数显示器上观感平滑。

⚠ 提高 TPS 是下面**多条稳定性问题的通用解法**
（穿透、堆叠、薄物体抖动、载具高速），
⛔ 但代价是 CPU，移动端/网页未必可行。

### 0.4 物理插值（4.4+）

开关：`Project Settings > Physics > Common > Physics Interpolation`。

⛔ **传送对象后必须调 `reset_physics_interpolation()`**，否则出现拖影
（官方原话：*"you don't want a smooth motion between where the object was … you want an instantaneous move"*）。

```gdscript
# 立定起步（玩家出生）：设 transform → 重置
global_position = spawn_point
reset_physics_interpolation()

# 移动起步（子弹）：设 transform → 重置 → 再设"一 tick 后"的预期位置
# ⓘ 顺序反了会拖影，官方明确要求按此顺序
```

⚠ 三条边界：

- ⛔ **开启插值后，不要在物理 tick 之外设置 transform**
  （官方会在编辑器里尝试告警，但是软规则）
- ⓘ **2D 首次入树会自动 reset，3D 不会** —— 3D 全靠手动
- ⓘ 3D 按**全局 transform** 逐节点独立插值（可设 `physics_interpolation_mode`
  为 On/Off/Inherited）；2D 按**局部 transform**，子节点会继承父节点的插值

ⓘ **2D 只有 `CPUParticles2D` 支持插值，`GPUParticles2D` 不插值**；
`get_global_transform_interpolated()` 目前只有 3D 有。

### 0.5 ⓘ 官方推荐的调试技巧：临时把 TPS 降到 10

官方原话建议临时设为 **10 TPS** 来测插值：
此时游戏"可能跑不好"，但**哪里该调 `reset_physics_interpolation()`、
哪里该自己做插值**会一眼看出来。

⛔ 这是本域最省事的一条自检手段——
正常 60 TPS 下这些问题的拖影只有 1 帧，肉眼根本抓不到。

## 1. 射线检测

### RayCast 节点（持续检测，如地面探测）

```gdscript
@onready var _ground_ray: RayCast2D = $GroundRay

func _ready() -> void:
    _ground_ray.enabled = true
    _ground_ray.target_position = Vector2(0, 20)   # 相对于节点向下 20px

func is_grounded() -> bool:
    return _ground_ray.is_colliding()
```

⚠ **改了 `target_position` 后同帧读取还是旧值**，必须手动刷新（审查 GD23）：

```gdscript
func check_at(dir: Vector2) -> bool:
    _ground_ray.target_position = dir * 100
    _ground_ray.force_raycast_update()      # 不调这行读的是上一帧缓存
    return _ground_ray.is_colliding()
```

### 代码射线（一次性查询）

4.x 用**参数对象**，不是 3.x 的位置参数列表：

```gdscript
func raycast_hit(from: Vector2, to: Vector2) -> Dictionary:
    var space := get_world_2d().direct_space_state
    var params := PhysicsRayQueryParameters2D.create(from, to)
    params.exclude = [self]                  # 排除自己
    params.collision_mask = Layers.WORLD     # 只查某一层
    params.collide_with_areas = false
    var result := space.intersect_ray(params)
    # 未命中返回空字典，不是 null
    if result.is_empty():
        return {}
    return result        # {collider, position, normal, rid, shape}

# 3D 版本
func raycast_hit_3d(from: Vector3, to: Vector3) -> Dictionary:
    var space := get_world_3d().direct_space_state
    var params := PhysicsRayQueryParameters3D.create(from, to)
    return space.intersect_ray(params)
```

⚠ 4.x 里 `intersect_ray(from, to, ...)` 这种位置参数写法是 **3.x 残留**（审查 GD24）。

### 其它空间查询

```gdscript
var space := get_world_2d().direct_space_state

# 形状查询（范围检测/爆炸）
var sp := PhysicsShapeQueryParameters2D.new()
sp.shape = CircleShape2D.new()
sp.shape.radius = 50.0
sp.transform = Transform2D(0, position)
var hits := space.intersect_shape(sp, 32)     # 第二参数是 max_results，默认 32

# 点查询（某点有什么）
var pp := PhysicsPointQueryParameters2D.new()
pp.position = mouse_pos
pp.collision_mask = Layers.ENEMY
var points := space.intersect_point(pp, 32)
```

⚠ `intersect_shape` / `intersect_point` 的 `max_results` 默认 32 ——
范围大时会**静默截断**，不是漏报 bug 而是参数太小。

**爆炸伤害示例**：

```gdscript
func explode(center: Vector2, radius: float, damage: int) -> void:
    var sp := PhysicsShapeQueryParameters2D.new()
    var circle := CircleShape2D.new()
    circle.radius = radius
    sp.shape = circle
    sp.transform = Transform2D(0, center)
    sp.collision_mask = Layers.ENEMY | Layers.PLAYER
    for hit in space.intersect_shape(sp, 64):
        var body := hit.collider as Node
        if body.has_method("take_damage"):
            # 距离衰减
            var d := center.distance_to(body.global_position)
            var factor := 1.0 - clampf(d / radius, 0.0, 1.0)
            body.take_damage(int(damage * factor))
```

## 2. Area2D / Area3D：触发检测

```gdscript
# pickup.gd
extends Area2D

@export var item_id: String = "coin"

func _ready() -> void:
    monitoring = true                   # 我要检测别人（默认 true）
    monitorable = true                  # 别人能检测我（默认 true）
    body_entered.connect(_on_body_entered)

func _exit_tree() -> void:
    if body_entered.is_connected(_on_body_entered):
        body_entered.disconnect(_on_body_entered)

func _on_body_entered(body: Node2D) -> void:
    if body.is_in_group("player"):
        Events.item_collected.emit(item_id, 1)
        queue_free()
```

**信号一览**：

| 信号 | 触发 |
|---|---|
| `body_entered` / `body_exited` | 物理体进出 |
| `area_entered` / `area_exited` | 另一个 Area 进出 |
| `area_shape_entered` | 带形状信息（需要具体哪个 shape 时用） |

**主动查询**（不用信号）：

```gdscript
func get_enemies_in_range() -> Array[Node2D]:
    var result: Array[Node2D] = []
    for body in get_overlapping_bodies():
        if body.is_in_group("enemy"):
            result.append(body)
    return result
```

⚠ `get_overlapping_bodies()` 在**物理步期间**更新。在 `_process` 里刚移动完立刻查，
拿到的是上一帧的结果。要同帧准确就用信号或手动 `force_update`。

⚠ 刚体（RigidBody）的 `body_entered` 需要 `contact_monitor = true`
且 `max_contacts_reported > 0`，否则**信号永不触发**（审查 GD26）。

## 3. RigidBody：施力

```gdscript
@export var impulse_strength := 500.0

func kick(dir: Vector2) -> void:
    # 一次性冲击（踢一脚、爆炸推力）—— 只调一次
    apply_central_impulse(dir * impulse_strength)

func push_continuously(dir: Vector2) -> void:
    # 持续力（风扇、水流）—— 每个物理帧调
    apply_central_force(dir * 100.0)
```

| 方法 | 用途 | 调用频率 |
|---|---|---|
| `apply_central_impulse` | 瞬时冲量（作用于质心） | 一次 |
| `apply_impulse(impulse, position)` | 瞬时冲量（带作用点，产生旋转） | 一次 |
| `apply_central_force` | 持续力 | 每物理帧 |
| `apply_force(force, position)` | 持续力（带作用点） | 每物理帧 |
| `apply_torque_impulse` / `apply_torque` | 扭矩 | 对应 |

⚠ **impulse 每帧调 = 力被放大 60 倍**。持续效果用 force（审查 GD22）。

⚠ 直接写 `linear_velocity = x` 会**覆盖物理积分**（碰撞/摩擦失效）。
推动物体用施力，只有传送才直接改 `position`。

### 睡眠

```gdscript
can_sleep = true        # 静止后自动休眠，省 CPU（默认 true）
sleeping = false        # 手动唤醒

func _on_body_entered(_b: Node) -> void:
    sleeping = false    # 被撞时唤醒
```

## 4. 移动平台

⚠ **用 `AnimatableBody2D/3D`，不要用 `StaticBody`**。

StaticBody 移动是"传送" —— 不会把速度传给站在上面的角色，角色会滑落或被卡住。
AnimatableBody 会把运动估算成速度传递出去。

```gdscript
# moving_platform.gd
extends AnimatableBody2D

@export var travel := Vector2(200, 0)
@export var duration := 3.0

func _ready() -> void:
    sync_to_physics = true      # 关键：让移动与物理步同步，否则角色会抖
    var tw := create_tween()
    tw.set_loops(0)             # 无限循环
    tw.tween_property(self, "position", position + travel, duration)\
      .set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
    tw.tween_property(self, "position", position, duration)\
      .set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_IN_OUT)
    tw.bind_node(self)
```

⚠ `sync_to_physics = true` 必须设，否则平台移动与物理步不同步，站在上面的角色会抖动。

⚠ AnimatableBody **仍是 StaticBody 的子类** —— 它不会被玩家推动。
需要"可推动的箱子"用 RigidBody。

## 5. 物理回调选择

| 需求 | 放哪 |
|---|---|
| 移动、施力、碰撞查询 | `_physics_process(delta)` |
| 输入采样、动画、UI | `_process(delta)` |
| 一次性事件响应 | 信号 / `_unhandled_input` |

⚠ 物理逻辑放 `_process` —— 低帧率时步长变化，会抖动甚至穿模（审查 GD14）。
物理默认 60 tick，不保证每个渲染帧执行一次。

## 5.5 碰撞层与形状：位掩码与命名

`collision_layer`（我是谁）和 `collision_mask`（我能撞谁）是**位掩码**，
不是层号。第 N 层的值是 `1 << (N-1)`：

| 层 | 值 |
|---|---|
| 第 1 层 | `1` |
| 第 2 层 | `2` |
| 第 3 层 | `4` |
| 第 4 层 | `8` |

⛔ **第 3 层是 4，不是 3**。写 `collision_layer = 3` 表示"同时属于第 1 和第 2 层"，
是合法值但不是你要的，⛔ 且不报错。

✅ **先在项目设置里给层命名**（项目设置 → Layer Names → 2D/3D Physics），
再用常量而不是裸数字：

```gdscript
# layers.gd —— 与项目设置里的命名一一对应
class_name Layers

const PLAYER := 1 << 0      # 第 1 层
const ENEMY  := 1 << 1      # 第 2 层
const WORLD  := 1 << 2      # 第 3 层（值 = 4）
const ITEM   := 1 << 3      # 第 4 层（值 = 8）

# 玩家：我是 PLAYER，能撞 WORLD / ENEMY / ITEM
const PLAYER_MASK := WORLD | ENEMY | ITEM
```

```gdscript
func _ready() -> void:
    collision_layer = Layers.PLAYER
    collision_mask = Layers.PLAYER_MASK
```

⚠ **两个字段都要显式设。** 只设其中一个表现为
"某两个东西永远撞不上"，⛔ 不报错，且物体少时看不出来。

### 单向平台

`CollisionShape2D.one_way_collision = true` —— 只能从上面站上去，下面能跳穿。
配合 `one_way_collision_margin` 调容差。

## 5.6 摩擦组合与卡帧追赶

### ⚠ 摩擦是"两个物体共同决定"的

**默认取所有碰撞物体中的最低摩擦**，不是相加也不是取其一：

| 情况 | 有效摩擦 |
|---|---|
| 都 `rough=false` | **取最低** |
| 都 `rough=true` | 取最高 |
| 只有一个 `rough` | 取标记为粗糙的那个 |

⛔ **"冰面 0.1、车轮 10.0 → 摩擦 10.0"是错的**——
默认组合下有效值是 **0.1**。
⚠ 表现为"调了半天摩擦没反应"，
⛔ 因为被另一个物体的低值拉走了。

ⓘ 更可控的策略：两边都保持 `rough=false`，
改用**质量、驱动参数**调牵引，⛔ 不要用 `rough` 全局强行覆盖。

### ⚠ 卡帧：最多追赶 `max_physics_steps_per_frame` 步

卡帧时引擎最多追赶 **`max_physics_steps_per_frame`** 步（默认 8），
之后 ⛔ **真实时间与实际模拟时间分离** ——
物理会**变慢**，而不是跳帧。

⚠ 这是同一个设置的**两面**，与第 7 节的"螺旋死亡"要一起看：

| 设置 | 症状 |
|---|---|
| 上限太低 | 物理变慢（时间分离），表现为"慢动作" |
| ⛔ 不设上限 / 模拟过多 | 引擎追不上 → 雪崩到 1–2 FPS |

ⓘ 所以这个值的选取不是越大越好：
⛔ 调大到能掩盖慢动作，⛔ 也调大到足以引发雪崩。

## 6. ⛔ 缩放禁令：物理体与碰撞形状不能缩放

**官方原话：Godot 目前不支持缩放物理体或碰撞形状。**

⛔ 改 `scale` 让角色变大 → **碰撞体不变**，
视觉与碰撞脱节：看起来撞上了、实际穿过去，或反之。
而且**不报错**——排查时没人会想到是 scale。

✅ 正确做法：**改形状自身的参数**（`radius` / `height` / `extents`），不是改 scale。

```gdscript
# ⛔ 错误：缩放碰撞形状
$CollisionShape2D.scale = Vector2(2, 2)

# ✅ 正确：改形状 extents
var shape := $CollisionShape2D.shape.duplicate()   # 见下方"共享资源"
$CollisionShape2D.shape = shape
shape.extents = Vector2(32, 32)
```

⚠ 三条配套约束（官方一并给出）：

1. **要让视觉也变**：分别改视觉节点（`Sprite2D`/`MeshInstance3D`）的 scale
   和碰撞形状的 extents，⛔ **两边各自独立**
2. ⛔ **碰撞形状不能是视觉表示的子节点** —— 否则父节点缩放会带过去
3. ⓘ **形状资源默认共享**：改之前要 `duplicate()`，
   否则场景里用同一资源的所有节点一起变

### 6.1 ⛔ 圆柱碰撞形状不稳定

官方：从 Bullet 迁移到 GodotPhysics 时圆柱形状是重写的，
而它是**最难支持的形状之一**，目前有若干已知 bug。

✅ 官方建议：**角色用 box 或 capsule**。
- box：可靠性最好，代价是对角方向占地更大
- capsule：无此代价，但会让**精确平台跳跃变难**

### 6.2 ⓘ 移动平台与角色

见第 4 节。补充两条常被忽略的：

- ⚠ `AnimatableBody` **仍是 StaticBody 的子类**，不会被玩家推动；
  "可推动的箱子"要用 `RigidBody`
- ⛔ 平台的 Tween/动画必须跑在**物理 tick**（`set_process_mode` 或
  Tween 的 physics 模式），否则开插值后会抖

### 6.3 ⛔ 角色在斜坡上下滑

`move_and_slide()` 的经典症状：站在斜坡上**无输入却缓慢下滑**，
且 `is_on_floor()` 在 true/false 间闪烁。

三条成因（按常见度）：

1. ⛔ **重力无条件施加** —— 在地面上还继续 `velocity.y -= gravity * delta`
2. ⛔ `floor_max_angle` 小于实际坡度（默认约 45°）→ 坡被当成墙
3. ⛔ `floor_snap_length` 太短 → 每 tick 脱离地面又吸回

```gdscript
func _physics_process(delta: float) -> void:
    if is_on_floor():
        if _input_dir == Vector2.ZERO:
            velocity.x = move_toward(velocity.x, 0.0, SPEED)
            velocity.y = 0.0            # ⛔ 关键：在地面不累积重力
    else:
        velocity.y -= GRAVITY * delta
    move_and_slide()
```

ⓘ `floor_stop_on_slope = true` 直接解决"无水平输入时下滑"。

## 7. 官方故障排查清单

⚠ 下面每条都是官方文档**专门列出来的已知问题**，
⛔ 不是"你代码写错了"——排查方向错了会浪费大量时间。

| 症状 | 官方原因 | 官方解法 |
|---|---|---|
| 高速物体互相穿透（tunneling） | 每 tick 移动距离大于碰撞体尺寸 | 开 Continuous CD；加厚静态碰撞；按速度扩大运动体形状；提高 TPS |
| 堆叠物体摇摆 | 力相互对抗，堆得越多越强 | 提高 TPS |
| ⛔ 缩放后不碰撞 | 引擎不支持缩放 | 改形状 extents（见第 6 节） |
| 薄物体在地面抖 | 地板碰撞太薄 / 刚体太薄 | 加厚地板；或提高 TPS（刚体太薄时只能提 TPS） |
| 圆柱形状不稳定 | 重写实现，已知 bug | 换 box 或 capsule |
| 载具高速不稳定 | 360 km/h 时每 tick 移动约 1.67 单位 | 提高 TPS |
| 跨 tile 移动有颠簸 | 撞到**已被另一个形状覆盖**的边缘（已知问题） | 做 composite collider（把一组 tile 合成一个） |
| 物体接触时掉帧 | 碰撞形状过于复杂 | 用 primitive（box/sphere/capsule）替换凸形状 |
| ⛔ 帧率骤降到 1–2 FPS | 物理引擎跟不上，雪崩 | 提高 `Max Physics Steps per Frame` 和/或降低 TPS |
| 远离世界原点后不可靠 | 浮点精度误差随距离放大 | 把世界移近原点 |

⛔ **最后一条（物理螺旋死亡）尤其值得单独说**：
它表现为"帧率突然掉到 1–2 FPS"，
排查时极易被引到渲染或 GC，⚠ 而根因是物理步数雪崩。

⚠ **远离原点**这条对开放世界是硬约束：
浮点精度在世界坐标很大时退化，
⛔ 表现为"走到地图边缘碰撞开始飘"，且在出生点**完全正常**。

## 8. 待核对项（运行时验证）

- [ ] 切换物理引擎后**确实**点过 Save & Restart（0.1）
- [ ] ⚠ 若用 Jolt：单 body 关节的限位方向已实测（0.2 ①）
- [ ] 开插值后，所有传送点都调了 `reset_physics_interpolation()`（0.4）
- [ ] ⓘ 已用 **10 TPS** 跑过一次，确认无拖影（0.5）
- [ ] ⛔ 场景里搜不到被缩放的 `CollisionShape*`（第 6 节）
- [ ] ⛔ 角色碰撞形状不是 `CylinderShape3D`（6.1）
- [ ] ⚠ 角色站在斜坡上不下滑、`is_on_floor()` 不闪（6.3）


## 9. 相关文档

| 全局块 | 本域落点 |
|---|---|
| `GC-03` 数据与逻辑分离 | TPS / `Max Physics Steps per Frame` / 质量必须可配，⛔ 不硬编码 |
| `GC-06` 性能：先定位再优化 | 简化碰撞形状前先 profile 定位到具体物体，⛔ 不凭猜测全换 |
| `GC-07` 手感优先于（物理）正确性 | 真实重力/真实车辆往往不好玩；冲突时手感优先但**记录取舍** |
| `GC-02` 池化 | 碎片池化必然瞬移，⛔ 必须配 `reset_physics_interpolation()`（见 destruction 域） |

【读】 `common/howto/principles.md#GC-03`　数据与逻辑分离（刻度与质量参数可配，不硬编码）
【读】 `common/howto/principles.md#GC-06`　性能：先定位再优化（先 profile 再简化形状）
【读】 `common/howto/principles.md#GC-07`　手感优先于（物理）正确性（冲突时记录取舍）
【读】 `common/howto/principles.md#GC-02`　频繁生成/销毁的东西要池化（池化瞬移要 reset 插值）
