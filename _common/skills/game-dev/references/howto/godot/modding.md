# 玩家 Mod 支持（Godot 4.7.2）

> **本篇分工：Mod「系统」层** —— 包格式、加载时机、清单与依赖、冲突、安全、存档交互。
> ⚠ **编辑器插件是给开发者扩展 Godot 用的** → `editor-plugin.md`；插件生态 → `plugins.md`。

## 0. 先定性：玩家 Mod ≠ 编辑器插件

⚠ **玩家 Mod 是给终端用户扩展游戏内容用的，编辑器插件是给开发者扩展 Godot 用的。**
两者路径完全不同，`EditorPlugin` 那条路（见 `editor-plugin.md`）**做不出玩家侧 Mod**。

官方给出的玩家 Mod 两条路：

1. **文档化结构 + 让玩家自己装 Godot 导出 PCK** —— 开发者要公开资源结构约定与脚本接口
2. **开发者做个 GUI 工具** —— 该工具必须跑在 **tools-enabled build** 上，用 `OS.execute()` 调 Godot 命令行导出

⛔ **游戏本体不该用 tool build**（官方原话，出于安全考虑）——**Mod 工具与游戏本体必须分离**。
用 tool build 发布游戏本体 = 把导出能力一起交给了攻击者。

## 1. 第一条正路：资源包覆盖

**正确入口是 `ProjectSettings.load_resource_pack()`，不是装 `EditorPlugin`。**

```gdscript
static func load_resource_pack(pack: String, replace_files: bool = true, offset: int = 0) -> bool
```

它把 PCK/ZIP 挂进运行时的 `res://` 虚拟文件系统。

| 参数 | 含义 |
|---|---|
| `pack` | 运行时可访问的路径 |
| `replace_files` | 同名文件是否接管 |
| `offset` | ⚠ **仅对 PCK 有效**，可从自执行包中间读取（官方 Note） |

### ⚠ 覆盖语义（最容易搞反）

**后来加载的包，在重复路径上压过先前加载的包** → **Mod 加载顺序就是优先级顺序**。
官方原话：*"A PCK/ZIP file of this kind can fix the content of a previously loaded PCK/ZIP (therefore, the order in which packs are loaded matters)."*

⛔ `replace_files=false` 是"**不覆盖**"，**不是"后来者优先"**。
传 false 时，后加载的同名文件被**忽略**。

## 2. ⛔ 加载时机：必须在 autoload 的 _init()

**这是"Mod 装了但游戏没变化"最常见的真正原因，且完全不报错。**

官方 Troubleshooting 原话：

> *"If you are loading a resource pack and are not noticing any changes, it may be due to the pack being loaded too late. This is particularly the case with menu scenes that may preload other scenes using `preload()`. This means that loading a pack in the menu will not affect the other scene that was already preloaded."*

⛔ 菜单场景用 `preload()` 预载了别的场景 → 在菜单里加载包**对已预载的场景无效**。

官方给的解法：

> *"create a new autoload script and call `ProjectSettings.load_resource_pack()` in the autoload script's **`_init()` function, rather than `_enter_tree()` or `_ready()`**."*

⚠ 关键细节是 **`_init()` 而不是 `_ready()`**。写在 `_ready()` 里仍可能晚于其他 autoload 的 `preload()`，
表现为"部分资源是 Mod 的、部分是原版的"——**比全部失效更难排查**。

### C# 的顺序

官方：先构建 DLL 放进项目目录，然后**在加载资源包之前** `Assembly.LoadFile("mod.dll")`。

⛔ 顺序反了：先加载资源包 → 包内脚本引用的程序集还没进 → 运行时找不到类型。

## 3. ⛔ 路径：CWD 不保证是可执行文件所在目录

官方成员明确回复过一个"从 Windows 搜索栏启动就加载不出资源"的问题：

> *"do not assume that its CWD will be the folder the executable is located in. Instead, read the executable location and concatenate any paths with it."*

⛔ `load_resource_pack("mods/foo.pck")` 这种相对路径，从快捷方式 / 搜索栏 / 符号链接启动时**全部失效**，
而双击 exe 时正常 —— **同一份代码、两种结果**，极难归因。

正确写法：

```gdscript
ProjectSettings.load_resource_pack(OS.get_executable_dir().path_join("mods/foo.pck"))
# 3.x 用 plus_file() 而非 path_join()
```

### ⚠ 导出项目里不能用 `globalize_path("res://...")`

官方 Note：*"GlobalizePath(String) with res:// will not work in an exported project."*
替代方案同样是拼可执行文件目录，不是把 `res://` 当真实磁盘路径。

实践建议：把 Mod 从 `user://mods/` 读到临时目录后，用**真实文件系统路径**加载。

## 4. PCK vs ZIP：怎么选

官方对比（exporting_projects）：

| | **PCK** | **ZIP** |
|---|---|---|
| 压缩 | 未压缩，**文件大但读写快** | 压缩，**文件小但读写慢** |
| OS 自带工具 | 打不开（需第三方工具） | **可直接读写** → 官方称"便于 modding" |
| **文件移除** | ⚠ **支持**（做补丁要靠它） | **不支持** |
| **加密** | ⚠ **支持内建加密** | **无原生加密** |

⛔ **要"删掉某个原版文件"的补丁只能用 PCK** —— ZIP 做不到移除，只能覆盖。
表现为"补丁装上后旧文件还在"，且不报错。

⚠ **已知 bug**：ZIP 作为**主 pack** 时，导出的二进制**不会自动使用它**，
必须自建启动脚本：`my_project.exe --main-pack my_project.zip`（Windows）/ 同目录 `.sh`（Linux）。

## 5. 第二条路（常被混为一谈）：编辑器导入

`EditorPlugin.add_import_plugin()` 面向**编辑器资源导入**，不是玩家侧 Mod。

⚠ **官方没有内建"玩家侧 .zip → PCK 自动导入器"**。
官方运行时建议是直接用 `load_resource_pack()`，
**而不是让游戏复制一遍编辑器的导入管线**。

⚠ **"直接拖入 .zip"与"覆盖式挂载 PCK/ZIP"是两套架构**，不是同一件事的两种说法。
混用的后果：**Mod 装了但游戏没变化**（压根没进覆盖链）。

## 6. ⚠ 安全：Mod 等于给玩家执行任意代码的能力

**Godot 里 Mod 脚本与游戏脚本权限相同，引擎内置无法沙箱隔离。**

⚠ `replace_files=false` 也**不构成安全沙箱**，它只是不覆盖同名文件。

### zip-slip（P0）

⚠ **手动解压时直接拼接文件名，未校验 `../` → 任意文件写入**。

正确做法：**规范化路径后必须仍在目标根目录内**（见 GD166）。

### ⓘ 出路：第三方沙箱（不是引擎内置）

存在第三方方案（如 `godot-sandbox`，提供 SafeGDScript 方言 + 内存安全沙箱 + 执行超时），
可让"加载不受信任代码"变得可控。

⛔ 但要清楚：**这不是引擎内置能力**，是外部插件，且它有自己的语言方言与限制。
ⓘ 引擎内置层面，"加载第三方 Mod = 运行第三方代码"这个结论不变。

## 7. 清单、依赖与加载顺序

常见约定：`user://mods/` 下每个 Mod 一个目录。

清单（mod.json / manifest）该有：**id、名称、版本、依赖、加载顺序、作者**。

⛔ **依赖必须做拓扑排序，不能直接按目录名或文件名字面序加载。**
依赖被排在依赖者之后 → 依赖者加载时找不到东西，**报的错指向依赖者而不是真正的问题**。

⛔ **循环依赖必须检测并报明确错误**，否则表现为"两个 Mod 都加载失败"而无从下手。

## 8. 冲突检测：声明来源 ≠ 运行时解析结果

⚠ **要记录已加载 pack 的来源** —— 出问题时能定位是哪个包引入的。

- PCK 条目可用 `PCKDirAccess` 在挂载前检查
- ZIP 条目可用 `ZIPReader.get_files()`

⛔ **覆盖式加载下，登记的是"包声明了哪些路径"，
不等于运行时最终解析结果** —— 调试 UI 要标注为"声明来源"，不能当成"当前生效来源"。

建议维护 `pack_id -> source_path / sha256 / version / load_time` 表，
玩家报告贴图错误时能快速区分**原版 / 补丁 / DLC / Mod**。

## 9. 4.x 的 ZIP 能力：能读也能写

⚠ 不是"只能读" —— `ZIPReader` 读，`ZIPPacker` 写。

| 类 | 主要方法 |
|---|---|
| `ZIPReader` | `open` / `close` / `get_files` / `file_exists` / `get_compression_level` / `read_file` |
| `ZIPPacker` | `open(path, append)` / `add_directory` / `start_file` / `write_file` / `close_file` / `close` |

`ZIPPacker` 支持无压缩、快速、默认、最佳压缩等级。
⚠ `read_file()` 会把整个条目读进内存。

## 10. 与存档的交互

⚠ **卸载 Mod 后存档可能打不开** —— 存档引用了 Mod 提供的内容。

- 存档要**记录启用了哪些 Mod**（id + 版本，不只是"数量"）
- 缺失 Mod 时要有**降级策略**（提示而非崩溃）

⛔ 只记"启用数量"不记 id → 换了一批 Mod 但数量相同，**校验通过但内容全错**。

## 11. 待核对项（运行时验证）

⚠ 待核对：4.7.2 中 `load_resource_pack` 对 ZIP 的实际支持程度 · 验证：打包一个 ZIP Mod 实机加载并确认覆盖生效

⚠ 待核对：导入插件文档与 4.7 的同步程度 · 验证：官方文档页面标注可能未完全同步至 4.7

⚠ 待核对：第三方沙箱插件与 4.7.2 的兼容状态 · 验证：实机加载一个含脚本的敌意 Mod 观察隔离效果

## 12. 相关文档

- 编辑器插件（开发者向）→ `editor-plugin.md`
- 插件生态 → `plugins.md`
- 资源加载 → `io-network.md`
- 存档安全 → `security.md`
- 存档与序列化 → `io-network.md`
- 物理与资源（Mod 提供物理材质）→ `physics.md`

## 13. 审核清单

> **反模式清单（不能怎么做，审核用）** → `audit/godot/modding.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-02`　频繁生成/销毁的东西要池化（Mod 扫描与临时解压）
【读】 `common/howto/principles.md#GC-04`　事件解耦 vs 直接引用（Mod 与游戏主逻辑解耦）
【读】 `common/howto/principles.md#GC-05`　缓存必须有失效路径（包索引缓存随 Mod 增删失效）
