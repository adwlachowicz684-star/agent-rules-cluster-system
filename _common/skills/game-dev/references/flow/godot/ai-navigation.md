# Godot 4.x 敌人 AI 与寻路

状态机、寻路、感知、转向、避障。给完整可运行实现。

## 1. 选型：先确定空间模型

```
你的场景是哪种？
├─ 有导航区域（NavRegion），要绕开复杂障碍  → NavigationAgent2D/3D
├─ 网格地图（塔防、roguelike、棋盘）        → AStarGrid2D   ← 更简单
└─ 完全开放无障碍，直线追就够              → 不用寻路，直接朝目标走
```

**别一上来就上 NavigationAgent** —— 网格游戏用 `AStarGrid2D` 更简单也更可控。

| 方案 | 适用 | 代价 |
|---|---|---|
| `NavigationAgent2D/3D` | 任意形状障碍、开放世界 | 要烘焙导航区域 |
| `AStarGrid2D` | 网格地图、塔防、roguelike | 只能走格子 |
| 直线追击 | 无障碍竞技场 | 会卡墙 |

## 2. NavigationAgent2D 标准模板

**这是所有地面敌人的基线写法**，照抄即可。

⚠ 关键：开了 `avoidance_enabled` 时，**不要在设完 `velocity` 后立刻 `move_and_slide()`** ——
要等 `velocity_computed` 信号回来再移动。两处都移 = 重复积分。

```gdscript
# enemy_agent_2d.gd
extends CharacterBody2D

@export var speed: float = 160.0
@export var navigation_layer: int = 1
@export var enable_avoidance: bool = true

@onready var _agent: NavigationAgent2D = $NavigationAgent2D

var _has_target := false

func _ready() -> void:
    _agent.navigation_layers = navigation_layer
    _agent.avoidance_enabled = enable_avoidance
    _agent.velocity_computed.connect(_on_velocity_computed)
    # 第一帧导航地图可能还没同步，等一帧再开始
    set_physics_process(false)
    await get_tree().physics_frame
    set_physics_process(true)

func _exit_tree() -> void:
    if _agent.velocity_computed.is_connected(_on_velocity_computed):
        _agent.velocity_computed.disconnect(_on_velocity_computed)

## 目标点可能落在墙外，吸附到最近的可达点
func set_target(pos: Vector2) -> void:
    var map := _agent.get_navigation_map()
    _agent.target_position = NavigationServer2D.map_get_closest_point(map, pos)
    _has_target = true

func clear_target() -> void:
    _has_target = false
    velocity = Vector2.ZERO

func _physics_process(_delta: float) -> void:
    if not _has_target or _agent.is_navigation_finished():
        velocity = Vector2.ZERO
        move_and_slide()
        return

    var next := _agent.get_next_path_position()
    var desired := global_position.direction_to(next) * speed

    if _agent.avoidance_enabled:
        _agent.velocity = desired       # 只提交，等信号
        return
    velocity = desired
    move_and_slide()

func _on_velocity_computed(safe_velocity: Vector2) -> void:
    velocity = safe_velocity           # 避障修正后的速度
    move_and_slide()
```

**场景结构**：

```
Enemy (CharacterBody2D)
├── Sprite2D
├── CollisionShape2D
└── NavigationAgent2D          ← 必须有
```

**NavigationAgent 关键属性**：

| 属性 | 作用 |
|---|---|
| `path_desired_distance` | 距路径点多近算"到达"，改下一个点 |
| `target_desired_distance` | 距终点多近算"到达终点" |
| `path_max_distance` | 偏离路径超过多少就重算（太小会"原地跳舞"） |
| `avoidance_enabled` | 开 RVO 避障（要配合 `velocity_computed`） |
| `radius` / `neighbor_distance` / `max_neighbors` / `time_horizon` / `max_speed` | 避障参数 |

⚠ **不要每帧重设 `target_position`** —— 频繁重算路径会让最近路径点来回跳，
表现为敌人"原地抖"。移动目标要节流：位置变化超过阈值、或固定间隔（0.3~0.5s）才刷新。

### 导航区域

```
NavigationRegion2D  ← 挂 NavigationPolygon，烘焙后才有可走区域
```

```gdscript
# 运行时烘焙（程序生成关卡后用）
func _ready() -> void:
    if not _region.navigation_polygon:
        _region.bake_navigation_polygon()
```

⚠ 导航多边形默认**不会自动跟随 TileMap 变化**。改了地形要重新烘焙。

⚠ 静态障碍应该直接**从导航多边形里挖掉**（烘焙时排除），
而不是用 NavigationObstacle —— 后者是给动态障碍用的，开销大。

## 3. AStarGrid2D（网格地图）

塔防、roguelike、棋盘类用它，比 NavigationAgent 简单得多。

```gdscript
# grid_nav.gd —— Autoload 或关卡节点
extends Node2D

@export var grid_size := Vector2i(40, 30)
@export var cell_size := Vector2(32, 32)

var _astar: AStarGrid2D

func _ready() -> void:
    _astar = AStarGrid2D.new()
    _astar.region = Rect2i(Vector2i.ZERO, grid_size)
    _astar.cell_size = cell_size
    _astar.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_NEVER   # 四向；八向用 ONLY_IF_NO_OBSTACLES
    _astar.update()

func set_solid(cell: Vector2i, solid: bool) -> void:
    _astar.set_point_solid(cell, solid)

func find_path(from_world: Vector2, to_world: Vector2) -> PackedVector2Array:
    var from := _astar.local_to_map(from_world)
    var to := _astar.local_to_map(to_world)
    if _astar.is_point_solid(to):
        return PackedVector2Array()      # 目标是墙
    return _astar.get_point_path(from, to)
```

**敌人类**：

```gdscript
extends CharacterBody2D

@export var speed: float = 120.0
var _path: PackedVector2Array = []
var _path_index: int = 0

func move_to(target: Vector2) -> void:
    _path = GridNav.find_path(global_position, target)
    _path_index = 0

func _physics_process(_delta: float) -> void:
    if _path_index >= _path.size():
        velocity = Vector2.ZERO
        move_and_slide()
        return
    var target := _path[_path_index]
    if global_position.distance_to(target) < 4.0:
        _path_index += 1
        return
    velocity = global_position.direction_to(target) * speed
    move_and_slide()
```

⚠ `AStarGrid2D.get_point_path()` 返回的是**世界坐标点数组**（`get_id_path()` 才是格子 id）。

⚠ 改了 `set_point_solid()` 后必须调 `update()`，否则不生效 —— 但每个物理帧都 update 很贵，
应该批量改完再 update 一次。

## 4. 状态机 AI（巡逻 / 追击 / 攻击 / 返回）

**这是最常用也最该写对的模式**。角色状态超过 3 个就别用 if 嵌套了。

```gdscript
# enemy_fsm.gd
extends CharacterBody2D

enum State { PATROL, CHASE, ATTACK, RETURN }

@export var speed: float = 100.0
@export var chase_speed: float = 160.0
@export var detect_range: float = 200.0
@export var attack_range: float = 40.0
@export var lose_range: float = 320.0      # 超出就放弃追击
@export var attack_cooldown: float = 1.2
@export var patrol_points: Array[Vector2] = []

@onready var _agent: NavigationAgent2D = $NavigationAgent2D

var _state: State = State.PATROL
var _patrol_index: int = 0
var _target: Node2D
var _attack_timer: float = 0.0
var _repath_timer: float = 0.0

func _ready() -> void:
    set_physics_process(false)
    await get_tree().physics_frame
    set_physics_process(true)
    if patrol_points.is_empty():
        patrol_points = [global_position]

func _physics_process(delta: float) -> void:
    _attack_timer = maxf(_attack_timer - delta, 0.0)
    _repath_timer = maxf(_repath_timer - delta, 0.0)
    _update_state()
    match _state:
        State.PATROL: _do_patrol()
        State.CHASE:  _do_chase()
        State.ATTACK: _do_attack()
        State.RETURN: _do_return()
    move_and_slide()

func _update_state() -> void:
    var dist := -1.0
    if _target and is_instance_valid(_target):
        dist = global_position.distance_to(_target.global_position)

    match _state:
        State.PATROL:
            if dist >= 0.0 and dist < detect_range:
                _set_state(State.CHASE)
        State.CHASE:
            if dist < 0.0 or dist > lose_range:
                _set_state(State.RETURN)
            elif dist <= attack_range:
                _set_state(State.ATTACK)
        State.ATTACK:
            if dist < 0.0 or dist > attack_range * 1.3:
                _set_state(State.CHASE)
        State.RETURN:
            if global_position.distance_to(patrol_points[_patrol_index]) < 8.0:
                _set_state(State.PATROL)

func _set_state(next: State) -> void:
    if _state == next:
        return
    _state = next
    _on_exit_state()
    _on_enter_state()

func _on_enter_state() -> void:
    match _state:
        State.ATTACK:
            velocity = Vector2.ZERO
            _try_attack()
        State.RETURN:
            _agent.target_position = patrol_points[_patrol_index]

func _on_exit_state() -> void:
    pass

func _do_patrol() -> void:
    var goal := patrol_points[_patrol_index]
    if global_position.distance_to(goal) < 8.0:
        _patrol_index = (_patrol_index + 1) % patrol_points.size()
        _agent.target_position = patrol_points[_patrol_index]
        return
    _follow_path(speed)

func _do_chase() -> void:
    # 节流：不要每帧重设目标，否则敌人会原地抖
    if _repath_timer <= 0.0 and _target:
        _agent.target_position = _target.global_position
        _repath_timer = 0.3
    _follow_path(chase_speed)

func _do_attack() -> void:
    velocity = velocity.move_toward(Vector2.ZERO, 800.0 * get_physics_process_delta_time())
    if _attack_timer <= 0.0:
        _try_attack()

func _do_return() -> void:
    _follow_path(speed)

> **反模式清单（不能怎么做，审核用）** → `audit/godot/ai-navigation.md`


## 感知：Area2D 进入/离开
func _on_detect_body_entered(body: Node2D) -> void:
    if body.is_in_group("player"):
        _target = body

func _on_detect_body_exited(body: Node2D) -> void:
    if body == _target:
        _target = null
```

⚠ **状态转换必须集中在一个函数**（这里是 `_update_state`）。
散在各状态的 update 里会变成"谁都能切状态"，调试时根本理不清。

⚠ `lose_range` 要比 `detect_range` **大**，否则会在边界反复横跳（发现→追→丢失→返回→发现…）。

⚠ 用 `is_instance_valid(_target)` 判空 —— 目标可能已被 `queue_free`，
只判 `if _target` 对已释放对象返回 true。

## 5. 感知：看得见吗

光靠距离不够，敌人应该被墙挡住就看不见玩家。

```gdscript
@onready var _los: RayCast2D = $LineOfSight

func can_see(target: Node2D) -> bool:
    if not target:
        return false
    var dist := global_position.distance_to(target.global_position)
    if dist > detect_range:
        return false

    # 视线检测：有没有墙挡着
    _los.target_position = to_local(target.global_position)
    _los.force_raycast_update()          # 改完必须调，否则读旧缓存
    if _los.is_colliding():
        var hit := _los.get_collider()
        if hit != target:
            return false                 # 中间有别的东西
    return true
```

⚠ `force_raycast_update()` 不调就是读上一帧结果 —— 追击时表现为"隔墙也能看见"。

**听觉**（不需要视线）：

```gdscript
func hear_noise(pos: Vector2, radius: float) -> void:
    if global_position.distance_to(pos) < radius:
        _last_known_pos = pos
        if _state == State.PATROL:
            _set_state(State.CHASE)
```

## 6. 转向行为（不用寻路时）

开放场地、飞行敌人，用 steering 比寻路自然。

```gdscript
func seek(target: Vector2, spd: float) -> Vector2:
    return global_position.direction_to(target) * spd

func flee(target: Vector2, spd: float) -> Vector2:
    return global_position.direction_to(target) * -spd

## arrive：接近时减速，不会在目标点来回过冲
func arrive(target: Vector2, spd: float, slow_radius: float) -> Vector2:
    var to := target - global_position
    var dist := to.length()
    if dist < 1.0:
        return Vector2.ZERO
    var desired_speed := spd
    if dist < slow_radius:
        desired_speed = spd * (dist / slow_radius)
    return to.normalized() * desired_speed


## 7. 群体避障（RVO）

`avoidance_enabled = true` 后，敌人之间会自动避让。参数含义：

| 参数 | 含义 |
|---|---|
| `radius` | 代理半径，要接近碰撞体尺寸 |
| `neighbor_distance` | 多远的邻居要考虑（太大开销高） |
| `max_neighbors` | 最多考虑几个邻居 |
| `time_horizon` | 预测多久内的碰撞（太小会抖） |
| `max_speed` | 避障计算用的最大速度 |

⚠ `max_speed` 必须 ≥ 你的实际速度，否则避障会"追不上"。

⚠ 几十个以上 agent 开避障开销明显。大量单位（RTS）要考虑别开，或用简化方案。

⚠ **关闭 `avoidance_enabled` 时 `velocity_computed` 不触发** ——
如果你把所有移动都写在信号回调里，关掉避障后敌人就完全不动了。

