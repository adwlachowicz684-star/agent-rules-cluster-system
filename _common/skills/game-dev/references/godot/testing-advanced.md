# Godot 4.x 高级测试：属性 / 模糊 / 视觉 / 性能 / 确定性

GUT 和单元测试能证明**单元正确**，不能证明**游戏整体不坏**。

| 测试类型 | 输入 | 检查目标 | 失败样例 |
|---|---|---|---|
| 单元测试 / GUT | 手工示例 | 精确输出、状态转移 | 扣血后血量错误 |
| **属性测试** | 随机合法/边界输入 | 不变量 | 库存总数变化、非法路径产生 |
| **模糊测试** | 随机字节、畸形事件 | 不崩溃、错误可恢复 | 随机存档导致引擎退出 |
| **视觉回归** | 固定场景/相机/种子 | 图像差异 | 光照/UI 像素偏移 |
| **性能基准** | 固定场景、固定帧数 | 分位数/内存 | p99 帧时间超标 |
| **确定性测试** | 同种子、同输入序列 | 回放比特一致 | 录播在不同机器分歧 |

它们**彼此不替代**：属性测试不保证 UI 像素，模糊测试不能证明逻辑正确，
截图 diff 不测量帧预算。

## 1. 属性测试：检查不变量，不是穷举输出

价值在于**找到反例**。与其写十个手写存档，不如生成随机实体集合。

适合测的不变量：
- 存档序列化 → 反序列化**往返一致**
- 库存增删**总数守恒**
- 寻路：**路径非空时终点是目标**、相邻点可达

```gdscript
class_name PropertyRunner
extends RefCounted

var rng: RandomNumberGenerator
var failures: Array[String] = []

func _init(seed_value: int = 1) -> void:
    rng = RandomNumberGenerator.new()
    rng.seed = seed_value

## 跑 n 次随机用例，property 返回 true 表示不变量成立
func check(n: int, gen: Callable, property: Callable) -> bool:
    failures.clear()
    for i in n:
        var input = gen.call(rng, i)
        if not property.call(input):
            failures.push_back("第 %d 次失败，输入: %s" % [i, str(input)])
            if failures.size() >= 5:
                break
    return failures.is_empty()

## 最小化反例：固定种子后二分缩小规模
func shrink(gen: Callable, property: Callable, max_n: int) -> int:
    for n in range(1, max_n):
        var rng2 := RandomNumberGenerator.new()
        rng2.seed = rng.seed
        for i in n:
            var input = gen.call(rng2, i)
            if not property.call(input):
                return n
    return -1
```

**用法定**：

```gdscript
func test_inventory_conservation() -> void:
    var runner := PropertyRunner.new(12345)
    var inv := Inventory.new()
    var ok := runner.check(500,
        func(r, _i): return r.randi_range(1, 10),      # 随机数量
        func(amount):
            var before := inv.count_of(&"potion")
            inv.add(potion_def, amount)
            inv.remove_first(&"potion", amount)
            return inv.count_of(&"potion") == before    # 不变量：总数守恒
    )
    assert(ok, "库存不变量被破坏: %s" % str(runner.failures))
```

⚠ **失败时要输出种子**，否则无法复现。随机测试的价值全在可复现。

⚠ 生成器和判定器要分离 —— 判定器里不能有随机，
否则"不变量"本身每次不一样，测试无意义。

⚠ 找到失败后要**缩小反例**（shrink），
500 个实体的失败用例无法调试。

## 2. 模糊测试：目标是进程存活

故意喂随机/畸形字节，检查**不崩溃、错误可恢复**。

```gdscript
class_name FuzzRunner
extends RefCounted

var rng := RandomNumberGenerator.new()
var crashes: Array[String] = []

## 对存档解析器做模糊测试
func fuzz_save_parser(n: int, max_bytes: int) -> bool:
    crashes.clear()
    for i in n:
        var buf := PackedByteArray()
        buf.resize(rng.randi_range(0, max_bytes))
        for j in buf.size():
            buf[j] = rng.randi_range(0, 255)
        # 解析器必须：要么成功，要么返回明确错误，绝不能崩溃
        var result = SaveParser.parse(buf)
        if result == null and not SaveParser.last_error_is_recoverable():
            crashes.push_back("第 %d 次：不可恢复错误 %s" % [i, SaveParser.last_error])
        # 变异已知良好存档，比纯随机更容易命中解析分支
        var good := FileAccess.get_file_as_bytes("user://good.sav")
        if good.size() > 0:
            var mutated := _mutate(good)
            SaveParser.parse(mutated)
    return crashes.is_empty()

func _mutate(src: PackedByteArray) -> PackedByteArray:
    var out := src.duplicate()
    for k in mini(8, out.size()):
        out[rng.randi_range(0, out.size() - 1)] = rng.randi_range(0, 255)
    return out
```

⚠ **纯随机字节很难命中深层解析分支**。
更有效的是**变异已知良好存档**（改几个字节）—— 能越过前面的格式校验。

⚠ 模糊测试**不证明逻辑正确**，只证明"喂垃圾不崩"。
两者都要有。

⚠ 要在**目标平台**跑，桌面不崩不代表移动端/主机不崩。

## 3. 视觉回归：截图 diff

```gdscript
class_name VisualRegression
extends Node

const DIFF_THRESHOLD := 0.02      # 2% 像素差异视为失败

func capture(path: String) -> void:
    await RenderingServer.frame_post_draw
    var img := get_viewport().get_texture().get_image()
    img.save_png(path)

func compare(baseline: String, current: String) -> float:
    var a := Image.new()
    var b := Image.new()
    if a.load(baseline) != OK or b.load(current) != OK:
        return 1.0
    if a.get_size() != b.get_size():
        return 1.0
    var diff := 0
    var total := a.get_width() * a.get_height()
    for y in a.get_height():
        for x in a.get_width():
            if a.get_pixel(x, y) != b.get_pixel(x, y):
                diff += 1
    return float(diff) / float(total)

func assert_matches(baseline: String) -> void:
    var cur := "user://_vr_current.png"
    await capture(cur)
    var d := compare(baseline, cur)
    assert(d < DIFF_THRESHOLD, "视觉回归失败，差异 %.2f%%" % (d * 100))
```

⚠ **必须固定相机、种子、时间、随机状态**，否则 diff 全是噪声。

⚠ 抗锯齿、浮点差异、GPU 驱动差异都会造成**微小像素差**。
阈值不能设 0，否则永远红。2% 是常见起点。

⚠ 逐像素循环在 GDScript 里很慢，大图要抽样或用 shader 做 diff。

⚠ **基线要人工确认过是对的**。把错误画面存成基线，以后每次都"通过"。

## 4. 性能基准：看分位数，不看平均值

```gdscript
class_name PerfBenchmark
extends Node

var _samples: Array[float] = []
var _frames := 0
var _total := 0

@export var warmup_frames := 60
@export var measure_frames := 600

func run() -> Dictionary:
    _samples.clear()
    _frames = 0
    set_process(true)
    await _measure_done
    _samples.sort()
    return {
        "p50": _percentile(0.50),
        "p95": _percentile(0.95),
        "p99": _percentile(0.99),
        "max": _samples[-1] if _samples else 0.0,
    }

func _process(delta: float) -> void:
    _frames += 1
    if _frames <= warmup_frames:
        return                              # 预热不计
    _samples.push_back(delta * 1000.0)      # 转毫秒
    if _samples.size() >= measure_frames:
        set_process(false)
        _measure_done.emit()

signal _measure_done

func _percentile(p: float) -> float:
    if _samples.is_empty():
        return 0.0
    var idx := int(_samples.size() * p)
    return _samples[clampi(idx, 0, _samples.size() - 1)]
```

⚠ **平均值没用**。玩家感受到的是最差的那些帧。
看 **p95 / p99**，不是 mean。

⚠ 必须**预热**（跳过前 60 帧）—— 前几帧包含加载、编译、首次分配。

⚠ 要在**目标硬件**上跑。开发机 200fps 不代表移动端能跑。

⚠ 基准要有**阈值断言**，否则数字摆在那没人看：
```gdscript
var r := await bench.run()
assert(r["p99"] < 16.6, "p99 帧时间 %.1fms 超标（目标 60fps）" % r["p99"])
```

## 5. 确定性测试：固定输入世界

目标：**同种子 + 同输入序列 → 同结果**。

```gdscript
func test_replay_determinism() -> void:
    var inputs := _load_recording("user://rec.bin")
    var a := _simulate(12345, inputs)
    var b := _simulate(12345, inputs)
    assert(a == b, "同种子同输入产生了不同结果")

func _simulate(seed_val: int, inputs: Array) -> Dictionary:
    var rng := RandomNumberGenerator.new()
    rng.seed = seed_val
    var state := {}
    for i in inputs:
        _step(state, i, 1.0 / 60.0)     # 固定 delta，不用真实帧时间
    return state
```

⚠ **必须用固定 delta**，不能用真实 `delta` ——
否则同一次录制在不同机器上结果不同。

⚠ 哈希表遍历顺序、字典迭代顺序可能不稳定 ——
**遍历前先排序**，或不用字典顺序敏感的写法。

⚠ 浮点在不同平台可能有微小差异（编译器优化、SIMD）。
严格比特一致很难，通常比较**关键状态**（位置取整、死亡数、得分）。

## 6. 常见坑

| 坑 | 后果 |
|---|---|
| 随机测试不记录种子 | 失败无法复现 |
| 判定器里也有随机 | "不变量"每次不同，测试无意义 |
| 模糊只喂纯随机 | 难命中深层分支，覆盖率虚高 |
| 视觉基线未人工确认 | 错图存成基线，永远"通过" |
| 视觉阈值设 0 | 抗锯齿噪声导致永远红 |
| 性能看平均值 | 掩盖卡顿，玩家感受的是 p99 |
| 性能不预热 | 把加载开销算进帧时间 |
| 性能只在开发机跑 | 移动端/主机实际不达标 |
| 确定性测试用真实 delta | 不同机器结果不同 |
| 基线存二进制不存文本 | diff 无法读，评审看不见 |

## 7. 落地建议

按投入产出排序：

1. **先有单元 + 存档往返属性测试** —— 投入小，能抓住最多的回归
2. **性能基准 + 阈值断言** —— 防止无声劣化
3. **存档模糊测试** —— 防止玩家坏档导致崩溃
4. **视觉回归**最后上 —— 维护成本最高，噪声最多

⚠ 不要一开始就搭全套。测试本身也有维护成本，
**没人看的测试等于没有测试**。
