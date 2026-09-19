<!-- oversize-exempt: 反模式清单，审核用 -->
# ui — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于审核完成效果、约束边界。
> 「怎么做」看开发侧：`game-dev/references/godot/ui.md`

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| 每帧赋值 `Label.text` | 每次触发重排，大文本明显卡 | GD13 |
| 重建列表只 `remove_child` 不 `queue_free` | 节点累积 | GD01 |
| UI 不用 CanvasLayer | 相机移动时 HUD 跟着跑 | 人工 |
| `await` 后不判 `is_instance_valid` | 节点已释放，访问报错 | GD75 |
| 菜单没设默认焦点 | 手柄玩家无法操作 | 人工 |
| 长文本用 `text +=` 累加 | 每帧全量重建，卡 | 人工 |
| 硬编码像素坐标 | 换分辨率 UI 错位 | 人工 |
