<!-- oversize-exempt: 反模式清单，审核用 -->
# camera-cutscene — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/camera-cutscene.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | Camera2D 兼做跟随和边界 | 要分层：Rig 跟随，Camera2D 管 limit |
| 2 | `lerp(a,b,0.1)` 是标准平滑 | **帧率相关**，要用 `1-exp(-k*dt)` |
| 3 | 死区就是 drag_margin | 内置是居中跟随，专业死区要固定区域 |
| 4 | 屏震=每帧随机偏移 | 那是抖动，要用 trauma+平方衰减+噪声 |
| 5 | 缩放改了不用管 limit | 可视区域变了，limit 要重算 |
| 6 | SpringArm 自动避让角色 | 要**显式排除角色碰撞层** |
| 7 | 过场用 AnimationPlayer 最专业 | 简单过场用 Tween 更轻 |
| 8 | 禁用玩家 = `can_move=false` | 会漏镜头/菜单/攻击，要用权限栈 |
| 9 | 过场结束恢复为 true | 异常路径会永久锁死，要从**快照**恢复 |
| 10 | 跳过=结束动画 | 要把状态**推进到终态** |
| 11 | 黑边用相机缩放做 | 是 UI，用 CanvasLayer+ColorRect |
| 12 | 黑边位置写死 | 分辨率变化会错位，用 anchor+offset |
| 13 | 动画播完属性自动恢复 | AnimationPlayer 不负责恢复 |
| 14 | 过场中途退出无所谓 | 要能续播或回到一致状态 |
