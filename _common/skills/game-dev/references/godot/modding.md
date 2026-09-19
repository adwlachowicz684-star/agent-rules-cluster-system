# 玩家 Mod 支持（Godot 4.7.2）

⚠ **玩家 Mod ≠ 编辑器插件** ——
编辑器插件是给开发者扩展 Godot 用的（见 `editor-plugin.md`），
玩家 Mod 是给终端用户扩展游戏内容用的。两者路径完全不同。

## 0. 第一条正路：资源包覆盖

**正确入口是 `ProjectSettings.load_resource_pack()`，不是装 `EditorPlugin`。**

```gdscript
static func load_resource_pack(pack: String, replace_files: bool = true, offset: int = 0) -> bool
```

它把 PCK/ZIP 挂进运行时的 `res://` 虚拟文件系统。

| 参数 | 含义 |
|---|---|
| `pack` | 运行时可访问的路径 |
| `replace_files` | 同名文件是否接管 |
| `offset` | 仅对 PCK 有效，可从自执行包中间读取 |

### ⚠ 覆盖语义（最容易误判）

**后来加载的包，在重复路径上压过先前加载的包** → **Mod 加载顺序就是优先级顺序**。

⚠ `replace_files=false` 是"**不覆盖**"，**不是"后来者优先"** —— 这两个常被搞反。

### ⚠ 路径注意

`user://` 下的路径可以。但**导出项目里不能用 `globalize_path("res://...")`**
把 `res://` 当真实磁盘路径。

实践建议：把 Mod 从 `user://mods/` 读到临时目录后，用**真实文件系统路径**加载。
C# 侧 `Assembly.LoadFile("mod.dll")` 必须在加载资源包**之前**执行。

## 1. 第二条路（常被混为一谈）：编辑器导入

`EditorPlugin.add_import_plugin()` 面向**编辑器资源导入**。

⚠ **官方没有内建"玩家侧 .zip → PCK 自动导入器"**。
官方运行时建议是直接用 `load_resource_pack()`，
**而不是让游戏复制一遍编辑器的导入管线**。

⚠ **"直接拖入 .zip"与"覆盖式挂载 PCK/ZIP"是两套架构**，不是同一件事的两种说法。
混用的后果：**Mod 装了但游戏没变化**（压根没进覆盖链）。

## 2. ⚠ 安全：Mod 等于给玩家执行任意代码的能力

**Godot 里 Mod 脚本与游戏脚本权限相同，无法沙箱隔离。**
⚠ `replace_files=false` 也**不构成安全沙箱**，它只是不覆盖同名文件。

要明示这个风险：加载第三方 Mod 等价于运行第三方代码。

### zip-slip（P0）

⚠ **手动解压时直接拼接文件名，未校验 `../` → 任意文件写入**。

正确做法：**规范化路径后必须仍在目标根目录内**（见 GD166）。

## 3. 目录结构与清单

常见约定：`user://mods/` 下每个 Mod 一个目录。

清单（mod.json / manifest）该有：id、名称、版本、依赖、加载顺序、作者。

⚠ **要记录已加载 pack 的来源** ——
出问题时能定位是哪个包引入的。

- PCK 条目可用 `PCKDirAccess` 在挂载前检查
- ZIP 条目可用 `ZIPReader.get_files()`

⚠ 覆盖式加载下，登记的是"**包声明了哪些路径**"，
**不等于运行时最终解析结果** —— 调试 UI 要标注为"声明来源"。

建议维护 `pack_id -> source_path / sha256 / version / load_time` 表，
玩家报告贴图错误时能快速区分**原版 / 补丁 / DLC / Mod**。

## 4. 4.x 的 ZIP 能力：能读也能写

⚠ 不是"只能读" —— `ZIPReader` 读，`ZIPPacker` 写。

| 类 | 主要方法 |
|---|---|
| `ZIPReader` | `open` / `close` / `get_files` / `file_exists` / `get_compression_level` / `read_file` |
| `ZIPPacker` | `open(path, append)` / `add_directory` / `start_file` / `write_file` / `close_file` / `close` |

`ZIPPacker` 支持无压缩、快速、默认、最佳压缩等级。
⚠ `read_file()` 会把整个条目读进内存。

## 5. 与存档的交互

⚠ **卸载 Mod 后存档可能打不开** —— 存档引用了 Mod 提供的内容。

- 存档要**记录启用了哪些 Mod**
- 缺失 Mod 时要有**降级策略**（提示而非崩溃）

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/modding.md`


## 6. 待核对项（运行时验证）

⚠ 待核对：4.7.2 中 `load_resource_pack` 对 ZIP 的实际支持程度 · 验证：打包一个 ZIP Mod 实机加载并确认覆盖生效

⚠ 待核对：导入插件文档与 4.7 的同步程度 · 验证：官方文档页面标注可能未完全同步至 4.7

## 7. 相关文档

- 编辑器插件（开发者向）→ `editor-plugin.md`
- 插件生态 → `plugins.md`
- 资源加载 → `io-network.md`
- 存档安全 → `security.md`
- 存档与序列化 → `io-network.md`
