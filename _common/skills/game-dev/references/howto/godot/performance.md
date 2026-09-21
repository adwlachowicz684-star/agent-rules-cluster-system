# Godot 4.x 性能诊断与优化

**先测量再优化。** 项目设置里有 Profiler / Monitors 两个工具，凭感觉改是最大的浪费。

## 1. 先定位，再动手

```
打开 Debugger → Profiler，跑最吃性能的场景，看哪一栏高
├─ Script 高   → 脚本逻辑（每帧查找节点？每帧分配？）
├─ Render 高   → DrawCall 太多（材质不共享？没合批？）
├─ Physics 高  → 物理体太多？每帧空间查询？
└─ Memory 涨   → 有东西没释放
```

**Monitors 面板**（实时数值，排查泄漏最有用）：

```gdscript
func _on_check_pressed() -> void:
    print("对象总数: %d" % Performance.get_monitor(Performance.OBJECT_COUNT))
    print("孤儿节点: %d" % Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT))
    print("DrawCall: %d" % Performance.get_monitor(
        Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
    print("静态内存: %.1f MB" % (Performance.get_monitor(
        Performance.MEMORY_STATIC) / 1048576.0))
```

**用法**：进关卡前记一次，出关卡后记一次。

- `OBJECT_COUNT` 不下降 → 有东西没释放
- `OBJECT_ORPHAN_NODE_COUNT` > 0 → 有节点没进树但被持有（典型是 `remove_child` 后忘了 `queue_free`）

⚠ 部分监视器在 release 构建下返回 0 —— **不能把 0 当成"没问题"**，要用 debug 构建测。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/performance.md`


## 2. 立刻能做的优化

### 屏幕外对象停止处理

```gdscript
# 挂在需要剔除的节点上
@onready var _notifier: VisibleOnScreenNotifier2D = $VisibleOnScreenNotifier2D

func _ready() -> void:
    _notifier.screen_entered.connect(_on_entered)
    _notifier.screen_exited.connect(_on_exited)

func _exit_tree() -> void:
    if _notifier.screen_entered.is_connected(_on_entered):
        _notifier.screen_entered.disconnect(_on_entered)
    if _notifier.screen_exited.is_connected(_on_exited):
        _notifier.screen_exited.disconnect(_on_exited)

func _on_entered() -> void:
    set_process(true)
    set_physics_process(true)

func _on_exited() -> void:
    set_process(false)
    set_physics_process(false)
    # 动画/粒子也一起停
```

⚠ 这是**性价比最高**的一条。屏幕外的敌人还在跑 AI = 纯浪费。

### 缓存节点引用

```gdscript
# 反例：每帧遍历场景树
func _process(_d: float) -> void:
    get_node("Player").position.x += 1

# 正例
@onready var _player: Node2D = $Player
func _process(_d: float) -> void:
    _player.position.x += 1
```

⚠ 用**场景唯一名**（`%Player`）比路径更抗重构。

### 距离比较用平方

```gdscript
# 反例：distance_to 内部要开方
if global_position.distance_to(target) < 100.0:

# 正例：平方比较，省一次 sqrt
if global_position.distance_squared_to(target) < 100.0 * 100.0:
```

⚠ 只在**比较**时用平方。真需要实际距离就别省。

### 热路径用 StringName

```gdscript
# 反例：每次比较都逐字符
if Input.is_action_pressed("jump"):
if _anim.current_animation == "run":

# 正例：&"name" 是 StringName，指针比较 O(1)
if Input.is_action_pressed(&"jump"):
if _anim.current_animation == &"run":
```

⚠ 用在哪：输入动作名、动画名、字典 key、节点组名、信号名 —— **任何在 `_process` 里反复比较的字符串**。

### 对象池

频繁生成销毁（子弹、伤害数字、粒子）用池，见 `systems.md`。

### 纹理与显存

- 启用 **VRAM Compressed**（Import 面板）
- 像素风**关掉**压缩（会有 artifacts）
- 移动端用 ETC2，桌面用 S3TC/BPTC
- 生成 mipmaps

⚠ VRAM 是有限的。一张 4096×4096 未压缩 RGBA = 64MB。

### 合批与 DrawCall

| 手段 | 适用 |
|---|---|
| 图集（TextureAtlas） | 大量小精灵 |
| `CanvasGroup` | 2D 一组节点整体合成 |
| 共享材质实例 | 相同外观的物体 |
| `MultiMesh` | 成千上万个相同网格（草、石头） |
| 合并网格 | 3D 静态场景 |

⚠ 每帧 `new ShaderMaterial()` / `new StandardMaterial3D()` 会打断合批（审查 GD31）。

### 物理

```gdscript
# RigidBody 静止后休眠
can_sleep = true          # 默认已 true，别关掉
```

- 物理层/掩码**只勾必要的**，别全勾
- 移动物体**不要**用 `ConcavePolygonShape`（ trimesh ），用 capsule/box/convex
- 大范围检测用 `Area2D` 而不是每帧 raycast
- 物理 tick 率按需调（回合制/俯视角 30Hz 够用）

### 主线程别阻塞

```gdscript
# 重活扔线程池
func _on_load_pressed() -> void:
    var task_id := WorkerThreadPool.add_task(_heavy_work)

func _heavy_work() -> void:
    # 在后台线程，不能碰场景树
    var data := _compute()
    # 结果回主线程再改节点
    _apply.call_deferred(data)

func _apply(data) -> void:
    _label.text = str(data)
```

⚠ **后台线程不能操作场景树**。只能算数据，改节点必须 `call_deferred` 回主线程。

⚠ 别用 `OS.delay_msec()` 卡主线程。

## 3. 性能预算（大型项目建议早定）

定一套数值，超标就报警。比"感觉有点卡"有用得多：

```gdscript
# perf_budget.gd —— Autoload，debug 构建才启用
extends Node

const BUDGET := {
    "draw_calls": 500,          # 移动端
    "objects": 3000,
    "frame_ms": 16.6,           # 60fps
    "static_mb": 300,
}

var _peak := {}

func _process(_d: float) -> void:
    if not OS.is_debug_build():
        return
    for k in BUDGET:
        var v := _sample(k)
        if v > _peak.get(k, 0):
            _peak[k] = v
        if v > BUDGET[k]:
            push_warning("超预算 %s: %.1f > %d" % [k, v, BUDGET[k]])

func _sample(k: String) -> float:
    match k:
        "draw_calls": return Performance.get_monitor(
            Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)
        "objects": return Performance.get_monitor(Performance.OBJECT_COUNT)
        "frame_ms": return Performance.get_monitor(
            Performance.TIME_PROCESS) * 1000.0
        "static_mb": return Performance.get_monitor(
            Performance.MEMORY_STATIC) / 1048576.0
    return 0.0

func report() -> void:
    for k in _peak:
        print("  %-12s 峰值 %.1f / 预算 %d" % [k, _peak[k], BUDGET[k]])
```

⚠ **release 构建要关掉**（`OS.is_debug_build()` 判断）。监视器本身有开销。

⚠ 预算数值必须**在目标机型上实测校准**，抄别人的没意义。

## 4. 上线前检查

- [ ] Profiler 跑过最吃性能场景，没有单函数 Self 超 30% 帧预算
- [ ] DrawCall 在目标内（移动 ≤500 / 桌面 ≤2000）
- [ ] 屏幕外对象已停止处理
- [ ] 共享材质的物体没有被每帧新建材质打断合批
- [ ] 纹理启用 VRAM 压缩（像素风除外）
- [ ] 物理层/掩码只勾必要的；RigidBody 开了 can_sleep
- [ ] 子弹/特效走对象池
- [ ] 热路径字符串比较用 StringName
- [ ] 没有 `print()` 残留（审查 GD74）
- [ ] 长时间挂机 20 分钟，OBJECT_COUNT 稳定不涨
- [ ] 在**最低配目标机型**上实测（桌面 60fps 不代表移动端能跑）

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-06`　性能：先定位再优化
