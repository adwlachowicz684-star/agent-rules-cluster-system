<!-- oversize-exempt: 反模式清单，审核用 -->
# render-pipeline — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于审核完成效果、约束边界。
> 「怎么做」看开发侧：`game-dev/references/godot/render-pipeline.md`

## 常见坑

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
