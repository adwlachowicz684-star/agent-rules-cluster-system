# 群集行为（boids）与 NavigationAgent 避障（Godot 4.7.2）

**此前文档里「群集 / boids / 群体行为」0 命中；避障在 `ai-navigation.md` 有提及但无参数级说明。**

⚠ **Godot 没有 boid 节点**，群体行为要自己写。

> 关节/约束/载具参数见 `vehicle-physics.md`；水面浮力见 `environment-systems.md`。

> 审核用反模式清单见 `audit/godot/boids-swarm.md`

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

## 2. NavigationAgent 避障

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
