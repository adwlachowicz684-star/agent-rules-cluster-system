<!-- oversize-exempt: 反模式清单，审核用 -->
# boids-swarm — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/boids-swarm.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | Godot 有 boid 节点 | **没有**，要自己写 |
| 2 | boids 全量两两比较 | O(n²)，要用网格 `cell_size = 感知半径` |
| 3 | 分离取平均位置 | 会互相粘死，要**按距离倒数加权** |
| 4 | 三规则就是完整 AI | 只是**局部行为**，目标层仍要 Navigation |
| 5 | RVO 输出再喂 NavigationServer | 形成**反馈环** |
| 6 | 用 `randf()` 抖动所有单位 | 造成**群体同步相位**，要各自独立相位 |
| 7 | 用形状查询当"视觉感知" | 那是**物理重叠**，不是感知 |
| 8 | 大规模用大量 Node | 要 MultiMesh + 连续数组 |
| 9 | `avoidance_enabled` 默认开 | **默认 false**，不开就是没避障 |
| 10 | 收到 `velocity_computed` 会自动移动 | 要**自己移动父节点** |
| 11 | `radius`/`max_speed` 用默认值 | 要匹配实际尺度，否则**互相重叠** |
| 12 | 静态障碍能每帧移动 | 重建成本高，瞬移会把代理**卡在边界内** |
| 13 | 所有墙都用运行时障碍 | 优先**烘焙到 NavigationMesh** |
| 14 | 传送后不用管 | 要同帧 `set_velocity_forced()` |
| 15 | 每帧调 `set_velocity_forced()` 更快 | 破坏预测 → 互相抖动或卡住 |
| 16 | `max_neighbors` 越大越好 | 从 10 起，成本随平方涨 |
