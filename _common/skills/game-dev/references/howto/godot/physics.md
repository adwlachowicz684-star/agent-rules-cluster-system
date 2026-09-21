# Godot 4.x 物理进阶

角色移动的基础在 `character.md`。本文件覆盖碰撞检测、射线、区域触发、刚体施力、移动平台。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/physics.md`


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

