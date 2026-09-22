# Godot 4.x 调试与故障排查

**调试不是 print 大法，是"先分类再定位"。** 本章讲方法论，不讲优化技巧（见 `performance.md`）。

## 0. 先分清故障类型

| 症状 | 最可能的原因 | 第一步做什么 |
|---|---|---|
| 崩溃 | 空引用 / 递归 / 栈溢出 | 看 stderr，不要看 stdout |
| 卡死不报错 | 死循环 / 阻塞等待 / 协程悬挂 | 看线程，不在主线程的逻辑先挪回来 |
| 帧率下降 | CPU 或 GPU 瓶颈 | 先区分是哪一侧（见 §3） |
| 只在导出版出现 | 资源未导出 / release 差异 | 对比 release 与 debug 的差异项 |
| 只在真机出现 | 性能 / 权限 / 平台 API | 远程调试 + 真机日志 |
| 内存持续增长 | 泄漏（节点 / 信号 / 资源） | Monitor 看对象数，不是看内存总量 |
| 节点为 null | 时机或路径错 | 确认是在 `_ready` 之后取的吗 |
| 信号没触发 | 连接未建立 / 名字错 / 对象已释放 | 打印 `is_connected` |

## 1. 断点

### 两种断点，用途不同

| | 存在哪 | 跨机器同步 |
|---|---|---|
| gutter 断点（点行号） | 编辑器本地 | ❌ 不随版本控制 |
| **`breakpoint` 关键字** | 脚本文件里 | ✅ 随版本控制 |

```gdscript
func _process(delta):
    var t = transform
    if t.origin.length() > 1000:
        breakpoint      # 单独一行，不加括号
    position += velocity * delta
```

⚠ **`breakpoint` 是裸关键字，不加括号不加参数**。

⚠ **多线程代码里断点不会生效**（官方明确警告）。
在 `Thread` 里打的断点会**静默失效**，程序照跑 —— 你会以为"这段代码没执行"。
定位办法：先挪回主线程复现，或用 `OS.get_thread_caller_id()` 打印执行线程。

### 调试器面板各标签

| 标签 | 看什么 |
|---|---|
| **Debugger** | 命中行、调用栈、局部变量、单步控制 |
| **Errors** | `push_error` / `push_warning` 输出，比 Output 更适合归类排查 |
| **Profiler** | 帧时间、idle/physics 的函数级分解 |
| **Visual Profiler** | CPU/GPU 各**渲染阶段**耗时 |
| **Monitor** | FPS、内存、对象数、draw call、音频 |
| **Network** | 多人游戏排查 |
| **Video RAM** | 纹理/缓冲占用，查显存泄漏 |
| **Evaluator** | 命中断点后求值表达式（REPL） |

⚠ **Visual Profiler 只测渲染任务的 CPU 时间**，不含脚本与物理。
这是区分 CPU/GPU 瓶颈的第一把钥匙（见 §3.4）。

### 远程调试

```bash
# 真机上运行，连回本机
./game --remote-debug tcp://<本机IP>:6007
```

- 默认端口 6007，本机要开防火墙并启用 "Keep Debug Server Open"
- `--remote-debug` 与 `--dap-port` 是**两条不同协议路径**，别混用
  - `--remote-debug`：连回 Godot 编辑器
  - `--dap-port`：Debug Adapter Protocol，给 VS Code 等外部编辑器用

## 2. 日志

### 三个输出，行为完全不同

| | release 导出后 | 是否带栈帧 |
|---|---|---|
| `print()` | ❌ **退出时才刷**，崩溃时可能丢失 | ❌ |
| `print_debug()` | ❌ 移除 | ❌ |
| `push_error()` | ✅ 保留，**立即刷新** | ✅ |
| `printerr()` | ✅ 保留，**立即刷新** | ❌ |
| `assert()` | ❌ **被完全剥离** | — |

⚠ **崩溃时只信 stderr**。`print()` 的输出在崩溃时很可能丢失，
导致"崩溃前最后一行日志"骗你 —— 那不是崩溃点。

⚠ **`assert` 在 release 被剥离**，绝对不能用它做运行时校验。
上线前要把 `assert` 换成 `push_error` + 降级处理。

### 日志分级约定

```gdscript
# 不要满屏 print，按级别走
func log_debug(msg: String) -> void:
    if OS.is_debug_build():
        print("[D] ", msg)

func log_warn(msg: String) -> void:
    push_warning(msg)

func log_error(msg: String, ctx: Dictionary = {}) -> void:
    push_error("%s | ctx=%s" % [msg, ctx])
```

⚠ 日志要能**关掉或分级**，不能发布版还在每帧打印。
每帧 `print()` 本身就是性能问题，会让 Profiler 数据失真。

## 3. 性能剖析：怎么找到瓶颈

### 3.1 用 Monitor 看总量

```gdscript
Performance.get_monitor(Performance.TIME_FPS)
Performance.get_monitor(Performance.TIME_PROCESS)        # 帧处理耗时
Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS)
Performance.get_monitor(Performance.OBJECT_COUNT)        # 对象总数
Performance.get_monitor(Performance.OBJECT_NODE_COUNT)
Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT)  # 孤儿节点
Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)
Performance.get_monitor(Performance.MEMORY_STATIC)
```

⚠ **`MEMORY_STATIC` 与 `OBJECT_ORPHAN_NODE_COUNT` 在 release 导出后恒返回 0**。
它们是 debug-only 指标 —— 别在发布版上靠它们查泄漏，会得到"没问题"的假象。

### 3.2 帧时间分解

```
一帧 = process (idle) + physics + render
```

- **process**：脚本 `_process`、tween、信号
- **physics**：`_physics_process`、物理模拟
- **render**：draw call、shader

先看这三项谁最大，再深入。

### 3.3 自定义埋点

Profiler 给的是函数级，业务级要自己埋：

```gdscript
class_name FrameProbe
extends RefCounted

var _t: Dictionary = {}
var _samples: Dictionary = {}

func begin(key: StringName) -> void:
    _t[key] = Time.get_ticks_usec()

func end(key: StringName) -> void:
    if not _t.has(key):
        return
    var d := Time.get_ticks_usec() - int(_t[key])
    if not _samples.has(key):
        _samples[key] = []
    var arr: Array = _samples[key]
    arr.push_back(d)
    if arr.size() > 120:
        arr.pop_front()

func report() -> String:
    var out := ""
    for k in _samples:
        var arr: Array = _samples[k]
        var sum := 0
        for v in arr:
            sum += int(v)
        out += "%s: 均值 %.2fms (n=%d)\n" % [k, sum / float(arr.size()) / 1000.0, arr.size()]
    return out
```

### 3.4 区分 CPU 瓶颈还是 GPU 瓶颈

这是最关键也最容易搞错的一步。

**判定流程**：

1. 看 **Visual Profiler** 的 GPU 时间
2. **降低分辨率**（渲染缩放降到 0.25）
   - 帧率明显上升 → **GPU 瓶颈**（像素填充率/纹理带宽）
   - 帧率几乎不变 → **CPU 瓶颈**
3. CPU 瓶颈再分：
   - Profiler 显示脚本函数占比高 → 脚本问题
   - draw call 数异常高 → 合批问题（CPU 侧提交开销）
   - physics 高 → 物理问题

⚠ **只看 FPS 无法区分**。80fps 可能是 GPU 满也可能是 CPU 满，
优化方向完全相反。降分辨率测试是最快的判别法。

## 4. 常见故障的定位流程

### 卡死不报错

```
1. 确认是不是死循环：while / 递归 / 大循环
2. 确认是不是阻塞：HTTP 同步等待、文件同步读、await 无信号源
3. 确认是不是多线程死锁
4. 在主线程打断点验证（多线程断点无效）
5. 用 --headless 跑：能跑通说明是渲染/输入卡住
```

⚠ `await` 一个**永远不会发出的信号**会永久悬挂，且不报错。
常见于 `await get_tree().create_timer(x).timeout` 里 timer 没被 keep。

### 帧率突然下降

```
1. 先降分辨率判定 CPU/GPU
2. 看 Monitor 的 OBJECT_COUNT 是否在涨（泄漏）
3. 看 draw call 是否突然变多
4. 看 Video RAM 是否涨（纹理泄漏）
5. 最近改动二分回退
```

### 只在导出版出现

| 差异项 | 说明 |
|---|---|
| `assert` 被剥离 | 依赖 assert 的分支行为变了 |
| `print` 不再输出 | 依赖 print 的调试逻辑失效 |
| debug-only 指标为 0 | 依赖这些指标的逻辑失效 |
| 资源未导出 | 编辑器里能读、导出后 res:// 找不到 |
| `.gd` 未包含在导出过滤 | 动态加载的脚本丢失 |
| 文件路径大小写 | Windows 不敏感、Linux 敏感 |

⚠ **动态 `load()` 的路径导出后可能找不到**。
引擎的导出依赖分析**静态扫描**，字符串拼接出来的路径扫不到。
要么把资源列入导出过滤，要么改用 `ResourceLoader.exists()` 兜底。

### 节点为 null

```
1. 是在 _ready 之后取的吗？（_init 里取子节点必失败）
2. 路径写对了吗？（%UniqueName / ../ 相对路径）
3. 节点是不是已经被 queue_free 了？
4. 场景是不是还没 instantiate？
5. 是不是在 _enter_tree 取的（此时子节点未就绪）
```

⚠ `get_node()` 失败返回 null 不报错，
后续用它才会空引用崩溃 —— 崩溃点和真正的原因不在一处。

### 信号没触发

```gdscript
# 先确认连上了没有
print(obj.is_connected("pressed", callable))
```

```
1. 信号名拼错（运行时才报错，且容易看漏）
2. 连接时机晚于信号发出
3. 对象已被释放（GDScript 通常自动断开，C# lambda 不会）
4. emit 的参数个数/类型不匹配
5. 连接在错误的实例上（多个实例混淆）
```

⚠ **C# 的 lambda 订阅不会自动断开**（见 `multiplayer.md` 与 `csharp.md`）。

### 内存持续增长

```
1. Monitor 看 OBJECT_COUNT / NODE_COUNT 是否单调涨
2. 看 ORPHAN_NODE_COUNT（debug 版）
3. remove_child 后是否 queue_free（Godot 最经典的泄漏）
4. 信号连接是否清理
5. Tween/Timer 是否停止
6. 资源是否 decRef
```

⚠ 看**对象数**比看内存总量有用得多。内存总量受 GC/分配器影响会滞后。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/debugging.md`


## 5. 相关文档

- 优化技巧 → `performance.md`
- 性能基准测试 → `testing-advanced.md`
- 内存泄漏判据 → 审查侧 `../../code-audit/scripts/godot-audit.py` 的 GD01/GD02
- 崩溃排查清单 → 见 §0 的症状表
