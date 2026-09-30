# 画质管线：超分、抗锯齿、后处理（Godot 4.7.2）

"FSR""DLSS""TAA""超分""post process" 此前 **全部 0 命中**。

## 0. 三条独立管线，别混为一谈

画质由三条**相互独立**的管线叠加：

| 管线 | 作用对象 | 机制 |
|---|---|---|
| 窗口/画布拉伸 | 2D | `stretch/mode` + `stretch/aspect` |
| 3D 视口分辨率缩放 | 3D | `scaling_3d_mode` + `scaling_3d_scale` |
| 后处理 | 全局 | `WorldEnvironment` + `CompositorEffect` |

⚠ **最常见的错误**是以为 `stretch/mode` 能降 3D 渲染分辨率，或以为 FSR2 能治 MSAA 治不了的透明锯齿。

### 4.7 的两个关键变化

1. ⚠ **新建项目 stretch 默认值从 `disabled/keep` 改为 `canvas_items/expand`**
2. 4.7 新增 3D 视口的 **`Nearest`（最近邻）**缩放模式 —— 专为低分辨率/复古风格，无额外开销

## 1. 超分：内置五种，没有 FSR3/DLSS/XeSS

**4.7.2 内置**：Bilinear · FSR1.0 · **FSR2.2** · **MetalFX**（macOS/iOS）· Nearest

⚠ **无 FSR3、无帧生成、无原生 DLSS、无原生 XeSS。**

DLSS/XeSS 只存在于 NVIDIA 的 RTX path-tracing fork 与少量 GDExtension 实验项目，
**不应视为可投产方案**。

| 模式 | 说明 | Compatibility | Mobile |
|---|---|---|---|
| Bilinear | 双线性 | — | — |
| **FSR 2.2** | FSR2 时域超分 | ⚠ **不支持，回退双线性下采样** | ⚠ **以原生分辨率作 TAA 使用** |
| MetalFX Spatial | Apple 时域上采样 | 不支持 | 关闭缩放 |
| MetalFX Temporal | Apple 时域上采样 | 不支持 | 以原生分辨率作 TAA 使用 |

⚠ 同一个模式在**不同渲染器下行为不同** —— 这是最容易误判的地方。

⚠ **超分 UI 要分层渲染**，否则文字会被连带糊掉。
⚠ **2D 像素游戏通常有害**（会让像素糊掉），要按画风决定开关。

### ⚠ FSR2 在原分辨率下是"降性能换质量"

官方原话：*"enabling FSR2 will actually **decrease** performance, but it will
significantly improve rendering quality."*

⛔ 这与"超分 = 提速"的直觉相反：FSR2 的价值在**降分辨率后重建质量**，
但为拿它的时域抗锯齿而用在原分辨率时，⛔ **比原生 TAA 更贵**。

ⓘ 官方注明：*"Using FSR2 at native resolution is more demanding than using TAA
at native resolution"* —— 只在有 GPU 余量时推荐。

### ⛔ FSR Sharpness 值越高，锐化越少

官方原话：*"the **FSR Sharpness** project setting is set to `0.2`
(**higher values result in less sharpening**)"*。

⛔ 方向是反的：默认 `0.2` 是**有锐化**，调到 `2.0` 等于**关掉锐化**。
表现为"想更锐一点就往上调，结果更糊了"，⛔ 排查不会想到是方向反了。

## 2. 抗锯齿：渲染器支持矩阵完全不同

⚠ **TAA 仅在 Forward+ 可用**，Mobile 与 Compatibility **均不支持**。
⚠ **2D MSAA 在 Forward+ 与 Mobile 可用，在 Compatibility 不可用** ——
这与 3D MSAA 的支持矩阵**完全不同**。

| 方案 | 特点 |
|---|---|
| MSAA | 质量好，⚠ 透明/alpha scissor 材质（植被）表现有坑 |
| FXAA | 快但糊；⛔ **不支持 Compatibility**（仅 Forward+ / Mobile） |
| TAA | ⚠ 有鬼影，与部分特性冲突，仅 Forward+ |
| SMAA | ⛔ 4.2+ **内置**（`screen_space_aa` 枚举），⛔ 不是社区方案；1080p 及以下有效 |

⚠ **MSAA 与 TAA 能否叠加**要按渲染器确认。

## 3. 后处理

`WorldEnvironment` 能做：Bloom · Tonemap · SSAO · SSR · 景深 · 色差 · 暗角。

### ⚠ Tonemap 与 HDR

**HDR 输出只在 Reinhard / AgX / Linear 下响应** ——
**Filmic 与 ACES 始终输出 SDR 范围**。

想用 4.7 新增的 HDR 输出，tonemap 模式不能随便选。

⚠ 后处理的**性能代价要排序**（哪个最贵），按预算取舍。

## 4. 调试：怎么判断"糊"是哪个环节

> ⓘ 可照做的完整顺序见 **第 6 节**。

逐项开关对比：

```
渲染分辨率 → 超分模式 → AA → 后处理
```

⚠ 4.7 的 **Viewport Debug Draw** 能看部分信息。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/upscaling.md`


## 5. ⚠ `scaling_3d_scale` 的官方语义：>1.0 只有 Bilinear 支持

官方枚举文档里，**除 Bilinear 外的每一种模式都写了同一句**：

> *"Values greater than 1.0 are **not supported** and bilinear
> downsampling will be used instead."*

⚠ 这意味着在 **FSR 1.0 / FSR 2.2 / MetalFX / Nearest** 下，
`scaling_3d_scale > 1.0` **不是超采样** ——
你以为在提升画质，引擎实际走的是**双线性下采样**。

⛔ 症状：把 scale 拉到 1.5 想做 SSAA，画面**没有变清晰**。
而且不报错。

ⓘ **Bilinear 是唯一例外**：它的官方口径是
*"values greater than 1.0 will result in **supersampling**"*
—— 详见第 9 节的完整对照表。

| scale 取值 | 实际行为 |
|---|---|
| `< 1.0` | 欠采样后按模式上采样（这是超分的正常用法） |
| `= 1.0` | ⚠ **分模式不同，见下** |
| `> 1.0` | ⛔ **不支持**，统一回退双线性下采样 |

### ⚠ `= 1.0` 的行为三种模式各不相同

这是最容易误判的地方（第 1 节表格已提，这里给官方口径）：

| 模式 | `scale = 1.0` 时 |
|---|---|
| Bilinear | **禁用缩放** |
| FSR 1.0 | **禁用缩放** |
| **FSR2** | ⚠ **以原生分辨率作 TAA 使用**（不是关闭！） |
| MetalFX Spatial | **禁用缩放** |
| **MetalFX Temporal** | ⚠ **以原生分辨率作 TAA 使用** |
| Nearest | **禁用缩放** |

ⓘ **推论**：想要 TAA 但不想降分辨率 → 选 FSR2 并把 scale 设为 1.0。
⛔ 以为 "1.0 = 关闭" 的话，你会不知道自己其实开着 TAA，
然后困惑"为什么画面有鬼影但我没开 TAA"。

### ⚠ Nearest 模式强烈建议用整数除数

官方原话：

> *"to avoid **uneven pixel scaling**, it's highly recommended to use a
> value equal to an **integer divisor with a dividend of 1**. For example,
> 0.5 (1/2), 0.3333 (1/3), 0.25 (1/4), 0.2 (1/5)..."*

⚠ 用 `0.7` 这类非整数除数 → **像素大小不均**，
表现为画面出现不规则的条纹/抖动。

ⓘ 这条对低分辨率复古画风尤其重要 ——
Nearest 的目的就是像素整齐。

### FSR 1.0 与 FSR 2.2 是两个不同枚举值

⚠ 官方枚举明确区分：
- `VIEWPORT_SCALING_3D_MODE_FSR = 1` → **FSR 1.0**（空间）
- `VIEWPORT_SCALING_3D_MODE_FSR2 = 2` → **FSR 2.2**（时域）

⛔ 选错会得到完全不同的画质表现，且 FSR1 没有时域累积，
不会出现鬼影但也不会有 FSR2 的细节重建。

### MetalFX 的平台限制是**驱动级**的

官方原话：*"Only supported when the **Metal rendering driver** is in use,
which limits this scaling mode to **macOS and iOS**."*

⚠ 这是**驱动**限制，不是操作系统限制 ——
在 macOS 上用非 Metal 驱动仍然不可用。

## 6. 三条管线的调试顺序（可照做）

⚠ "糊"是最难定位的画质问题，因为**三条管线都会糊**。

✅ **必须逐项开关对比，且顺序不能变**（从上游到下游）：

```
① 渲染分辨率（scaling_3d_scale）  ← 先确认原始分辨率对不对
② 超分模式（scaling_3d_mode）     ← 再看是不是超分糊的
③ 抗锯齿（AA）                    ← 再看是不是 AA 糊的
④ 后处理（Bloom/DOF 等）          ← 最后才是后处理
```

ⓘ 为什么必须这个顺序：**后处理会掩盖上游的糊**。
先关后处理，才能看清上游。反过来从下游往上游调，
会把上游的缺陷误判成后处理参数问题。

⚠ **2D 与 3D 要分开判断** ——
`stretch/mode` 只影响 2D 画布，`scaling_3d_*` 只影响 3D 视口。
UI 糊了去调 3D 超分是**完全错误的方向**。

### ⚠ UI 被超分糊掉的正确解法

官方/社区一致做法：**分层渲染**。

ⓘ 把 UI 放在**不受 3D 缩放影响的层**（独立 CanvasLayer /
独立 Viewport），⛔ 不要靠"把 scale 调回 1.0"来解决 ——
那等于放弃超分。

⚠ **2D 像素游戏通常有害** ——
超分会让像素边缘糊掉，与美术目标冲突。
✅ 判据：**按画风决定开关，不是默认开启**。

## 7. 抗锯齿：先确认渲染器，再选方案

⚠ **选 AA 之前必须先确认渲染器**，因为支持矩阵完全不同
（第 2 节已给矩阵）。

| 方案 | ⚠ 关键限制 |
|---|---|
| MSAA | 质量好；⚠ **透明/alpha scissor 材质（植被）表现有坑** |
| FXAA | 快但糊；⛔ **不支持 Compatibility**（仅 Forward+ / Mobile） |
| TAA | ⚠ 有鬼影；**仅 Forward+** |
| SMAA | ⛔ 4.2+ **内置**（`screen_space_aa` 枚举），⛔ 不是社区方案；1080p 及以下有效 |

⚠ **MSAA 治不了透明材质的锯齿** ——
因为 alpha scissor 走的是 discard，不产生 MSAA 需要的覆盖信息。

ⓘ 所以"植被边缘闪烁"用 MSAA 是**无效**的，
要考虑 alpha-to-coverage 或换方案。

⚠ **MSAA 与 TAA 能否叠加要按渲染器确认** ——
⛔ 不要假设能叠加，实测。

## 8. 后处理的性能代价要排序

⚠ 第 3 节说了"要排序"，这里给可执行的做法：

```
① 记录基线帧时间（关全部后处理）
② 逐个开启，每次记录增量
③ 按"每毫秒的画质收益"排序
```

ⓘ 为什么要实测而不是凭经验：
**同一个后处理在不同分辨率、不同渲染器下的代价差异很大**，
经验值会误导。

⚠ **注意后处理之间会互相影响** ——
例如开了 Bloom 之后景深的表现会变。
⛔ 单独测出的代价不等于组合后的代价。

### Tonemap 与 HDR 的硬约束

⚠ **HDR 输出只在 Reinhard / AgX / Linear 下响应** ——
**Filmic 与 ACES 始终输出 SDR 范围**（第 3 节已说）。

ⓘ 这条的实操含义：想用 4.7 的 HDR 输出功能，
**必须先改 tonemap 模式**，⛔ 不是"设置里打开 HDR"就行。

## 9. ⛔ 只有 Bilinear 支持 `> 1.0` 超采样，其余模式全部回退双线性

第 5 节说"每种模式都写了同一句"—— ⛔ **Bilinear 是唯一的例外**，官方原话相反：

> *"Values less than 1.0 will result in undersampling while values greater than 1.0 will result in supersampling."*

| 模式 | `scale > 1.0` 的官方口径 |
|---|---|
| **Bilinear** | ✅ **是超采样（SSAA）**，可用，代价很高 |
| FSR 1.0 | ⛔ 不支持，回退双线性**下采样** |
| FSR 2.2 | ⛔ 不支持，回退双线性**下采样** |
| MetalFX Spatial / Temporal | ⛔ 不支持，回退双线性**下采样** |
| Nearest | ⛔ 不支持，回退双线性**下采样** |

⛔ 症状有两种，方向相反，都要能识别：

- 在 **FSR2 / MetalFX / Nearest** 下拉到 1.5 想做超采样 → 画面**没有变清晰**，且不报错
- 以为"所有模式都不支持 >1.0" → 于是**从不用 Bilinear 做 SSAA**，白白丢掉唯一可用的超采样路径

ⓘ `msaa_3d` 的官方文档也指向这条：*"See also bilinear scaling 3D scaling_3d_mode for supersampling, which provides higher quality but is much more expensive."*

⚠ **SSAA 在整数倍下更锐利**：官方原话 —— *"Since Godot uses the hardware's own
bilinear filtering to perform the downsampling, the result will look **crisper at
integer scale factors** (namely, `2.0`)"*。

⛔ 所以 `1.5` 与 `2.0` 不是"多花钱多买清晰度"的线性关系：
`1.5`（2.25× SSAA）反而比 `2.0`（4× SSAA）**更糊**，
⛔ 表现为"花了性能却没买到清晰度"。

⚠ Bilinear 的 `= 1.0` 是**禁用缩放**（与 FSR2 的"原生分辨率作 TAA"不同）。

## 10. ⛔ TAA 与 FSR2 不能叠加：`Use TAA` 会被忽略

官方原话：

> *"The Use TAA project setting is **ignored** when FSR2 is used as the 3D scaling method, since FSR2's temporal antialiasing takes priority."*

⛔ 表现为"两个都开了，但画质没有叠加改善"——面板上两项都是开着的，
排查方向必然被引向"TAA 参数没调好"，而实际是**它根本没生效**。

配套三条同源的：

| 情况 | 官方口径 |
|---|---|
| FSR1 配什么 AA | ⓘ **最好配 TAA 或 MSAA**；⚠ FXAA 不提供时域信息，只会更糊 |
| FSR2 要不要再叠 MSAA | ⓘ **收益很小**——FSR2 自带时域抗锯齿 |
| TAA 的代价 | ⚠ 静止画面也有轻微模糊，**相机移动时更明显**；有鬼影；⛔ 帧率越高收敛越快（所以低帧率下鬼影更重） |

⚠ **TAA 是唯一能处理透明锯齿的**：MSAA 对 alpha scissor **无效**（走 discard，不产生覆盖信息），
而 TAA **完全支持透明抗锯齿**。所以"植被边缘闪烁"用 MSAA 是**无效**的，
要么上 TAA / FSR2，要么在材质上开 **alpha antialiasing（alpha-to-coverage）**。

ⓘ alpha-to-coverage 有中等性能代价，但**不引入模糊**（与 FXAA 的关键差别）。

### ⚠ 透明 viewport 上的已知问题（issue #69492）

官方 issue #69492 ——
在开了 per-pixel transparency 的 viewport 上启用 **TAA 或 FSR2 会让 viewport 变不透明**
（FXAA 与 MSAA 不受影响）。

⛔ 表现为"做透明背景 / 内嵌 3D 视图时，一开 TAA 背景就黑了"，
而排查被引向 alpha 设置或合成模式。

## 11. ⚠ 负 mipmap LOD bias：改缩放 / 改 AA 会连带改纹理清晰度

Godot 在 `scaling_3d_scale < 1.0` 时**自动施加负纹理 LOD bias**，公式是官方给的：

```
log2f(min(scaling_3d_scale, 1.0)) + custom_texture_mipmap_bias
```

为了抵消抗锯齿带来的模糊，还会**额外叠加**：

| 开启 | 额外偏移 |
|---|---|
| FXAA | `-0.25` |
| TAA | `-0.5` |
| 两者都开 | `-0.75` |

⚠ 官方注明：这个偏移在分辨率缩放偏移**之前**应用，所以**不随缩放值变化**。

⛔ 三条容易踩的：

1. **LOD bias 同时影响 2D 与 3D** —— 但 2D 纹理**默认不开 mipmap**，
   所以只有给 2D 纹理开了 mipmap 才会被影响（表现为 2D 元素变**颗粒/噪点**）
2. ⛔ **负 bias 会让画面在运动时发颗粒感**，且**可能降低性能**（要采样更高分辨率的 mip）
3. ⛔ **正 bias 会让贴图变糊**——手动调只建议在 `-0.5 ~ 0.0` 之间

⚠ 手动改的位置：`rendering/textures/default_filters/texture_mipmap_bias`（项目设置）
或 Viewport 的 `texture_mipmap_bias` 属性（运行时）。
ⓘ 仅 **Forward+ / Mobile** 可用，Compatibility **不支持**。

## 12. ⚠ 缩放是逐轴的 + 降 scale 不涨帧说明瓶颈不在分辨率

**逐轴**：官方原话是 *"halving the resolution scale factor will reduce the number of rendered megapixels per frame by a factor of 4, not 2"*。

⛔ 把 scale 从 1.0 降到 0.5 以为是"省一半"，实际只渲 **1/4** 的像素——
反向也成立：想靠 scale 精细调性能时，**0.1 的改动会带来远超预期的帧时间变化**。

**Troubleshooting（官方原节）**：

> 降低到 0.5 而性能没明显提升 → ⛔ **瓶颈不在分辨率**，而在别处。

官方点名两类：draw call 太多（**CPU 瓶颈**）、开了 SDFGI / SSAO / SSR 等（GPU 侧不是被分辨率限制的）。

⛔ 这条最实际的用途：⛔ **不要用"降 scale 没用"去继续降 scale** ——
那时应该去 `perf` 域定位，而不是把画质越调越低。

ⓘ 官方还建议：**同时暴露"分辨率缩放"与"画质设置"两个选项**，
⛔ 不要用缩放替代低端硬件上的画质降级。

## 13. 流程：按什么顺序做

> **流程域** → `flow/godot/upscaling/`
> **反模式清单（不能怎么做，审核用）** → `audit/godot/upscaling.md`

⛔ 画质最容易错序的一步是 **01 三条管线定性**：
先把超分和抗锯齿一起调，会发现"糊"分不清是哪条管线造成的 ——
三条都会糊，而**后处理会掩盖上游的糊**。

## 14. 待核对项（运行时验证）

⚠ 待核对：各渲染器对 AA/超分的实际支持矩阵 · 验证：目标渲染器下逐项切换确认（官方文档沿用主版本，4.7.2 未发独立变更说明）

✅ 已核实（原为待核对）：SMAA 1x 自 4.2 起**内置**于 `screen_space_aa` 枚举，无需插件；ⓘ 官方注明 1080p 及以下最有效，可与 TAA / FSR2 叠加（代价更高、更糊）

## 15. 相关文档

- 渲染架构与管线 → `render-pipeline.md`
- 光照 → `lighting.md`
- 着色器 → `shaders.md`
- 渲染进阶（LOD/预热） → `rendering-advanced.md`
- 性能剖析 → `perf-profiling.md`
- 3D 场景 → `3d.md`
- 4.7 新特性 → `version-47-48.md`
