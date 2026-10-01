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

## 8. ⛔ 官方口径：路径查询、避让默认值与 force_update 的代价

### 8.1 `map_get_path` 的 `optimize` 是玩法选型，不是画质开关

官方（Using NavigationPaths）：

- `optimize = true` —— 用 funnel 算法沿多边形拐角**收缩**路径。
  官方补充：**网格用小格子时，A* 会产生很窄的 funnel 走廊，
  配合网格使用会得到难看的拐角路径。**
- `optimize = false` —— 路径点落在**多边形边中点**。适合等大网格的纯格子移动。
  官方补充：**网格之外，多边形常以单条长边覆盖大片开阔区，
  这时会产生不必要的绕远。**

⛔ 两句话合起来才是完整口径：**不是"网格就一定用 false"，
而是"等大网格 + 纯格子移动"用 false；自由移动用 true。**
只记"网格用 false"，在开阔地形的混合关卡上会得到绕远路径。

### 8.2 `map_force_update()` 会 flush 整个命令队列（官方严厉警告）

库里常说"建塔后要立刻生效就调 `map_force_update()`"。官方原文：

> *"Due to technical restrictions the current NavigationServer command queue
> will be flushed. This means all already queued update commands for this
> physics frame will be executed, even those intended for other maps,
> regions and agents not part of the specified map."*

> *"Note: With great power comes great responsibility. This function should
> only be used by users that really know what they are doing and have a good
> reason for it."*

⛔ 所以它**不是"让改动立即生效的免费开关"**：
它清空的是**整个** NavigationServer 的命令队列（含别的地图、区域、代理），
官方明说会严重影响性能并可能引入 bug。

ⓘ 塔防里的正确用法：**只在"一帧内建/拆一批塔之后"调一次**，
而不是每放一座塔调一次。批量收敛到帧末由引擎自然同步，通常根本不需要它。

### 8.3 避让相关默认值（官方 `NavigationAgent2D`）

| 属性 | 默认值 | ⛔ 后果 |
|---|---|---|
| `avoidance_enabled` | **`false`** | ⛔ 避让**默认不开启**，不是"开了才要配" |
| `max_speed` | `100.0` | 开启后不显式配置，千军万马挤成一团或走得极慢 |
| `max_neighbors` | `10` | 只考虑 10 个邻居，密集阵型下避让不完整 |
| `neighbor_distance` | `500.0` | 搜索半径，超出这个距离的怪互相看不见 |
| `path_desired_distance` | `20.0` | ⛔ **双向都会出问题**，见下 |

⛔ `path_desired_distance` 是塔防最该显式配置的一个：

- **设太高** —— 官方：*"the NavigationAgent will skip points on the path,
  which can lead to it leaving the navigation mesh"*（跳过路径点，
  **走出导航网格**）
- **设太低** —— 官方：*"will be stuck in a repath loop because it will
  constantly overshoot the distance to the next point on each physics frame
  update"*（**陷入重寻路循环**）

ⓘ 两种失败都不报错：前者表现为"怪偶尔走到墙里/贴边卡住"，
后者表现为"帧率莫名下降"（重寻路是真开销）。

### 8.4 `intersect_shape` 的两个静默边界

官方：

- **已经重叠的形状会被忽略** —— *"Any Shape2Ds that the shape is already
  colliding with e.g. inside of, will be ignored. Use `collide_shape` to
  determine the Shape2Ds that the shape is already colliding with."*
  ⛔ 怪贴着塔刷出来时查不到，官方给的补法就是 `collide_shape()`。
- **`max_results` 默认 32** —— 超过的结果**静默截断，不报错**。
  ⛔ 塔的射程很大 + 怪很密集时，会**漏掉一部分怪**，
  表现为"塔偶尔不攻击"，而射程、mask、冷却全对。

### 8.5 `AStarGrid2D` 的 `allow_partial_path` 默认 `false`

签名：`get_id_path(from_id, to_id, allow_partial_path = false)`。

⛔ **目标不可达时返回空数组**，而不是"走到最接近的点"。

ⓘ 这对塔防是**核心机制级**的：如果玩法允许用塔封路（大多数塔防不允许完全封死），
封死的那一刻 `get_id_path` 返回空，怪**原地不动且不报错** ——
`is_point_solid` 检查处处是绿的，路径缓存也是绿的。

⛔ 正确做法不是"返回一个空路径让怪停着"，而是**在建塔前就用同一张图验证**：
放下去之后从每个出生点到终点仍需有解，否则**拒绝这次建造**。

## 9. 流程：按什么顺序做

> **本域流程** → `flow/godot/tower-defense/00-域流程总览.md`

7 个功能点按依赖排序：波次数据化 → 路径与寻路 → 敌人移动与避让 →
建塔与格子 → 索敌与伤害分发 → 波次结算与经济 → 验收。

⛔ **01 不能跳过** —— 波次一旦写成"每只怪自己计时的 Timer"，
后面所有"这波到底刷完没有"的判定都要靠猜，
而 `get_nodes_in_group().is_empty()` 会被池里的休眠怪污染。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-tower-defense.md`
