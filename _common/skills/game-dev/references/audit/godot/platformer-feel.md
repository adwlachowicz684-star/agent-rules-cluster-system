<!-- oversize-exempt: 反模式清单，审核用 -->
# platformer-feel — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/platformer-feel.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | `is_action_just_pressed("jump")` 只写 `_physics_process` | 渲染帧与物理帧错位会被吞，要在 `_input` 捕获置缓冲 |
| 2 | 用 `velocity.y` 判断是否真跳起来 | `velocity` 是请求值，斜坡真实速度要 `get_real_velocity()` |
| 3 | `floor_max_angle` 直接填 45° | 是相对 `up_direction` 的偏离角，改了会改变"地板还是墙" |
| 4 | 松开跳 `velocity.y = 0` | 要截断到 CUT_SPEED，归零手感发飘 |
| 5 | 平台用 `position += v*delta` 移动 | 不产生接触速度叠加，角色不跟着走 |
| 6 | 冲刺时改 `CollisionShape2D.shape.radius` | 重建接触，要用固定形状 + 状态分层 mask |
| 7 | 土狼时间用 `is_on_floor()` 判断离开 | 离开第一帧它就是 false，要缓存 `was_on_floor` |
| 8 | 忽略键盘 ghosting | 某键确实按下也可能返回 false |
| 9 | 帧顺序随便排 | 采样→消耗缓冲→重力→move_and_slide→更新状态，错了手感就错 |
| 10 | 移动平台角色抖动就调参 | 要先确认平台运动在物理帧内完成、同层同物理空间 |
