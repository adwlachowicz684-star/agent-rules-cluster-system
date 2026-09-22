# Godot 4.x 模拟经营 / 放置

模拟经营的核心是**"固定步长累积 + 资源图 + 建筑网格"**，
离线收益是独立的纯函数结算器。

## 0. 四层分离

| 层 | 职责 |
|---|---|
| **资源层** | `Economy` 持有 `Dictionary[StringName, float]` |
| **建筑层** | `Building` Resource：inputs / outputs / interval |
| **网格层** | `BuildingGrid` 格子校验（O(1) 数组查询） |
| **时间层** | `TickEngine` 固定步长 + `OfflineCalculator` |

## 1. TickEngine 必须固定步长 + 累加器

```gdscript
const FIXED_STEP := 0.25   # 4 tick/s 足够，不必每帧

var _acc := 0.0

func _process(delta: float) -> void:
    _acc += delta
    while _acc >= FIXED_STEP:
        _tick(FIXED_STEP)
        _acc -= FIXED_STEP
```

⚠ **绝不能用 `delta` 直乘产出率** ——
帧率不同结果不同，且无法做离线结算复用。

⚠ **资源量用 `float` 并设上限** ——
长期运行下避免精度丢失或溢出。

## 2. 离线收益要跑完整经济循环，不能简单相乘

```gdscript
func calc_elapsed(state, seconds: float, cfg) -> Result:
    var capped := minf(seconds, cfg.offline_cap_hours * 3600.0)
    var t := 0.0
    while t < capped:
        economy.tick(FIXED_STEP)   # 复用完整 tick，含依赖链与上限
        t += FIXED_STEP
    return Result.new(economy.snapshot(), t)
```

⚠ **不要按"每秒产出 × 离线秒数"直接乘** ——
忽略了建筑依赖链（A 产出是 B 的输入，B 满仓时 A 应停产）、上限、事件 buff。

⚠ **正确做法是把离线时间切成若干大步长，循环推进完整 `tick()`
并每步截断到上限**。

## 3. 时间基准用 Unix 时间，不要累计游戏内秒数## 3. 时间基准用 Unix 时间，不要累计游戏内秒数

> 更深一层的**跨品类结算内核**（余数写回、分段速率、封顶三数、周期重置硬边界）
> 见 `time-progression.md`。本篇只讲放置品类自身的时间基准。

```gdscript
var last_save_unix := Time.get_unix_time_from_system()

func on_load() -> void:
    var elapsed := float(Time.get_unix_time_from_system() - last_save_unix)
    var r := calc_elapsed(_state, elapsed, _cfg)
```

⚠ **不要用 `delta` 累计游戏内秒数作为离线基准** ——
暂停、切后台、`Engine.time_scale` 都会让它失真。

⚠ **离线上限不要直接写死 8 小时** —— 应作为 `MetaUpgrade` 解锁项，
且要防玩家改系统时间作弊（记录上次时间、拒绝"倒退"）。

## 4. 建筑放置用数组校验，不是 Area2D

```gdscript
func can_place(cell: Vector2i, b: Building) -> bool:
    for c in b.footprint(cell):
        if _grid[c.y][c.x] != null:
            return false
    return true
```

⚠ **网格放置应查 `BuildingGrid` 的二维数组，O(1)** ——
`Area2D` 只适合非网格的自由放置碰撞。
相邻建筑、道路连通性也是数组运算。

## 5. 每建筑一个 _process 是性能杀手

⚠ **1000 个建筑各有脚本回调会显著开销** ——
改为 `TickEngine` 持有 `Array[Building]` 批量遍历，
非活跃/无产出的建筑从活跃数组移除（但保留在网格数据里）。

```gdscript
var _active: Array[Building] = []    # 只遍历这些
```

## 6. 资源键用 StringName

```gdscript
var amounts: Dictionary[StringName, float] = {}
```

⚠ **不要用 `String` 作资源键** ——
`StringName` 避免每次哈希新字符串，且 GDScript 的
`Dictionary[Key, Value]` 类型化能提速并早报错。

## 7. 存档：user:// 不是安全存档

⚠ **`ResourceSaver.FLAG_COMPRESS` 是压缩不是加密** ——
玩家可改本地文件。含付费/关键进度的放置游戏需服务端权威或至少签名校验。

⚠ **`OS.get_user_data_dir()` 与 `user://` 不是一回事** ——
前者返回 OS 级绝对路径，后者是项目数据目录，
要转绝对得 `ProjectSettings.globalize_path("user://")`。

## 8. 周期存档不要每帧写

⚠ **用 `Timer` + 周期存档，间隔随活跃度自适应** ——
每帧写存档会拖垮 IO，也在崩溃时留下半截文件（要写临时文件 + 原子重命名）。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-idle-sim.md`
