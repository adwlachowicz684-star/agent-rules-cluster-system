# 03 手部追踪与 pinch 判定（XR 域）

> **本步交付**：支持性查询时机正确 + 关节数据有效性判据 + pinch 归一化与迟滞
> **对应**：流程 `howto/godot/xr-deep.md` · 审核 `audit/godot/xr-deep.md`

## 0. 交付物定义

1. `is_hand_tracking_supported()` 在接口初始化**之后**才查
2. 关节数据按 flags 区分**有效**与**实测**（未置位即预测数据）
3. pinch 阈值已归一化（除以掌骨跨度）并有**迟滞**
4. 快速挥手不会误判成捏合（速度防抖已实现）
5. 手部与控制器**共享同一套游戏语义**

## 1. 前置检查清单

- [ ] 支持性查询发生在 OpenXR 初始化之后
- [ ] 关节读取前先判 flags，不是直接取位置
- [ ] pinch 阈值与手指跨度相关，不是固定厘米数
- [ ] 有速度防抖
- [ ] 手部与控制器走同一套语义

## 2. 工序

### Step 1　支持性查询必须在初始化之后，初始化前恒为 false　`[xr/03#S1]`

【读】`howto/godot/xr-deep.md#6. ⛔ 官方口径：渲染器、foveation 与设置时机`

【做】
把 `is_hand_tracking_supported()` 的调用放到 OpenXR 初始化完成之后
（监听初始化完成信号或首帧之后），⛔ 不在 `_ready()` 里查。
⛔ 官方注明"only returns a valid value after OpenXR has been initialized" ——
初始化前拿到的是默认值 `false`，
于是**设备明明支持**却直接走进降级分支，
⛔ 表现为"这机器不支持手部追踪"，而真机上的光学追踪**根本没被执行过一次**。

ⓘ 同类的还有 `is_eye_gaze_interaction_supported()`，同样的时机要求。

【产出】初始化后查询支持性的调用点

【判据】在支持手部追踪的设备上，查询结果与设备能力一致（不是恒 false）。

【审】`audit/godot/xr-deep.md#16`

### Step 2　关节数据先看 flags：valid 与 tracked 是两件事　`[xr/03#S2]`

【读】`howto/godot/xr-deep.md#1. 手部追踪 vs 控制器`

【做】
读关节位置前先取 `get_hand_joint_flags()`，按官方 BitField 判：
`HAND_JOINT_POSITION_VALID`(4) 位置可用、
`HAND_JOINT_POSITION_TRACKED`(8) 来自实测追踪（⛔ 未置位即**预测数据**）、
`LINEAR/ANGULAR_VELOCITY_VALID`(16/32) 速度可用。
⛔ 直接取位置不看 flags —— 拿到的是预测出来的关节位姿，
表现为"手指位置飘、捏合时灵时不灵"，
⛔ 而数值永远有值、永远在合理区间，看数据查不出问题。

ⓘ 这与 02 的"有数据不等于可信"是同一条原则，
只是这里官方给了**位级**的判据，比布尔精确得多。

【产出】关节读取函数（先判 flags 再取数）

【判据】手指移出摄像头视野时，判据落到"未 tracked"而不是继续使用。

【审】`audit/godot/xr-deep.md#17`

### Step 3　pinch 阈值要归一化，且必须有迟滞　`[xr/03#S3]`

【读】`howto/godot/xr-deep.md#pinch 判定的降级方案`

【做】
把拇指尖与食指尖的距离**除以中指掌骨—中指尖的跨度**做归一化，
或在运行时做一次校准；并设置**不对称阈值**（进入窄、释放宽）。
⛔ 用固定厘米阈值 —— 手指长度因人而异，
同一套阈值在不同人手上表现为"有人捏不上、有人一直捏着"。

ⓘ 迟滞不是可选项：没有迟滞时临界处会**高频抖动**，
表现为"捏合事件连发"，⛔ 而每次触发单独看都成立。

【产出】归一化后的 pinch 判定（含进入/释放双阈值）

【判据】同一手势在不同人手上都能稳定触发；临界处不出现连续触发。

【审】`audit/godot/xr-deep.md#7`

### Step 4　用速度防抖抑制挥手误判　`[xr/03#S4]`

【读】`howto/godot/xr-deep.md#pinch 判定的降级方案`

【做】
指尖相对速度超过阈值时抑制点击判定。
⛔ 只看距离阈值 —— 快速挥手时两指距离会在某一帧偶然落进阈值，
被识别成捏合，表现为"甩手时乱触发"，
⛔ 而单帧数据完全符合判定条件，看日志查不出来。

ⓘ 官方已提供逐关节的 `get_hand_joint_linear_velocity()`，
⛔ 但关节速度不等于抓取点速度，手锚本身仍要自己缓存差分（见 04）。

【产出】速度防抖判据（含阈值登记）

【判据】快速挥手 100 次，误触发次数为 0。

【审】`audit/godot/xr-deep.md#8`

### Step 5　手部与控制器共享同一套游戏语义　`[xr/03#S5]`

【读】`howto/godot/xr-deep.md#1. 手部追踪 vs 控制器`

【做】
把"抓取 / 指向 / 菜单确认"等语义抽成一层，手部与控制器各自只负责
**产生**这些语义，⛔ 不为两套输入各写一份玩法逻辑。
⛔ 写两套 —— 必然行为不一致，且**只在一侧被测过**，
表现为"用手玩没事、用控制器玩就少一个功能"，
⛔ 而每个开发者只测自己手边那套设备。

ⓘ 也要先确认运行时的性质：部分平台（如 SteamVR）
只有"基于控制器的手部追踪"，不是光学追踪，
⛔ 把两者当同一种能力来设计会给出错误的可用性承诺。

【产出】共享语义层（输入源可替换）

【判据】同一操作在两种输入下结果一致；换输入源不需要改玩法代码。

【审】`audit/godot/xr-deep.md#18`

## 3. 参考实现

```gdscript
# ⓘ 承接本步产出：flags 判据 + 归一化 pinch + 速度防抖
# ⛔ PINCH_ENTER / PINCH_EXIT / MAX_TIP_SPEED 由 00 参数表实测回填
const PINCH_ENTER := 0.45        # 归一化比值（相对掌骨跨度），非厘米
const PINCH_EXIT := 0.60         # ⛔ 必须大于 PINCH_ENTER，否则临界抖动
const MAX_TIP_SPEED := 1.8       # m/s，超过则抑制捏合判定

var _oxr: OpenXRInterface
var _pinching := false

func _pinch_ratio() -> float:
    var hand := OpenXRInterface.HAND_RIGHT
    var flags := _oxr.get_hand_joint_flags(hand, OpenXRInterface.HAND_JOINT_INDEX_TIP)
    if flags & OpenXRInterface.HAND_JOINT_POSITION_VALID == 0:
        return 1.0                                   # ⛔ 无效按"未捏合"处理
    if flags & OpenXRInterface.HAND_JOINT_POSITION_TRACKED == 0:
        return 1.0                                   # ⛔ 预测数据不参与判定
    var thumb := _oxr.get_hand_joint_position(hand, OpenXRInterface.HAND_JOINT_THUMB_TIP)
    var index := _oxr.get_hand_joint_position(hand, OpenXRInterface.HAND_JOINT_INDEX_TIP)
    return thumb.distance_to(index) / _palm_span()   # ⓘ 归一化，不用固定厘米

func _palm_span() -> float:
    var hand := OpenXRInterface.HAND_RIGHT
    var a := _oxr.get_hand_joint_position(hand, OpenXRInterface.HAND_JOINT_MIDDLE_PROXIMAL)
    var b := _oxr.get_hand_joint_position(hand, OpenXRInterface.HAND_JOINT_MIDDLE_TIP)
    return maxf(a.distance_to(b), 0.001)             # ⛔ 除零保护
```

ⓘ 上例只示范判据结构，
⛔ 关节位姿不含 world_scale（见 01/S4），跨尺度使用要自己乘。

## 4. 验收清单

- [ ] 支持性查询在初始化之后
- [ ] 关节读取先判 flags
- [ ] pinch 阈值已归一化且有迟滞
- [ ] 快速挥手 0 误触发
- [ ] 两种输入共享同一套语义

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 设备明明支持却走降级 | 初始化前查支持性，恒 false | S1 |
| 手指位置飘、捏合时灵时不灵 | 用了预测关节数据 | S2 |
| 有人捏不上 / 一直捏着 | 固定厘米阈值 | S3 |
| 甩手时乱触发 | 无速度防抖 | S4 |
| 用手玩没事、用控制器少功能 | 两套玩法逻辑 | S5 |

## 6. 下一步

→ 04 抓取与释放动量

## 7　整体审核（功能点级收尾）

【审】`audit/godot/xr-deep.md#16`、`audit/godot/xr-deep.md#17`、`audit/godot/xr-deep.md#7`、`audit/godot/xr-deep.md#8`、`audit/godot/xr-deep.md#18`
