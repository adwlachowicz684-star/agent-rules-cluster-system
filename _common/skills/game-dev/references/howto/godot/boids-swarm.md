# 群集行为（boids）与 NavigationAgent 避障（Godot 4.7.2）

**此前文档里「群集 / boids / 群体行为」0 命中；避障在 `ai-navigation.md` 有提及但无参数级说明。**

⚠ **Godot 没有 boid 节点**，群体行为要自己写。

> 关节/约束/载具参数见 `vehicle-physics.md`；水面浮力见 `environment-systems.md`。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/boids-swarm.md`

## 1. 群集 boids

三规则（Reynolds 1987）：
- **Separation** 避免个体过近
- **Alignment** 趋近邻居平均朝向
- **Cohesion** 趋近邻居平均位置

```gdscript
acceleration += w_sep * separation + w_align * alignment + w_coh * cohesion + w_goal * goal
velocity += acceleration * delta
```

⚠ **分离要按距离倒数或平滑截断加权**，不能只取平均位置 —— 否则个体互相粘死。
⚠ 三规则是**局部行为，不是完整 AI**。

### 邻居查询必须裁剪，不能 O(n²)

三级优化：
1. **固定网格**：`cell_size = max_perception_radius`，只查自身 cell + 3×3（2D）/27（3D）邻域 → 接近 O(n+k)
2. `PhysicsServer2D/3D` 的 shape query 做半径查询 → ⚠ 别把"物理重叠"当"视觉感知"
3. 超大规模用 `MultiMesh` + 连续数组存状态，别用大量 Node

⚠ **分层：Navigation 决定"去哪里"，boids 决定"怎样一起走"。**
路径方向 → goal steering → 叠加分离/对齐/聚合 → 送 RVO。
⚠ **不要把 RVO 输出再作为 NavigationServer 的目标点** —— 会形成反馈环。

⚠ **降频比加实例数更有效**：近处每物理帧、中距每 2–4 帧、远处只跟随目标（关分离）、屏幕外暂停。
⚠ 避免用 `randf()` 抖动所有单位 —— 会造成群体同步相位；给每个 boid 独立相位或固定种子索引。

## 2. NavigationAgent 避障：基础流程

⚠ **下面这段代码有个前置条件：必须先设 `target_position`**
（见 ①），否则 `safe_velocity` 恒为零。


⚠ **正确流程是"提交期望速度 → 接收安全速度 → 自己移动"**：

```gdscript
agent.avoidance_enabled = true
agent.velocity_computed.connect(_on_velocity_computed)

func _physics_process(_d):
    agent.set_velocity(desired_velocity)

func _on_velocity_computed(safe_velocity: Vector3) -> void:
    velocity = safe_velocity      # ⚠ 必须自己移动父节点
```

⚠ `avoidance_enabled` **默认 false**，不打开就是没有避障。

| 属性 | 3D 默认 | 2D 默认 |
|---|---:|---:|
| `max_speed` | 10.0 | 100.0 |
| `radius` | 0.5 | 10.0 |
| `neighbor_distance` | 50.0 | 500.0 |
| `max_neighbors` | 10 | 10 |
| `time_horizon_agents` | 1.0s | 1.0s |
| `use_3d_avoidance` | false | — |

⚠ **`radius` 要匹配实际碰撞/避障包围圆，`max_speed` 要 ≥ 实际最高速度**
→ 否则 RVO 无法保证不碰撞，单位会互相重叠。

⚠ **静态障碍与动态障碍不可互换**：
- 静态 `NavigationObstacle` 由 `vertices` 定义多边形，是硬边界，**不能每帧移动**（重建成本高，瞬移会把代理卡在边界内）
- 动态障碍由 `radius>0` 定义（2D 圆 / 3D 球），是软排斥，可每帧移动；设 `velocity` 能让其他代理预测

→ 会移动的物体：删掉静态顶点、启用半径；到新位置后再恢复静态几何。

⚠ **静态关卡几何优先烘焙到 NavigationMesh**，别全用运行时障碍。
把整张地图的 tile 每帧当动态障碍 → 避障与寻路双重开销。

⚠ **传送时要同帧调用 `set_velocity_forced()`**，否则代理会基于旧速度继续预测避让。
⚠ 但**不要每帧调用 forced** —— 会破坏预测，导致互相抖动或卡住。

⚠ **没有统一的性能拐点数字**（官方只警告"大量注册代理有显著开销"）。
控制手段：只给需要的代理开 `avoidance_enabled`；`max_neighbors` 从 10 起；远处单位退化为跟随领队；屏幕外暂停 RVO。

## 3. NavigationAgent 避障：官方教程里六条文档没有的

### ⚠ ① 只用避障也必须设 `target_position`

官方原话：

> *"The NavigationAgent must be supplied with a `target_position` attribute,
> even if you are only using the agent for avoidance. **Otherwise, the
> safe_velocity received from the `velocity_computed` signal will always be
> the zero vector**."*

⚠ **症状极具迷惑性**：你按教程接了 `velocity_computed`、设了
`avoidance_enabled = true`、每帧 `set_velocity()`，然后——
**单位一动不动**。没有报错，信号确实在发，只是永远是 `(0,0,0)`。

⛔ 排查方向很容易被引到"信号没接上""velocity 算错了"，
而根因只是"没设目标点"。

✅ 纯避障场景（如群体跟随、没有寻路目标）也要给一个
**占位目标点**，否则拿不到安全速度。

### ⚠ ② `radius` 是身体半径，**不是**避让距离

官方原话：

> *"The property `radius` controls the radius of the avoidance circle...
> **This area describes the agents body and not the avoidance maneuver
> distance.**"*

⚠ 这条纠正了一个非常普遍的误解：把 `radius` 调大想让单位"躲得更开"。

⛔ 实际后果：radius 过大 → 单位之间**保持一个巨大的空档**，
看起来像互相排斥而不是避让；且 `max_neighbors` 会更快耗尽。

✅ 想控制"提前多远开始躲"，靠的是 `time_horizon_*`，不是 `radius`。

### ⚠ ③ `time_horizon` 越低越好——它是"减速承诺"

官方原话：

> *"...they choose velocities that can be kept for this amount of seconds
> without colliding... **The prediction time should be kept as low as
> possible as agents will slow down their velocities** to avoid collision
> in that timeframe."*

⚠ **这条解释了"单位走路畏畏缩缩"**：time_horizon 开大了，
RVO 为了保证"未来 N 秒内都不撞"，会**主动把速度降下来**。

ⓘ 表现：单位在没有障碍的空地上也走不快。
⛔ 很容易被误判为"max_speed 没设对"。

✅ 调参顺序：**先把 time_horizon 压到最低，再往上加一点点**，
而不是从 1.0 往下试。

### ⚠ ④ 2D 避障与 3D 避障是**两个互不相通的模拟**

官方原话：

> *"**2D avoidance and 3D avoidance run in separate avoidance simulations
> so agents split between them do not affect each other.**"*

⚠ 后果：`use_3d_avoidance` 不一致的单位**会直接穿过彼此**。

⛔ 这是最难发现的一类：项目里一部分单位（飞行的）开了 3D、
另一部分（地面）用 2D，飞行单位与地面单位**互相无视**，
而同类之间避障正常 —— 看起来像"随机有时会穿模"。

✅ 判据：**全项目的 `use_3d_avoidance` 必须一致**，
除非你明确要让两类互不干扰。

ⓘ 3D 专属属性 `height`：与全局 y 坐标一起决定垂直放置；
用 2D 避障时会自动忽略上/下方的其他 agent。

### ⚠ ⑤ RVO 对"自然行为"有隐含假设——**对冲测试必然失败**

官方原话：

> *"RVO avoidance makes implicit assumptions about natural agent behavior...
> **very clinical avoidance test scenarios will commonly fail**. E.g.
> agents moved directly against each other with perfect opposite velocities
> will fail because the agents can not get their passing sides assigned."*

⚠ **这条救了无数个小时的调试时间。**

⛔ 你写的测试："两个 agent 正对着走，看会不会撞" → **必然撞**。
这不是 bug，是 RVO 的原理决定的：完全对称时无法决定各自往哪边让。

✅ 正确的测试方法：**轻微不对称**（错开一点、速度略有差异），
或观察真实场景而不只是单元测试。

ⓘ 也解释了为什么"加一点随机抖动"能改善观感 —— 它打破对称。

### ⚠ ⑥ 避障**不知道**导航网格和物理碰撞的存在

官方原话：

> *"**Avoidance exists in its own space and has no information from
> navigation meshes or physics collision.** Behind the scene avoidance
> agents are just circles... on a flat 2D plane or spheres in an otherwise
> empty 3D space."*

⚠ 三条直接推论：

| 推论 | 后果 |
|---|---|
| 避障不会帮你绕开墙体 | 墙必须由 `NavigationObstacle` 或烘焙进 NavMesh |
| ⛔ 物理碰撞体**不参与**避障 | 加了 `CollisionShape` 也不影响避障 |
| 只有**注册避障的同地图** agent 才会被考虑 | 没开 `avoidance_enabled` 的单位对别人是透明的 |

ⓘ 最后一条的官方原话：*"Only other agents on the same map that are
registered for avoidance themself will be considered."*

⚠ 还有：**避障不影响寻路**（官方明确）。
它只是给"无法高效烘焙进 NavMesh 的持续移动物体"绕行的补充手段。
⛔ 不要用避障去解决"路径穿墙"问题。

### 避障属性速查（含义按官方口径修正）

| 属性 | 官方含义 | ⚠ 易误解成 |
|---|---|---|
| `radius` | 代理**身体**半径 | 避让距离 |
| `neighbor_distance` | 搜索半径，低值省开销 | — |
| `max_neighbors` | 同时考虑几个；**太低会忽略避障** | — |
| `time_horizon_agents` | 保持多久不撞；**越低越好** | 越大越安全 |
| `time_horizon_obstacles` | 同上，对障碍 | — |
| `max_speed` | 父节点超过它 → safe_velocity 不准 | — |
| `use_3d_avoidance` | ⚠ **切换后进入另一个独立模拟** | 只是精度选项 |
| `height`（3D） | 与 y 坐标决定垂直放置 | — |
| `avoidance_layers/mask` | 位掩码，与物理层同理 | — |
| `avoidance_priority` | ⚠ **高优先级"忽略"低优先级** | 只是让路顺序 |

ⓘ `avoidance_priority` 是编队与 Boss 的工具：给重要 NPC 高优先级，
它就不用被小兵推着走，⛔ 不必手写推挤逻辑。

### 服务器级切换（官方给的写法）

⚠ **官方推荐用 `avoidance_enabled` 属性切换，而不是直接操作
`NavigationServer`**。文档给出的服务器级代码是给需要动态创建/删除
回调的场景：

```gdscript
var agent: RID = get_rid()
NavigationServer2D.agent_set_avoidance_enabled(agent, true)
NavigationServer2D.agent_set_avoidance_callback(agent, Callable(self, "_avoidance_done"))
```

ⓘ 删除回调要显式 `agent_set_avoidance_callback(agent, Callable())`。

## 4. 路径位置"在身后"：精度问题不是 bug

官方原话：

> *"expect path positions to be sometimes slightly 'behind' your actors
> current orientation. This happens due to **precision issues and can not
> always be avoided**."*

⚠ **只有当你把角色"瞬时旋转朝向路径点"时才会被看见**（官方原话）。

✅ 两条应对：
- 给转向加平滑（不要瞬时对齐）
- ⛔ 不要试图"修掉"这个精度问题 —— 官方明确说无法完全避免
