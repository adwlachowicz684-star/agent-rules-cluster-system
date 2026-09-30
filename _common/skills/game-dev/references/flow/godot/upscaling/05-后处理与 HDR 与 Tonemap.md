# 05 后处理与 HDR / Tonemap（画质域）

> **本步交付**：后处理代价排序表 + tonemap 模式
> **对应**：流程 `howto/godot/upscaling.md` · 审核 `audit/godot/upscaling.md`

## 0. 交付物定义

1. 每个后处理都有**实测**的毫秒增量，⛔ 不是经验值
2. tonemap 模式已选定，且已知它对 HDR 输出的影响
3. 开了哪些后处理、各自换来什么，能逐项说清
4. 组合后的代价已复测，⛔ 不等于各项单独代价之和

## 1. 前置检查清单

- [ ] 已记录关全部后处理时的基线帧时间
- [ ] 每个后处理都有逐个开启的增量记录
- [ ] 已按"每毫秒的画质收益"排序
- [ ] tonemap 模式已选定并有理由
- [ ] ⚠ 组合后的总代价已复测

## 2. 工序

### Step 1　后处理代价要实测排序，不能用经验值　`[upscaling/05#S1]`

【读】`howto/godot/upscaling.md#8. 后处理的性能代价要排序`

【做】
① 关掉全部后处理，记录基线帧时间
② 逐个开启，每次记录增量
③ 按"每毫秒的画质收益"排序

⛔ "后处理代价用经验值"是错的 ——
**同一个后处理在不同分辨率、不同渲染器下的代价差异很大**，经验值会误导。

ⓘ 还要实测的另一件事：**后处理之间会互相影响**
（例如开了 Bloom 之后景深的表现会变），
⛔ 单独测出的代价**不等于组合后的代价**。

【产出】后处理代价排序表（含实测毫秒增量）

【判据】每个开启的后处理都能报出实测的毫秒增量。

【审】`audit/godot/upscaling.md#25`

### Step 2　开了 HDR 不等于有 HDR 输出　`[upscaling/05#S2]`

【读】`howto/godot/upscaling.md#⚠ Tonemap 与 HDR`

【做】
HDR 输出只在 **Reinhard / AgX / Linear** 下响应，
⛔ **Filmic 与 ACES 始终输出 SDR 范围**。

⛔ "开了 HDR 就有 HDR 输出"是错的 ——
想用 4.7 的 HDR 输出功能，**必须先改 tonemap 模式**，
⛔ 不是"设置里打开 HDR"就行。

【产出】tonemap 模式的选择与理由

【判据】能说清当前 tonemap 下 HDR 是否真的响应。

【审】`audit/godot/upscaling.md#10`、`audit/godot/upscaling.md#24`

### Step 3　后处理不能随便开，要按预算取舍　`[upscaling/05#S3]`

【读】`howto/godot/upscaling.md#3. 后处理`

【做】
`WorldEnvironment` 能做 Bloom · Tonemap · SSAO · SSR · 景深 · 色差 · 暗角。

⛔ "后处理随便开"是错的 ——
要按**性能代价排序**取舍，在预算内选收益最高的那几个。

【产出】开了哪些后处理、各自换来什么的清单

【判据】每一项开启的后处理都能说清它换来了什么、花了多少毫秒。

【审】`audit/godot/upscaling.md#12`

## 3. 参考实现

```gdscript
# ⓘ 承接 Step 1：逐个开启并记录增量，⛔ 不用经验值
const POST_BUDGET_MS := 4.0   # ⓘ 待实测：按目标档位的帧时间预算定
```

## 4. 验收清单

- [ ] 基线帧时间已记录（关全部后处理）
- [ ] 每个后处理的增量已逐个实测
- [ ] 已按每毫秒画质收益排序
- [ ] tonemap 模式已选定，HDR 响应已确认
- [ ] ⚠ 组合后的总代价已复测

## 5. 常见返工

| 症状 | 回到 |
|---|---|
| 按经验关了后处理但没省出时间 | S1 —— 代价随分辨率/渲染器变 |
| 开了 HDR 但画面没变 | S2 —— Filmic / ACES 恒输出 SDR |
| 后处理越加越多 | S3 —— 按预算取舍 |
| 单独测的代价与实跑不符 | S1 —— 后处理之间互相影响 |

## 6. 下一步

→ `06-纹理清晰度与性能归因.md`（改缩放会连带改纹理清晰度）

## 7　整体审核（功能点级收尾）

【审】`audit/godot/upscaling.md#25`、`audit/godot/upscaling.md#10`、`audit/godot/upscaling.md#24`、`audit/godot/upscaling.md#12`
