# 诊断与稳定性工程（Godot 4.7.2）

"错误处理" 此前 **0 命中**。已有文档讲调试面板，本文讲**上线后怎么知道哪里坏了**。

## 0. 三类事件是三个通道

⚠ **脚本错误、GDScript 调用栈、原生崩溃属于不同通道，绝不能当作同一类事件处理。**

| 事件 | 通道 |
|---|---|
| 脚本错误 | `Logger._log_error` |
| 原生崩溃 | **进程直接终止**，靠外部收集 |

## 1. ⚠ 发布版的 stdout 与 stderr 行为不同

**`print()` 所在 stdout 直到退出或崩溃才可能刷盘；**
**`printerr()` / `push_error()` / `push_warning()` 所在 stderr 会逐条立即刷盘。**

⚠ 这意味着崩溃前的最后一条 `print()` **可能根本没写出去**。
要留面包屑就得用 stderr 通道，或 4.7 的 `debug/file_logging`（把 stdout/stderr 与崩溃回溯一起写入 `user://`）。

⚠ **日志内容是隐私边界** —— 不写 token、口令、聊天原文、设备标识符原文；
⚠ 截图/录像/场景树同样可能含聊天与昵称，上传前要授权并脱敏。

## 2. ⚠ GDScript 没有 try/catch

必须靠显式控制流（返回值 / `Result` 类型 / 断言）。

**未捕获脚本错误的可观测入口是 `Logger._log_error`**
—— 可接收函数、文件、行号、代码/原因、错误类型与脚本回溯，
错误类型包括普通 Error、Warning、Script、Shader。

⚠ 注册必须尽早：官方建议在 **autoload 的 `_init()`** 调 `OS.add_logger()`，
因为引擎自身初始化消息仍不可访问。

### ⚠ assert 在 release 中不求值

**`assert` 在非 debug 构建中被忽略，表达式也不会求值。**

⚠ 因此**不能**把修改状态、释放资源、累加指标、读取外部数据写进 assert：
`assert(inventory.remove(item))`、`assert(a == b, expensive_debug_dump())`
在 release 里**根本不执行**。

→ assert 参数必须是**无副作用表达式**；
→ 发布版输入校验与恢复流程**不能用 assert 承担**。

### ⚠ 静默失败最危险

`load()` 失败返回 null、文件打开失败返回 null。
**静默继续是最危险的反模式** —— 要显式分支或用 `Result` 向上传递。

## 3. 原生崩溃：进程没机会上报

⚠ **进程崩溃时脚本可能没机会执行** ——
只能依赖日志文件、**外部 watchdog** 和崩溃后上报。

⚠ **退出码为 0 不代表没崩溃** —— 自定义退出可能掩盖异常。
watchdog 还应检查 session marker、崩溃字符串、最近错误日志。

**带符号模板 + 平台 minidump/dSYM/PDB** 决定能否符号化。

**Sentry**：官方有 Godot SDK（Native/minidump、Cocoa、Android、Web），
可捕获脚本/shader/C# 错误、GDScript 栈、日志、上下文、场景树和截图。
⚠ 但"4.7.2 各导出模板均开箱兼容"**仍待核对**，要在每个目标模板分别验证。

## 4. 截图与录像：时机决定画面

`get_viewport().get_texture().get_image()` 要在**正确时机**调用（帧末 vs 帧中结果不同）。

⚠ **Movie Maker 是离线影视工具，不是玩家实时录像器** ——
官方明确说不适用于最终用户录制，玩家应用 OBS 等。
且只能在启动时启用，**启动后无法切换**。

内置 AVI 用 MJPEG，最多 4 GB；PNG 序列 + WAV 无损但体积大速度慢。

## 5. 运行时健康检查

`Performance.get_monitor()` 在**发布版可用**的：FPS、节点数、**孤儿节点**、对象数。
⚠ **静态/动态内存监视器在发布版不可用**。

⚠ 监控要有采样窗口、变化率与绝对阈值 —— 单帧抖动会触发误降级。

⚠ 长时间运行要**外部 watchdog**，不能只信任游戏内统计。

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/diagnostics.md`


## 6. 待核对项（运行时验证）

⚠ 待核对：Sentry 在 4.7.2 各导出模板的开箱兼容性 · 验证：每个目标模板分别验证初始化、捕获、附件、符号上传

⚠ 待核对：`debug/file_logging` 在目标平台的实际落盘路径 · 验证：导出后崩溃并检查 user://logs

## 7. 相关文档

- 调试工具/GM → `devtools.md`
- 性能剖析 → `perf-profiling.md`
- 埋点与统计 → `analytics.md`
- 平台导出 → `platform-export.md`
- 存档安全 → `security.md`
- 崩溃与存档的关系 → `save-migration.md`
