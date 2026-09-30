# 03 超分选型与 scale 语义（画质域）

> **本步交付**：模式定死 + scale 取值语义 + 档位表
> **对应**：流程 `howto/godot/upscaling.md` · 审核 `audit/godot/upscaling.md`

## 0. 交付物定义

1. 超分模式已定死到枚举值，⛔ 不靠名字猜
2. `scale > 1.0` 的真实行为已知，⛔ 不以为那是超采样
3. SSAA 档位只取整数倍
4. `scale = 1.0` 在所选模式下的真实语义已知
5. 用 FSR2 是为了提帧还是换质量，已定性
6. Nearest 档位表只含整数除数

## 1. 前置检查清单

- [ ] 已定死模式枚举值（FSR=1 / FSR2=2）
- [ ] 已知 scale 三个区间的真实行为
- [ ] SSAA 档位表里没有 1.5
- [ ] 已知"1.0 时 TAA 到底开没开"
- [ ] Nearest 档位表里没有 0.7

## 2. 工序

### Step 1　FSR 与 FSR2 是两个枚举值，别选错　`[upscaling/03#S1]`

【读】`howto/godot/upscaling.md#FSR 1.0 与 FSR 2.2 是两个不同枚举值`

【做】
官方枚举明确区分：
`VIEWPORT_SCALING_3D_MODE_FSR = 1` → **FSR 1.0**（空间）；
`VIEWPORT_SCALING_3D_MODE_FSR2 = 2` → **FSR 2.2**（时域）。

⛔ "FSR 就是 FSR2"是错的 —— 枚举里是两个值，
选错得到完全不同的画质表现：FSR1 **没有时域累积**，
不会出现鬼影，但也不会有 FSR2 的细节重建。

【产出】已定死的模式枚举值及其空间/时域属性

【判据】能说清选的是 1 还是 2，以及它是空间的还是时域的。

【审】`audit/godot/upscaling.md#19`

### Step 2　scale > 1.0 只有 Bilinear 是超采样　`[upscaling/03#S2]`

【读】`howto/godot/upscaling.md#5. ⚠`

【做】
除 Bilinear 外，每种模式的官方口径都是同一句：
*"Values greater than 1.0 are **not supported** and bilinear downsampling
will be used instead."*

⛔ "scale>1.0 是超采样"是错的 —— **不支持**，统一回退双线性下采样。
⛔ 症状：把 scale 拉到 1.5 想做 SSAA，画面**没有变清晰**，且不报错。

ⓘ Bilinear 是唯一例外（它的官方口径是 supersampling），
⛔ 但反过来也别以为所有模式都不支持而白白丢掉唯一可用的超采样路径。

【产出】scale 取值与真实行为的对照表

【判据】能说清把 scale 拉到 1.5 时引擎实际在做什么。

【审】`audit/godot/upscaling.md#16`

### Step 3　做 SSAA 就用整数倍，1.5 反而比 2.0 糊　`[upscaling/03#S3]`

【读】`howto/godot/upscaling.md#9. ⛔`

【做】
Godot 用硬件自带的双线性过滤做下采样，所以**整数倍更锐利**（2.0 优于 1.5）。
官方原话：*"the result will look **crisper at integer scale factors**
(namely, 2.0)"*。

⛔ "SSAA 用 1.5 和 2.0 差不多"是错的 ——
`1.5`（2.25× SSAA）反而比 `2.0`（4× SSAA）**更糊**，
⛔ 表现为"花了性能却没买到清晰度"。

【产出】SSAA 档位表（只含整数倍）

【判据】档位表里没有 1.5。

【审】`audit/godot/upscaling.md#28`

### Step 4　scale = 1.0 不等于关闭超分　`[upscaling/03#S4]`

【读】`howto/godot/upscaling.md#5. ⚠`

【做】
`scale = 1.0` 的行为分模式：
Bilinear / FSR 1.0 / MetalFX Spatial / Nearest 下是**禁用缩放**；
⛔ **FSR2 与 MetalFX Temporal 下是以原生分辨率作 TAA 使用**，不是关闭。

⛔ "scale=1.0 就是关闭超分"是错的 —— 以为 1.0 = 关闭的话，
你会不知道自己其实开着 TAA，然后困惑"为什么画面有鬼影但我没开 TAA"。

ⓘ 推论：想要 TAA 但不想降分辨率 → 选 FSR2 并把 scale 设为 1.0。

【产出】scale=1.0 在所选模式下的真实语义

【判据】能说清"1.0 时 TAA 到底开没开"。

【审】`audit/godot/upscaling.md#17`

### Step 5　原分辨率用 FSR2 反而降性能　`[upscaling/03#S5]`

【读】`howto/godot/upscaling.md#⚠ FSR2 在原分辨率下是"降性能换质量"`

【做】
FSR2 的价值在**降分辨率后重建质量**；
为拿它的时域抗锯齿而在原分辨率使用它，⛔ 官方明确：
*"enabling FSR2 will actually **decrease** performance"*，
且 *"more demanding than using TAA at native resolution"*。

⛔ "FSR2 降分辨率一定提速"是错的 —— 提速的前提是**真的降了分辨率**；
在原分辨率下它是净亏，只在有 GPU 余量时才推荐。

【产出】本次用 FSR2 的场景定性（提帧 / 换质量）

【判据】能说清这次用 FSR2 是为了提帧还是为了画质，以及代价。

【审】`audit/godot/upscaling.md#27`

### Step 6　Nearest 用整数除数，它是为复古风设计的　`[upscaling/03#S6]`

【读】`howto/godot/upscaling.md#⚠ Nearest 模式强烈建议用整数除数`

【做】
用 `0.5` / `0.3333` / `0.25` / `0.2` 这类 **1 的整数除数**。

⛔ "Nearest 随便给个 0.7"是错的 —— 像素大小不均，
表现为画面出现不规则的条纹 / 抖动。
⛔ "Nearest 缩放没用"也是错的 —— **复古 / 低分辨率风专为它设计**，
它的目的就是像素整齐。

【产出】Nearest 档位表（只含整数除数）

【判据】档位表里没有 0.7 这类非整数除数。

【审】`audit/godot/upscaling.md#18`、`audit/godot/upscaling.md#14`

## 3. 参考实现

```gdscript
# ⓘ 承接 Step 3/6：档位只取整数除数，排除 0.7 与 1.5
const NEAREST_STEPS := [1.0, 0.5, 0.3333, 0.25]
const SSAA_STEPS := [1.0, 2.0]   # ⛔ 不含 1.5（整数倍才锐利）
```

## 4. 验收清单

- [ ] 模式枚举值已定死，空间/时域属性已确认
- [ ] scale 三个区间的真实行为已写清
- [ ] ⚠ SSAA 档位表里没有 1.5
- [ ] "1.0 时 TAA 开没开"已确认
- [ ] 用 FSR2 的场景已定性（提帧 / 换质量）
- [ ] Nearest 档位表里没有 0.7

## 5. 常见返工

| 症状 | 回到 |
|---|---|
| 选了 FSR 但画质和预期完全不同 | S1 —— FSR1 与 FSR2 两个枚举 |
| scale 拉到 1.5 画面没变清晰 | S2 —— 回退双线性下采样 |
| 做了 SSAA 却比更低倍率还糊 | S3 —— 整数倍才锐利 |
| 画面有鬼影但没开 TAA | S4 —— FSR2 在 1.0 下就是 TAA |
| 用了 FSR2 反而更慢 | S5 —— 原分辨率下净亏 |
| Nearest 下画面有条纹/抖动 | S6 —— 非整数除数 |

## 6. 下一步

→ `04-抗锯齿选型与组合.md`（AA 的组合关系由超分模式决定）

## 7　整体审核（功能点级收尾）

【审】`audit/godot/upscaling.md#19`、`audit/godot/upscaling.md#16`、`audit/godot/upscaling.md#28`、`audit/godot/upscaling.md#17`、`audit/godot/upscaling.md#27`、`audit/godot/upscaling.md#18`、`audit/godot/upscaling.md#14`
