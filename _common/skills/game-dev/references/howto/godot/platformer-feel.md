# Godot 4.x 平台跳跃手感（Platformer Feel）

进阶手感是**"多个时间窗 + 状态 + 自定义积分"**，不是调大重力。

## 0. 控制器状态

```gdscript
var coyote_timer := 0.0        # 土狼时间剩余
var jump_buffer_timer := 0.0   # 跳跃缓冲剩余
var jump_hold := 0.0           # 按住时长
var was_on_floor := false
var is_jumping := false

const COYOTE_WINDOW := 0.12
const BUFFER_WINDOW := 0.15
const MAX_HOLD := 0.25
const CUT_SPEED := -150.0
```

**每帧顺序**（顺序错了手感就错）：

```
① 采样输入 → ② 消耗缓冲 → ③ 重力/水平
  → ④ move_and_slide() → ⑤ 更新状态
```

## 1. 土狼时间（Coyote Time）

```gdscript
func _physics_process(delta: float) -> void:
    var on_floor := is_on_floor()

    if was_on_floor and not on_floor:
        coyote_timer = COYOTE_WINDOW      # 刚离开地面
    if on_floor:
        coyote_timer = 0.0

    var can_jump := on_floor or coyote_timer > 0.0
    was_on_floor = on_floor
```

⚠ **`is_on_floor()` 只在最后一次 `move_and_slide()` 撞到地板时为 `true`** ——
角色离开平台的第一帧它就已经是 `false`，这正是土狼时间的入口。
所以必须用 `was_on_floor` 缓存前一帧状态。

## 2. 跳跃缓冲（Jump Buffer）

```gdscript
func _input(event: InputEvent) -> void:
    if event.is_action_pressed("jump"):
        jump_buffer_timer = BUFFER_WINDOW
```

```gdscript
# 在 _physics_process 里消费
if jump_buffer_timer > 0.0 and can_jump:
    jump_buffer_timer = 0.0
    do_jump()
jump_buffer_timer = maxf(0.0, jump_buffer_timer - get_physics_process_delta_time())
```

⚠ **`is_action_just_pressed("jump")` 不能只写在 `_physics_process` 里** ——
官方定义它"在该帧或该物理 tick 为真"，渲染帧与物理帧频率不同时，
一次按键可能落在两个物理 tick 之间被吞掉。
**必须**在 `_input`/`_process` 里捕获置缓冲标志，`_physics_process` 消费。

⚠ **键盘有 ghosting 时该函数可能返回 `false`** 即使某键确实按下。

## 3. 可变跳跃高度

```gdscript
func do_jump() -> void:
    velocity.y = JUMP_SPEED
    is_jumping = true
    jump_hold = 0.0

# 按住时持续给上升力
if is_jumping and Input.is_action_pressed("jump") and jump_hold < MAX_HOLD:
    velocity.y -= HOLD_FORCE * get_physics_process_delta_time()
    jump_hold += get_physics_process_delta_time()
elif is_jumping and not Input.is_action_pressed("jump"):
    velocity.y = maxf(velocity.y, CUT_SPEED)   # 截断，不是归零
    is_jumping = false
```

⚠ **松开跳不要用 `velocity.y = 0`** ——
截断到 `CUT_SPEED`（如 -150）才自然。归零会让每次短按高度
完全一致且手感发飘。

## 4. 读真实速度用 get_real_velocity()

```gdscript
var real_v := get_real_velocity()
if real_v.y > FALL_DAMAGE_SPEED:
    apply_fall_damage()
```

⚠ **`move_and_slide()` 是 `[const]` 方法，不修改 `velocity` 成员** ——
`velocity` 是"你希望的速度"，斜坡上实际沿斜面移动的真实速度
只能由 `get_real_velocity()` 拿到。做落地粒子、下落伤害阈值要以它为准。

## 5. floor_max_angle 的含义

⚠ **`floor_max_angle` 是相对 `up_direction` 的最大偏离角** ——
改它会影响"这算地板还是墙"，从而改变 `is_on_floor()` 与沿墙滑落行为。
要配合项目设置的默认地面/墙上速度综合调参，不是单独调一个值。

## 6. 移动平台

⚠ **接触移动平台时平台速度会自动叠加到角色运动**（官方行为），
但前提是平台自己在物理帧内完成移动。

⚠ **不要用 `position += v * delta` 移动平台** ——
手动改位置不会产生接触速度叠加，站在上面的角色不会跟着走。
统一用物理移动的平台（AnimatableBody / CharacterBody）+ `CharacterBody2D`。

⚠ **平台停下/掉头时角色抖动** —— 确认平台运动在物理帧内完成、
角色与平台同层同物理空间。


## 8. 顶点悬停（apex）：降低顶点附近的重力

> ⓘ 本节为流程 `flow/godot/character/02-跳跃手感.md` S6 提供取用锚点。

顶点悬停不是"变慢"，而是**在上升末段到下落初段临时降低重力**，
让这段滞空时间变长，玩家能更从容地做空中决策。

```gdscript
const APEX_THRESHOLD := 60.0      # 待实测：|velocity.y| 小于此值视为顶点附近
const APEX_GRAVITY_SCALE := 0.5   # 待实测

var g := gravity
if is_jumping and absf(velocity.y) < APEX_THRESHOLD:
    g *= APEX_GRAVITY_SCALE
velocity.y += g * delta
```

⚠ 三个必须注意的点：

1. **只在上升/下落都生效**，⛔ 不要在"落地瞬间"也生效——会出现贴地飘。
2. **阈值用 `absf(velocity.y)` 而不是 `velocity.y < 0`**：后者只覆盖上升段，
   下落初段会突然恢复正常重力，手感是"断崖式"的。
3. **必须实测录像逐帧看**，不能凭感觉调。判据是"上升末段到下落初段明显变慢"。

## 7. 碰撞形状不要高频变更

⚠ **冲刺时改 `CollisionShape2D.shape.radius` 或 `disabled` 会重建接触** ——
用固定形状 + 状态分层 mask 更稳定。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/platformer-feel.md`
