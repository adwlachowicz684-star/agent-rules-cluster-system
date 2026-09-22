# 编辑器插件开发（Godot 4.7.2）

可发布的插件 = **可见 + 可撤销 + 可恢复**。三者缺一不算完成。
概览见 `gdext-plugin.md`，本文讲实战。

## 0. 生命周期：安装与卸载必须对称

⚠ **`_enter_tree()` 创建的 dock、菜单、自定义类型、导入器、检视器、导出器，
必须在 `_exit_tree()` 里反向注销并释放。**

⚠ **只隐藏控件而不断开注册，会留下跨插件实例的悬空回调。**

## 1. `@tool` 深入

⚠ **`@tool` 的作用不是"启用编辑器 UI"，而是允许脚本在编辑器进程中运行。**
对 `EditorPlugin` 它是必需的——没有它，脚本不会在编辑器里运行，
插件列表即使显示也无法启用。

⚠ **任何被 tool 脚本使用的 GDScript 也应是 tool** ——
否则编辑器无法构造其实例、调用其方法、访问成员变量。

### 三个必须区分的判断

| 判断 | 含义 |
|---|---|
| `Engine.is_editor_hint()` | 当前运行在**编辑器进程**（不代表正在跑游戏） |
| `OS.has_feature("editor")` | 区分**编辑器构建**与正式导出 |
| `is_editor_hint() == false` | 运行时 |

⚠ **在编辑器中运行 ≠ 只在编辑器中运行**。
共享组件被插件场景和运行时场景同时使用时尤其危险。

**正确边界不是"脚本顶部有没有 `@tool`"，而是每个副作用调用点回答三问**：
1. 当前是编辑器吗？
2. 当前对象归编辑场景还是运行场景？
3. 这次改动是否应写入源文件？

### 生命周期回调确实会在编辑器里触发

⚠ `_process` / `_physics_process` / `_input` **都会跑**，
要按"编辑器主循环的一部分"理解。

⚠ **不能假定"场景打开一定只调用一次 `_ready()`"** ——
复制节点、跨场景撤销/重做、资源被检视器持有都可能重新进入生命周期。
初始化应**幂等**：`_ready()` 只连接尚未连接的信号。

### 安全模式：预览层与提交层分离

| 层 | 能做什么 |
|---|---|
| **预览层** | 只读、计算、绘制。**不写源状态** |
| **提交层** | 改源状态，**必须由用户明确动作触发** + UndoRedo |

⚠ **编辑不是沙箱**。常见事故：
- `@tool` setter 里 `queue_free()` 父节点 → 编辑器崩溃
- `_process()` 里随机化属性 → 场景永远"脏"
- 直接保存资源到项目目录 → **覆盖用户源文件**

## 2. UndoRedo（可撤销是硬要求）

⚠ **4.7 用 `EditorPlugin.get_undo_redo()`，不要自行持有全局 UndoRedo。**

`EditorUndoRedoManager` 为**每个打开的场景维护独立历史**，
自动根据**首个操作的对象**选择历史：
Node → 当前编辑场景；内嵌资源 → 按路径所属场景；外部资源 → 全局历史。

⚠ **所以创建动作时要保证首个 do 操作已绑定正确对象**。
先 `add_do_method(some_manager, "prepare")` 而 manager 不是场景/资源
→ 历史进入全局历史 → **撤销顺序错乱**。

### 最小正确流程

```gdscript
var ur := get_undo_redo()
ur.create_action("设置敌人数量")
ur.add_do_property(enemy, "max_hp", 200)
ur.add_undo_property(enemy, "max_hp", 100)
ur.commit_action()
```

**建动作 → 描述 do → 描述 undo → 提交**。

⚠ **属性动作与结构性动作要分开**：
- `add_do_property` 适合原子属性变化
- `add_do_method` 适合 `add_child` / `remove_child` / `queue_free` / `reparent`

⚠ **创建新节点还要 `add_do_reference(new_node)`** ——
历史丢弃时新建节点引用随之清理。
⚠ 别把 `add_do_reference()` 用于资源（它控制的是"历史丢弃时删除对象"）。

⚠ **删除节点时 undo 侧用 `add_undo_reference()`** ——
确保撤销重建后历史再次丢失不会误删刚恢复的对象。

## 3. 自定义检视器

`EditorInspectorPlugin` 的核心钩子：
`_can_handle` / `_parse_begin` / `_parse_property` / `_parse_category` / `_parse_end`

⚠ **属性编辑优先走 `EditorProperty.emit_changed()`** ——
这样能自动接入 UndoRedo，不用手动建动作。

### ⚠ 自定义控件必须能聚焦

⚠ **自定义属性控件里的可交互控件要 `add_focusable()`** ——
否则键盘/手柄**选不中**它，表现为"能用鼠标点，但 Tab 键跳过"。

```gdscript
func _update_property() -> void:
    _btn.text = str(get_edited_property_value())
    _btn.add_focusable()          # ⚠ 不加则键盘不可达
```

⚠ **`_update_property()` 与 `emit_changed()` 是配套的两件事**：
`_update_property()` 负责把**值刷回控件**，
`emit_changed()` 负责把**控件改动上报**。
⛔ 只写后者 → 值变了但界面不刷新；只写前者 → 改了不生效。

### ⚠ 卸载必须对称

⚠ **`_exit_tree` 里不调 `remove_inspector_plugin` 仍生效** ——
插件已卸载但钩子还挂着，表现为"改了脚本后检视器重复渲染两次"。

```gdscript
func _exit_tree() -> void:
    remove_inspector_plugin(_inspector)   # ⚠ 与 add 成对，缺了不会报错
    _inspector = null
```

ⓘ 这条与第 0 节"安装与卸载必须对称"是同一条原则，
但**检视器插件这一处最容易被漏** —— 因为它不报错、不崩溃，
只是行为变得诡异。

用途：给自定义 Resource 做专属编辑界面、给特定类型加自定义控件。

## 4. 自定义导入器

`EditorImportPlugin` 要实现：
`_get_importer_name` / `_get_visible_name` / `_get_recognized_extensions` /
`_get_save_extension` / `_get_resource_type` / `_get_preset_count` /
`_get_import_options` / `_import`

⚠ **`_get_importer_name()` 必须稳定且全局唯一** ——
它决定了 `.godot/imported/` 里的缓存路径。

⚠ **改了导入逻辑却不触发重导入** ——
用 `_get_format_version()` 递增，或让导入器代码随源文件变化触发；
最可靠的是删除对应 `.import`/缓存文件，或重新保存源文件。

## 5. Dock 与菜单（4.7 变化）

⚠ **4.7 已把 dock 统一到 `EditorDock`**：
`add_control_to_dock()` 被 `add_dock()` 取代，
`add_control_to_bottom_panel()` 已弃用（但仍存在于 API）。
**旧文章不能直接照抄。**

其他：`add_tool_menu_item()` / `add_tool_submenu_item()`。

## 6. 发布

`plugin.cfg` 完整字段 + 版本兼容声明。

⚠ **卸载不干净的排查**：查 `_exit_tree()` 是否对称注销了所有注册项。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/editor-plugin.md`


## 7.  EditorScript（一次性脚本）不在这里

⚠ **只跑一次、不做成插件的脚本**（批量改名、统计、修数据）
用 `EditorScript`，⛔ 不要为此做一个插件 → 见 `devtools.md#6. 编辑器工具：一次性脚本与批量改资源`。

ⓘ 该文含官方明确的三条坑：输出走 stdout 不在 Output 面板、
是 `RefCounted` 异步会出错、`add_root_node`/`get_scene` 已废弃。

## 8. 相关文档

- 决策 / 插件类型概览 → `gdext-plugin.md`
- GDExtension 实战 → `gdextension-deep.md`
- 导入管线 → `advanced-topics.md`
- CI 与发布 → `cicd-publish.md`
- 架构规范 → `architecture.md`
- 一次性脚本与批量改资源 → `devtools.md`
