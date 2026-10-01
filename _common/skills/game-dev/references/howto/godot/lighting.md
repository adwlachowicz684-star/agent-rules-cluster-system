# Godot 4.x 光照

三种光照方案的本质区别是**"谁付运行时成本"**。
先选方案，再调参数——顺序反了会反复返工。

## 0. 方案选型（先看这个）

| 方案 | 运行时成本 | 静态/动态 | 需要哪个渲染器 |
|---|---|---|---|
| **实时光** | 最贵（每帧算 + 阴影图） | 全动态 | 都行 |
| **LightmapGI**（烘焙） | 几乎免费 | **完全静态**，动态物体靠探针 | 都行（烘焙需 RenderingDevice 硬件） |
| **VoxelGI** | 高 | 灯可动、动态物体能收 GI | **仅 Forward+** |
| **SDFGI** | 最高 | 半实时，随相机自动级联 | **仅 Forward+** |

**经验法则**：

```
场景 80% 以上静态        → LightmapGI
中小封闭、灯与物体都动态 → VoxelGI
开放世界 / 程序化生成    → SDFGI
移动端 / 低端硬件        → 只有 LightmapGI
```

⚠ **移动端与 Compatibility 只有 LightmapGI** 这一个 GI 选项。
选渲染器时就把光照方案定了（见 `render-pipeline.md`）。

## 1. LightmapGI 烘焙

### 流程（六步）

1. 静态几何体的 `GeometryInstance3D.gi_mode` 设为 **Static**
2. 确保 **UV2 唯一且连续**（最容易卡住的一步）
3. 设纹素密度 `Meshes → Lightmap Texel Size`
4. 摆 WorldEnvironment 与光源的 `Bake Mode`（Static/Dynamic/Disabled）
5. 点烘焙
6. **处理失败码**（最容易跳过的一步）

```gdscript
# 代码触发烘焙（编辑器工具脚本里用）
var gi := LightmapGI.new()
gi.bake()
```

⚠ **LightmapGI 只烘焙与它同层级或作为它子节点的对象**。
节点放错位置 = 烘出来全黑。

⚠ **UV2 生成**：导入面板里选场景，把 `Meshes → Light Baking`
设成 `Static Lightmaps`，Godot 会生成 UV2 并缓存。
UV2 的关键是**每个面在 UV 里有独立位置、不共享像素**。

⚠ 官方推荐：复用网格时 Godot 只为找到的**第一个**实例生成 UV2。
若实例缩放差异超过一半或两倍，纹素密度会低效——
**缩放差异大的资产应做成独立网格资源**。

### 失败码

| 码 | 通常原因 |
|---|---|
| `BAKE_ERROR_NO_MESHES` | gi_mode 没设 Static，或 UV2 无效 |
| `..._TEXTURE_SIZE_TOO_SMALL` | 贴图装不下 |
| `..._LIGHTMAP_TOO_SMALL` | 光照图装不下 |
| `..._ATLAS_TOO_SMALL` | 图集装不下 |
| `FOREIGN_DATA` / `NO_LIGHTMAPPER` / `NO_SAVE_PATH` | 配置问题 |

### 常见失败原因（按概率排序）

1. **忘记 UV2**（最常见）
2. gi_mode 不是 Static，或节点不在 LightmapGI 同级/子级 → **全黑**
3. 没有 WorldEnvironment/天空 → 环境光贡献为 0，**烘出来是黑的**
4. 纹素太大 → 模糊；太小 → 图集放不下或烘焙爆内存
5. **漏光**：薄墙、开放结构、物体间有缝隙，采样到另一侧的光
6. 自阴影黑斑 → 调 LightmapGI 的 `bias`
7. 曝光问题：`CameraAttributes` 曝光太高会 banding/过曝
8. **LightmapGI 占用 UV2 槽**，烘焙后材质里不能再把 UV2 挪作他用
9. **Web 版编辑器不能烘焙** —— 只能在非 Web 平台烘好再到 Web 渲染

⚠ `bias` 只影响**烘焙阴影**，不影响实时灯阴影。
调过头会 peter-panning（影子脱离物体）。

## 2. VoxelGI vs SDFGI

可以用"要不要在编辑器里摆盒子"来记：

| | VoxelGI | SDFGI |
|---|---|---|
| 布置 | 要放节点、设范围、**烘体素** | 几乎不用摆（开开关即可） |
| 适合 | 房间、走廊、**封闭/半封闭中小场景** | **开放世界、程序化关卡** |
| 动态光 | 完全动态 | 支持 |
| 动态遮挡物 | ✓ | **✗** |
| 动态自发光表面 | ✓ | **✗** |
| 动态物体 GI 质量 | **更好** | 一般 |
| 手动成本 | 高 | **几乎为零** |
| 代价 | GPU 要求高，集显不推荐 | Godot 里**最贵**的 GI 之一 |

**开启 SDFGI**：MeshInstance 的 GI Mode 设 Static → 加 WorldEnvironment →
在 Environment 的 SDFGI 段启用。级联随相机自动移动。

⚠ **VoxelGI 的坑**：墙壁太薄会漏光，斜面上会有条纹。
实体面厚至少约一个体素，可用临时静态网格堵漏后隐藏。

⚠ **SDFGI 的坑**：快移动相机可见级联偏移；
漏光可开 Use Occlusion，但有额外开销。

## 3. 阴影

### bias / normal bias 是一组 trade-off

| 现象 | 成因 | 修法 |
|---|---|---|
| **shadow acne**（条纹状自阴影） | bias 过低，表面把自己的阴影投给自己 | 提高 bias |
| **peter-panning**（影子不连脚） | bias 过高，容差太大 | 降低 bias |

⚠ 官方建议**优先提高 Shadow Normal Bias** ——
它比 Shadow Bias 引起的 peter-panning 少，但可能让某些阴影变细。

⚠ **没有通用值**，要按几何尺寸和复杂度逐灯调，每盏灯可以不同。

ⓘ **Pancake Size** 用于修复**大物体 + 未细分网格**导致的阴影缺失，
官方明确**只在确认不是 shadow biasing 问题之后**才改它。
⛔ 把它当成"又一种 bias"去调，会掩盖真正的成因。
提高阴影图分辨率也能缓解 acne，代价是性能。

⚠ 平面/薄片几何两面都难调，最终往往是组合方案：
适度 normal bias + 适度 bias + 足够分辨率 + 拆分大灯/近距离补光。

### PSSM（方向光级联阴影）

⚠ **关键参数是"分段点"和"最大距离"，不是 cascade 数量**。

- 默认 PSSM 4 分屏
- `split_1/2/3` 是相对相机 far（或 `max_distance`）的比例：
  **0 = 眼睛位置，1 = 阴影终点**
- 官方建议把**第一段稍微调近**，给第三人称角色脚下更多细节
- **`max_distance` 是性能与精度的最大杠杆**：越低，近处阴影越精细、
  参与阴影渲染的物体越少

⚠ **大物体跨 cascade 会画 5 遍** ——
"大世界地面 + 4 cascade"必须用分段网格或降低 `max_distance` 对冲。

⚠ 每增加带阴影的方向光会**稀释有效阴影分辨率**（8 盏共享阴影图集）。

## 4. 体积雾与体积光

⚠ **Godot 用 Volumetric Fog（三维 froxel 缓冲）实现，不是后处理贴片**。
**只有 Forward+ 支持**，Mobile 与 Compatibility 没有。

开启：`WorldEnvironment` → Environment 里开 `volumetric_fog_enabled`，
然后调 density / albedo / emission / anisotropy / length / detail spread。

⚠ **`FogVolume` 不是"另一种雾"** —— 它是在全局体积雾上叠加/减去局部雾的区域节点。
**没有开 Environment 的体积雾，FogVolume 不可见**。

⚠ FogVolume 密度**可正可负**，负值用来"挖洞"（比如屋里不要雾）。

⚠ **体积雾能响应光与阴影，但 emission 不向其他表面投射光/阴影** ——
想做"体积光柱照亮地面"要用真正的体积雾 + 光源，单靠雾 quad 做不到。

## 5. 4.7 的 AreaLight3D

矩形面光源，替代过去"自发光材质 + GI"模拟发光屏幕/灯箱/窗户的做法。

```gdscript
var light := AreaLight3D.new()
light.size = Vector2(2.0, 1.0)
add_child(light)
```

- 继承 `Light3D`，发光方向沿 **-Z**
- 参数：`area_size` / `area_range` / `area_attenuation` /
  `area_normalize_energy` / `area_texture`

⚠ **它是实时光，会参与光照预算和阴影预算**，不是免费的。

⚠ **跨渲染器限制**：
Mobile 支持有限（PCSS 半影不随距离正确变化）；
**Compatibility 不能投影面积光阴影，面积纹理也不支持**。
跨渲染器项目只能在 Forward+ 主档用，其他档要验证或回退。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/lighting.md`


## 7. ⛔ 烘焙的静默失效：三类不报错的错

### 隐藏灯 ≠ 不参与烘焙

官方 WARNING 原文：*"Hiding a light has no effect on the resulting lightmap bake.
This means you must use the Disabled bake mode instead of hiding the Light node
by disabling its Visible property."*

⛔ 把灯 `visible = false` 以为它不参与烘焙 —— **照样烘进去**。
表现为"烘完场景里多了一块不该有的光"，
排查必然被引向漏光或反弹次数，
⛔ 不会想到是那盏"看不见的灯"。

✅ 唯一正确的做法是 `Light3D.light_bake_mode = BAKE_MODE_DISABLED`。

### 环境光：编辑器预览天空不被计入

`ENVIRONMENT_MODE_SCENE` 在场景**没有 WorldEnvironment 节点**时
**等同 DISABLED**，且官方注明
**编辑器的预览天空与太阳不被 LightmapGI 计入**。

⛔ 表现为"编辑器里看着有天空、烘出来是黑的"，
而排查时"场景里明明有光"会是第一反应。

### 8 个节点上限

官方：Godot **最多同时渲染 8 个 LightmapGI 节点**。
超出后视口内的实例会 **popping in and out（闪烁）**。

⛔ 表现为"相机移动时光照闪"，
排查被引向纹素密度或烘焙质量，与节点数量无关的表象很像。

### 探针：手动放置后必须重烘

动态物体的间接光靠探针。官方：手动放置 `LightmapProbe` 之后
**必须重新烘焙才生效**；自动生成的探针
**在场景树里不可见、烘焙后无法修改**。

ⓘ 烘焙后编辑器里显示的白色球体**不在运行项目中出现**。

ⓘ **直接光永远由 Light3D 实时施加在动态物体上**，
即使该灯的 bake mode 是 Static —— 探针只存间接光。

### 数据落盘与显存

- ⛔ `.tscn` 里内联 light data 会用 Base64 膨胀 → 应存外部 `.lmbake`
- ⛔ 烘焙可能**耗尽显存导致引擎崩溃**
  （官方注明：即使显存很大的系统也可能）

## 8. ⛔ SDFGI 的反馈循环、收敛与更新时机

| 项 | 官方口径 | 后果 |
|---|---|---|
| Bounce Feedback | **> 0.5 可能导致无限反馈循环，场景几秒内变得极亮** | 调参时看着"变亮了挺好" |
| 收敛 | 默认 **25 帧**才完全收敛 | 切场景时有明显过渡 |
| 更新时机 | **仅在相机移入/移出级联时更新 SDF** | 改了网格不动相机 = 间接光一直错 |
| 网格 GI mode | **Dynamic 等同 Disabled**（不贡献间接光） | 摆了物体却不参与 GI |
| Max Distance | 应**始终低于相机 far** | 超出部分算了也没有收益 |

⛔ **生成后修改网格**：官方要求**相机远离再靠近**，或**关闭再开启 SDFGI**。
否则间接光"看起来不对劲"，而 SDFGI 面板上一切正常。

ⓘ Y Scale 设 **75% 或 50%** 可减少漏光且**不影响性能**
（多数场景不是高度垂直的）。

## 9. 体积雾的可见性前提与薄雾闪烁

⛔ `FogVolume` **只在 `Environment.volumetric_fog_enabled = true` 时有可见效果**。

ⓘ 想只保留局部雾：把全局 `volumetric_fog_density` 设为 `0.0`，
**而不是关掉体积雾** —— 关掉会让 FogVolume 一起失效。

⛔ **薄雾闪烁**：相机移动 / 旋转时薄 FogVolume 会闪。三条官方修法：

1. 提高 `rendering/environment/volumetric_fog/volume_depth`（**有性能代价**）
2. 降低 `volumetric_fog_length`（**无性能代价**，但雾程变短）
3. 加厚体积 + 降低材质密度

⛔ cone / cylinder **不支持用 size 做非均匀缩放** —— 要缩放节点本身。

## 10. 面光源的预算与几何限制

⛔ **预算**：Forward+ 下**只要视锥内有一个面光源，
所有渲染物体都有额外 GPU 成本**（clustered lighting 性质）。
官方建议只用于过场动画或高端设备。

⛔ **几何**：投射阴影的物体**细分不足且离面光源很近**时阴影会不对
（与 OmniLight3D 的 Dual Paraboloid 限制相同）。

⛔ **衰减**：`area_attenuation = 2.0` 是物理正确，但
range 4096 时 100 单位处衰减因子为 **0.0001** ——
默认亮度下那盏灯**根本看不见**。负值或 > 10.0 会有意外结果。

⛔ **纹理**：运行时切换面光源纹理有性能代价；
每维为 **128 的倍数或 2 的幂**时可省掉缩放 pass。

## 11. 流程：按什么顺序做

→ `flow/godot/lighting/`

## 6. 相关文档

- 渲染器能力矩阵 → `render-pipeline.md`
- 3D 场景搭建 → `3d.md`
- 性能 → `performance.md`
- 开放世界（SDFGI 场景）→ `openworld.md`
- 4.7 新特性 → `version-47-48.md`
