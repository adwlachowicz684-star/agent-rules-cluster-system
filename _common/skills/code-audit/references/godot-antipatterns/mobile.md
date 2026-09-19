<!-- oversize-exempt: 反模式清单，审核用 -->
# mobile — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于审核完成效果、约束边界。
> 「怎么做」看开发侧：`game-dev/references/godot/mobile.md`

## 常见漏写

| 漏写 | 后果 |
|---|---|
| 开了 `emulate_mouse_from_touch` 又处理两套事件 | 动作触发两次 |
| 用 `InputEventScreenSwipe` | 4.x 不存在，直接报错 |
| 摇杆用绝对像素半径 | 不同 DPI 手感差异巨大 |
| 摇杆 Control 的 `mouse_filter` 不是 STOP | 触摸穿透到游戏世界 |
| 返回键未 `set_input_as_handled()` | 处理了还是退出 |
| 权限请求后立刻使用 | 异步未返回，功能失败 |
| 安全区未从屏幕坐标转换 | 有拉伸时边距全错 |
| `get_display_cutouts()` 用在 iOS | 仅 Android 实现 |
| 玩家代码里分平台写输入 | 后续维护灾难 |
| 未在低端机实测 | 上线后大量掉帧投诉 |
