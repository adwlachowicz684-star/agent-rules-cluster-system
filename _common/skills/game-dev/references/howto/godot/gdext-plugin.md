# Godot 4.x GDExtension 与编辑器插件

两个都是"看起来很高级、实际很容易做错方向"的领域。
本文先讲**什么时候不该用**，再讲怎么做。

## 第一部分：GDExtension

### 0. 决策树：先看瓶颈，再看语言

⚠ **不要预设"C++ 就一定快"**。先用 profiler 确认热点在哪。

| 情形 | 首选 | 何时升级 |
|---|---|---|
| 原型、工具链、UI、内容驱动规则 | **GDScript** | 热点经 profiler 确认后再迁移 |
| 团队已有 C# 资产 | C# | 跨 Godot API 热路径成为瓶颈 |
| 大量循环/数学/逐元素处理 | GDExtension C++ | **算法本身没优化前别迁移** |
| 接第三方 C/C++/Rust 库或平台 SDK | GDExtension | 无脚本接口且不能用进程间通信 |
| 改渲染、模块系统、ClassDB 深层 | 静态 C++ 模块 | godot-cpp 暴露不了所需内部能力 |
| 只想要"更快"，但热点在 GPU/导航/加载 | **保持 GDScript** | 换语言只改 CPU 侧脚本开销 |

⚠ **热点在 GPU / 导航 / 资源加载时，换 C++ 基本没用**。

### 1. 版本匹配（最大的坑）

工具链：`gdextension_interface.h`（C 函数）+ extension_api.json（API 描述）
+ `.gdextension`（加载配置）+ 绑定生成器。

```python
# SConstruct：显式指定目标 API，别依赖 master 自动选最新
env = SConscript("godot-cpp/SConstruct", {"api_version": "4.7"})
```

⚠ **官方长期目标是旧扩展兼容以后小版本，反之不成立**。
4.0 的扩展**不能**用在 4.1+（4.0→4.1 是已确认的入口 ABI 破坏）。

⚠ **`compatibility_minimum` 必须写**，4.3 起才有 `compatibility_maximum`。

```ini
[configuration]
compatibility_minimum = 4.1
```

⚠ **报"仅兼容 Godot 4.x 或更高"或入口未找到时，
第一反应是版本下限、入口符号、API JSON 三者不一致**，不是加编译器优化。

### 2. 浮点精度是隐形 ABI

⚠ **扩展只能与编译时精度相同的引擎一起工作**。
双精度引擎必须用双精度构建的扩展。

⚠ 大世界项目换成自编译双精度后，**旧的 `.so/.dll/.dylib` 不可直接复用**。
CI 必须把 `precision=double` 与 `single` 当作**两种工件**。

（这与 `openworld.md` 的双精度构建是同一件事的两面。）

### 3. 热重载 ≠ 生产热更新

⚠ `GDExtensionManager.reload_extension()` **只在编辑器可用**。
⚠ `reloadable=true` 从 4.2 起支持 godot-cpp 绑定，其他语言未必支持，
官方建议**只用于开发调试**。
⚠ 静态状态、全局单例、已创建对象、资源格式、类布局**不能迁移**。

安全做法：保存场景 → 关闭引用扩展的场景 → 重新编译 → 让编辑器重载 → 重新打开。

### 4. 语言绑定

| | 状态 |
|---|---|
| **godot-cpp** | **官方提供并支持** |
| Rust `gdext` | 最成熟的社区方案（`cdylib` 输出，有三级安全检查） |
| Swift `SwiftGodot` | 社区，Windows 还要分发 Swift 运行库 |

⚠ 选社区绑定要检查：目标 Godot 小版本、是否维护、热重载支持、是否暴露最新 API。
**不要只看 Star。**

## 第二部分：编辑器插件

### 5. 插件类型

| 基类 | 作用 |
|---|---|
| `EditorPlugin` | 通用入口（面板、菜单、dock） |
| `EditorInspectorPlugin` | 自定义检视器 |
| `EditorImportPlugin` | 自定义导入器 |
| `EditorExportPlugin` | 导出时处理 |
| `EditorScenePostImportPlugin` | 场景导入后处理 |

### 6. 最小结构

```ini
; plugin.cfg
[plugin]
name="MyPlugin"
description="..."
author="..."
version="1.0.0"
script="plugin.gd"
```

```gdscript
@tool                      # ← 忘了这行：脚本在编辑器里不执行
extends EditorPlugin

func _enter_tree() -> void:
    pass                   # 注册 UI、菜单、检视器

func _exit_tree() -> void:
    pass                   # **必须对称注销**
```

⚠ **`@tool` 不加，脚本在编辑器里根本不跑** —— 插件看起来完全没生效。

⚠ **`_exit_tree()` 必须对称注销** `_enter_tree()` 里注册的一切。
不注销会导致：禁用插件后 UI 残留、重复启用时控件翻倍、编辑器状态泄漏。

### 7. 插件的坑

⚠ **编辑器侧最危险的不是 API 写错，是生命周期和状态泄漏**。

- `@tool` 脚本会在编辑器里跑，**副作用会真的修改场景文件**
- 与 UndoRedo 不集成，用户无法撤销插件的修改
- 导入缓存需要显式处理，否则改了导入器不生效
- 插件里持有节点引用会阻止释放

> **反模式清单（不能怎么做，审核用）** → `audit/godot/gdext-plugin.md`


## 第四部分：相关文档

- 插件引入与版本锁（commit）→ `plugins.md`
- 版本与 ABI → `version-47-48.md`
- 大世界双精度 → `openworld.md`
- 性能剖析 → `performance.md`
- C#/.NET → `csharp.md`
