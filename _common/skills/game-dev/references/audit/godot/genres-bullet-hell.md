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
