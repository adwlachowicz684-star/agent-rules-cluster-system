<!-- oversize-exempt: 反模式清单，审核用 -->
# genres-bullet-hell — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/genres-bullet-hell.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 每颗子弹一个 `Area2D` | 千个 Area2D = 千个每帧回调，最典型死法 |
| 2 | 每帧 `instance_count = n` | 会清空重分配整个 buffer，抵消合批收益 |
| 3 | 玩家 `Area2D` 检测每颗子弹 | 几千次 enter/exit 信号分发，要只查判定点 |
| 4 | `intersect_point` 默认 32 够用 | 密集弹幕会被截断，要提高或先粗筛 |
| 5 | 判定点等于精灵中心 | 常见 2-4px 且要单独渲染提示 |
| 6 | 擦弹与命中用同一半径 | 是两个独立半径，不可混 |
| 7 | 弹幕逻辑用 `delta` | 对帧率敏感且要确定性回放，要固定逻辑步长 |
| 8 | 图案写成一串 `for` 循环 | 要 BulletPattern Resource + 时间轴发射器 |
| 9 | 每帧改 `set_instance_color` | 仍走缓冲区，单色用纹理 + shader 参数分组 |
| 10 | 所有节点每帧 `queue_redraw()` | CanvasItem 不需要每帧重绘，要分层 |
| 11 | GDScript 硬扛 3000 颗 | 通常撑不住，要 PackedFloat32Array 或 C#/GDExtension |
| 12 | `instance_count` 定完再开 `use_colors` | 官方：只能在 `instance_count` 为 0 及以下设置，否则逐实例颜色**静默不生效** |
| 13 | 复用槽位直接改 transform 就行 | 插值下会从上一帧位置滑过来，必须 `reset_instance_physics_interpolation()`（官方举例即 bullet） |
| 14 | 累加器能追上就行 | `max_physics_steps_per_frame` 默认 8 就是防 spiral of death，⛔ 自写累加器无上限会越追越慢 |
| 15 | 提高 `physics_ticks_per_second` 更准 | 官方不建议超 240：渲染低于 30 FPS 时游戏整体变慢，除非同步改 `max_physics_steps_per_frame` |
| 16 | 遍历里顺手回收不影响 | 边遍历边改活跃索引会错位，表现为“偶尔少一颗 / 多一颗”，且不报错 |
| 17 | 图案时间轴用秒 | 用秒会因浮点累积让回放密度不同，要用**逻辑 tick 计数** |
| 18 | 任何碰撞形状都能被查到 | Segments build mode 的 `CollisionPolygon2D` 与 `ConcavePolygonShape2D` 不是 solid，`intersect_point` 不检测 |
| 19 | 发射器参数写在发射函数里 | 写死则图案不可复用、不可预览，要 Resource 化 |
| 20 | 图案直接 `set_instance_transform` | 图案层只产出 spawn 请求，⛔ 直接碰渲染会让图案与规模档耦合 |
| 21 | 分裂弹想分几层分几层 | 递归无深度上限会被指数级放大，一帧内打满上限 |
| 22 | 图案调参就跑一遍看 | 没有 seek / 预览只能整段重跑，调一个角度要几十秒 |
| 23 | `set_instance_transform` 通用 | `TRANSFORM_2D` 格式要用 `set_instance_transform_2d()`，传错类型报错或画错 |
| 24 | C# 里每颗子弹一个类 | 要用值类型 / 结构体数组才有意义，否则不如直接上 GDExtension |
| 25 | GDExtension 用 `Array[Vector2]` 就行 | 要 SoA 布局 + 分块才有 SIMD 收益，AoS 与 GDScript 差别不大 |
| 26 | 打满就扩容 | `MAX_BULLETS` 是硬上限，⛔ 运行时扩容等于重分配 buffer，必须丢弃或复用最旧 |
| 27 | 弹幕占满帧预算 | 弹幕吃掉整帧预算会让敌机 AI / 掉落变卡，要按档位定预算上限 |
