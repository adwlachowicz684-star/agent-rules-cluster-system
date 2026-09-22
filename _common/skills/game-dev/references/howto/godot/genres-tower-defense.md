# Godot 4.x 塔防（Tower Defense）

塔防的架构核心是**"波次数据化 + 路径缓存 + 索敌降频"**，
不是"每只怪自己寻路、每座塔自己检测"。

## 0. 三层分离

| 层 | 职责 | 典型实现 |
|---|---|---|
| **波次层** | 什么时候刷什么、刷几只 | `WaveRunner` + `Wave` Resource |
| **调度层** | 生成、对象池、路径分配 | `MobDirector` |
| **战场层** | 建塔、格子、索敌、结算 | `TowerGrid` |

⚠ **敌人不一定要是 `CharacterBody2D`。**
需要相互推挤才用 `CharacterBody2D` + `NavigationAgent2D`；
纯路径插值用普通 `Node2D` 沿路径移动即可，省掉整套物理开销。

## 1. 波次配置用 Resource，不要硬编码数组

```gdscript
# wave.gd
class_name Wave extends Resource

@export var groups: Array[SpawnGroup] = []
@export var delay_before: float = 0.0

# spawn_group.gd
class_name SpawnGroup extends Resource

@export var enemy_scene: PackedScene
@export var count: int = 10
@export var interval: float = 0.5
@export var path_id: int = 0
```

⚠ **不要用 `Timer` 串"间隔 0.05 秒刷 50 只"** —— `Timer` 每帧/每 tick
最多处理一次超时，密集刷怪会依赖帧率。用累加器显式结算：

```gdscript
var _acc: float = 0.0

func _process(delta: float) -> void:
    _acc += delta
    while _acc >= interval and spawned < count:
        spawn_one()
        _acc -= interval
        spawned += 1
```

## 2. 路径缓存，不要每只怪独立寻路

同一起点终点的路径只算一次，怪物只在路径上插值 + RVO 避让。

```gdscript
var _path_cache: Dictionary = {}   # path_id -> PackedVector2Array

func get_path(pid: int) -> PackedVector2Array:
    if not _path_cache.has(pid):
        _path_cache[pid] = NavigationServer2D.map_get_path(
            _map, _start[pid], _goal[pid], true, 1)
    return _path_cache[pid]
```

⚠ **`optimize` 参数要按玩法选**：
`true` 走 funnel 收缩（适合自由移动），
`false` 路径点落在多边形边中点（适合纯格子移动）。

⚠ **NavigationServer 的改动要到下一物理帧才生效**。
建塔后立刻 `map_get_path()` 拿到的是旧数据，
要立即生效得调 `NavigationServer2D.map_force_update()`。

## 3. 敌人移动：agent 只给路径，移动要自己写

```gdscript
func _physics_process(_d: float) -> void:
    if agent.is_navigation_finished():
        return
    var next := agent.get_next_path_position()
    var dir := (next - global_position).normalized()
    velocity = dir * speed
    move_and_slide()
```

⚠ **`move_and_slide()` 是 `[const]` 方法，不修改 `velocity` 成员变量。**
读碰撞修正后的真实速度要用 `get_real_velocity()`。

⚠ **`NavigationAgent2D.get_next_path_position()` 必须每物理帧调一次**，
它同时更新 agent 内部路径逻辑。只在到达时调会卡住。

⚠ **开避让时 `max_speed` 默认只有 100 px/s** —— 不显式配置，
千军万马会挤成一团或走得极慢。

## 4. 索敌：降频查询，不要用信号

```gdscript
var _scan_acc: float = 0.0
const SCAN_INTERVAL := 0.15

func _process(delta: float) -> void:
    _scan_acc += delta
    if _scan_acc < SCAN_INTERVAL:
        return
    _scan_acc = 0.0
    var q := PhysicsShapeQueryParameters2D.new()
    q.shape = CircleShape2D.new()
    q.shape.radius = range_radius
    q.transform = global_transform
    q.collision_mask = ENEMY_LAYER
    var hits := get_world_2d().direct_space_state.intersect_shape(q, 32)
    _retarget(hits)
```

⚠ **`intersect_shape()` 会忽略"形状内部已重叠"的对象** ——
怪贴着塔刷出来时查不到，必须单独处理（或改用 `collide_shape()`）。

⚠ **20 座塔 × 200 只怪的 `body_entered/exited` 是信号风暴**。
塔的射程检测应该集中、降频、按需查询。

## 5. 波次完成判定要显式计数

```gdscript
var spawned_count := 0
var killed_count := 0
var escaped_count := 0

func is_wave_clear() -> bool:
    return spawned_count == killed_count + escaped_count
```

⚠ **不要用 `get_nodes_in_group("enemies").is_empty()`** ——
对象池里的休眠怪、正在退场的怪都会污染计数。

## 6. 塔的伤害分发：接口，不是字符串

```gdscript
# 敌人统一实现
func take_damage(amount: float, type: int) -> void: ...
```

⚠ **不要 `body_entered` 回调里 `if body.name == "Enemy"`** ——
`TileMap`/`TileMapLayer` 只要配了碰撞形状也会触发 `body_entered`。

## 7. 性能预算

| 项 | 建议 |
|---|---|
| 路径重算 | 每波共享缓存；只有路径被破坏才重算 |
| 建筑频繁增删 | 改 `AStarGrid2D` 点权重，比 carving 导航网格便宜得多 |
| 屏幕外/冰冻怪 | `set_physics_process(false)`，不是 `if not active: return` |

⚠ **运行时频繁改建筑的塔防，用 `NavigationObstacle2D` 切导航网格
代价远高于改 A* 图**。重算一张 100×60 的网格比切导航网格便宜得多。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-tower-defense.md`
