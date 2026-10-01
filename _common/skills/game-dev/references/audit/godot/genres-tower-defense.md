<!-- oversize-exempt: 反模式清单，审核用 -->
# genres-tower-defense — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/genres-tower-defense.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 每只怪 `NavigationAgent2D.target_position=goal` 就自动走 （→ `ai-navigation.md`）| agent 只给路径，移动要自己写并调 `move_and_slide()` |
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
| 14 | 建塔后立刻 `map_get_path()` 就能拿到新路径 | 官方：地图默认只在**物理帧末**同步。要立即生效可 `map_force_update()`，⛔ 但它会 flush **整个** NavigationServer 命令队列（含其他地图/区域/代理），官方警告「严重影响性能并可能引入 bug」；⛔ **不是每放一塔调一次**，只在批量建拆后调一次 |
| 15 | `optimize=false` 是网格的通用正确答案 | 官方：false 时路径点落在多边形边中点，⛔ **网格之外**多边形常以单条长边覆盖大片开阔区，会产生**不必要的绕远**；true 的 funnel 在小格子网格上会产生难看拐角。⛔ 判据是「等大网格 + 纯格子移动」用 false，自由移动用 true |
| 16 | `path_desired_distance` 用默认 20 就行 | 官方：⛔ **设太高会跳过路径点、走出导航网格**；⛔ **设太低会陷入重寻路循环**（每帧都过冲）。两种都不报错：前者表现为怪走到墙里，后者表现为帧率莫名下降 |
| 17 | 避让默认开着，只要调 `max_speed` 就行 | 官方：`avoidance_enabled` 默认 **`false`**。⛔ 不显式打开的「避让优化」全部无效，而 `max_speed` 面板上确实写着 100 —— 看着像配好了 |
| 18 | `intersect_shape` 查不到就是没有怪 | 官方两个静默边界：⛔ **已重叠的形状被忽略**（贴脸刷出的怪查不到，官方给的补法是 `collide_shape()`）；⛔ `max_results` 默认 **32**，超出**静默截断不报错**，密集时表现为「塔偶尔不攻击」 |
| 19 | 路被塔封死后怪会自己绕 / 会报错 | `AStarGrid2D.get_id_path` 的 `allow_partial_path` 默认 **false** → ⛔ 目标不可达时返回**空数组**，怪原地不动**且不报错**，`is_point_solid` 与路径缓存全绿 |
| 20 | 封路是玩家的事，建塔只管占位 | ⛔ 必须在**建塔前**用同一张图验证「放下后所有出生点仍可达」，否则拒绝建造。⛔ 事后发现封死再处理等于接受「怪卡住不动」这个已发生状态 |
| 21 | 波次写成硬编码数组字面量就行 | ⛔ 改一个数要先读代码才知道第几位是什么，而改波次是**每次迭代都发生**的事。要用 `Wave`/`SpawnGroup` Resource 承载 `count / interval / path_id`，⛔ `path_id` 要在波次里就定下（它是路径缓存键，两种含义会让缓存串味） |
| 22 | 击杀后先归还池再发奖励（顺序无所谓） | ⛔ 先归还再发奖励会出现「奖励发给了复用出来的那只新怪」（池里是同一个对象），表现为偶尔多拿一次奖励，而日志里每笔奖励都有合法的怪 ID。⛔ 死亡表现挂在怪上也会随归还被回收，表现为怪多了没有死亡特效 |
