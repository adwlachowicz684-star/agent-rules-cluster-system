# Godot 版本兼容与迁移

⚠ **"同属 4.x"不是免测证明。** 小版本升级可能改变 SDK、TFM、导出依赖和默认行为。

## 1. 4.x 各版本的结构性变化

| 版本 | 已确认的变化 | 升级要做什么 |
|---|---|---|
| **4.0** | C# 从 Mono 迁到 .NET 6；C# 不能导出 Android/iOS/Web | 运行时、CI、导出模板一起迁 |
| **4.1** | 维护分支，只回移最安全修复 | 版本锁定，跑完整回归 |
| **4.2** | C# Android/iOS 实验支持；SDK 门槛分化 | 移动端先建 release/AOT 验证 |
| **4.3** | **`TileMapLayer` 替代旧 TileMap**；`Parallax2D` 推荐；**2D 物理插值** | 转换场景，测插值与相机 |
| **4.4** | GodotSharp 面向 **.NET 8**，打开项目自动改 `net8.0` | 升 SDK、NuGet、AOT/trim、CI 镜像 |
| **4.5** | 要求 .NET 8+ | 统一 TFM 策略 |
| **4.6** | 要求 .NET 8+，**Android 导出要求 .NET 9+** | 桌面/Android 分开设 SDK |

⚠ **官方也承认所有发布都可能带来变化**。团队不应把"4.x 内部升级"当低风险。

### 4.3 的两个行为变化（不只是改名）

**① 2D 物理插值** —— 显示帧与物理 tick 解耦。
这**改变视觉表现**：角色移动、相机跟随、拖尾都可能不同。
升级后必须重测手感。

**② `TileMap` → `TileMapLayer`** —— 这是三重迁移：

```
类型改名 + 场景结构改变 + 脚本 API 改变
```

⚠ 旧 `TileMap` 标 deprecated 但暂时保留。
官方有转换工具处理**场景节点结构**，但**脚本仍要手工改**。

⚠ 不要只在 `using` 里加别名。要重新核对：
图层遍历、单元格坐标、地形、导航、碰撞、渲染顺序、保存数据。
如果资产管线自动生成 TileMap 场景，**生成器也要改**。

⚠ **4.3 的 `TileMap.set_cell` 首参变了**：
4.0–4.2 是 `layer: int`，4.3+ 是 `coords: Vector2i`。
用错版本的表现是"代码不报错但图块不出现"——最难排查。
（详见 `tilemap.md`）

## 2. 从 3.x 迁移到 4.x

### 官方工具会做什么、不会做什么

官方升级工具会**自动重命名节点和资源名**，但：

- ⚠ **不会备份** —— 迁移前必须自己完整备份
- ⚠ **不处理字符串里的路径、组名、信号名**
- ⚠ **不处理动态字符串调用、编辑器插件、生成器**
- ⚠ **不做决策** —— 每个自动替换仍需 review

### 高频改名对照

| Godot 3.x | Godot 4.x | 注意 |
|---|---|---|
| `instance()` | `instantiate()` | |
| `Spatial` | `Node3D` | |
| `KinematicBody` / `2D` | `CharacterBody3D` / `2D` | 物理 API 也变了 |
| `File` / `Directory` | `FileAccess` / `DirAccess` | **API 整体不同**，多为静态方法 |
| `OS.get_screen_size()` | `DisplayServer` API | 职责迁移 |
| `AnimatedSprite` | `AnimatedSprite2D` | |
| `Viewport` | `SubViewport` | |
| `Particles` | `GPUParticles3D` | |
| `GIProbe` | `VoxelGI` | |
| `Thread.is_active()` | `Thread.is_alive()` | |
| `connect("sig", obj, "m")` | `SignalName.X += handler`（C#） | |

⚠ **不能只靠搜索替换**。重载、默认参数、异常行为必须对照目标稳定版 API。

### 必须手工处理的部分

| 项 | 变化 |
|---|---|
| 文件 IO | `File`/`Directory` → `FileAccess`/`DirAccess`，API 整体不同 |
| 窗口/屏幕 | OS 方法移到 `DisplayServer` |
| 线程 | `start(self, "method", [...])` → `start(method.bind(...))` |
| **随机种子** | **4.x 加载项目时自动 randomize**，需要确定性必须显式设种子 |
| 资源格式 | `.res`/`.tres` 的 `ArrayMesh` 在 4.0 与 3.x **格式不兼容**，需重新导入 |

⚠ **随机种子自动 randomize** 是个静默陷阱：
3.x 项目迁移后"随机行为变了"，且看不出原因。
需要确定性（回放、程序化生成）必须显式 `seed()`。

⚠ 迁移时**只迁源资源与项目配置**，
`.godot/` 和 `.import` 产物要在目标引擎**重新导入**，不要迁移。

### 迁移策略

```
完整备份 + 建分支
  ↓
在目标 Godot 4 打开项目
  ↓
运行官方升级工具
  ↓
修复无法自动转换的 API
  ↓
转换 TileMap / Parallax 等资源
  ↓
锁定 NuGet 与 GodotSharp
  ↓
跑全平台导出 + 烟雾测试
```

⚠ **不要长期维持双版本**。3/4 的资源、脚本 API、C# 运行时都不同，
长期双版本会持续制造分支差异。引擎版本必须唯一。

## 3. 跨版本兼容的做法

### 版本号探测：只用于构建期

```gdscript
var v := Engine.get_version_info()   # {major, minor, patch, status, build, hex}
if v["hex"] >= 0x040300:
    ...
```

⚠ **不要把它散布进每帧业务逻辑**。
只应在 polyfill、插件兼容层、临时迁移代码里用，且要设删除日期。

### `OS.has_feature` vs `Engine.is_editor_hint`

| | 含义 |
|---|---|
| `OS.has_feature("editor")` | 编辑器内为真，**导出后为假** |
| `Engine.is_editor_hint()` | 脚本是否在编辑器上下文中运行 |

⚠ 别用 `has_feature` 去猜 API 是否存在。它是环境检测，不是版本检测。

### 插件锁 commit，不锁版本范围

⚠ **"兼容 Godot 4.x"这种版本范围在引擎小版本升级时必然变成排查负担**。
插件依赖场景结构、编辑器 API、内部类，小版本都可能破坏。

要记录的清单：

```
Godot 版本（精确，含 status）
插件 Git commit（不是版本号）
plugin.cfg 内容
依赖的 DLL / NuGet 版本
导出模板版本
```

用 Git submodule 锁 commit，比写版本范围可靠。

## 4. 升级检查清单

按这个顺序执行，**不要跳**：

1. **备份 + 建分支**，记录 Godot/SDK/NuGet/插件 commit
2. 清理 `.godot`、`.import`、旧构建产物
3. 打开项目，运行升级工具
4. 编译 C#，修复 GodotSharp API、信号、路径
5. 处理 TileMap、Parallax、着色器、材质、动画、输入映射、物理设置
6. **逐个导出目标平台**并运行烟雾测试

⚠ **不要先改业务逻辑再处理资源导入** ——
那样无法区分是脚本问题还是资产问题。

### 升级后的回归重点

从"能打开"升到"**行为不变**"：

- 启动与 autoload 顺序
- 场景实例化、资源加载
- 输入映射
- 存档/读档
- 动画、粒子、着色器、光照/GI
- **TileMap 图层与碰撞**
- **Parallax**
- **2D/3D 物理插值**（4.3+，影响移动、相机、拖尾）
- 音频、多线程、GC 卡顿
- C# 信号连接、跨语言调用
- Android/iOS 权限与生命周期
- 发布签名与包体大小

> **反模式清单（不能怎么做，审核用）** → `audit/godot/version-migration.md`


## 5. 相关文档

- TileMap 4.3 vs 4.2 两套 API → `tilemap.md`
- C# .NET 版本政策 → `csharp.md`
- 导出模板版本 → `cicd-publish.md`
- 确定性/种子 → `advanced-topics.md`
