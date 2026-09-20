# 环境系统：水面、天空、天气、昼夜（Godot 4.7.2）

"水面""天气""昼夜""海洋" 此前基本空白。

## 0. 没有官方水节点

⚠ 截至 4.7.2，**核心引擎没有官方 `Water` 节点、海洋节点或内置浮力组件**。

⚠ 但"无官方浮力"的准确含义是：没有自动检测水面网格、计算排开体积、生成浮力点的
`BuoyancyBody3D` —— **不等于做不了浮力**。

`RigidBody3D` 的 `apply_force(force, position)` / `apply_central_force()` /
`apply_impulse()` 都是**每物理帧施加**的接口，足够实现浮力、阻力、升力与扭矩。

### ⚠ Gerstner 波的采样必须 CPU/GPU 一致

Gerstner 波用水平位移制造**波峰尖锐、波谷宽**的效果，比纯 sine 更像开放水域。

⚠ 代价：**物体查询高度时必须对同一套波数求和**。
若顶点着色器用八层 Gerstner，而浮力脚本只算一层 sine，
**船会"漂在另一个高度上"**。

→ 波参数与采样函数要放共享常量/统一接口（可考虑 `ShaderGlobals`），
**不要在脚本里复制近似值**。

### 水面推荐方案

Gerstner/Sine 顶点波 + 深度纹理浅水透明 + 屏幕空间法线扰动 + **选择性反射**。
⚠ 移动端与大面积湖泊优先低反射，只在相机附近开平面反射或 ReflectionProbe。

## 1. 天空：三种材质，取舍明确

`Sky` 只有四条路径：Panorama / Procedural / Physical / 自定义 Shader。

| 材质 | 特点 |
|---|---|
| **ProceduralSkyMaterial** | 便宜、可控，**最多四个太阳**，适合卡通/风格化 |
| **PhysicalSkyMaterial** | Rayleigh/Mie 散射，日出日落自然，但**更贵、只支持一个太阳、夜间会变黑** |
| Panorama | 静态 HDR，换贴图最贵，适合固定时间/预烘焙 |

⚠ **天空、雾、环境光、曝光和 GI 是一套联动状态**
—— 都在 `Environment` 上，不能像"换张背景图"那样只换天空材质。
⚠ 天空是**环境光的主要来源**，改天空会整体变亮/变暗。

## 2. ⚠ 昼夜循环与烘焙 GI 是矛盾的

⚠ **Static 烘焙光完全锁定，Dynamic 烘焙光只锁间接光**
→ 不要试图烘焙后逐帧移动方向光。

户外大世界更适合 **SDFGI** 或 **Dynamic LightmapGI + 实时方向光**。

⚠ 用**缓存、固定更新节拍、指数平滑**控制开销 —— 不能每帧重算环境光。

## 3. 天气

- 雨雪用粒子（⚠ GPUParticles vs CPUParticles 的取舍）
- ⚠ **雨要跟随相机** —— 不能只在场景一处下
- 风对植被/粒子的影响
- 闪电：⚠ 瞬时强光要避免炸曝光
- ⚠ **天气切换要平滑** —— 突变会很廉价

> **反模式清单（不能怎么做，审核用）** → `audit/godot/environment-systems.md`


## 4. 渲染器能力矩阵（选型前先查这个）

| 能力 | Forward+ | Mobile | Compatibility |
|---|---|---|---|
| 体积雾 / FogVolume | 完整 | 有限 | **无** |
| VoxelGI / SDFGI / SSIL | 有 | 无 | 无 |
| LightmapGI | 有 | 有 | 可渲染，烘焙需 RenderingDevice |
| GPU 粒子 + GPU 碰撞 | 有 | 有 | **无 GPU 碰撞节点** |
| RenderingDevice 计算管线 | 有 | 有 | **无** |
| 屏幕空间反射 SSR | 有 | 无 | 无 |

⚠ **Web / 旧 OpenGL 设备只能用 Compatibility** ——
不要围绕体积雾、GPU 粒子碰撞或计算着色器做核心设计。
Compatibility 是 Godot 3 渲染器前向移植的**独立代码路径**，shader 与另两者不互通。

## 5. 体积雾：froxel 全局效果，FogVolume 只增减密度

体积雾采用**视锥对齐体素（froxel）**方案，不是后期抠像，可与多种光源交互。

⚠ **放一个 `FogVolume` 不会自动开启体积雾** ——
它依赖 `Environment.volumetric_fog_enabled`。

```gdscript
var env := world_env.environment
env.volumetric_fog_enabled = true
env.volumetric_fog_density = 0.02
env.volumetric_fog_length = 64.0
```

⚠ **`FogMaterial.density` 可为负**（在世界体积雾里减去密度）。

⚠ **Fog 自定义走 `ShaderMaterial` 的 `fog` shader 类型**，
不是通用顶点/片元材质。

⚠ **锥/圆柱不支持通过 `size` 非均匀缩放** —— 要缩放节点本身。

**薄雾移动闪烁的三个选择**：

| 做法 | 成本 |
|---|---|
| 加大 `volume_depth` | 有性能成本 |
| 减小 `volumetric_fog_length` | **免费**，但降低有效范围 |
| 把体积做厚并降低密度 | 视情况 |

⚠ **Godot 没有"在体积内重新投射光束"的传统体积光** ——
所谓内置体积光应理解为"光与体积雾交互"。
要各向异性光束、丁达尔条纹，还得用屏幕光轴/噪声/光锥网格自实现。

⚠ **很多小体积并不自动比一个受控的大体积便宜** ——
成本与屏幕占用、深度采样、材质复杂度有关。

## 6. 昼夜：一个太阳角驱动一切

⚠ **不要每帧分别插值天空色、环境色、灯光色、雾色** ——
结果太阳方向和天空太阳位置不一致。

```gdscript
func set_time_of_day(hour: float) -> void:      # 0..24
    var angle := (hour / 24.0) * TAU - PI / 2.0
    sun.rotation = Vector3(angle, 0.0, 0.0)     # 绕正确轴向，不是欧拉角直映
    _update_sky(angle)
    _update_exposure(angle)
    _update_fog(angle)
```

⚠ **`DirectionalLight3D` 的位置无关** —— 光照方向由节点基向量决定。

⚠ **`ProceduralSkyMaterial` 最多读取四个 `DirectionalLight3D`**
的颜色、能量、方向/角距离。所以"控制太阳"应优先控制主平行光，
再同步天空参数；放多盏平行光后天空会出现多个太阳。

⚠ **夜间可让月亮 `sky_mode = SKY_ONLY`** —— 只进天空不照亮场景。

**阴影级联**：

⚠ **不要用 4 分片阴影覆盖超大开放世界而不降 `max_distance`** ——
远处分辨率与性能同时变差。

```gdscript
sun.shadow_mode = DirectionalLight3D.SHADOW_ORTHOGONAL  # 或 PSSM 2/4 分片
sun.directional_shadow_max_distance = 120.0
sun.directional_shadow_fade_start = 0.8
```

## 7. 湿滑是玩法状态，不只是材质

```gdscript
vehicle.friction_slip = lerpf(DRY_GRIP, WET_GRIP, wetness)
```

⚠ **只改材质不算湿滑** —— 摩擦、扭矩、刹车曲线都要作为参数驱动，
再借 `ShaderMaterial` 的 `roughness/metallic` 与 wetmap 控制外观。

⚠ **雨雪碰撞用 `GPUParticlesCollisionHeightField3D`**，
它不烘焙、可实时更新，适合开放世界，但**不能表示洞穴/悬垂**，
且 `UPDATE_MODE_ALWAYS` 成本显著。

⚠ **雨雪碰撞节点只影响 `GPUParticles3D`** —— 不要拿它给 `CPUParticles3D` 或水面用。

⚠ **`fixed_fps = 2` 不是时间缩放** ——
只降低碰撞/状态更新频率，**不会**放慢粒子寿命或模拟时钟。

⚠ **`local_coords` 与重力方向混用**会让旋转发射器产生反直觉结果。

## 8. 待核对项（运行时验证）

⚠ 待核对：第三方水面插件在 4.7.2 的兼容性与授权 · 验证：按目标版本实测后再决定引入

⚠ 待核对：Godot Hydrodynamics（C++ 模块）的编译可行性 · 验证：按 4.7.2 源码编译测试

## 5. 相关文档

- 渲染管线与 GI → `render-pipeline.md` / `lighting.md`
- 着色器 → `shaders.md`
- 开放世界 → `openworld.md`
- 3D 场景 → `3d.md`
- 性能剖析 → `perf-profiling.md`
- 物理进阶 → `vehicle-physics.md`
