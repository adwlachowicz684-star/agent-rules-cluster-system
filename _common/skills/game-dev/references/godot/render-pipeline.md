# Godot 4.x 渲染管线

**三个渲染器不是"高/中/低配"，是三条不同的代码路径。**
选错不是性能差一点，而是中途换要重做 shader、粒子、GI、后处理。

## 0. 底层差异（决定了后面所有的取舍）

| | Forward+ | Mobile | Compatibility |
|---|---|---|---|
| 底层 | RenderingDevice | RenderingDevice | **OpenGL** |
| 图形 API | Vulkan / D3D12 / Metal | 同左 | OpenGL 3.3 / GLES3 |
| 定位 | 桌面优先 | 移动端为主 | 低端桌面、移动端、**Web** |

⚠ **Compatibility 不是另两个的"低配模式"**，是 Godot 3 渲染器前向移植的独立路径。
⚠ **Shader 在 RenderingDevice 系与 Compatibility 之间不互通** ——
自定义 ShaderMaterial 通常要写两套。这是最容易被低估的一格。

## 1. 能力矩阵

| 能力 | Forward+ | Mobile | Compatibility |
|---|---|---|---|
| 每 mesh 点光/聚光上限 | **512/簇**（可增） | 8/mesh、256/视图（不可改） | 8/mesh（可增，代价是编译时间） |
| 方向光数量 | 8（共享阴影图集） | 8 | 8 |
| 点光/聚光 PCSS | ✓ | ✓ | ✗ |
| 方向光 PCSS | ✓（很贵） | ✗ | ✗ |
| 光投影纹理 | ✓ | ✓ | ✗ |
| **VoxelGI** | ✓（仅此） | ✗ | ✗ |
| **SDFGI** | ✓（仅此） | ✗ | ✗ |
| LightmapGI 渲染 | ✓ | ✓ | ✓ |
| ReflectionProbe | 无上限 | 8/mesh | 2/mesh |
| SSIL | ✓ | ✗ | ✗ |
| SSR | ✓ | ✗ | ✗ |
| **体积雾 Volumetric Fog** | ✓ | ✗ | ✗ |
| FogVolume | ✓ | ✗ | ✗ |
| 传统雾（非体积） | ✓ | ✓ | ✓ |
| Compute Shader | ✓ | ✓ | ✗ |
| RenderingDevice 直访 | ✓ | ✓ | ✗ |
| **GPUParticles3D** | ✓ | ✓ | **无法运行**（OpenGL 无 compute） |
| **自动实例化** | ✓ | ✗ | ✗ |
| MultiMesh | ✓ | ✓ | ✓ |
| MSAA | 2×/4×/8× | 2×/4× | 2×/4×/8× |
| TAA | ✓ | ✗ | ✗ |
| FXAA/SMAA/SSAA | ✓ | ✓ | ✓ |
| FSR2.2 | 主路径 | 待核对 | ✗ |
| Glow/Bloom | 完整 | 受限 | 受限 |
| DOF / SSAO | ✓ / ✓ | ✓ / ✗ | ✓ / ✗ |
| 色调映射/曝光/色差 | ✓ | ✓ | ✓ |
| **Compositor / CompositorEffect** | ✓ | ✓ | ✗ |
| 2D 基础渲染 | ✓ | ✓ | ✓ |
| 2D Compute/GPU 粒子 | ✓ | ✓ | ✗ |
| **基础开销** | **最高** | 中等 | 最低 |
| **随复杂度缩放** | **最低** | 中等 | **最高** |
| 4.7 AreaLight3D | 完整 | 有限（PCSS 半影不对） | 无阴影、无投影纹理 |

### 性能曲线形状不同 —— "哪个更快"是错的问法

```
场景简单、物体少     → Compatibility / Mobile 更快（基础开销低）
物体多、光源多、复杂 → Forward+ 反超（clustered 分簇 + 自动实例化）
```

⚠ **100 个物体的简单移动端场景，Mobile 可能比 Forward+ 快**；
但 200 个点光 + 大量动态物体的桌面场景，Forward+ 显著胜出。

⚠ **Mobile 快的原因**：默认 `R10G10B10A2` 而非 `RGBA16F`（带宽近减半）
+ Vulkan subpass 在 tile 内一次走完。
代价是**一旦开读屏/读深度的效果（Glow、DOF、屏幕空间）subpass 优化就失效**，
移动端会明显掉帧。

⚠ **矩阵里最危险的一格是"自动实例化"**：
Forward+ 对"同 Mesh + 同材质 + 不透明/Alpha Scissor/Alpha Hash"自动合批，**无需代码**；
Mobile 与 Compatibility **都不支持**。
所以"一万根草"在 Forward+ 能跑满，换 Mobile 直接崩 draw call。

## 2. 选型决策

| 项目类型 | 选 |
|---|---|
| **2D 游戏** | **Compatibility**（通常够用且最稳） |
| Web 平台 | **Compatibility（硬约束，没得选）** |
| 移动端 3D | **Mobile** |
| 桌面中高端 3D | **Forward+** |
| 老设备 / 集显 | Compatibility |
| 需要 VoxelGI/SDFGI/体积雾 | **只能 Forward+** |

⚠ **Web 只能用 Compatibility** —— 这是硬约束，不是偏好。

⚠ **中途换的代价**：
Mobile ↔ Forward+ 切换代价小；
Compatibility ↔ 另两者要**重做 Shader、粒子、GI、后处理**。
所以选型要在项目早期定死。

⚠ 驱动回退：Vulkan ↔ D3D12 ↔ Metal 之间会自动回退；
无 RenderingDevice 时兜底到 Compatibility（4.4 起）。

## 3. 一帧里发生了什么（能用就够）

- **Clustered Forward**（Forward+）：用 compute shader 分簇，
  所以能支持海量光源
- **深度预通道（depth pre-pass）**：先画一遍深度，减少 overdraw
- **透明物体排序**：经典问题，透明物体不写深度、按距离排序，
  互相穿插时会出排序错误
- **什么时候打断批处理**：材质不同、Mesh 不同、透明、
  用了 instance 特有的 uniform —— 都会打断

⚠ **共享材质为什么重要**：自动实例化要求"同 Mesh + 同材质"。
给每个实例 clone 一份材质 = 批处理全部失效。

## 4. 后处理

### 接入优先级

```
Camera3D（最高，局部覆盖）
  > WorldEnvironment（推荐，每场景树只能一个，多个会警告）
    > 预览环境（最低，仅编辑器）
```

⚠ **自 Godot 4 起，效果的质量与性能参数移到 Project Settings**，
Environment 里只管"开什么"——不用给每个场景单独调性能档。

### 开销排序（便宜 → 贵）

```
色调映射/曝光/色彩调整
  < Glow/Bloom
    < DOF
      < SSAO
        < SSIL
          < SSR
            < Volumetric Fog（最贵）
```

⚠ 排序是**相对的**：分辨率翻倍时所有全屏效果成本翻倍，
DOF/SSAO/SSR 尤其明显。

⚠ **移动端该关的是"读深度/读屏"的那一组**，不是盲目关全部：
SSR、SSIL、SSAO → 体积雾 → Glow 降质量 → DOF 降质量或按距离关。

⚠ Glow/DOF/色调映射在 Mobile 与 Compatibility **都支持**，
关它们不是"换渲染器才支持"。

⚠ Mobile 若效果依赖 HDR 范围（强 Bloom），要开 `hdr_2d`，
但**帧带宽和集显性能会下降**。

### 自定义 pass

⚠ **"我想让自定义效果在 Glow 之前、DOF 之后"** ——
WorldEnvironment 的勾选框做不到，要用 **CompositorEffect** 插点
（只能在 Forward+/Mobile 用，Compatibility 不支持）。

⚠ **2D 后处理不走 WorldEnvironment 的 3D 效果栈**。
SSR/SSIL/体积雾/DOF 依赖 3D 深度与法线，对 2D 无意义。
2D 要 Bloom/色差/暗角/扫描线：渲染到 Viewport，再对纹理跑自定义 shader。

⚠ **像素风项目别同时开高分辨率后处理 + viewport 拉伸**，
像素感会先被插值再处理，全糊。

## 5. 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | Compatibility 是低配版 | 是**独立代码路径**，shader 不互通 |
| 2 | Mobile 和 Forward+ 差不多 | 差 VoxelGI/SDFGI/体积雾/SSR/自动实例化 |
| 3 | Forward+ 一定最快 | 简单场景 Mobile/Compatibility 更快（基础开销低） |
| 4 | Web 能选渲染器 | **只能 Compatibility** |
| 5 | 换渲染器改个设置 | Compatibility↔其他要重做 shader/粒子/GI/后处理 |
| 6 | GPUParticles3D 到处能用 | **Compatibility 无法运行**（无 compute） |
| 7 | 一万根草没问题 | 只有 Forward+ 自动实例化，其他要 MultiMesh |
| 8 | 材质 clone 一下没关系 | 破坏批处理 |
| 9 | 移动端关掉所有后处理 | 该关的是**读深度/读屏**那组 |
| 10 | SSR 移动端能开 | Mobile/Compatibility **没有**这个功能 |
| 11 | 后处理顺序能拖 | 自定义顺序要 CompositorEffect |
| 12 | 2D 也能用 WorldEnvironment 的 SSR | 2D 没有深度/法线，要 Viewport + shader |
| 13 | 分辨率不影响后处理成本 | 翻倍就翻倍 |
| 14 | Mobile 开 hdr_2d 没代价 | 帧带宽与集显性能下降 |
| 15 | 多个 WorldEnvironment 没问题 | 每场景树只能一个，多个会警告 |
| 16 | 效果质量在 Environment 里调 | 4.x 起在 **Project Settings** |

## 6. 相关文档

- 光照方案（GI/烘焙/阴影/体积光）→ `lighting.md`
- Shader 编写 → `shaders.md`
- 渲染进阶（LOD/XR/Trail）→ `rendering-advanced.md`
- 性能优化 → `performance.md`
- 开放世界 → `openworld.md`
- 版本差异 → `version-47-48.md`
