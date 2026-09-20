# Godot 4.x 遮挡剔除 / 实例化 / GPU 粒子 / Compute

## 0. 遮挡剔除：CPU 光栅化测试 AABB

Godot 的遮挡剔除在 CPU 把遮挡物光栅化到低分辨率缓冲，再测被遮挡物的 AABB。

⚠ **AABB 必须被完全遮挡才剔除** ——
所以小物体比大物体更容易受益，厚大墙体比细杆有效。

```gdscript
ProjectSettings.set_setting("rendering/occlusion_culling/use_occlusion_culling", true)
```

`OccluderInstance3D` 持有 `Occluder3D`，形状有
Quad / Box / Sphere / Polygon / ArrayOccluder3D，可在视口"烘焙遮挡物"。

⚠ **Godot 3 的 Room/Portal 系统已不存在** ——
4.7 不要把它当 API 假设，改用 `OccluderInstance3D` 烘焙体系。

⚠ **自动烘焙只考虑 `MeshInstance3D`** ——
不考虑 `MultiMeshInstance3D`、`GPUParticles3D`、`CPUParticles3D`、`CSG`。
这些可作为被遮挡物；若要它们遮挡视线，需手动添加近似遮挡形状。

⚠ **开阔空地未必有收益** —— 遮挡剔除要维护烘焙表示 + 每帧查询，
室内或视线被墙体频繁打断才有价值。

⚠ **遮挡烘焙要排除角色与动态道具** —— 否则它们成为无效遮挡物。

## 1. MultiMesh：所有实例共享同一 AABB

```gdscript
var mm := MultiMesh.new()
mm.transform_format = MultiMesh.TRANSFORM_3D
mm.mesh = _rock_mesh
mm.instance_count = MAX
mm.visible_instance_count = 0
```

⚠ **所有实例共享同一 AABB** —— 远处 LOD 是整个节点一起切换，
**实例分散过大时遮挡与视锥剔除无法剔除个体**，要拆成多个 `MultiMeshInstance3D`。

⚠ **"自动实例化"不是引擎自动合并所有重复网格** ——
它指导入器按材质合并和渲染端批次优化，`MultiMesh` 仍需显式配置。

⚠ **`instance_count` 设置会清空并重分配整个 buffer** ——
运行时要改 `visible_instance_count`，不要改 `instance_count`。

⚠ **MultiMesh 不免费** —— 实例数、阴影、逐实例参数、可见范围都影响性能；
移动或动画实例无法享受静态网格批次。

## 2. GPU 粒子：默认 VFX 工具

```gdscript
gpu.amount = 20000
gpu.lifetime = 2.0
gpu.fixed_fps = 30
gpu.visibility_aabb = AABB(Vector3(-50,-50,-50), Vector3(100,100,100))
```

⚠ **"GPU 粒子能逐粒子回调"是误解** ——
粒子不是可直接查询的 CPU 数组。要做游戏逻辑，
应在生成时刻或少量代表性粒子处读取，或回退到 `CPUParticles3D`。

⚠ **`fixed_fps` 不是时间缩放，也不保证确定性**。

⚠ **`visibility_aabb` 之外粒子会消失，碰撞也不计算** ——
AABB 不足会导致边缘突然消失。

⚠ **粒子数不是唯一指标** ——
少量近距离、半透明、屏幕覆盖大的粒子可能比远处数万点更贵（过度绘制）。

⚠ **子发射器、碰撞高度场、四通道网格都可能压垮 GPU**。

## 3. Compute Shader：RenderingDevice 专用

```gdscript
var rd := RenderingServer.create_local_rendering_device()
var shader := rd.shader_create_from_spirv(_spirv)
var pipe := rd.compute_pipeline_create(shader)
var list := rd.compute_list_begin()
rd.compute_list_bind_compute_pipeline(list, pipe)
rd.compute_list_bind_uniform_set(list, uset, 0)
rd.compute_list_dispatch(list, groups_x, 1, 1)
rd.compute_list_end()
rd.submit()
rd.sync()
```

⚠ **计算着色器不是普通 `ShaderMaterial`** —— 走 `RenderingDevice`。

⚠ **Compatibility（OpenGL）后端没有 `RenderingDevice`** ——
不能把它作为 Web/低兼容目标的核心方案。

⚠ **不要每帧大量小 dispatch 并立即 `sync`** ——
立即回读会让 CPU 等 GPU。避免 CPU/GPU 乒乓、跨帧等待、过大数据回读。

⚠ **Windows 长时间计算可能触发 TDR** —— 需要拆分 dispatch。

**适合的用途**：纹理处理、缓冲区转换、GPU 数据预处理。

## 4. 三渲染器差异（实测为准）

⚠ **Mobile / Compatibility 的遮挡、LOD、实例化能力与 Forward+ 不完全相同** ——
项目应在目标渲染器下实测，不要凭 Forward+ 的表现推断。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/occlusion-instancing.md`
