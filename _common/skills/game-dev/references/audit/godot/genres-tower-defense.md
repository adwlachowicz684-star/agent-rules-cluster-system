<!-- oversize-exempt: 反模式清单，审核用 -->
# genres-tower-defense — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/genres-tower-defense.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 每只怪 `NavigationAgent2D.target_position=goal` 就自动走 | agent 只给路径，移动要自己写并调 `move_and_slide()` |
| 2 | 建塔后怪立刻重算路径 | NavigationServer 改动要下一物理帧才生效，要 `map_force_update()` |
| 3 | `body.name=="Enemy"` 做伤害分发 | TileMap 配了碰撞也会触发 `body_entered`，要用接口 |
| 4 | `get_nodes_in_group("enemies").is_empty()` 判波次清 | 池里休眠怪、退场怪污染计数，要显式计数 |
| 5 | 每只怪独立寻路 | 同起终点路径缓存，只有路径被破坏才重算 |
| 6 | 用 `Timer` 串 0.05 秒刷 50 只 | Timer 每帧最多处理一次超时，要用累加器 |
| 7 | `body_entered` 做高频实时索敌 | 20 塔 × 200 怪是信号风暴，要降频 shape query |
| 8 | `intersect_shape` 能查到贴脸的怪 | 它忽略形状内部已重叠对象，要单独处理 |
| 9 | 建筑频繁增删用 carving 切导航网格 | 改 `AStarGrid2D` 点权重便宜得多 |
| 10 | 屏幕外怪 `if not active: return` | 要 `set_physics_process(false)` |
| 11 | 敌人一律用 `CharacterBody2D` | 无推挤需求时纯路径插值更省 |
| 12 | `optimize` 参数随便填 | true 走 funnel（自由移动），false 落边中点（格子移动）|
| 13 | 开避让就用默认 `max_speed` | 默认只有 100 px/s，不配会挤成一团 |
