<!-- oversize-exempt: 反模式清单，审核用 -->
# genres-roguelike — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/genres-roguelike.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 生成后直接 `set_cell` 刷满整张图 | 失败难回滚且多次重算，要先建纯数据中间表示再批量提交 |
| 2 | `randi()`/`randf()` 当确定性随机 | 与 `RandomNumberGenerator` 是不同状态，混用不复现 |
| 3 | 摆放房间失败后不还原 RNG | 一次失败尝试污染后续序列，同种子不再复现 |
| 4 | `AStar2D` 与 NavigationServer 混用 | 两套独立 API，官方明确 NavigationServer 不处理 AStar |
| 5 | 房间坐标不对齐 cell_size | 走廊连接点落非格心，A* 图无法对齐 |
| 6 | 生成时开着 `navigation_enabled` | 每个 set_cell 触发导航更新，要先关后开 |
| 7 | Meta 进度只在退出时存一次 | 崩溃/强杀会丢，关键节点变化即存 |
| 8 | 直接覆盖写存档文件 | 崩溃留下半截文件，要写临时文件 + 原子重命名 |
| 9 | `FLAG_COMPRESS` 当加密 | 是压缩不是加密，玩家可改本地文件 |
| 10 | 道具池每次重算总权重 | O(n)，要用累积权重二分或别名法 |
| 11 | 连通性校验后期补 | 防卡关是生死线，要在设计阶段写进检查清单 |
| 12 | 生成期大量 Array/Dictionary 分配 | 进入新层时 GC 尖峰，要预分配复用 |
