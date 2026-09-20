<!-- oversize-exempt: 反模式清单，审核用 -->
# csharp — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/csharp.md`

## 先决定要不要用 C#

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

## 命名与生命周期：最容易踩的坑

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

## 异步的坑

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

## 常见坑

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
