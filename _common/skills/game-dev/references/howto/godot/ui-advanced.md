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

> ⓘ 官方契约里两条容易漏的点（`Vector2.INF`、can/drop 分工）见 **第 7 节**。

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


## 7. 拖拽：官方契约里两条没人提的

### ⚠ ① 键盘/无障碍发起拖拽时，`at_position` 是 `Vector2.INF`

官方原话（`_get_drag_data` 与 `_can_drop_data` 两条都写了）：

> *"If the drag was initiated by **a keyboard shortcut or
> `accessibility_drag()`**, `at_position` is set to **`Vector2.INF`**,
> and the currently selected item/text position should be used as the drag
> position."*

⚠ 后果：如果你直接用 `at_position` 去算"拖的是哪个格子"，
键盘发起的拖拽会**拿到无穷大**，算出来的索引是垃圾值。

⛔ 症状：鼠标拖拽一切正常，键盘/手柄拖拽拿到错误的物品。
而且**不报错**。

✅ 防御写法：

```gdscript
func _get_drag_data(at_position):
    var idx = _index_at(at_position) if at_position != Vector2.INF \
              else _selected_index()
```

ⓘ 这条同时说明：**拖拽不是鼠标专属功能**，
`force_drag()` 也可以强制发起。

### ⚠ ② `_can_drop_data` 只做测试，处理必须在 `_drop_data`

官方原话：*"This method should only be used to **test** the data.
**Process the data in `_drop_data()`**."*

⚠ 在 `_can_drop_data` 里改数据是常见错误：
它会被**多次调用**（悬停移动时反复问），副作用会重复执行。

ⓘ 官方还说明：`_drop_data` 之前**一定先调** `_can_drop_data`。

### `set_drag_preview` 的最佳时机

官方原话：*"**A good time to set the preview is in this method.**"*
（指 `_get_drag_data` 内）

⚠ 预览节点**绝不能在场景树中**，也不能自己 `free` —— 引擎接管生命周期
（第 3 节已说）。

### `_gui_input` 不触发的四种情况（官方列出）

| 情况 | 结果 |
|---|---|
| 点在控件外（见 `_has_point`） | 不触发 |
| 控件 `mouse_filter = MOUSE_FILTER_IGNORE` | 不触发 |
| ⚠ **被上层另一个非 IGNORE 的 Control 挡住** | 不触发 |
| ⚠ **父级是 `MOUSE_FILTER_STOP` 或已 `accept_event`** | 不触发 |

ⓘ 第 3、4 条是"按钮点了没反应"最常见的根因，
⛔ 而不是信号没连上。

## 8. BBCode：官方给的实现与三条反直觉

### ✅ `escape_bbcode` 官方实现只替换 `[`

官方教程给的完整实现：

```gdscript
func escape_bbcode(bbcode_text):
    # We only need to replace opening brackets to prevent tags from being parsed.
    return bbcode_text.replace("[", "[lb]")
```

⚠ **只需要替换开括号** —— 因为 BBCode 的标签解析只认 `[`。
⛔ 不要自己去写复杂的标签过滤正则，官方方案更短更安全。

### ⚠ 官方明确反对"移除标签"，主张"转义"

官方原话：

> *"Removing BBCode tags entirely **isn't advised for user input**,
> as it can **modify the displayed text without users understanding why**
> part of their message was removed. **Escaping user input should be
> preferred.**"*

⚠ 这条纠正了一种常见做法：用正则把 `[...]` 全删掉。

⛔ 后果：玩家输入 `[大笑]` 想表达情绪，结果**显示出来什么都不剩**，
而玩家不知道发生了什么。

✅ 正确：转义后原样显示 `[大笑]`。

ⓘ 官方也给了剥离的正则（用于把富文本显示到不支持 BBCode 的
tooltip 里）：`RegEx` 编译 `\[.*?\]` 后 `sub` 替换为空。
⛔ 但**这个用途是 tooltip，不是用户输入**。

### ⚠ `append_text()` 只解析新增部分，`text =` 会重解析全文

官方原话：*"This function will **only parse BBCode for the added text**,
rather than parsing BBCode from the entire text property."*

⚠ 聊天/日志这类**持续增长**的文本：
- ✅ 用 `append_text()` —— 只解析新的一行
- ⛔ 用 `text += ` —— 每次都把全文重新解析一遍

ⓘ 这是"聊天框越长越卡"的直接原因。

### ⚠ `text` 直接赋值会**擦除** push/pop 的修改

官方 Warning：

> *"**Do not set the `text` property directly when using formatting
> functions.** Appending to the `text` property will **erase all
> modifications** made using `append_text()`, `push_[tag]()` and `pop()`."*

⚠ 混用两种写法 → 格式**莫名其妙消失**。

### `push_[tag]()` / `pop()`：不用 BBCode 的写法

ⓘ 每个 BBCode 标签都有对应的 `push_[tag]()`，还有
`push_bold_italics()` 这类便捷函数。

⚠ **`pop()` 关闭最近开始的标签**（标签栈语义），
不是"关闭指定标签"。

```gdscript
append_text("BBCode ")
push_color(Color.GREEN)
append_text("test ")
push_italics()
append_text("example")
pop()   # 关 italics
pop()   # 关 color
```

### Threaded 属性：不加速，只防阻塞

官方原话：*"This **won't speed up processing**, but it will prevent the
main thread from blocking... **Only enable threading if it's actually
needed**, as threading has some overhead."*

⚠ 两条要点：
- ⛔ 它不是性能优化，是**卡顿转移**（从主线程挪走，总耗时不变甚至更多）
- ⛔ 默认别开 —— 有开销，只在确实卡时才开

## 9. 虚拟列表：自己写时的四个要点

⚠ **Godot 至今没有内置虚拟列表**（第 1 节已说），这里给实现要点。

| 要点 | ⚠ 不做会怎样 |
|---|---|
| **只实例化可见范围 + 缓冲区** | 一千条必卡死 |
| ⚠ **回池必须重置全部状态** | 复用出脏数据（见全局块 GC-02） |
| ⚠ **滚动条长度按总数，不是按已实例化数** | 滚动条会随滚动**变长变短** |
| ⚠ **数据变化时只刷新可见项** | 改一条要重排一千个 |

ⓘ **`ScrollContainer` 按子节点的 `custom_minimum_size` 调整滚动条** ——
所以虚拟列表通常要**自己撑一个占位 Control** 来表示总高度，
⛔ 不能靠真实子节点。

⚠ **`Tree` 不是替代方案**（第 1 节有实测数字）：
它所有行都会被布局与排版，**不虚拟化**。

ⓘ 若必须用 `Tree`：控制**列数与行数**，
尤其 ⚠ 每增一列，每个 Cell 都无条件分配约 488 B 的 `TextParagraph`。

## 10. 待核对项（运行时验证）

⚠ 待核对：Tree 在 4.7.2 的确切内存表现 · 验证：按目标版本构造 70k 项实测

⚠ 待核对：自定义剪贴板 MIME 的支持范围 · 验证：实际写入自定义格式并读取

## 11. 相关文档

- 基础 UI 与布局 → `ui.md`
- 无障碍与字幕（呈现层） → `accessibility.md`
- 背包/物品栏 → `game-systems.md`
- 移动端触控 → `mobile.md`
- 本地化技术 → `i18n.md`
- 调试工具 → `devtools.md`
- 性能剖析 → `perf-profiling.md`
