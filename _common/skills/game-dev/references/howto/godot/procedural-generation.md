# 程序化关卡生成（Godot 4.7.2）

现有文档只有 TileMap 手工编辑，`advanced-topics.md` 里的生成只是片段。本文讲**可维护的 PCG 管线**。

## 0. 起点不是"生成画面"，是可复现的数据管线

```
seed → RNG → 布局数据 → 场景实例
```

⚠ **没有 seed 的 PCG 无法维护** ——
"这个关卡有问题"这句话在没有种子时无法复述，也就无法修。

## 1. RandomNumberGenerator

```gdscript
var rng := RandomNumberGenerator.new()
rng.seed = numeric
rng.randi_range(0, 10)      # 闭区间 [0, 10]
rng.randf_range(0.0, 1.0)
rng.randfn(mean, deviation)
```

⚠ **全局 `randi()` 是全局状态** ——
任何脚本、插件、引擎行为调用它都可能改变下一次结果。
**必须用实例**，多人游戏里主机与世界生成、客户端特效各自一个 RNG。

⚠ **`state` 只能恢复同一实例序列的状态**，不能把任意整数当高质量种子。
保存/恢复走 `state`，分享与复现走 `seed`。

⚠ **`seed` 的 getter 返回的是先前状态，不是原始种子** ——
不要靠读 seed 去"回看分享码"。

⚠ **确定性还要锁定调用顺序与浮点路径** ——
官方明确 PCG32 是**实现细节，不承诺跨版本复现**。
要求可复现就固定 Godot 版本与导出模板，或自带 RNG。

## 2. 算法选型

| 算法 | 适合 | 注意 |
|---|---|---|
| **BSP 分割** | 结构化地牢、房间 | 产出的是树，**可能没有环**，探索感差 |
| **递归回溯迷宫** | 小/中 TileMap | 总是连通无环，但**机械、多长死胡同** |
| **Prim 迷宫** | 有机洞穴、区域扩张 | 比回溯分支更多 |
| **元胞自动机** | 洞穴 | **最容易产生不可达区域** |
| **WFC** | 邻接约束明确（街区/管道/平台拼接） | 约束求解，最坏组合级，需回退 |
| **泊松磁盘采样** | 植被、敌人布点 | 只管"不挤"，**不管玩法密度** |

⚠ **100×100 迷宫用二格间隔 → 逻辑网格 51×51**，瓦片写入仍是 O(宽×高)，要纳入预算。

⚠ **BSP 产出的是树**：从起点 BFS 算距离，把最远房间设为目标、
中段设为精英区；需要环时按距离给少数不相邻房间补边。

⚠ **迷宫可以先建完美迷宫再按概率破墙** ——
迷宫保证连通，破墙增加环路。运行时非常便宜。

## 3. 连通性校验是必做步骤

⚠ **元胞自动机最容易产生不可达区域**。
从出生点 flood fill，**未访问的地板必须改写、连接或删除**。
另一策略：保留最大连通分量，删掉其余。

⚠ **只有当地图由方法本身保证连通时才能省略检查**。
即便 BSP，若后续程序化改了瓦片，也要重新验证。

⚠ **泊松采样只保证"不挤"** ——
只用"距离足够远"会生成四角远离路径、**玩家完全看不到的奖励**。
每个合法子区域应单独算可接受点，再叠加威胁预算、视线、出生距离。

## 4. TileMap / GridMap 对接

⚠ **4.3+ 的 `set_cell` 签名变了**：

```gdscript
# 4.3+
tilemap_layer.set_cell(coords, source_id, atlas_coords, alternative_tile)
# 4.0–4.2：首参是 layer: int
```

写错的表现是"代码不报错但图块不出现"。4.3 起 `TileMap` 已 deprecated，
推荐 `TileMapLayer` 一节点一层。

⚠ **TileMapLayer 要批量提交**，不要逐格误调旧 API。

## 5. 分帧与线程

⚠ **别在循环里改场景树** —— 每帧插几十节点会掉帧。
正确做法：**先在纯数据层算完，最后一次性实例化**。

⚠ **与活动场景树的交互不是线程安全的** ——
后台算完回主线程提交才是合理架构。

## 6. 坐标精度是硬约束

| 偏移 | 精度 | 表现 |
|---|---|---|
| 约 ±10⁷ | 约 1 单位 | **可见抖动、吸附、行走异常** |
| 超出建议单精度范围 | 渲染与物理异常 | 需双精度或原点重置 |

⚠ **这是浮点数值精度问题，不是渲染贴图或物理设置问题。**
⚠ **大世界坐标不是免费开关，原点重置也不是落后方案** —— 两者都有成本。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/procedural-generation.md`


## 7. 种子质量：RNG 无雪崩效应

⚠ **官方口径**：*"The RNG does not have an avalanche effect, and can output similar random streams given similar seeds."*

⛔ 用局数 1 / 2 / 3 或关卡号 1 / 2 / 3 当种子 ——
相邻种子产出的**结构高度相似**，玩家连开三局会觉得"根本没随机"。

✅ 外部来源的种子**先过一次 `hash()`** 再喂给 `rng.seed`：

```gdscript
rng.seed = hash(seed_source)   # seed_source 可以是字符串、关卡号、分享码
```

⚠ 还有一条官方副作用：*"Setting this property produces a side effect of changing the internal state, so make sure to initialize the seed **before** modifying the state"*
—— 先恢复 `state` 再设 `seed`，恢复的状态会被覆盖掉。顺序只能是 **先 seed 后 state**。

## 8. FastNoiseLite 的默认值与取值域

⚠ **`noise_type` 的默认值是 `1`，即 `TYPE_SIMPLEX_SMOOTH`**（不是 value 噪声）。

⛔ 以为默认是 value 噪声 → 按 value 的特征调参，
表现为"怎么调都不像教程里的效果"，而去反复改一个根本没生效的旋钮。

⚠ **`fractal_*` 参数对所有噪声类型生效**（按官方属性表），
不存在"value 用一套、simplex 用另一套"之分 —— 别去找那套不存在的对应关系。

⚠ **cellular（Cellular / Worley）的返回值可能大于 1**：
官方写明 *"Most generated noise values are in the range of `[-1, 1]`, but not always. Some of the cellular noise algorithms return results above `1`."*

⛔ 把 cellular 输出当 `[0, 1]` 直接用 → 阈值判断失效，
表现为"洞穴比预期大一圈"，而阈值看着完全正常。

## 9. 待核对项（运行时验证）

- ⚠ **连续 `RandomNumberGenerator.new()` 可能拿到同一种子** ——
  有实测报告指出 `randomize()` 的时间源是微秒粒度，紧密循环里连续构造会撞种子
  （来源为第三方实测，非官方文档）。⛔ 未亲自复现前不要当成结论写进判据，
  但可以**规避**：不要在循环里 new，复用单个实例或显式设 seed。
- ⚠ **`randi()` 实现质量的说法**：有文章称官方形容其实现"bad and insulting"，
  未从官方文档核实。⛔ 本库只采用"全局 `randi()` 是全局状态、必须实例隔离"这条已有结论。

## 10. 相关文档


- TileMap 手工编辑 → `tilemap.md`
- 3D 与 GridMap → `3d.md`
- 开放世界与原点重置 → `openworld.md`
- 性能 → `perf-profiling.md`
- 坐标与物理 → `physics.md`
