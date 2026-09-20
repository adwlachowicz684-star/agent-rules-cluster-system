# Godot 4.x C# / .NET 工具链

> **反模式清单（不能怎么做，审核用）** → `audit/godot/csharp.md`


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


## 2. 导出字段与信号

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

## 3. 节点获取

```csharp
var a = GetNode<Label>("Path");        // 类型不匹配抛异常
var b = GetNodeOrNull<Label>("Path");  // 不匹配返回 null
```

⚠ 泛型版本**不是语法糖**，它把类型转换放进 API，提供类型安全。
优先用 `GetNode<T>`。


## 4. 字符串类型

| | 用途 |
|---|---|
| `StringName` | 节点名、方法名、信号名、输入动作、资源路径 |
| `string` | 用户文本、日志、动态拼接 |

⚠ 两者**不是无条件互换**。`StringName` 适合可复用的内部标识（比较快、可缓存），
但**本地化文本不要转成 `StringName`**。

## 5. 释放

```
QueueFree()   请求释放（下一帧安全释放）—— 最常用
Free()        立即释放 —— 危险，易悬空
Dispose()     C# 侧释放（IDisposable）
```

⚠ Godot 对象**不要用 `using` 或手动 `Dispose`** 随意释放，
引擎侧生命周期由 `QueueFree`/引用计数管。
对 `RefCounted`（如 `Resource`）不用手动释放。

## 6. 互操作

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


## 7. 相关文档

- GDScript 进阶 → `gdscript-advanced.md`
- 调试 → `debugging.md`
- 平台导出限制 → `cicd-publish.md`
- 多人/信号的 C# 注意 → `multiplayer.md`
