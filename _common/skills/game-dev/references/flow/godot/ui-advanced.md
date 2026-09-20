# UI 进阶：列表、富文本、拖拽、无障碍（Godot 4.7.2）

"UI框架""富文本""虚拟列表""tooltip""键盘导航" 此前几乎全部 **0 命中**。
基础控件与布局见 `ui.md`，本文讲**复杂交互与可用性**。

## 0. 商业项目"能用"与"好用"的分界

是**列表性能、输入鲁棒性、焦点链完整性、无障碍**四层。

## 1. ⚠ 没有内置虚拟列表

**Godot 至今没有内置虚拟列表。**
`ScrollContainer + VBoxContainer` 里塞一千个控件节点**必然卡死**。

⚠ **`Tree` 也不虚拟化** —— 它所有行都会被布局与排版。
4.7 稳定版有公开复现：70k 项 8 列约 **1.21 GiB**，改文本后 2.81 GiB，
12 列 4.30 GiB，清空后回落到 118.3 MiB。

拆解：`TreeItem` 448 B + `TreeItem::Cell` 376 B，每个 Cell 还无条件分配
约 488 B 的 `TextParagraph` 和约 100 B 的 `AccessibilityElement`
→ 每个 8 列项约 7.7 KiB。

⚠ `ScrollContainer` 根据子节点的 `custom_minimum_size` 调整滚动条，
**并未声称对不可见区域做裁剪或回收**。

→ 海量条目必须**自己写对象池化虚拟列表**。

## 2. ⚠ BBCode 有注入风险

玩家名/聊天内容含 `[` 会**破坏排版** —— 必须对用户输入做 `escape_bbcode`。

`RichTextLabel` 支持 `[b]`/`[color]`/`[img]` 等标记，可自定义效果。
⚠ 大量文本或频繁更新时要注意性能。

## 3. 拖拽：三回调只是契约

`_get_drag_data` / `_can_drop_data` / `_drop_data`。

⚠ **`set_drag_preview` 传入的节点绝不能在场景树中，也不能自己 `free`**
—— 引擎会接管其生命周期。

⚠ **拖拽与 `ScrollContainer` 的冲突**：滚动区域里拖的行为要实测。

## 4. ⚠ 鼠标能点 ≠ 手柄能选

缺的几乎总是 **`grab_focus()` 与 `focus_neighbor_*`**。

- `focus_mode` / `focus_neighbor_*` / `focus_next`
- 手柄动作：`ui_accept` / `ui_cancel` / `ui_focus_next`
- ⚠ **弹窗关闭后焦点去哪了** —— 焦点丢失是最常见的无障碍缺失

## 5. 4.7 的无障碍：实质加强

（本文只讲**交互层**：焦点链、键盘/手柄导航。
**呈现层**——字幕、色盲、屏幕阅读器、高对比度——见 `accessibility.md`）

**`AccessibilityServer` 从 `DisplayServer` 中独立成单例**，
新增 `accessibility_region` 属性 —— 屏幕阅读器可导航到**区域级节点**。

⚠ `accessibility_live` 类型改为 `AccessibilityServer.AccessibilityLiveMode`。

## 6. 剪贴板 / 输入法

⚠ **4.x 已从 3.x 的 `OS.set_clipboard` 迁移到 `DisplayServer`**：

| API | 作用 |
|---|---|
| `DisplayServer.clipboard_set(text)` | 写入系统剪贴板 |
| `DisplayServer.clipboard_get()` | 读取系统剪贴板 |

⚠ 4.7 修复了 Wayland/KDE 分数缩放下 **IME 定位**问题。

⚠ 自定义剪贴板 MIME 格式在现有 API 中仅见纯文本与图像 —— **待核对**。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/ui-advanced.md`


## 7. 待核对项（运行时验证）

⚠ 待核对：Tree 在 4.7.2 的确切内存表现 · 验证：按目标版本构造 70k 项实测

⚠ 待核对：自定义剪贴板 MIME 的支持范围 · 验证：实际写入自定义格式并读取

## 8. 相关文档

- 基础 UI 与布局 → `ui.md`
- 无障碍与字幕（呈现层） → `accessibility.md`
- 背包/物品栏 → `game-systems.md`
- 移动端触控 → `mobile.md`
- 本地化技术 → `i18n.md`
- 调试工具 → `devtools.md`
- 性能剖析 → `perf-profiling.md`
