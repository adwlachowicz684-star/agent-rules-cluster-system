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

## 2. 抗锯齿：渲染器支持矩阵完全不同

⚠ **TAA 仅在 Forward+ 可用**，Mobile 与 Compatibility **均不支持**。
⚠ **2D MSAA 在 Forward+ 与 Mobile 可用，在 Compatibility 不可用** ——
这与 3D MSAA 的支持矩阵**完全不同**。

| 方案 | 特点 |
|---|---|
| MSAA | 质量好，⚠ 透明/alpha scissor 材质（植被）表现有坑 |
| FXAA | 快但糊 |
| TAA | ⚠ 有鬼影，与部分特性冲突，仅 Forward+ |
| SMAA | 社区方案，待核对 |

⚠ **MSAA 与 TAA 能否叠加**要按渲染器确认。

## 3. 后处理

`WorldEnvironment` 能做：Bloom · Tonemap · SSAO · SSR · 景深 · 色差 · 暗角。

### ⚠ Tonemap 与 HDR

**HDR 输出只在 Reinhard / AgX / Linear 下响应** ——
**Filmic 与 ACES 始终输出 SDR 范围**。

想用 4.7 新增的 HDR 输出，tonemap 模式不能随便选。

⚠ 后处理的**性能代价要排序**（哪个最贵），按预算取舍。

## 4. 调试：怎么判断"糊"是哪个环节

逐项开关对比：

```
渲染分辨率 → 超分模式 → AA → 后处理
```

⚠ 4.7 的 **Viewport Debug Draw** 能看部分信息。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/upscaling.md`


## 5. 待核对项（运行时验证）

⚠ 待核对：各渲染器对 AA/超分的实际支持矩阵 · 验证：目标渲染器下逐项切换确认（官方文档沿用主版本，4.7.2 未发独立变更说明）

⚠ 待核对：SMAA 在 4.7.2 的可用方案 · 验证：社区插件实测

## 6. 相关文档

- 渲染架构与管线 → `render-pipeline.md`
- 光照 → `lighting.md`
- 着色器 → `shaders.md`
- 渲染进阶（LOD/预热） → `rendering-advanced.md`
- 性能剖析 → `perf-profiling.md`
- 3D 场景 → `3d.md`
- 4.7 新特性 → `version-47-48.md`
