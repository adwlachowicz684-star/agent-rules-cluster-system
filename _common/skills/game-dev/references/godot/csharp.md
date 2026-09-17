# Godot 4.x C# / .NET 工具链

## 0. 先决定要不要用 C#

**C# 的收益来自工程能力，不是运行时性能。**

⚠ **官方 FAQ：C# 与 GDScript 大致同一数量级**。
C# 纯计算更快，但大量调用 Godot API 时有 marshalling 成本，
GC 还可能在不确定时刻引入卡顿。

**别把"换成 C#"当优化**。先用 Profiler 找到热点（见 `debugging.md`）：

| 热点类型 | C# 更可能胜出？ |
|---|---|
| 大量纯数值计算、序列化、数据管线、网络协议 | ✅ |
| 反复跨边界访问 `GlobalTransform` | ✅ |
| `MoveAndSlide`、物理、导航、渲染、资源加载 | ❌ 只把胶水层变快 |
| 每帧遍历少量节点 | ❌ |

### 四项决策门槛

1. **目标平台含 Web → 不用 C# 作主语言**（Godot 4 C# 不能导出 Web）
2. 单人 / 两周原型 / 美术驱动 → **优先 GDScript**
3. 需要 NuGet、强类型、复杂数据模型、自动测试、已有 C# 团队 → **优先 C#**
4. 混合技术 → **边界做成少量稳定接口**，不要让两种语言对象两两互调

⚠ **"先开发以后再加 Web"如果以 C# 为主，是立项时就要锁定的架构风险**。
后期改不回来。

## 1. 环境：四个版本必须一致

```
编辑器架构（必须 .NET 版，不是标准版）
.NET SDK 版本
目标框架 TFM（net6.0 / net8.0）
导出模板版本
```

| Godot | .NET 政策 | 状态 |
|---|---|---|
| 4.0 | .NET 6.0 | 官方确认 |
| 4.1 | 沿用 .NET 6 | 总体确认，逐补丁待核对 |
| 4.2 | 桌面最低 6，Android 最低 7，iOS 最低 8 | 官方确认 |
| 4.3 | 沿用既有目标，但应核查本地 GodotSharp | 部分确认 |
| **4.4** | GodotSharp 面向 **.NET 8**，打开项目自动改 `net8.0` | 官方确认 |
| 4.5 | 要求 .NET 8+ | 官方确认 |
| 4.6 | 要求 .NET 8+，**Android 导出要求 .NET 9+** | 官方确认 |

⚠ **"4.x"不是有效的版本标签**。小版本升级可能改变 SDK、TFM 和导出依赖。
4.4 打开旧项目会**自动**把目标升到 `net8.0` —— 这是便利机制，**不是迁移证明**。

⚠ `dotnet` 命令存在 ≠ SDK 架构正确。要检查 `dotnet --list-sdks` 与编辑器日志里实际选的 TFM。

⚠ **标准版 Godot 不能运行或构建 C# 项目**。下载时必须选 .NET/C# 版。

## 2. 命名与生命周期：最容易踩的坑

⚠ **C# 用 PascalCase 访问 Godot API**，生命周期方法名和签名都必须匹配，
否则**不会被调用**（没有报错）。

| GDScript | C# |
|---|---|
| `_ready()` | `public override void _Ready()` |
| `_process(delta)` | `_Process(double delta)` |
| `_physics_process(delta)` | `_PhysicsProcess(double delta)` |
| `_enter_tree()` / `_exit_tree()` | `_EnterTree()` / `_ExitTree()` |
| `_input(event)` | `_Input(InputEvent @event)` |
| `_unhandled_input(event)` | `_UnhandledInput(InputEvent @event)` |
| `_draw()` | `_Draw()` |
| `set_name("x")` | `Name = "x"` |

⚠ **C# 没有 `@onready`**。字段初始化发生在构造期，此时节点**还没进树**，
`GetNode` 会失败。必须在 `_Ready` 里取：

```csharp
private Label _label;

public override void _Ready()
{
    _label = GetNode<Label>("Label");   // ✅ 在 _Ready 里
}

// ❌ 字段初始化期取子节点，路径查找失败
// private Label _label = GetNode<Label>("Label");
```

## 3. 导出字段与信号

```csharp
[Export] private NodePath _targetPath;
[Export] private string _displayName = "默认";
[Export(PropertyHint.Range, "0,100,1")] private int _hp = 100;
[Export(PropertyHint.File, "*.tres")] private string _dataFile;
```

```csharp
[Signal]
public delegate void HealthChangedEventHandler(int current);
// 生成 HealthChanged 事件 + SignalName.HealthChanged

// 发射
EmitSignal(SignalName.HealthChanged, current);

// 订阅（在 _Ready）
public override void _Ready()
{
    HealthChanged += OnHealthChanged;
}

// 取消订阅 —— 必须！
public override void _ExitTree()
{
    HealthChanged -= OnHealthChanged;
}
```

⚠ **委托名必须以 `EventHandler` 结尾**，否则不生成事件。

⚠ **C# 的信号不会自动断开** —— 这与 GDScript 不同。
长期订阅者若不在 `_ExitTree` 清理，会阻止对象回收。
（详见 `multiplayer.md` 里 lambda 订阅的坑）

⚠ 别把业务逻辑放进 `[Export]` 属性的 setter 里，
编辑器改值的时机可能与初始化顺序冲突。

## 4. 节点获取

```csharp
var a = GetNode<Label>("Path");        // 类型不匹配抛异常
var b = GetNodeOrNull<Label>("Path");  // 不匹配返回 null
```

⚠ 泛型版本**不是语法糖**，它把类型转换放进 API，提供类型安全。
优先用 `GetNode<T>`。

## 5. 异步的坑

```csharp
await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
```

⚠ **await 恢复后节点可能已被 `QueueFree`**，
`this` 可能不再是有效引擎实例。必须守卫：

```csharp
await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
if (!IsInstanceValid(this))
    return;
```

⚠ `async void` 的异常会**逃离 Godot 调用栈**，且生命周期难控制。
不要用 `async void`，用 `async Task`。

⚠ 别在后台 `Task` 里长期持有 `Node` 引用。

## 6. 字符串类型

| | 用途 |
|---|---|
| `StringName` | 节点名、方法名、信号名、输入动作、资源路径 |
| `string` | 用户文本、日志、动态拼接 |

⚠ 两者**不是无条件互换**。`StringName` 适合可复用的内部标识（比较快、可缓存），
但**本地化文本不要转成 `StringName`**。

## 7. 释放

```
QueueFree()   请求释放（下一帧安全释放）—— 最常用
Free()        立即释放 —— 危险，易悬空
Dispose()     C# 侧释放（IDisposable）
```

⚠ Godot 对象**不要用 `using` 或手动 `Dispose`** 随意释放，
引擎侧生命周期由 `QueueFree`/引用计数管。
对 `RefCounted`（如 `Resource`）不用手动释放。

## 8. 互操作

```csharp
// C# 调 GDScript
var script = GD.Load<Script>("res://helper.gd");
var obj = new GodotObject();
obj.SetScript(script);
obj.Call("my_method", 123);
```

```gdscript
# GDScript 调 C#
var cs_node = get_node("CSharpNode")
cs_node.Call("MyMethod", 123)
```

⚠ **互调用是字符串式的**，编译期不检查 —— 改个方法名两边都不报错，运行时才失败。

⚠ 混用时**边界要做窄**。让 C# 与 GDScript 对象两两互调，
会得到一个无法重构、无法静态检查的网。

## 9. 常见坑

| 坑 | 后果 |
|---|---|
| 用标准版 Godot 开 C# 项目 | 无法运行/构建 |
| 认为 C# 一定更快 | 大量 API 调用时反而更慢 |
| 字段初始化期 `GetNode` | 节点未进树，失败 |
| 方法名写成 `_ready` | **不会被调用，且不报错** |
| 委托名不加 `EventHandler` | 不生成事件 |
| 不取消信号订阅 | 阻止对象回收（C# 不会自动断开） |
| await 后不检查 `IsInstanceValid` | 对已释放节点操作 |
| `async void` | 异常逃离调用栈 |
| 用 `Free()` 而不是 `QueueFree()` | 悬空引用 |
| 手动 `Dispose` 引擎对象 | 生命周期混乱 |
| 目标平台含 Web 仍用 C# | 无法导出 |
| 4.4 自动升 net8.0 当迁移完成 | NuGet 包可能不兼容 |
| 跨语言调用改方法名 | 编译不报错，运行时失败 |

## 10. 相关文档

- GDScript 进阶 → `gdscript-advanced.md`
- 调试 → `debugging.md`
- 平台导出限制 → `cicd-publish.md`
- 多人/信号的 C# 注意 → `multiplayer.md`
