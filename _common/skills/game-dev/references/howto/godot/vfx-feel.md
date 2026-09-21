# VFX 与游戏感（Godot 4.7.2）

"命中反馈""juice""屏幕震动"此前 **0 命中**。本文讲视觉特效与打击感。

## 0. 游戏感不是叠加更多特效

⚠ **是让反馈的强度与事件的重要性严格匹配。**

反馈分三层：即时反馈（命中）/ 持续反馈（燃烧）/ 结算反馈（击杀）。

## 1. 粒子：GPU 不是默认答案

| | `GPUParticles2D/3D` | `CPUParticles2D/3D` |
|---|---|---|
| 优势 | 高吞吐、拖尾、子发射器、吸引子、碰撞、自定义 shader | 兼容渲染器/**Web 导出**稳定，逐粒子位置/速度/颜色**可被脚本读** |
| 前提 | 后端支持 GPU 计算（Forward+ / Mobile） | 无 |

⚠ **"默认 GPU"只适用于"现代桌面/主机/移动端 + 不需要读粒子数据"**。
面向 **Web 或兼容性渲染器**，或需要粒子位置驱动逻辑 → **默认选 CPU**。

`ParticleProcessMaterial` 是参数主体。

### 粒子常见坑

⚠ 不循环、不回收、`emitting` 后不消失、`restart()` 时机不对 ——
这几个的表现都是"特效越来越多，帧越来越低"。

## 2. 屏幕震动：trauma 模型

⚠ **直接把随机偏移写进 `camera.offset` 是错的**：

```gdscript
# 错误写法
offset = Vector2(randf_range(-10,10), randf_range(-10,10))
```

三个问题：
1. **多源同时命中会互相覆盖**
2. 随机值每帧独立 → 频谱是**白噪声**，看起来像画面在抖而不是"被撞"
3. 强度不衰减 → 没有余震

**正确模型**：维护 0–1 的 `trauma`，它**只衰减、可叠加（cap 在 1）**，
再用 `trauma^exponent` 作为振幅驱动**采样噪声**。

这样小击中 = 低频小幅，大击中 = 堆叠后振幅上升，且采样走噪声曲线 → 画面有连贯的"摇"。

⚠ **震动加在 Camera 节点上**，不是场景根节点。

## 3. 顿帧 hitstop

⚠ **`Engine.time_scale = 0` 时 `SceneTreeTimer` 默认也停摆** ——
必须用 `create_timer(..., ignore_time_scale=true)`，**否则游戏永久卡死**。

⚠ 时长控制：太长难受，太短没感觉（几十毫秒量级）。

## 4. 拖尾与残影

- 2D：Line2D / GPUParticles2D trail / 自定义
- 3D：GPUParticles3D trail
- **4.7.2 官方对应 `RibbonTrailMesh` / `TubeTrailMesh`**
- ⚠ `Trail3D` 属社区插件或未来版本线索，**待核对**

残影：Sprite 复制 + tween alpha，**材质要独立**否则一起改。

## 5. 命中反馈的完整配方

一个可复用的命中反馈包含六个通道：

| 通道 | 手段 | 注意 |
|---|---|---|
| 视觉-白闪 | 材质闪白（shader 或 modulate） | 时长要短 |
| 时间-顿帧 | `Engine.time_scale` | **必须 ignore_time_scale 恢复** |
| 镜头-震动 | trauma + noise → `camera.offset` | 只改 camera，多源合并 |
| 视觉-粒子 | 飞溅 | 池化、限流 |
| UI-数字 | 伤害数字弹出 | UI 层，注意坐标转换 |
| 音效 | 命中音 | 与视觉同步 |

⚠ **六通道不是每次全开** —— 按事件重要性选强度档。

## 6. 性能

⚠ **高频特效必须池化与限流** ——
同时触发的瞬间开销才是真正的帧率杀手（不是稳态开销）。

粒子数量要定预算，并按目标平台下调。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/vfx-feel.md`


## 7. 待核对项（运行时验证）

⚠ 待核对：`Trail3D` 是否为 4.7.2 官方节点 · 验证：4.7.2 编辑器节点搜索，确认官方对应为 RibbonTrailMesh/TubeTrailMesh

⚠ 待核对：目标平台 GPU 粒子的实际吞吐上限 · 验证：目标设备逐步加粒子数测帧时间

⚠ 待核对：顿帧时长的手感阈值 · 验证：目标项目实测，按事件重要性分档调

## 8. 相关文档

- 着色器 → `shaders.md`
- 2D 渲染 → `2d-rendering.md`
- 相机 → `camera-cutscene.md`
- 音频 → `audio-advanced.md`
- 战斗 → `combat.md`
- 性能 → `perf-profiling.md`
- 对象池 → `systems.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-07`　手感优先于正确性
