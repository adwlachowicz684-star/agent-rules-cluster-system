# Godot 4.x 角色控制器

**版本**：Godot 4.x（4.0–4.4 验证）。3.x 的 `move_and_slide(velocity, up)` 已废弃，见文末迁移。

覆盖：2D 平台跳跃 / 2D 俯视角 / 3D 第一人称 / 3D 第三人称。
每个都给**完整可运行脚本**，不是片段。

## 选型：先决定用哪个节点

选错了后面全歪，这一步别跳。

```
角色需要被物理力推吗？
├─ 否（玩家/NPC，完全由代码控制）→ CharacterBody2D/3D  ← 大多数情况
└─ 是（箱子、载具、受爆炸影响）  → RigidBody2D/3D
```

**CharacterBody 不受物理力影响** —— 重力要自己加到 `velocity` 上，
不是引擎给的。这是与 3.x `KinematicBody` 最大的心智差异。

| 需求 | 节点 | 关键属性 |
|---|---|---|
| 2D 平台跳跃 | `CharacterBody2D` | `velocity` · `up_direction` · `floor_snap_length` |
| 2D 俯视角（无重力） | `CharacterBody2D` | `motion_mode = MOTION_MODE_FLOATING` |
| 3D 第一/第三人称 | `CharacterBody3D` | `velocity` · `floor_max_angle` |
| 移动平台 | `AnimatableBody2D/3D` | **不是** StaticBody（见下） |

⚠ **移动平台用 `AnimatableBody`，不用 `StaticBody`**。
StaticBody 移动是"传送"，不会推动站在上面的角色；
AnimatableBody 会把运动估算成速度传递出去。

## 2D 平台跳跃（完整）

带四个手感优化：**土狼时间**（离开平台后仍可跳）、**跳跃缓冲**（落地前按跳也算）、
**可变跳跃高度**（松开键就减速上升）、**加速度/摩擦分离**。

```gdscript
extends CharacterBody2D
class_name PlayerController2D

## 水平移动
@export var speed: float = 300.0
@export var acceleration: float = 2000.0    # 地面加速
@export var friction: float = 2500.0        # 地面减速
@export var air_acceleration: float = 900.0 # 空中控制力（比地面弱）
@export var air_friction: float = 400.0

## 跳跃
@export var jump_velocity: float = -400.0   # 负值 = 向上（Godot 2D 的 -Y 是上）
@export var jump_cut_multiplier: float = 0.5  # 松开跳键时上升速度乘这个
@export var coyote_time: float = 0.12       # 土狼时间（秒）
@export var jump_buffer: float = 0.12       # 跳跃缓冲（秒）
@export var max_fall_speed: float = 900.0

## 重力：直接用 ProjectSettings 里配的，保持一致
var gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")

var _coyote_timer: float = 0.0
var _buffer_timer: float = 0.0
var _was_on_floor: bool = false

func _physics_process(delta: float) -> void:
    _update_timers(delta)
    _apply_gravity(delta)
    _handle_jump()
    _handle_horizontal(delta)
    move_and_slide()          # 4.x：无参！速度从 velocity 属性读
    _update_coyote()

func _apply_gravity(delta: float) -> void:
    if not is_on_floor():
        velocity.y += gravity * delta
        # 注意：是 velocity.y += gravity * delta，不是 velocity *= delta
        # 后者是二次积分，审查的 GD21 会抓
        if velocity.y > max_fall_speed:
            velocity.y = max_fall_speed

func _handle_jump() -> void:
    # 缓冲：提前按跳，落地瞬间自动起跳
    if Input.is_action_just_pressed("jump"):
        _buffer_timer = jump_buffer

    if _buffer_timer > 0.0 and _coyote_timer > 0.0:
        velocity.y = jump_velocity
        _buffer_timer = 0.0
        _coyote_timer = 0.0

    # 可变跳跃高度：上升中松开跳键 → 立刻削减上升速度
    if Input.is_action_just_released("jump") and velocity.y < 0.0:
        velocity.y *= jump_cut_multiplier

func _handle_horizontal(delta: float) -> void:
    var dir := Input.get_axis("move_left", "move_right")
    if dir != 0.0:
        var accel := acceleration if is_on_floor() else air_acceleration
        velocity.x = move_toward(velocity.x, dir * speed, accel * delta)
    else:
        var fric := friction if is_on_floor() else air_friction
        velocity.x = move_toward(velocity.x, 0.0, fric * delta)

func _update_timers(delta: float) -> void:
    _buffer_timer = maxf(_buffer_timer - delta, 0.0)
    _coyote_timer = maxf(_coyote_timer - delta, 0.0)

func _update_coyote() -> void:
    # 离开地面的瞬间开始计时，期间仍可跳
    if _was_on_floor and not is_on_floor():
        _coyote_timer = coyote_time
    elif is_on_floor():
        _coyote_timer = coyote_time
    _was_on_floor = is_on_floor()
```

**场景结构**：

```
Player (CharacterBody2D)  ← 挂上面这个脚本
├── Sprite2D
└── CollisionShape2D      ← 必须有，否则 move_and_slide 不碰任何东西
```

**必配 Input Map**（项目设置 → Input Map）：
`move_left` / `move_right` / `jump`

**关键属性**（Inspector 里设）：

| 属性 | 值 | 为什么 |
|---|---|---|
| `up_direction` | `(0, -1)` | 决定哪边算"地板"，不设则 `is_on_floor()` 永远 false |
| `floor_snap_length` | `1.0` | 下坡时吸附地面，避免"下坡起飞" |
| `floor_max_angle` | `0.785`（45°） | 超过这个角度不算地板 |

## 2D 俯视角（无重力）

```gdscript
extends CharacterBody2D

@export var speed: float = 200.0
@export var acceleration: float = 1500.0
@export var friction: float = 1500.0

func _ready() -> void:
    # 浮动模式：不区分地板/墙壁，无重力
    motion_mode = MOTION_MODE_FLOATING

func _physics_process(delta: float) -> void:
    var dir := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
    if dir != Vector2.ZERO:
        velocity = velocity.move_toward(dir * speed, acceleration * delta)
    else:
        velocity = velocity.move_toward(Vector2.ZERO, friction * delta)
    move_and_slide()
```

## 3D 角色（第一/第三人称通用）

```gdscript
extends CharacterBody3D

@export var speed: float = 5.0
@export var jump_velocity: float = 4.5
@export var mouse_sensitivity: float = 0.002

@onready var _camera: Camera3D = $Camera3D
var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")

func _ready() -> void:
    Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)   # 锁定鼠标（FPS）

func _unhandled_input(event: InputEvent) -> void:
    # 鼠标看视角放这里，不放 _process：
    # InputEventMouseMotion 是事件驱动，_process 里轮询会丢精度
    if event is InputEventMouseMotion:
        rotate_y(-event.relative.x * mouse_sensitivity)
        _camera.rotate_x(-event.relative.y * mouse_sensitivity)
        _camera.rotation.x = clampf(_camera.rotation.x, -PI / 2.0, PI / 2.0)
    if event.is_action_pressed("ui_cancel"):
        Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)

func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y -= gravity * delta      # 3D 的 +Y 是上，所以减

    if Input.is_action_just_pressed("jump") and is_on_floor():
        velocity.y = jump_velocity

    var input_dir := Input.get_vector("move_left", "move_right", "move_fwd", "move_back")
    # 把输入从局部转到世界空间（考虑角色朝向）
    var direction := (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
    if direction != Vector3.ZERO:
        velocity.x = direction.x * speed
        velocity.z = direction.z * speed
    else:
        velocity.x = move_toward(velocity.x, 0.0, speed * delta * 10.0)
        velocity.z = move_toward(velocity.z, 0.0, speed * delta * 10.0)

    move_and_slide()
```

⚠ 3D 的重力是 `velocity.y -= gravity * delta`（**减**，因为 +Y 朝上），
2D 是 `+=`（因为 -Y 朝上）。写反了角色会往天上飞。

## 与动画联动

```gdscript
@onready var _anim: AnimatedSprite2D = $AnimatedSprite2D

func _process(_delta: float) -> void:
    # 只在状态变化时才切动画，不要每帧 play()
    var target := "idle"
    if not is_on_floor():
        target = "jump" if velocity.y < 0.0 else "fall"
    elif velocity.x != 0.0:
        target = "run"

    if _anim.animation != target:
        _anim.play(target)

    if velocity.x != 0.0:
        _anim.flip_h = velocity.x < 0.0
```

⚠ 每帧调 `play()` 会不断重启动画，表现为"第一帧定住"。

## 常见漏写

写完对照看一遍，这些是审查会抓的：

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| `move_and_slide(velocity, Vector2.UP)` | 4.x 无参，带参是 3.x 残留 | GD09 |
| `velocity *= delta` | 二次积分，移动速度不对 | GD21 |
| 物理逻辑放 `_process` | 低帧率时步长变化，抖动/穿模 | GD14 |
| 没设 `up_direction` | `is_on_floor()` 永远 false，跳不起来 | 人工 |
| 没加 `CollisionShape2D` | 不碰任何东西，直接穿墙 | 人工 |
| 每帧 `_anim.play()` | 动画卡在第一帧 | GD54 |

## 从 3.x 迁移

| 3.x | 4.x |
|---|---|
| `KinematicBody2D` | `CharacterBody2D` |
| `move_and_slide(velocity, up)` | 设 `velocity` / `up_direction` 属性，调 `move_and_slide()` |
| `move_and_slide_with_snap(...)` | `floor_snap_length` 属性 |
| `is_on_floor()` 依赖 `up` 参数 | 依赖 `up_direction` 属性 |
