<!-- oversize-exempt: 反模式清单，审核用 -->
# lighting — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/lighting.md`

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
