<!-- oversize-exempt: 反模式清单，审核用 -->
# 2d-rendering — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/2d-rendering.md`

## 常见漏写

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | `y_sort_enabled` 开在子节点 | 不排序 | 人工 |
| 2 | 排序对象不在同一父节点 | 不互排 | 人工 |
| 3 | 原点不在脚底 | 角色半身陷进物体 | 人工 |
| 4 | 改 Parallax2D 的 `position` | 被相机逻辑覆盖 | 人工 |
| 5 | 4.x 里写 `SCREEN_TEXTURE` | 编译错误 | 人工 |
| 6 | `set_shader_parameter` 名拼错 | 静默失效 | GD64 |
| 7 | hitstop 的 timer 未 `ignore_time_scale` | 游戏永久卡死 | 人工 |
| 8 | 转场 ColorRect 未设 `mouse_filter` | 挡住点击 | 人工 |
| 9 | `Light2D`（3.x 类名） | 4.x 已拆分 | GD34 |
| 10 | 描边未留透明边距 | 视觉与碰撞体不符 | 人工 |
