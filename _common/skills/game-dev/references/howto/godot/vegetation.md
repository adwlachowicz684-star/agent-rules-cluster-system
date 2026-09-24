# Godot 4.x 植被 / 大规模散布物

> **适用**：草、灌木、树、石头等需要**成千上万实例**的散布物。
> **不适用**：单个精心摆放的装饰物（那是普通 `MeshInstance3D`）。
> ⚠ 本域的前提是：**数量大到不能逐个建节点**。

## 0. 先定性：这是实例化问题，不是建模问题

⚠ **植被的第一性问题不是"叶子长什么样"，而是"一万个怎么画"。**

⛔ 用 `MeshInstance3D` 逐个建节点是最常见的起点错误：
一万个节点 = 一万个 `Node3D` 参与遍历、剔除、变换更新，
**在加第二棵树之前帧率就已经崩了**——而这个方向的错误
要等到铺满场景才暴露，返工成本极高。

✅ 唯一可行路径是 `MultiMeshInstance3D`（一次 draw call 画全部实例）。

ⓘ 但 MultiMesh 有自己的代价，见第 1 节——
它**不是**"用上就快了"。

## 1. ⚠ MultiMesh 是一个 AABB，不是一万个

⚠ **整个 MultiMesh 共享一个包围盒：只要摄像机看到其中一个实例，
全部实例都会被提交。**

⛔ 一万棵树放进一个 `MultiMeshInstance3D`，
摄像机看到一棵 → GPU 画一万棵。
性能**不随屏幕覆盖率变化**——第一次 profile 森林的人都会被这点惊到。

### 1.1 两种症状

| 症状 | 原因 |
|---|---|
| 摄像机背对原点时**整片植被消失** | 代码填 transform 前 AABB 已算好 → 退化成原点上的零尺寸盒 |
| 转向时顶点数**完全不降** | 只有一个 AABB，没有真剔除 |

### 1.2 两步解法

**① 填完 transform 后显式写 `custom_aabb`：**

```gdscript
var aabb := AABB(Vector3.ZERO, Vector3.ZERO)
for i in instance_count:
    var t := Transform3D(Basis.IDENTITY, positions[i])
    mm.set_instance_transform(i, t)
    aabb = aabb.expand(positions[i])
custom_aabb = aabb.grow(mesh_radius)   # ⚠ grow 留出网格半径
```

⛔ 少了 `grow()`，中心刚好在视锥外的实例**边缘会被切掉**。

**② 按格子分块** —— 只写对 AABB 仍然是一刀切。

```gdscript
const CELL_SIZE := 32.0    # 密集植被的合理起点
```

ⓘ 每格一个 `MultiMeshInstance3D`、各自 AABB，
引擎逐格剔除，**帧时间随可见格数变化，而不是随总实例数变化**。

⚠ 验证方法：Monitor 面板看 `Vertices Drawn`，
转视角应当**立刻下降**；不降就是 AABB 还是错的。

### 1.3 ⛔ 逐实例剔除引擎不做

⚠ **引擎标准管线不做 MultiMesh 内的逐实例剔除** ——
这正是 MultiMesh 存在的意义（避免 CPU 侧的逐实例工作）。

⛔ 别指望"把山后面的草剔掉"能自动发生。
真需要的话要自己写 compute shader 生成间接绘制参数，ⓘ 那是专家级路径。

ⓘ 退而求其次的办法是 `visible_instance_count` + 按距离排序——
⛔ 它只能隐藏**索引靠后**的实例，不做空间剔除。

## 2. ⚠ alpha scissor 植被：MSAA 无效，正确解法是两者组合

⚠ **官方原话：*"MSAA does not reduce transparency aliasing for materials
using the Alpha Scissor transparency mode (1-bit transparency)."***

⛔ 所以"植被边缘闪烁"用 MSAA 治是**无效的**。
但别停在这里——**正确解法是 MSAA + alpha to coverage 组合**：

**① 先开 MSAA 3D ≥ 2×**（项目设置，⚠ 是 `MSAA 3D` 不是 `MSAA 2D`）
**② 再在材质上开 Alpha Antialiasing**（StandardMaterial3D / ORMMaterial3D）

ⓘ **官方 Important：*"MSAA 3D should be set to at least 2× ... when using
alpha antialiasing. This is because this feature relies on alpha to coverage,
which is a feature provided by MSAA."***

⚠ 只开后者不开 MSAA → 退化成固定抖动图案，官方原话
*"isn't very effective at smoothing out edges"*。

### 2.1 ⛔ Alpha Antialiasing Edge 必须严格低于阈值

⚠ **官方：*"Alpha Antialiasing Edge must always be set to a value that is
strictly below the alpha scissor threshold."***

默认 `edge = 0.3` 配 `threshold = 0.5` 是合理的，
⛔ **改了 scissor 阈值就必须同步改 edge**——两者不匹配时
表现为"摄像机靠近时贴图外观明显变化"。

### 2.2 三种模式

| 模式 | 又名 | 效果 |
|---|---|---|
| Disabled | — | 硬边 |
| Alpha Edge Blend | alpha to coverage | 平滑过渡 |
| Alpha Edge Clip | alpha to coverage + alpha to one | 锐利但仍抗锯齿 |

ⓘ 两种模式都只在 transparency 为 **Alpha Scissor / Alpha Hash** 时可见。

## 3. ⛔ 双面叶片：从 Blender 导出会带上 Disabled

⚠ **官方：*"By default, Blender has backface culling disabled on materials
and will export materials to match how they render in Blender. This means
that materials in Godot will have their cull mode set to Disabled."***

⛔ 后果是**背面也会被渲染**——植被这种大量叶片片的场景，
等于把填充率翻倍，而**完全不报错**。

✅ 解法：在 Blender 材质面板**开启 Backface Culling**，再导出 glTF。
ⓘ 需要双面时（薄叶片）显式设 `Disabled`，⛔ 不要让它"碰巧"是 Disabled。

## 4. ⓘ 透明草地/树叶：官方点名要用 Depth Pre-Pass

**Depth Draw Mode** 的 `Depth Pre-Pass` 项，官方原话：
*"Use this option with transparent grass or tree foliage."*

ⓘ 先画一遍不透明部分、再在其上画透明部分，
避免透明植被自穿插时的排序错误。

## 5. 风动画：走 shader，不走 CPU

⚠ **一万个实例的摇摆绝不能在 CPU 上逐个改 transform** ——
那就把 MultiMesh 的意义全部抵消了。

✅ 做法是顶点着色器里按世界坐标 + 时间做位移，
ⓘ 用 `INSTANCE_ID` 或 `custom_data` 做每株相位偏移。

ⓘ 需要每实例不同参数时用
`set_instance_shader_parameter()`（官方提供的 per-instance uniform），
⛔ 不要用 `set_shader_parameter()`——那是改所有实例共享的那个。

⚠ **风的强度应是全局 uniform 或全局状态**（`environment-systems.md#3. 天气`），
⛔ 每株各自算风 → 天气系统改了风的强度，植被不会跟着变。

## 6. LOD 与可见距离

### 6.1 visibility range 的 margin 语义会变

⚠ **官方：margin 的含义取决于 `visibility_range_fade_mode`：**

| fade_mode | margin 含义 |
|---|---|
| `FADE_DISABLED` | 作为**滞后距离**（hysteresis） |
| `FADE_SELF` / `FADE_DEPENDENCIES` | 作为**淡入淡出过渡距离**，⚠ 必须 > 0 才看得出效果 |

⛔ 设了 fade 却把 margin 留 0 → **没有任何过渡，直接硬弹**。

ⓘ `visibility_range_begin/end` 默认 0 = **不做范围检查**（不是"距离为 0"）。

### 6.2 ⚠ 远距离不能只靠 visibility range

⛔ 只设 range 的话，远处植被是**突然消失**而不是变稀疏。

✅ 常规做法是两套 MultiMesh：近处高模 + 远处低模/billboard，
配合 `visibility_range_end` 交叉。

ⓘ 4.7 官方文档已有
*"Using mesh LOD with MultiMesh and particles"* 与
*"Visibility ranges (HLOD)"* 两节，ⓘ 说明 LOD 与 MultiMesh 的组合是官方支持路径。

### 6.3 ⓘ lod_bias = 0 是调试工具

官方：`lod_bias` 为 0 会**强制最低 LOD**，用于测试 LOD 切换。
ⓘ 调 LOD 距离时先把它设 0 确认"最低档长什么样"，比反复改距离快得多。

## 7. ⛔ 可交互植被：MultiMesh 实例没有独立身份

⚠ **MultiMesh 里的实例不是节点，没有独立 ID、不能单独挂脚本。**

⛔ 所以"这棵树被砍了"不能靠删除实例表达——
常见错误做法是把它缩放到 0，ⓘ 那样**索引就错位了**，
第二棵被砍时会砍错树。

✅ 做法是维护一张**平行的状态表**（按实例索引），
砍伐 = 状态置空 + 把该实例与末尾交换 + 降 `visible_instance_count`。

⚠ **交换会打乱索引** → 状态表必须跟着交换，
⛔ 只改数组不改状态表 = "砍了 A，倒下的是 B"。

## 8. 待核对项（运行时验证）

> ⚠ 以下为本域**尚无统一法定数值/口径**的项，落地时必须实测确认。
> ⛔ 不要凭印象填数值——这些恰恰是各项目差异最大的地方。

- ⚠ 待核对：分块尺寸（`CELL_SIZE`）取多少 · 验证：在目标场景实测 `Vertices Drawn` 随视角转动的下降幅度，32m 是密集植被的起点而非结论
- ⚠ 待核对：每株网格的顶点上限 · 验证：实测目标平台帧时间；⚠ 注意 MultiMesh 只省 draw call，**GPU 顶点处理仍随 实例数×顶点数 增长**
- ⚠ 待核对：`visible_instance_count` 是否需要配合距离排序 · 验证：确认排序成本低于省下的顶点处理，否则不划算
- ⚠ 待核对：alpha antialiasing 的 edge 取值 · 验证：与当前 scissor threshold 配对实测，官方要求 edge **严格低于** threshold
- ⚠ 待核对：billboard 切换距离 · 验证：实测"看得出突变"的临界距离，再往回收 10–20%

## 9. 相关文档

- 遮挡剔除与 MultiMesh 基础 → `occlusion-instancing.md`
- 天气与风的状态源 → `environment-systems.md`
- 开放世界与流式 → `openworld.md`
- 程序化布点（泊松采样）→ `procedural-generation.md`
- 抗锯齿选型与超分 → `upscaling.md`
- 渲染器能力矩阵 → `render-pipeline.md`
- 性能剖析 → `perf-profiling.md`

## 10. 审核清单

> **反模式清单（不能怎么做，审核用）** → `audit/godot/vegetation.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-02`　池化与复用（实例复用而非逐个建节点）
【读】 `common/howto/principles.md#GC-06`　性能：先定位再优化（先测 Vertices Drawn 再调参）
