<!-- oversize-exempt: 反模式清单，审核用 -->
# genres-rts — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/genres-rts.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 指令队列用信号串起来 | 信号只适合"已发生"，不适合"待执行意图"，要用显式数据结构 |
| 2 | `Camera2D.screen_to_world_point()` | 没有这个方法，要用 `get_screen_transform().affine_inverse()` |
| 3 | 用 `Area2D` 套选框 | 框选是屏幕矩形 + 世界坐标转换 + `Rect2.has_point()` |
| 4 | `Rect2.has_point()` 边界算包含 | 约定右/底边缘不算，要手动加容差 |
| 5 | 编队把所有单位指同一目标点 | RVO 能缓解但引入抖动，要算偏移位各自寻路 |
| 6 | `Light2D` 能做战争迷雾 | 那是 2D 光照阴影，迷雾要独立格子状态 + 批量脏区提交 |
| 7 | 每帧 `get_nodes_in_group("units")` | 全树扫描，应持有 `Array[Unit]` |
| 8 | 1000 个 `CharacterBody2D` 各跑物理 | 要按规模分三档降级，>800 走逻辑网格 + MultiMesh |
| 9 | 2D RTS 靠 Jolt 加速 | Jolt 是 3D 默认物理，2D 默认仍是 Godot Physics |
| 10 | 每帧各单位写一次 `set_cell` 更新视野 | 反复触发重算，要脏区批量提交 |
| 11 | 迷雾层开 `navigation_enabled` | 会生成无意义导航区域，要关掉 |
| 12 | `intersect_point()` 默认够用 | 默认 max_results=32，密集单位会被截断 |
