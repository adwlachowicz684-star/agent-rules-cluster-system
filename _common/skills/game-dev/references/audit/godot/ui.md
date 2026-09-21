<!-- oversize-exempt: 反模式清单，审核用 -->
# ui — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/ui.md`

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

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【审】 `common/audit/global.md#GA-02`　资源没配对
【审】 `common/audit/global.md#GA-04`　每帧做本该事件驱动的事
【审】 `common/audit/global.md#GA-05`　缓存无失效路径
