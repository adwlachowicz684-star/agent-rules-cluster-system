<!-- oversize-exempt: 反模式清单，审核用 -->
# lighting — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/lighting.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 先调参数再选方案 | 方案选错，参数怎么调都返工 |
| 2 | 移动端也能用 VoxelGI/SDFGI | **只有 Forward+ 有**，移动端只有 LightmapGI |
| 3 | 摆好 LightmapGI 就能烘 | 节点位置、gi_mode、UV2 三个都要对 |
| 4 | 有光源就够了 | **没有 WorldEnvironment/天空 → 烘出来全黑** |
| 5 | UV2 引擎会自动搞定 | 复用网格只给第一个实例生成 |
| 6 | bias 调大更干净 | 过头就 peter-panning |
| 7 | 先调 Shadow Bias | 官方建议**先调 Normal Bias** |
| 8 | 阴影有通用最优值 | 要逐灯按几何尺寸调 |
| 9 | cascade 越多越精细 | 关键是**分段点和 max_distance** |
| 10 | 大地面配 4 cascade 没问题 | 大物体跨 cascade **画 5 遍** |
| 11 | 多开几盏带阴影的方向光 | 8 盏**共享**阴影图集，会稀释分辨率 |
| 12 | 体积光用雾 quad 做 | emission 不投射光/阴影，要用真体积雾+光源 |
| 13 | FogVolume 能独立用 | 没开全局体积雾就**不可见** |
| 14 | 体积雾到处能开 | **只有 Forward+** |
| 15 | Web 也能烘焙 | **Web 编辑器不能烘**，要换平台烘 |
| 16 | AreaLight3D 是 GI 替代 | 是**实时光补充**，吃光照与阴影预算 |
| 17 | AreaLight3D 跨渲染器一致 | Compatibility 无阴影、无面积纹理 |
| 18 | 把灯 `visible = false` 以为不参与烘焙 | ⛔ 官方 WARNING：隐藏**不影响烘焙结果**，必须用 `BAKE_MODE_DISABLED`。表现为多出一块不该有的光 |
| 19 | 手动摆了 LightmapProbe 就算完 | ⛔ 官方：放置后**必须重新烘焙**才生效，不重烘等于没摆 |
| 20 | 自动生成的探针可以事后微调 | ⛔ 官方：自动探针**在场景树不可见、烘焙后无法修改**，要改只能重烘 |
| 21 | 动态物体从 lightmap 拿直接光 | ⛔ 直接光**永远由 Light3D 实时施加**，即使灯 bake mode 是 Static；探针只存间接光 |
| 22 | light data 留在 .tscn 里就行 | ⛔ 应存外部 `.lmbake`，内联会用 Base64 膨胀场景文件 |
| 23 | 大场景烘焙只是慢一点 | ⛔ 官方：**可能耗尽显存导致引擎崩溃**（即使显存很大的系统） |
| 24 | 编辑器里有预览天空，烘出来就有环境光 | ⛔ 官方：预览天空与太阳**不被计入**；无 WorldEnvironment 时 ENVIRONMENT_MODE_SCENE 等同 DISABLED |
| 25 | `directional` 属性只管方向光 | ⛔ 官方注明该属性名**与 DirectionalLight3D 无关**，对所有灯类型生效 |
| 26 | 场景里多放几个 LightmapGI 分段烘焙 | ⛔ 官方：**最多同时渲染 8 个**，超出后视口内实例会 popping in/out 闪烁 |
| 27 | SDFGI 的 Bounce Feedback 调高更真实 | ⛔ 官方：> 0.5 **可能导致无限反馈循环，场景几秒内变得极亮** |
| 28 | SDFGI 生成后改网格，间接光会自动跟上 | ⛔ 官方：**仅在相机移入/移出级联时更新 SDF**，要相机远离再靠近或开关 SDFGI |
| 29 | 网格 GI mode 设 Dynamic 能贡献 GI | ⛔ SDFGI 下 **Dynamic 等同 Disabled**，只接收不贡献 |
| 30 | SDFGI 的 Max Distance 调大覆盖全场景 | ⛔ 官方：应**始终低于相机 far**，超出部分算了也没有收益 |
| 31 | SDFGI 开关/切场景后立刻就是正确光照 | ⛔ 官方：默认需 **25 帧收敛**，期间有明显过渡 |
| 32 | FogVolume 放上去就有局部雾 | ⛔ 官方：只在 `Environment.volumetric_fog_enabled = true` 时有可见效果 |
| 33 | 想要只有局部雾就关掉全局体积雾 | ⛔ 关掉会让 FogVolume 一起失效；应把全局 `volumetric_fog_density` 设 `0.0` |
| 34 | 薄 FogVolume 闪烁是精度不够，只能忍 | 修法三条：提高 `volume_depth`（有性能代价）/ 降低 `volumetric_fog_length`（无代价但雾程变短）/ 加厚并降密度 |
| 35 | cone / cylinder 用 size 做非均匀缩放 | ⛔ 官方：**不支持**，要缩放 FogVolume 节点本身 |
| 36 | 聚光灯角度开到很大照样有阴影 | ⛔ 官方：**角度 > 89 度时阴影完全停止工作**，要更宽用全向光 |
| 37 | 大物体阴影缺失就继续调 bias | ⛔ 官方：属 **Pancake Size** 场景（大物体 + 未细分网格），且只在确认不是 bias 问题后才改 |
| 38 | Fade Start 设 1.0 让阴影不淡出 | ⛔ 官方：**只在 Max Distance 完全覆盖场景时可用**，否则阴影会在远处突然被切断 |
| 39 | 面光源阴影不对就继续调 bias | ⛔ 官方：物体**细分不足且离面光源很近**时阴影会不对（同 OmniLight3D 的 Dual Paraboloid 限制） |
| 40 | 面光源只是单盏灯的成本 | ⛔ 官方：Forward+ 下**视锥内有一个面光源，所有渲染物体都有额外 GPU 成本** |
| 41 | `area_attenuation = 2.0` 求物理正确就行 | ⛔ 官方：range 4096 时 100 单位处衰减因子 **0.0001**，默认亮度下那盏灯根本看不见 |
| 42 | 面光源纹理运行时随便切 | ⛔ 官方：切换有性能代价；每维为 **128 的倍数或 2 的幂**可省掉缩放 pass |
| 43 | 先调参数再选方案 | 方案选错，参数怎么调都返工（⛔ 本域第一原则） |
