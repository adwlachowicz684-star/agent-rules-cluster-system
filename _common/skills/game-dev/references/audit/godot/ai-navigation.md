<!-- oversize-exempt: 反模式清单，审核用 -->
# ai-navigation — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/ai-navigation.md`

## 常见漏写

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | 每帧重设 `target_position` | 敌人原地抖 | 人工 |
| 2 | `RayCast` 改完未 `force_raycast_update` | 隔墙能看见 | GD23 |
| 3 | 开避障时自己又 `move_and_slide()` | 重复积分，速度翻倍 | 人工 |
| 4 | 目标已释放只判 `if _target` | 访问已释放对象 | 人工 |
| 5 | `lose_range` ≤ `detect_range` | 边界反复横跳 | 人工 |
| 6 | `AStarGrid2D` 改了不 `update()` | 不生效 | 人工 |
| 7 | 导航多边形不重新烘焙 | 改了地形寻路还是走旧的 | 人工 |
| 8 | 状态转换散在各处 | 调试时理不清 | 人工 |
| 9 | `patrol_points` 为空 | `% 0` 除零崩溃 | 人工 |
| 10 | 避障一直开着最安全 | 官方：大量 agent 有**显著开销**；只给需要的开，远处可关 |
| 11 | 只用避障不设 `target_position` | 官方：`safe_velocity` **恒为零向量** → 单位一动不动、信号却在发、不报错 |
| 12 | 到达后继续调 `get_next_path_position()` | 官方：会让 agent **jitter in place** |
| 13 | 在 `waypoint_reached` 回调里调它 | 官方：会触发重算 → **无限递归** |
