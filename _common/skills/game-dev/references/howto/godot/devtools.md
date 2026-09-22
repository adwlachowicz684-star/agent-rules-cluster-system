# 开发者调试工具与 GM 命令系统（Godot 4.7.2）

"GM命令""作弊码" 此前 **0 命中**。这是**每天都在用**但极少被写成文档的东西。

## 0. 首要要求不是功能丰富

⚠ 是 **默认关闭、构建隔离、状态可见、操作可审计**。
这些属性不成立，调试工具会**反过来污染测试结果**。

⚠ **不是"开发期随手写、上线前删除"的代码** ——
它会在整个项目生命周期反复使用。正确做法是当成长期维护的**内部工具层**：
统一入口、命令接口、权限等级、日志记录、UI 样式、构建开关。

## 1. 命令行参数

⚠ **自定义参数必须放在 `--` 之后**，并用 `OS.get_cmdline_user_args()` 读取
—— 否则会被引擎提前消费（`--headless` 等已处理参数不会出现在该结果里）。

```gdscript
# 启动：godot -- --level=5 --god --speed=2
for arg in OS.get_cmdline_user_args():
    ...
```

⚠ **`--headless` 不是"不渲染但仍运行完整游戏"** ——
导出模板是否有对应能力取决于模板、平台与启动方式。
更稳妥的架构是**把平台无关逻辑与渲染层分开**，用自定义参数决定进入哪个启动器。

## 2. 调试面板

⚠ **面板自身的绘制、布局、字符串拼接会消耗帧时间** ——
不能把它自己的开销当成玩家世界的消耗。只在调试构建显示。

### ⚠ Performance 的坑

- **部分监控在 Release 导出包中恒为 0**
- 部分监控**最高约 1 秒延迟**（为避免性能开销，非实时更新）
- `MEMORY_STATIC` / `MEMORY_VIDEO_MEM_USED` **release 不可用**
- `OBJECT_ORPHAN_NODE_COUNT` **只在 debug 可用**
- `TIME_FPS` **每秒只更新一次**，查再频繁也不更细

→ 不能只显示裸数字，要同时显示 **debug/release 标记、采样时间、更新间隔、值是否可用**。

## 3. GM / 作弊命令系统

常用命令：跳关、无敌、给物品、加钱、刷怪、时间缩放、瞬移。

⚠ **作弊状态必须有持久视觉标识** ——
否则测试者不知道自己开着无敌，测出不真实的结果。

⚠ **所有命令要进带时间戳的结构化审计日志** ——
否则"这个 bug 复现不了"可能只是因为开着无敌。

⚠ **release 包要不要保留**要明确决策，用构建开关控制。

## 4. 调试绘制

⚠ **官方没有内置 `DebugDraw3D` 节点** ——
官方有的是 **Viewport Debug Draw 模式**，不是跨帧、可在场景代码里调用的官方节点/全局函数。

社区插件可用，但要在 **Debug 构建门控后加载**。

⚠ GitHub 上用 `ImmediateGeometry` 的旧示例**不能直接迁移** ——
Godot 4 对应 API 与生命周期已不同。

## 5. 日志

⚠ **崩溃时日志是唯一线索** —— 要有崩溃兜底记录。
日志文件位置：`user://logs/`。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/devtools.md`


## 6. 编辑器工具：一次性脚本与批量改资源

ⓘ `编辑器工具` `EditorScript` `批量处理` `资源检查` 此前**全部 0 命中**——
这是"每个项目都要写、但没人系统整理"的一块。

⚠ **插件开发（常驻面板、自定义检视器、自定义导入器、UndoRedo、Dock）
不在这里** → 见 `editor-plugin.md`。
本篇只讲**不做成插件**的那一半：一次性跑的脚本、批量改资源、构建隔离。

### 什么时候不做插件

| 需求 | 用什么 |
|---|---|
| 跑一次就完事（批量改名、统计、修数据） | ✅ `EditorScript` |
| 常驻 UI / 自定义检视器 / 可撤销操作 | ⛔ 不是本篇 → `editor-plugin.md` |
| 节点在编辑器里预览效果 | `@tool`（⚠ 见 `editor-plugin.md#1. @tool 深入`） |

ⓘ 官方原话：EditorScript *"For more complex additions, consider using
**EditorPlugins** instead."*

### ⚠ `EditorScript`：四个官方文档写明的坑

ⓘ `EditorScript` 在 Godot 4.x **仍然存在**，⛔ 不是被移除的 API。
通过 **File > Run** 菜单或 **Ctrl + Shift + X** 执行，⛔ 必须带 `@tool`。

```gdscript
@tool
extends EditorScript

func _run():
    print("Hello from the Godot Editor!")
```

⚠ **① 输出不在 Output 面板。**
官方原话：*"The script is run in the Editor context, which means the output is
visible in the **console window started with the Editor (stdout)** instead of
the usual Godot Output dock."*

⛔ 症状：执行了但 Output 面板什么都没有 → 以为脚本没跑。
✅ 从终端启动编辑器才能看到 `print`。

⚠ **② 它是 `RefCounted`，异步会出错。**
官方原话：*"EditorScript is `RefCounted`, meaning it is destroyed when nothing
references it. This can cause **errors during asynchronous operations**."*

⛔ 在 `_run()` 里 `await` 之后再访问成员 → 可能已被销毁。
✅ 异步批量任务改用 `EditorPlugin`，或自己持住引用。

⚠ **③ 多个方法在 4.x 已废弃。**

| 废弃方法 | 替代 |
|---|---|
| `add_root_node()` | `EditorInterface.add_root_node()`（ⓘ 4.0 文档注明该方法当时**实现被禁用**） |
| `get_editor_interface()` | 直接用全局单例 `EditorInterface` |
| `get_scene()` | `EditorInterface.get_edited_scene_root()` |

ⓘ **4.x 新增**：若脚本有 `class_name`（全局类名），会出现在编辑器的
**命令面板**里——这是让一次性工具可被发现的官方途径。

### ⚠ 批量改资源：改了内存 ≠ 存盘

⚠ **在编辑器里改资源对象的属性，不会自动写回磁盘。**
必须显式 `ResourceSaver.save()`，否则重开编辑器**全部丢失**。

```gdscript
@tool
extends EditorScript

func _run() -> void:
    var dir := DirAccess.open("res://data/items")
    for f in dir.get_files():
        if not f.ends_with(".tres"):
            continue
        var res = load("res://data/items/" + f)
        res.version += 1
        var err := ResourceSaver.save(res, "res://data/items/" + f)   # ⚠ 必须
        if err != OK:
            push_error("保存失败 %s: %d" % [f, err])
    print("完成")     # ⚠ 输出在 stdout，见上文
```

⚠ 批量处理前**必须先备份或用版本控制**，⛔ 不要对唯一副本直接跑。
ⓘ 批量改错会污染整个资源目录，且**没有撤销**（`EditorScript` 不接 UndoRedo）。

ⓘ 改完若编辑器未刷新，需要触发文件系统重新扫描。

⚠ **批量改资源不属于"调试工具"的构建隔离范畴** ——
它只在编辑器跑，但**写坏的是项目源文件**，风险等级高于运行时调试工具。

### 编辑器工具也要构建隔离

⚠ `@tool` 脚本里的代码**会被导出**。
⛔ 在 `@tool` 脚本里引用编辑器 API（如 `EditorInterface`）而没做条件判断
→ **导出包运行报错**。

✅ 访问编辑器 API 前判 `Engine.is_editor_hint()`，C# 用 `#if TOOLS`。
ⓘ `@tool` 的三个官方警告（崩溃、修改永久、两边都跑）
→ 见 `editor-plugin.md#1. @tool 深入`，本文不重复。

## 7. 待核对项（运行时验证）

⚠ 待核对：社区 Debug Draw 插件在 4.7.2 的 API 与许可 · 验证：目标版本与平台实测后再决定引入

⚠ 待核对：Android 远程调试端口与可用性 · 验证：真机连接检查

⚠ 待核对：`ImmediateMesh` 在 4.7.2 的确切签名 · 验证：编辑器类参考核对

## 8. 相关文档

- 关卡快速迭代 → `level-design.md`
- 性能剖析 → `perf-profiling.md`
- 调试排错 → `debugging.md`
- 埋点与数据分析 → `analytics.md`
- 测试 → `testing.md`
- 命令参数与平台导出 → `platform-export.md`
- 作弊面板 → `economy.md`
- 配表与自定义 Resource 的检视器 → `datatable.md`
- 插件开发（含 EditorPlugin 生命周期） → `advanced-topics.md`
- 资源导入与导入期处理 → `art-assets.md`
