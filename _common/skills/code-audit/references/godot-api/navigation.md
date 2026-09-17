<!-- oversize-exempt: 引擎 API 查表文档，按 API 索引，需整体查阅 -->
# Godot 4.x 寻路与 AI 技能包

## 摘要

Godot 4.x 的导航不是“设置目标后自动移动”：`NavigationAgent` 只负责寻路和可选的 RVO 避障，移动必须由开发者在 `_physics_process` 中根据 `get_next_path_position()` 完成；避障启用时还要把期望速度写入 `velocity`，并在同帧稍后的 `velocity_computed` 回调里执行真正移动 [1][2]。大型、任意形状的地面优先使用 `NavigationRegion`/`NavigationServer`；规则网格、TileMap 或需要精细控制阻挡与代价的场景优先使用 `AStarGrid2D`，二者并非替代关系 [9]。Godot 没有内置行为树，也没有 GOAP 节点；社区主流选择是 LimboAI 或 Beehave，GOAP 可继续用 GDScript 插件 [10]。最稳妥的感知组合是：`Area2D` 负责“附近”，`RayCast2D` 负责“有无遮挡”，距离/视锥参数决定“是否应该看见”。本报告 API 条目主要核对到 4.1/4.2 稳定文档；4.3–4.7 可能新增或重命名属性，合并前应再用当前版本的离线类参考进行版本差量检查。

## 1. 技术选型：先确定空间模型，再选择寻路 API

**NavigationServer 适合“任意可达点”，AStarGrid2D 适合“格子世界”，AStar2D/3D 适合自定义图。** NavigationServer2D/3D 的输入和目标都是连续坐标，导航数据是可走区域；官方明确指出它适合需要角色到达导航区域内任意位置、且地图很大的实时游戏，因为一大片区域可能只需一个多边形 [9]。相反，AStarGrid2D 的单元是规则网格，初始化 `region`、`cell_size`、可选 `offset` 后自动建立邻接关系，适合 TileMap、网格塔防、回合制战棋或单元化阻挡。AStar2D/3D 则是最通用的点—边图，适合路点网络、房间中心图、铁路式路径等；它必须显式 `add_point()` 和 `connect_points()`，不自动生成邻居 [11]。

| 场景 | 首选 | 理由 | 不宜使用 |
|---|---|---|---|
| 2D 平台/俯视角大地图，碰撞形状不规则 | `NavigationRegion2D` + `NavigationAgent2D` | 连续目标，编辑多边形即可 | 为整张大地图逐格建 A* |
| TileMap、网格战棋、程序生成网格 | `AStarGrid2D` | 区域/单元尺寸配置后即获得邻接 | 让静态网格承受每帧烘焙 |
| 房间、据点、固定巡逻路点 | `AStar2D`/`AStar3D` | 精确控制节点和边代价 | 重复画多边形描述同一路点图 |
| 移动箱子、NPC、球状单位密集群集 | NavigationAgent + RVO | 本地规避自然 | 让动态障碍承担全局重规划 |
| 门、定时关闭的路、低频改变的墙 | 动态修改导航数据并请求新路径 | 路径可以绕开 | 仅加 RVO 障碍却期待新路线 |

**性能与正确性要一起判断，不能只看“寻路算法”。** NavigationServer 的变化并非立即生效，而是在物理帧同步阶段统一应用；程序化创建地图、区域和代理后至少等待一个物理帧再查询，否则容易得到空路径 [12]。AStarGrid2D 的 `set_point_solid()`、权重与矩形填充不会使网格变脏；但改变 `region`、`cell_size`、`offset`、`cell_shape` 后必须 `update()`，而 `update()` 会重建点数据，因此项目应把“真实阻挡状态”保存在 TileMap 自定义数据、瓦片实体或自己的二维数组里，在 `update()` 之后重放 [13]。

## 2. NavigationAgent 的完整 API 与调用时序

**`NavigationAgent` 是 Node 助手，不是 CharacterBody 的驱动。** `NavigationAgent2D`/`NavigationAgent3D` 把地图查询、路径跟随和避让注册封装起来，并自动加入默认 World2D/World3D 导航地图；官方明确其全部功能都能用脚本直接调用 NavigationServer 替代 [1]。这带来一个重要编码规则：`target_position` 只表示“请求一条新路径”，不会自动推进父节点；父节点必须由 `CharacterBody2D/3D`、`RigidBody` 或其他运动代码显式移动。

| 成员/信号 | GDScript | C# | 用途与误用 | 判据与验证 | 置信度 |
|---|---|---|---|---|---|
| `target_position` | `Vector2/3` | `Vector2/3` | 设置后请求新路径。误用：当作“自动寻路启用开关”；若目标超出导航图，路径只会到最近可达点。 | 正则：`nav(?:igation)?_agent\.target_position\s*=`；确认路径结果并检查 `is_target_reachable()`。 | 官方明确 [1][3] |
| `velocity` / `set_velocity()` | `Vector2/3` | `Vector2/3 Velocity` / `SetVelocity()` | 向 RVO 提交期望速度；不表示本帧实际速度。误用：直接读取返回值后立刻移动；避障开启时移动必须等回调。 | 正则：`agent\.velocity\s*=`；设置后必须连接 `velocity_computed`。 | 官方明确 [3] |
| `get_next_path_position()` | `Vector2/3` | `Vector2/3 GetNextPathPosition()` | 返回下一步世界坐标，并推进代理内部路径状态。误用：在 `waypoint_reached` 回调中再调用；没有路径时返回父节点位置。 | 正则：`get_next_path_position\(\)`；每物理帧只调用一次。 | 官方明确 [3] |
| `is_navigation_finished()` | `bool` | `bool IsNavigationFinished()` | 是否到达当前路径终点。误用：不检查就持续移动；误以为它代表“绝对不可达”。 | 正则：`is_navigation_finished\(\)`；到达后应清空速度。 | 官方明确 [3] |
| `is_target_reachable()` | `bool` | `bool IsTargetReachable()` | 当前查询的目标在导航意义上是否可达。误用：作为连续昂贵查询；地图尚未同步时会失真。 | 正则：`is_target_reachable\(\)`；在路径变化后读取。 | 官方明确 [3][12] |
| `distance_to_target()` | `float` | `float DistanceToTarget()` | 父节点到 `target_position` 的当前距离。误用：零目标时把返回值当作路径长度；用于精确定位时应优先检查 `is_target_reached()`。 | 正则：`distance_to_target\(\)`。 | 官方明确 [3] |
| `get_final_position()` | `Vector2/3` | `Vector2/3 GetFinalPosition()` | 当前路径可达终点；目标不可达时可能落在最近位置。误用：把它当成原始目标位置。 | 正则：`get_final_position\(\)`。 | 官方明确 [3] |
| `path_desired_distance` | `float` | `float` | 离下一个路径点的距离阈值，用于推进路径索引。误用：过小而速度过快会越点；过大则切角离开导航面。 | 正则：`path_desired_distance\s*=`；令距离阈值显著大于单帧位移。 | 官方明确 [1][3] |
| `target_desired_distance` | `float` | `float` | 到达最终目标的距离。误用：设为 0 或低于移动误差，容易抖动/反复重路径。 | 正则：`target_desired_distance\s*=`；2D 默认值通常是 10，3D 是 1，应结合项目单位重配 [3]。 | 官方明确 |
| `path_max_distance` | `float` | `float` | 被挤出理想路径多远后请求重路径。误用：过小导致每帧抖动式重路径；过大则障碍挤出后反应迟钝。 | 正则：`path_max_distance\s*=`；应与速度、半径及更新频率匹配。 | 官方明确 [1][3] |
| `pathfinding_algorithm` | `PathfindingAlgorithm` | `PathfindingAlgorithm` | 选择 A* 等路径搜索算法族。误用：盲目切换到未知枚举值；应按目标 Godot 版本查看枚举。 | 正则：`pathfinding_algorithm\s*=`；在离线类参考核对枚举。 | 官方明确 [3] |
| `avoidance_enabled` | `bool` | `bool` | 是否注册 RVO 回调。误用：开启后还走非避障移动分支；或给数百个不需要避障的单位全开。 | 正则：`avoidance_enabled\s*=`；同时检索 `velocity_computed`。 | 官方明确 [3] |
| `navigation_layers` | `int` 位掩码 | `uint`/`int` | 限制代理可使用哪些区域/链接。误用：代理与区域层位不匹配导致“找不到路径”。 | 正则：`navigation_layers\s*=`；让代理层与区域层有交集。 | 官方明确 [3][4] |
| `path_postprocessing` | `PathPostProcessing` | `PathPostProcessing` | 对原始路径进行 funnel/corridor 后处理。误用：纯网格运动误用依赖连续漏斗结果。 | 正则：`path_postprocessing\s*=`；按 2D/3D 与网格或自由运动选择。 | 官方明确 [1][3] |
| `radius`/`height` | `float` | `float` | RVO 体积。误用：把它当物理碰撞半径；路径查询仍以导航面边缘为准。 | 正则：`agent\.radius\s*=`；与视觉、物理半径分别配置。 | 官方明确 [3][5] |
| `neighbor_distance` | `float` | `float` | 搜索避让邻居的半径。误用：设得过小会让远处快速单位来不及反应。 | 正则：`neighbor_distance\s*=`；越小的搜索范围性能越低，但保真度下降。 | 官方明确 [5] |
| `max_neighbors` | `int` | `int` | 一次避让计算考虑的最大邻居数。误用：在拥挤场景设 1–2，可能漏避。 | 正则：`max_neighbors\s*=`；做同屏规模压测。 | 官方明确 [3][5] |
| `time_horizon_agents`/`time_horizon_obstacles` | `float` | `float` | 预测碰撞的时间窗口。误用：过大导致单位过早减速、排队；必须为正。 | 正则：`time_horizon_(agents|obstacles)\s*=`；以真实单位/速度校准。 | 官方明确 [3][5] |
| `max_speed` | `float` | `float` | RVO 允许的最大安全速度。误用：小于实际速度时安全速度可能仍无法避免碰撞。 | 正则：`max_speed\s*=`；设置不低于角色可达到的平面速度。 | 官方明确 [3][5] |
| `velocity_computed` | `signal` | `VelocityComputed` | 避障计算完成时发出安全速度。误用：没连接；或在非避障模式下等它。 | 正则：`velocity_computed\.connect\(`；回调中执行 `move_and_slide()`。 | 官方明确 [2][3] |
| `navigation_finished`/`target_reached`/`path_changed`/`waypoint_reached`/`link_reached` | `signal` | `event` | 生命周期通知。误用：在 `waypoint_reached` 中重新请求重路径或递归调用路径推进；把 `path_changed` 当成到达。 | 正则：`\.connect\(_on_[\w_]*\)`；检查连接的函数名与用途。 | 官方明确 [3] |

**避障的“两分支”合同不能省。** 官方给出的执行顺序是：脚本 `_physics_process` → 设置代理 `velocity` → NavigationServer 同步并计算避让 → 在 PhysicsServer 提交前发出 `velocity_computed` → 回调执行移动 [2]。因此导航更新和避障移动发生在同一物理帧、不同阶段；若回调里再调用会触发额外路径更新的函数，或回调继续设置新的 `target_position`，就可能形成意料之外的重路径链。

## 3. NavigationAgent2D 敌人标准模板

**此模板应作为所有地面/俯视角导航敌人的基线，而不是把移动逻辑散落在动画、计时器和状态脚本中。** 下面的实现使用 `CharacterBody2D`：将导航更新放在固定物理步，仅计算期望速度；`avoidance_enabled == true` 时提交给代理，并在回调中移动；关闭避障时直接移动。模板有意不处理动画、伤害和停止动画；这些应由状态层驱动，避免与导航层互相写入速度。

```gdscript
# EnemyAgent2D.gd
# 挂载于 CharacterBody2D；子节点包含 NavigationAgent2D（节点名 NavigationAgent2D）。
# 关闭避障时可直接移动；开启避障时只能在 velocity_computed 中移动。
extends CharacterBody2D

@export var speed: float = 160.0
@export var navigation_layer_flags: int = 1
@export var enable_avoidance: bool = true

@onready var _agent: NavigationAgent2D = $NavigationAgent2D

var _has_target: bool = false
var _current_target: Vector2 = Vector2.ZERO


func _ready() -> void:
    _agent.navigation_layers = navigation_layer_flags
    _agent.avoidance_enabled = enable_avoidance
    _agent.velocity_computed.connect(_on_velocity_computed)

    # 避免在第一帧导航地图尚未同步时得到空路径。
    set_physics_process(false)
    if _agent.is_inside_tree():
        await get_tree().physics_frame
    set_physics_process(true)


func set_target(position: Vector2) -> void:
    var map: RID = _agent.get_navigation_map()
    var safe_position := NavigationServer2D.map_get_closest_point(map, position)
    _current_target = safe_position
    _has_target = true
    _agent.target_position = safe_position


func clear_target() -> void:
    _has_target = false
    velocity = Vector2.ZERO


func _physics_process(_delta: float) -> void:
    if not _has_target or _agent.is_navigation_finished():
        velocity = Vector2.ZERO
        move_and_slide()
        return

    var next_position: Vector2 = _agent.get_next_path_position()
    var direction: Vector2 = global_position.direction_to(next_position)
    var desired_velocity: Vector2 = direction * speed

    if _agent.avoidance_enabled:
        # 只提交期望速度；不要在设置 velocity 后立刻 move_and_slide()。
        _agent.velocity = desired_velocity
        return

    velocity = desired_velocity
    move_and_slide()


func _on_velocity_computed(safe_velocity: Vector2) -> void:
    velocity = safe_velocity
    move_and_slide()
```

模板中 `map_get_closest_point()` 并不是必须，但它是处理点击/投射点落在墙外时的防御性措施；代价是目标会被吸附到可达位置。若设计明确要求“玩家点击的位置就是逻辑目标”，应保留原始目标，同时使用 `is_target_reachable()` 显示反馈，而不能假设路径终点等于点击点。

**停止、取消和重目标是三个不同动作。** `is_navigation_finished()` 返回 `true` 时，调用者可以停止；切换目标只需再次赋值 `target_position`，不需要先“重置代理”。但不要在同一个物理帧既把 `velocity` 设成安全值又自己调用 `move_and_slide()`，否则可能出现重复积分。官方警告频繁、逐帧重路径会使最近路径点来回切换，造成“原地跳舞”；`path_max_distance` 过小也会诱发相同症状 [1]。因此动态目标应做节流：玩家每帧移动时不刷新路径，采用固定周期、位置移动超过阈值或视线/状态变化时刷新。

## 4. NavigationRegion、导航多边形与运行时烘焙

**导航多边形描述的是“角色中心可以安全站立的区域”，不是碰撞形状。** 官方明确导航网格只描述特定代理的安全可达区域；若希望路径考虑角色体积，应从导航面中收缩，或通过 `NavigationMesh` 的 `agent_radius`、高度、坡度、攀爬高度等烘焙参数反映 [6]。因此把 TileMap 可走格子的几何边原样当导航边界，通常会让角色中心贴着墙、随后被自己的物理体卡住。

| 节点/资源 | 关键成员 | 用途 | 判据与误用 |
|---|---|---|---|
| `NavigationRegion2D` | `navigation_polygon`、`navigation_layers`、`enabled`、`enter_cost`、`travel_cost`、`use_edge_connections`、`bake_navigation_polygon(on_thread)` | 向导航地图提交 2D 可走多边形 | 正则：`NavigationRegion2D`/`bake_navigation_polygon(`；未烘焙、节点禁用或层不匹配均会无路径。 |
| `NavigationPolygon` | `agent_radius`、`cell_size`、`vertices`、`add_polygon()`、`add_outline()`、`make_polygons_from_outlines()` | 定义 2D 导航区域，可手建多边形或烘焙 | 2D 概述指出 outline 不能交叉、重叠；同一 `NavigationPolygon` 内的不相连岛屿不会自动连接 [7][14]。 |
| `NavigationRegion3D` | `navigation_mesh`、`bake_navigation_mesh(on_thread)`、`bake_finished` | 向 3D 地图提交并烘焙 `NavigationMesh` | 正则：`bake_navigation_mesh\(`；异步烘焙完成时才有新网格。 |
| `NavigationMesh` | `agent_radius/height/max_slope/max_climb`、`cell_size/height`、`geometry_*` | 从网格或静态碰撞解析并生成 3D 导航数据 | 它是近似数据；斜坡贴合还应通过物理或投影处理 [6]。 |
| `NavigationLink2D`/`NavigationLink3D` | `start_position/end_position`、`bidirectional`、`enter_cost`、`travel_cost`、`navigation_layers` | 表示跳点、滑索、传送门等非沿面移动 | 起点/终点会吸附到最近多边形；传送动画仍需自行实现 [8]。 |
| `NavigationObstacle2D`/`NavigationObstacle3D` | `radius`、`velocity`、`avoidance_layers`、`affect_navigation_mesh` | 让持续移动的物体参与 RVO | 它不影响寻路；静态/偶尔移动物体应重新烘焙导航面 [15]。 |

**`bake_navigation_polygon()` 与 `region_bake_navigation_mesh()` 不应在热路径逐帧调用。** 2D 的 `NavigationRegion2D.bake_navigation_polygon()` 与 3D 的 `NavigationRegion3D.bake_navigation_mesh()` 都接受 `on_thread`，默认在另一线程执行；官方明确指出运行时烘焙是昂贵操作 [4][6]。正确流程是：门关闭 → 修改唯一可走的真实数据结构 → 触发增量或区域烘焙 → 监听 `bake_finished` → 所有在途代理请求新路径。不要为每个门保留一份 `NavigationPolygon`/`NavigationMesh` 副本后各自烘焙；应划分可重新烘焙的块，并确保门/障碍的“开/关”数据来自单一事实源。

**链接不等于传送逻辑。** `NavigationLink2D`/`NavigationLink3D` 的 `start_position`/`end_position` 会寻找最近的导航多边形并附加；`enter_cost` 控制从其他区域进入该链接的代价，`travel_cost` 控制沿链接移动的代价，`bidirectional` 控制是否可双向通行 [8]。但链接只影响寻路，不代表代理会自动播放跳跃、滑索、坠落动画，也不自动执行冷却。项目应在 `NavigationAgent.link_reached` 中暂停常规移动，播放专属过渡，完成后恢复；若链接需要条件触发，应设计自己的 `can_use()` 判断，而不是试图用导航层完全编码复杂规则。

## 5. NavigationServer 的直接调用与高级地图管理

**Node 帮手不能覆盖全部 NavigationServer 能力，多地图/多代理尺寸才需要直接调用。** 直接路径查询是 `NavigationServer2D.map_get_path(map, from, to, optimize, navigation_layers)` 和 `NavigationServer3D.map_get_path(map, from, to, optimize, navigation_layers)`，返回对应维度的紧凑向量数组；起点/终点会被映射到导航面上的最近点 [16]。`optimize=true` 使用 funnel/corridor 优化，适合不等大多边形上的自由移动；纯网格可选 `false`，以免狭窄漏斗产生怪异转角。直接调用不会自动重路径、跟随或避障，适合一次性路线、绘制调试路径、车辆沿预定轨迹移动等。

NavigationServer3D 的高级流程通常是：`map_create()` → `map_set_active()` → `map_set_up()` → `region_create()` → `region_set_map()` → `region_set_navigation_mesh()`；程序化源几何需要 `parse_source_geometry_data()`，再 `bake_from_source_geometry_data()` [17]。不同尺寸的角色（小型、标准、大型）应分别烘焙代理半径/高度对应的 `NavigationMesh`，并放入各自地图；官方特别说明代理只由半径和高度定义，导航系统不识别更复杂的形状 [17]。

关于 `agent_set_target()`：这是一个容易被误读的名称。用户列出的“NavigationServer 完整 API”应区分“Node 的 `target_position`”与“NavigationServer 内部 agent 操作”。公开 Node API 使用 `target_position`；导航服务器内部对 RID 代理的配置集中在 `agent_set_*`、`agent_set_position`、`agent_set_radius`、`agent_set_velocity`、`agent_set_avoidance_*` 等函数。写跨版本代码时不应凭名称猜测 `agent_set_target()` 的存在或语义，而应查询当前版本的 `NavigationServer2D/3D` 类参考。本报告对 `agent_set_target()` 的具体签名标为**未在当前核对文档中找到**，置信度“待版本核对”，不虚构签名。

## 6. AStarGrid2D 与 AStar2D/3D 的完整用法

**AStarGrid2D 的关键不是“调用一次 update”，而是区分结构变化和阻挡变化。** 推荐初始化顺序：配置 `region`、`cell_size`、`offset`、`cell_shape` → `update()` → 从唯一真实数据源填充实心/权重 → 查询路径。之后开门关门只需 `set_point_solid()`、权重函数或 `fill_solid_region()`；仅改变这些状态无需 `update()`。改变结构后必须 `update()`，随后重放所有阻挡和代价 [13]。

| API | 签名/类型 | 用途 | 误用与判据 | 置信度 |
|---|---|---|---|---|
| `region` | `Rect2i` | 世界坐标下的网格范围 | 误用：只用 `size`；旧文档或未来版本可能有弃用差异。判据：正则 `astar\.region\s*=` 及 `Rect2i\(`。 | 官方明确 [18] |
| `cell_size` | `Vector2` | 网格单元的世界尺寸 | 误用：与 TileMap `cell_size` 不一致。判据：比较 TileMap 和 A* 的 cell_size。 | 官方明确 [18] |
| `offset` | `Vector2` | 把网格原点偏移到世界位置 | 误用：忘记补偿导致世界→网格坐标差一个单元。判据：正则 `astar\.offset`。 | 官方明确 [18] |
| `set_point_solid(id, solid=true)` | `void (Vector2i, bool)` | 单格开关阻挡 | 误用：动态关门后忘记重请求代理路径。判据：`set_point_solid\(` 后应触发寻路。 | 官方明确 [18] |
| `is_point_solid(id)` | `bool` | 读取单元阻挡状态 | 误用：把它当作真实 TileMap 数据的唯一来源。 | 官方明确 [18] |
| `fill_solid_region(region, solid)` | `void (Rect2i, bool)` | 批量填充阻挡 | 误用：只对当前代理有效，没有持久化设计。 | 官方明确 [18] |
| `set_point_weight_scale(id, weight)`/`fill_weight_scale_region()` | `void` | 为泥地、楼梯、危险区等设置代价 | 误用：权重为 0、负或极小导致优先度异常；应与启发式一起理解。 | 官方明确 [18] |
| `get_id_path(from, to)` | `Vector2i[]` | 返回格点 ID 序列 | 适合把路径离散为格子，判据：结果用于占格/技能判定。 | 官方明确 [18] |
| `get_point_path(from, to)` | `PackedVector2Array` | 返回世界坐标路径 | 误用：当作碰撞路径；相邻格转角仍可能卡碰撞。 | 官方明确 [18] |
| `get_point_position(id)` | `Vector2` | 由格点 ID 取世界坐标 | 用于把 id 路径转成移动目标。 | 官方明确 [18] |
| `update()` | `void` | 重建网格结构 | 误用：每帧调用或改变阻挡后忘记重放。判据：仅在 region/cell_size/offset/cell_shape 后调用。 | 官方明确 [13][18] |
| `is_dirty()` | `bool` | 检查是否需要结构更新 | 用于延迟 `update()` 批处理。 | 官方明确 [18] |
| `diagonal_mode` | `DiagonalMode` | 控制对角移动及切角规则 | 误用：`ALWAYS` 让单位从对角固体之间“切角”；视距判断不要简单复用路径可达性。 | 官方明确 [19] |
| `jumping_enabled` | `bool` | 允许跳点/直线穿越可走路径优化 | 误用：把它理解成物理跳跃；它只是寻路连通优化。 | 官方明确 [18] |
| `default_compute_heuristic`/`default_estimate_heuristic` | `Heuristic` | 选择 g/h 的默认启发式 | 误用：覆盖 `_compute_cost`/`_estimate_cost` 后仍期待默认值生效。 | 官方明确 [18] |
| `_compute_cost`/`_estimate_cost` | `float (from_id, to_id)` 虚函数 | 自定义边代价和启发式估计 | 误用：启发式不满足适当下界时可能影响最优性；应覆盖并保持可预测。 | 官方明确 [11][18] |

AStar2D/3D 的基本生命周期是 `add_point(id, position, weight_scale)` → `connect_points(id_a, id_b, bidirectional)` → `get_id_path()`/`get_point_path()`。`weight_scale` 会乘以相邻边的 `_compute_cost`；相同条件下算法偏好较小权重 [11]。3D 版本坐标使用 `Vector3`，其余寻路语义与 AStar2D 相同。适合使用它的情况包括：只有数十个房间或检查点；图由关卡工具生成；需要显式门、开关、单向传送边；需要临时禁用某个点而非逐格布尔阻挡。

## 7. AStarGrid2D 动态障碍模板

**“动态障碍”应拆成两层：A* 重新计算路线，物理/避让处理局部接触。** 下面示例保存一个权威 `Walkability` 数据，并提供 `set_wall()` 与 `update_grid()`。开门、关门、放置炸弹都走同一接口，避免 AStarGrid2D 成为唯一事实源。

```gdscript
# GridPathfinder2D.gd
# 适合 TileMap、网格战棋；调用方将世界坐标转换为网格坐标。
extends RefCounted

var astar := AStarGrid2D.new()
var region: Rect2i = Rect2i(-20, -20, 40, 40)
var cell_size: Vector2 = Vector2(32, 32)
var offset: Vector2 = Vector2(-16, -16)

# 真实可走性事实源；只有它能决定网格阻挡。
var walkability: Dictionary = {}

var _needs_structure_update: bool = true


func setup() -> void:
    astar.region = region
    astar.cell_size = cell_size
    astar.offset = offset
    astar.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_NEVER
    astar.default_compute_heuristic = AStarGrid2D.HEURISTIC_MANHATTAN
    astar.default_estimate_heuristic = AStarGrid2D.HEURISTIC_MANHATTAN
    _rebuild_structure()
    _replay_walkability()


func _rebuild_structure() -> void:
    astar.update()
    _needs_structure_update = false


func _replay_walkability() -> void:
    for cell_str in walkability:
        var cell: Vector2i = Vector2i(
            int(cell_str.get_slice(",", 0)),
            int(cell_str.get_slice(",", 1))
        )
        astar.set_point_solid(cell, not bool(walkability[cell_str]))


func world_to_cell(world_position: Vector2) -> Vector2i:
    var local: Vector2 = world_position - offset
    return Vector2i(
        floor(local.x / cell_size.x),
        floor(local.y / cell_size.y)
    )


func cell_to_world(cell: Vector2i) -> Vector2:
    return Vector2(
        cell.x * cell_size.x + offset.x,
        cell.y * cell_size.y + offset.y
    )


func set_wall(cell: Vector2i, is_walkable: bool) -> void:
    var key: String = "%d,%d" % [cell.x, cell.y]
    if walkability.get(key) == is_walkable:
        return
    walkability[key] = is_walkable
    if _needs_structure_update:
        # 若结构也改变了，先调用 update_grid()，再统一重放。
        return
    if astar.is_in_boundsv(cell):
        astar.set_point_solid(cell, not is_walkable)


func update_grid(new_region: Rect2i, new_cell_size: Vector2, new_offset: Vector2) -> void:
    # 结构变化必须 update()，之后重放真实数据。
    region = new_region
    cell_size = new_cell_size
    offset = new_offset
    astar.region = region
    astar.cell_size = cell_size
    astar.offset = offset
    _rebuild_structure()
    _replay_walkability()
    _needs_structure_update = false


func request_path(from_world: Vector2, to_world: Vector2) -> PackedVector2Array:
    var from_cell: Vector2i = world_to_cell(from_world)
    var to_cell: Vector2i = world_to_cell(to_world)
    if not astar.is_in_boundsv(from_cell) or not astar.is_in_boundsv(to_cell):
        return PackedVector2Array()
    if astar.is_point_solid(from_cell) or astar.is_point_solid(to_cell):
        return PackedVector2Array()
    return astar.get_point_path(from_cell, to_cell)
```

模板没有在每次 `set_wall()` 后自动 `update()`，因为只改单元阻挡不会使网格变脏；但修改了 `region`/`cell_size`/`offset` 后调用 `update_grid()` 会重建并丢失原生实心/权重，所以必须重放 [13]。下一步最好增加一个“脏代理路径缓存”：世界状态变化后，通知使用旧路径的敌人重新查询，而不是让每个敌人在 `_physics_process` 中每帧寻路。

## 8. 状态机 AI：巡逻、追击、攻击、返回

**状态机是 Godot 4.x 中小队规模敌人的最实用默认，FSM 负责“现在做什么”，导航负责“怎么到达”。** 官方没有与动画树状态机绑定的通用游戏逻辑状态机类，纯枚举 + `match` 已足够表达巡逻、追击、攻击、返回、死亡等有限状态。建议保留 `enter/update/exit` 生命周期，并在状态切换时清空导航目标、移动速度和计时器，避免上一次状态的残余速度继续生效。

```gdscript
# EnemyStateMachine2D.gd
# 组合 NavigationAgent2D 敌人。挂载在同一 CharacterBody2D 下。
extends Node

enum State { PATROL, CHASE, ATTACK, RETURN_HOME }
enum Event { ENTER, UPDATE, EXIT }

const PATROL_WAIT_TIME: float = 1.5
const CHASE_LOST_TIME: float = 3.0
const CHASE_RANGE: float = 320.0
const ATTACK_RANGE: float = 46.0
const RETURN_ARRIVE_RANGE: float = 16.0

@export var patrol_points: Array[Marker2D] = []
@export var chase_target: Node2D
@export var agent: NavigationAgent2D
@export var speed: float = 150.0
@export var chase_speed: float = 210.0

var current_state: State = State.PATROL
var patrol_index: int = 0
var patrol_timer: float = 0.0
var lost_timer: float = 0.0
var home_position: Vector2 = Vector2.ZERO
var _was_chasing: bool = false


func _ready() -> void:
    home_position = get_parent().global_position
    _change_state(State.PATROL)


func _physics_process(delta: float) -> void:
    match current_state:
        State.PATROL: _update_patrol(delta)
        State.CHASE: _update_chase(delta)
        State.ATTACK: _update_attack(delta)
        State.RETURN_HOME: _update_return_home(delta)


func _change_state(next_state: State) -> void:
    _dispatch(current_state, Event.EXIT)
    current_state = next_state
    _dispatch(current_state, Event.ENTER)


func _dispatch(state: State, event: Event) -> void:
    match state:
        State.PATROL:
            match event:
                Event.ENTER:
                    patrol_timer = 0.0
                    _goto_patrol_point()
                Event.EXIT:
                    _was_chasing = false
                Event.UPDATE: pass
        State.CHASE:
            match event:
                Event.ENTER:
                    lost_timer = CHASE_LOST_TIME
                    _was_chasing = true
                Event.EXIT:
                    agent.target_position = agent.global_position
                Event.UPDATE: pass
        State.ATTACK:
            match event:
                Event.ENTER:
                    agent.target_position = agent.global_position
                Event.EXIT: pass
                Event.UPDATE: pass
        State.RETURN_HOME:
            match event:
                Event.ENTER:
                    agent.target_position = home_position
                Event.EXIT: pass
                Event.UPDATE: pass


func _goto_patrol_point() -> void:
    if patrol_points.is_empty():
        return
    agent.target_position = patrol_points[patrol_index].global_position


func _update_patrol(delta: float) -> void:
    if _can_see_target():
        _change_state(State.CHASE)
        return

    var body: CharacterBody2D = get_parent()
    if patrol_points.is_empty():
        return

    if agent.is_navigation_finished() or body.global_position.distance_to(patrol_points[patrol_index].global_position) < RETURN_ARRIVE_RANGE:
        patrol_timer -= delta
        if patrol_timer <= 0.0:
            patrol_index = wrapi(patrol_index + 1, 0, patrol_points.size())
            patrol_timer = PATROL_WAIT_TIME
            _goto_patrol_point()


func _update_chase(delta: float) -> void:
    var body: CharacterBody2D = get_parent()
    if chase_target == null:
        _change_state(State.RETURN_HOME)
        return

    var to_target: float = body.global_position.distance_to(chase_target.global_position)
    if to_target <= ATTACK_RANGE:
        _change_state(State.ATTACK)
        return

    if _can_see_target():
        lost_timer = CHASE_LOST_TIME
        # 不要每帧无条件设置；这里为简化而更新。生产项目建议按距离阈值/计时器刷新。
        agent.target_position = chase_target.global_position
    else:
        lost_timer -= delta
        if lost_timer <= 0.0:
            _change_state(State.RETURN_HOME)
            return

    if to_target > CHASE_RANGE * 1.6:
        _change_state(State.RETURN_HOME)


func _update_attack(delta: float) -> void:
    var body: CharacterBody2D = get_parent()
    if chase_target == null or not is_instance_valid(chase_target):
        _change_state(State.RETURN_HOME)
        return

    var distance: float = body.global_position.distance_to(chase_target.global_position)
    if distance > ATTACK_RANGE * 1.25:
        _change_state(State.CHASE)
        return

    # 攻击冷却、命中判定与动画交给 AttackComponent，不要在此展开。
    body.velocity = Vector2.ZERO


func _update_return_home(delta: float) -> void:
    var body: CharacterBody2D = get_parent()
    if _can_see_target():
        _change_state(State.CHASE)
        return

    if body.global_position.distance_to(home_position) <= RETURN_ARRIVE_RANGE:
        _change_state(State.PATROL)


func _can_see_target() -> bool:
    # 由感知组件实现；此处仅占位，避免状态机依赖具体视觉节点。
    return false
```

该模板刻意将 `_can_see_target()` 留给感知组件，使状态机可单元测试而不依赖玩家实例。若攻击需要精确前置摇臂、取消窗口和伤害帧，应把攻击拆成 `AttackStateComponent`；状态机只决定进入/退出，动画和伤害由 `AnimationPlayer`/`AnimationTree` 回调完成。

## 9. 视觉与听觉感知：Area2D、RayCast 与距离

**“看见”不是碰撞检测的同义词，而是距离、方向/视锥、视线遮挡、记忆与状态的联合判定。** 一个常见而稳健的 2D 实现是：`Area2D` 监听进入/退出，缩小持续检测集合；在目标处于范围内时，检查距离与前方角度，再从敌人向目标做 `RayCast2D`；只有没有墙等遮挡物且 `collider` 正是目标时才确认看见。听觉则可由发声者向附近敌人发送事件，或让敌人监听声音传播器，按距离和掩体简化衰减。

```gdscript
# VisionSensor2D.gd
# 挂载于敌人；需要 Area2D（命名为 DetectionArea）、CollisionShape2D 和 RayCast2D（命名为 SightRay）。
extends Node

@export var view_range: float = 300.0
@export var hearing_range: float = 180.0
@export var field_of_view_degrees: float = 90.0
@export var awareness_duration: float = 4.0

@onready var _ray: RayCast2D = $SightRay

var detected_target: Node2D
var awareness_timer: float = 0.0


func _ready() -> void:
    var area: Area2D = $DetectionArea
    area.body_entered.connect(_on_body_entered)
    area.body_exited.connect(_on_body_exited)


func _physics_process(delta: float) -> void:
    if detected_target != null and is_instance_valid(detected_target):
        if has_line_of_sight(detected_target):
            awareness_timer = awareness_duration
        else:
            awareness_timer -= delta
            if awareness_timer <= 0.0:
                detected_target = null
    else:
        awareness_timer = 0.0


func has_line_of_sight(target: Node2D) -> bool:
    var owner_node: Node2D = get_parent()
    var to_target: Vector2 = target.global_position - owner_node.global_position
    var distance: float = to_target.length()

    if distance > view_range:
        return false

    if not is_within_view_cone(to_target):
        return false

    _ray.global_position = owner_node.global_position
    _ray.target_position = to_target
    _ray.force_raycast_update()
    return _ray.is_colliding() and _ray.get_collider() == target


func is_within_view_cone(direction: Vector2) -> bool:
    var owner_node: Node2D = get_parent()
    var forward: Vector2 = Vector2.RIGHT.rotated(owner_node.global_rotation)
    var angle: float = rad_to_deg(forward.angle_to(direction))
    return abs(angle) <= field_of_view_degrees * 0.5


func hear_event(origin: Vector2, intensity: float) -> bool:
    # intensity 越大，有效传播范围越大；可进一步按墙体/楼层降低。
    var owner_node: Node2D = get_parent()
    var falloff: float = clampf(intensity, 0.0, 1.0) * hearing_range
    return owner_node.global_position.distance_to(origin) <= falloff


func _on_body_entered(body: Node2D) -> void:
    if body.is_in_group("player"):
        detected_target = body


func _on_body_exited(body: Node2D) -> void:
    if detected_target == body:
        # 保留记忆，让目标离开 Area2D 后仍能继续追击一段时间。
        pass
```

`force_raycast_update()` 很重要：射线通常依赖物理帧同步，若在本帧移动目标后立即读取 `is_colliding()`，不用它会读到上一帧状态。判据上，代码库应至少同时出现 `body_entered`/`body_exited`、`is_colliding()`、`get_collider()` 三个特征；只检查 `is_colliding()` 时，敌人会把“射线撞到墙”误判为看见玩家。

**听觉应比视觉宽容，但不能无视传播衰减。** 简单方案是玩家奔跑/枪声调用 `hear_event(global_position, intensity)`，只有范围内的敌人接收；复杂方案为声音生成临时 `Area2D` 或事件总线。若项目需要声音绕过墙，听觉距离可大于视线距离；若声音应在实体墙后显著衰减，应让声音源按遮挡层数缩放 `intensity`，而不是重新实现完整声学。

## 10. 转向行为：Seek/Flee/Arrive/Separation

**转向不是寻路，而是把寻路目标转换成有质量的加速度/速度。** 经典公式先计算“期望速度”，再求期望与当前速度的差作为转向力；最终速度应被最大速度和加速度约束。Seek 追求目标，Flee 反向逃离；Arrive 在减速半径内按距离缩放速度；Separation 根据邻居距离倒数生成排斥。Godot 没有内置 `SteeringBehavior` 类，这些通常是自定义的 `RefCounted` 或组件。

```gdscript
# Steering2D.gd
# 纯函数式工具；由调用者负责加速度限制、最大速度与最终移动。
extends RefCounted


static func seek(actor_position: Vector2, current_velocity: Vector2,
        target: Vector2, max_speed: float, weight: float = 1.0) -> Vector2:
    var desired: Vector2 = (target - actor_position).normalized() * max_speed
    return (desired - current_velocity) * weight


static func flee(actor_position: Vector2, current_velocity: Vector2,
        threat: Vector2, max_speed: float, panic_range: float,
        weight: float = 1.0) -> Vector2:
    var to_threat: Vector2 = actor_position - threat
    var distance: float = to_threat.length()
    if distance > panic_range or distance <= 0.0:
        return Vector2.ZERO
    var desired: Vector2 = (to_threat / distance) * max_speed
    return (desired - current_velocity) * weight


static func arrive(actor_position: Vector2, current_velocity: Vector2,
        target: Vector2, max_speed: float, slowing_radius: float,
        weight: float = 1.0) -> Vector2:
    var to_target: Vector2 = target - actor_position
    var distance: float = to_target.length()
    if distance <= 0.0:
        return -current_velocity

    var desired_speed: float = max_speed
    if distance < slowing_radius:
        desired_speed = max_speed * (distance / slowing_radius)
        desired_speed = max(desired_speed, 10.0)

    var desired: Vector2 = (to_target / distance) * desired_speed
    return (desired - current_velocity) * weight


static func separation(actor_position: Vector2, current_velocity: Vector2,
        neighbors: Array, max_speed: float, neighbor_radius: float,
        weight: float = 1.0) -> Vector2:
    var steering: Vector2 = Vector2.ZERO
    var count: int = 0
    for neighbor in neighbors:
        if neighbor == null or not is_instance_valid(neighbor):
            continue
        var neighbor_node: Node2D = neighbor as Node2D
        if neighbor_node == null:
            continue
        var diff: Vector2 = actor_position - neighbor_node.global_position
        var distance: float = diff.length()
        if distance <= 0.0 or distance > neighbor_radius:
            continue
        steering += (diff / distance) / distance
        count += 1

    if count == 0:
        return Vector2.ZERO

    steering /= count
    if steering.length() > 0.0:
        steering = steering.normalized() * max_speed
    return (steering - current_velocity) * weight
```

调用方应采用受控积分，而不是把转向结果直接赋值给 `velocity` 后又被避障覆盖：

```gdscript
var steering: Vector2 = Steering2D.seek(global_position, velocity, target_position, max_speed)
steering += Steering2D.separation(global_position, velocity, nearby_agents, max_speed, 90.0)
velocity += steering * delta
if velocity.length() > max_speed:
    velocity = velocity.normalized() * max_speed
move_and_slide()
```

**转向与 NavigationAgent 不应争夺同一个 `velocity`。** 推荐两种架构之一：第一，让 NavigationAgent 提供长期路径，转向只用于局部接近、暂停和群体散开；第二，规则网格完全由 A* 给出目标点，转向负责到达与群体行为。两者若同时直接写入 `velocity`，导航方向会被分离力盖掉；若同时进入 RVO，又可能重复约束。项目应明确“主控者”：谁负责最终 `velocity`，其他模块只输出建议力。

## 11. 群体避障：RVO 能做什么与不能做什么

**RVO 的“避”是本地预测避让，不是“重新找路”。** `NavigationAgent` 的 `avoidance_enabled` 会注册代理；`velocity` 被提交后，服务器计算避免与其他代理/障碍碰撞的安全速度 [3]。`radius` 是代理自身的避让体积；`neighbor_distance` 是邻居搜索半径；`max_neighbors` 是计算时考虑的最大邻居数；`time_horizon_agents`/`time_horizon_obstacles` 是预测多久内不发生碰撞；`max_speed` 是避障允许的最大速度 [5]。官方指出较大时间范围会让代理过早减速，而所有“agent 前缀”的函数也可用于把障碍物创建为 NavigationServer 代理 [15]。

群体参数应按“单位半径和真实速度”而不是凭外观设定。例如小兵半径为 0.5、最大速度 4，而 `neighbor_distance=50`、`max_neighbors=10`、`time_horizon_agents=1` 只是一个待调起点；若小兵经常穿过彼此，应先提高 `max_speed`、检查回避层和掩码，再做更大范围压测。`neighbor_distance` 过大、`max_neighbors` 过多会让每单位计算成本增加；官方明确，许多注册代理启用避让有显著性能成本，应只给当前需要避让的代理开启 [3]。

**`NavigationObstacle` 是动态/持续移动障碍的最后手段。** 官方说明它适用于因持续移动而无法高效烘焙的物体；静态或偶尔改变的障碍最好重新烘焙，以获得更贴合轮廓的可走面 [15]。动态障碍以 `radius>0` 表示，每帧移动没有额外重建成本，并可设置 `velocity` 帮助预测；静态障碍以顶点轮廓表示，不能每帧移动，否则重建代价高，且传送到代理身上可能卡住。最关键的是：`NavigationObstacle` 不影响寻路路线，只影响避让速度；如果路中央出现一面新墙，必须更新导航网格，单靠障碍会让单位在可走路径上“绕行式拥挤”而找不到真正绕墙的路线。

群体性能分层建议：

1. 只给玩家周围 N 米内、或当前正在移动/交战的单位启用 `avoidance_enabled`。
2. 远处单位使用简单分离、路径跟随或完全静态移动；进入相关区域再启用 RVO。
3. 大量同速单位共享参数资源，避免在 `_physics_process` 中反复创建 `Vector2`、数组和定时器。
4. 动态障碍优先使用 `NavigationObstacle`；门、桥梁、可破坏平台等全局结构变化使用导航网格增量烘焙。
5. 将感知更新、重路径请求和状态检查错开到不同 tick，避免同一帧完成所有敌人的全套 AI。

## 12. 反直觉坑：本能以为 X，实际 Y

1. **本能以为设置 `target_position` 后敌人会自动移动；实际 NavigationAgent 只计算路径，不会移动父节点。** 官方明确要求用 `get_next_path_position()` 得到下一步，再使用自己的移动代码 [1]。判据：代码里出现 `target_position=` 却没有 `move_and_slide()`/`velocity` 写入。

2. **本能以为关闭避障时也会收到 `velocity_computed`；实际官方明确该信号只在 `avoidance_enabled=true` 且速度被处理后发出。** 若信号未连接，敌人不会自动移动；连接后还可能在非避障分支执行两次移动 [3]。判据：`avoidance_enabled=true` 必须与 `velocity_computed.connect` 成对。

3. **本能以为 `_ready()` 里设置目标就能立即得到路径；实际 NavigationServer 要等待物理帧同步，立即查询可能返回空路径。** 官方教程使用 `call_deferred` 和 `await get_tree().physics_frame` [12]。判据：`_ready()` 中直接调用 `target_position=` 且没有延迟/同步等待。

4. **本能以为 `NavigationObstacle` 会令寻路绕开障碍；实际它只影响避让速度，不改变路径。** 持续移动物体适合障碍，静态/偶尔变化的结构应重新烘焙导航面 [15]。判据：关卡逻辑修改墙壁却只新增 Obstacle 节点。

5. **本能以为每帧 `set_point_solid()` 后必须 `update()`；实际改变阻挡不会使 AStarGrid2D 变脏。** 但改变 `region`/`cell_size`/`offset`/`cell_shape` 后必须 `update()`，且会丢失原生实心/权重，必须重放真实数据 [13]。判据：动态阻挡后调用 `update()` 是无谓开销；结构变化后不重放才是数据丢失。

6. **本能以为 `path_desired_distance` 越小越精确；实际过小而单位速度过快会反复越过路径点，导致抖动甚至重路径死循环。** 官方建议让速度对应单帧位移保持合理，并对距离阈值做调参 [1]。判据：`speed / Engine.physics_ticks_per_second` 明显大于 `path_desired_distance`。

7. **本能以为 `RayCast2D.is_colliding()` 为真就是看见玩家；实际射线可能撞到墙、另一敌人或道具。** 必须与 `get_collider() == target` 组合；移动目标后还要 `force_raycast_update()` [20]。判据：只存在 `is_colliding()` 而没有目标身份判断。

8. **本能以为导航多边形边缘就是角色可站立边缘；实际它是角色中心的安全区域，不自动包含碰撞体体积。** 官方明确导航只描述代理可安全经过的区域；贴边会导致角色体卡墙 [6]。判据：导航面边界与 `CollisionShape` 边界完全共线。

9. **本能以为链接能让代理自动播放跳跃/传送；实际链接只改变寻路成本与连通性。** 动画、冷却、失败回退必须由项目实现 [8]。判据：只有 `NavigationLink2D/3D` 节点而没有 `link_reached` 处理。

10. **本能以为 RVO 障碍必然被严格遵守；官方说明动态障碍是“请离我远点”的软避让，在拥挤或狭窄空间并非可靠约束。** 狭窄门、必须不能进入的区域应来自导航网格和可走性，而非依赖 RVO [15]。判据：用 `NavigationObstacle` 限制关键通道。

## 13. 集成清单与代码审查判据

**代码审查不应只检查“能否跑起来”，而应检查导航、状态、感知、物理四层是否单一职责。** 导航组件只负责路径与移动；状态组件只决定目标、攻击和返回；感知组件只产生“看见/听见/丢失记忆”；物理组件负责碰撞响应。若一个脚本同时直接设置 `agent.target_position`、修改 `velocity`、播放动画、计算视线并执行伤害，后续几乎无法扩展。

建议的审查清单：

- 正则 `target_position\s*=`：其后是否有导航更新逻辑，而非自动移动假设。
- 正则 `velocity_computed\.connect`：是否缺少；`avoidance_enabled=true` 时是否有两处移动。
- 正则 `get_next_path_position\(\)`：是否每物理帧一次，是否在 `waypoint_reached` 回调中重复调用。
- 正则 `is_navigation_finished\(\)`：到达后是否清零 `velocity`；非导航目标是否被错误复用。
- 正则 `set_point_solid\(`/`update\(\)`：真实障碍数据是否有单一事实源；结构更新后是否重放。
- 正则 `RayCast2D|is_colliding`：是否有 `get_collider()` 身份判断；目标移动后是否 `force_raycast_update()`。
- 正则 `avoidance_enabled\s*=\s*true`：性能是否受控，是否仅对需要单位开启；`max_speed` 是否不低于实际速度。
- 正则 `bake_navigation_polygon|bake_navigation_mesh`：是否位于热路径、是否监听完成信号、是否做了区域化或节流。
- 状态转换：退出状态是否清理 `target_position` 和速度；进入状态是否重置记忆计时器。

## 14. 版本与生态边界

**Godot 4.x 没有内置行为树，也没有 GOAP 节点。** AnimationTree 内置的状态机适合动画状态，不能被当作通用 AI 状态机 [10]。LimboAI 与 Beehave 是社区常见行为树方案：前者偏资源化、可视化编辑器与原生实现，适合大量代理和较复杂树；后者由 Godot 节点构成，学习成本低但每个代理持有一棵活动节点树，规模更大时更重 [10]。选择时还应检查插件支持的具体 Godot 小版本、GDExtension 与 C# 兼容性和导出模板；不要假设插件支持所有 4.x 版本。

GOAP 同样由社区 GDScript 插件提供，采用目标优先、运行期规划动作链的思路；它适合需要可组合行为的中大型项目，但不应作为第一个敌人原型。对两三个敌人，枚举 FSM 的开发、调试和维护成本通常更低；对大量同质小兵，NavigationAgent + RVO 可能已足够；当行为需要“在多个目标间选择、动作可复用、条件变化后重新规划”，行为树或 GOAP 才值得引入额外依赖。

最后，本报告依据 4.x 官方教程和截至 4.2 的离线类参考核对；导航服务器内部 `agent_set_target()` 的精确公开签名未在当前核对材料中找到，标记为待核对，不应直接复制到生产代码。合并时应以目标引擎 `Godot -> 查看文档` 导出的类 XML/在线类参考为准，并针对 4.3、4.4、4.5 的导航类变更做差量扫描。

## 引用来源

[1] https://docs.godotengine.org/en/4.4/tutorials/navigation/navigation_using_navigationagents.html
> “The navigation system never moves the parent node of a NavigationAgent. The movement is entirely in the hands of users and their custom scripts.”

[2] https://docs.godotengine.org/en/4.0/tutorials/navigation/navigation_using_navigationservers.html
> “The simplified order of execution for NavigationAgents that use avoidance: physics frame starts… Agent sends velocity and position to NavigationServer… Agents receive the signal and move their parent.”

[3] https://docs.godotengine.org/en/4.1/classes/class_navigationagent2d.html
> “Only emitted when avoidance_enabled is true.”

[4] https://docs.godotengine.org/en/4.2/classes/class_navigationregion2d.html
> “void bake_navigation_polygon(bool on_thread=true) Bakes the NavigationPolygon.”

[5] https://docs.godotengine.org/zh-tw/4.5/tutorials/navigation/navigation_using_navigationagents.html
> “radius 屬性設定代理體迴避圓的半徑…max_speed 屬性決定代理體避障運算時允許的最大速度。”

[6] https://docs.godotengine.org/en/4.0/tutorials/navigation/navigation_using_navigationmeshes.html
> “A navigation mesh describes the traversable safe area for an agent with its center position at zero radius.”

[7] https://docs.godotengine.org/en/4.2/classes/class_navigationpolygon.html
> “NavigationPolygon = newNavigationMesh; Adding vertices and polygon indices manually.”

[8] https://docs.godotengine.org/en/4.1/classes/class_navigationlink2d.html
> “Links are useful to express navigation methods other than traveling along the surface of the navigation polygon, such as ziplines, teleporters, or gaps that can be jumped across.”

[9] https://godot.readthedocs.io/en/stable/tutorials/navigation/navigation_introduction_2d.html
> “The NavigationServer is best suited for 2D realtime gameplay that does require actors to reach any possible position within a navigation mesh defined area.”

[10] https://www.behaviortrees.com/learn/behavior-trees-in-godot
> “Unlike Unreal, Godot has no built-in behavior tree system.”

[11] https://docs.godotengine.org/en/4.2/classes/class_astar2d.html
> “An implementation of A* for finding the shortest path between two vertices on a connected graph in 2D space.”

[12] https://godot.readthedocs.io/en/stable/tutorials/navigation/navigation_using_navigationservers.html
> “Each added or changed map, region or agent need to be registered with the NavigationServer.”

[13] https://vav-labs.com/blog/runtime-astargrid2d-updates-without-full-rebuilds
> “Call update() after changing the grid's structure: region, cell_size, offset, or cell_shape.”

[14] https://docs.godotengine.org/en/4.0/tutorials/navigation/navigation_using_navigationmeshes.html
> “Multiple outlines can be added to the same NavPolygon resource as long as they do not intersect or overlap.”

[15] https://docs.godotengine.org/en/4.2/tutorials/navigation/navigation_using_navigationobstacles.html
> “NavigationObstacles do not change or influence the pathfinding in any way. NavigationObstacles only affect the avoidance velocities of agents controlled by avoidance.”

[16] https://docs.godotengine.org/en/4.0/tutorials/navigation/navigation_using_navigationpaths.html
> “To obtain a 2D path, use NavigationServer2D.map_get_path(map, from, to, optimize, navigation_layers).”

[17] https://docs.godotengine.org/en/4.1/tutorials/navigation/navigation_different_actor_types.html
> “Agents are exclusively defined by a radius and height value for baking navigation meshes, pathfinding and avoidance.”

[18] https://docs.godotengine.org/en/4.2/classes/class_astargrid2d.html
> “To remove a point from the pathfinding grid, it must be set as ‘solid’ with set_point_solid.”

[19] https://godot-es.readthedocs.io/es/4.x/classes/class_astargrid2d.html
> “DIAGONAL_MODE_NEVER… the path will always be orthogonal.”

[20] https://docs.godotengine.org/en/4.1/classes/class_raycast2d.html
> “force_raycast_update() Updates the collision information for the physics server’s next frame.”
