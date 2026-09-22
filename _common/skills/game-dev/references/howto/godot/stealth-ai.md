# 潜行 / 侦察 AI 玩法层（Godot 4.7.2）

**此前文档里「潜行 / 暗杀 / 侦察 / 搜查 / 警戒 / 视野锥 / 掩体 / 嗅觉」全部 0 命中。**

> ⚠ **与既有文档的分工**：
> `ai-perception.md` 是**感知机制本身**（视觉三闸门、听觉事件、记忆、群体共享）；
> `ai-behavior.md` 是 FSM / 行为树；`ai-navigation.md` 是寻路。
> 本篇是**感知之上的玩法层**——敌人怎么被瞒过、怎么起疑、怎么搜查，以及玩家的隐匿手段。

⚠ **潜行不是"发现/未发现"的布尔判断**，而是三层模型：

```
连续怀疑度（公平累积） → 离散警戒等级（决定行为） → 可观察行为（玩家能读出来）
```

> 审核用反模式清单见 `audit/godot/stealth-ai.md`

## 0. 警戒 = 两段独立语义：知道什么 + 正在做什么

⚠ **只用 `alerted: bool` 会把"看见影子""听见响声""看见尸体""看见玩家本人"
压缩成同一种后果**，玩家也无法从守卫图标、语音、巡逻密度反推自己暴露了多少。

| `EvidenceTier`（我知道多少） | 含义 |
|---|---|
| `UNSEEN` | 没有可归因威胁 |
| `GLIMPSE` | 曾看见移动/残影，身份不确定 |
| `CIRCUMSTANTIAL` | 声音、开着的门、尸体、同伴消失等**间接证据** |
| `IDENTIFIED` | 已稳定确认玩家身份与最近位置 |
| `HOSTILE` | 已交战、受击或被明确攻击 |

| `ActionState`（我现在做什么） | 含义 |
|---|---|
| `PATROL` / `IDLE` | 常规 |
| `OBSERVE` | 转向证据源，**不离开岗位** |
| `INVESTIGATE` | 移动到证据源并局部检查 |
| `SEARCH` | 覆盖式搜查 |
| `ENGAGE` | 追踪、射击或呼叫支援 |
| `EVASION_COOLDOWN` | 不再看见目标，但**仍紧张、仍在找** |
| `CALMING` | 区域可信为已清空，逐步衰减 |

⚠ **两者不必一一对应。** 守卫发现尸体时是 `INVESTIGATE + CIRCUMSTANTIAL`，
却还没 `IDENTIFIED`；看见玩家奔跑可以直接跳 `IDENTIFIED + HOSTILE`。

⚠ **升级要快且允许短路，降级必须慢且不能跨越中间态。**
"升级快"不是取消反馈——玩家已经暴露，就不该让守卫继续背对目标慢速巡逻。
但 ⛔ **`HOSTILE → UNSEEN` 直接跳级 = 抹掉玩家已经付出的代价**。

```
最低安全降级路径：HOSTILE → EVASION_COOLDOWN → CALMING → UNSEEN
```

- `EVASION_COOLDOWN` 仍在主动寻找，任一时刻可被新证据打断
- `CALMING` 才开始冷却，需要达到 `RE_UPGRADE_THRESHOLD` 才会重新升温

⚠ **世界态势与个人怀疑要分开。** 哨站可以整体长期封锁（`world_threat_level`），
但**单个守卫的个人怀疑按冷却下降**——否则潜行失败后没有恢复路径。

```gdscript
func transitions() -> void:
    if tier >= IDENTIFIED and target_visible:
        state = ENGAGE; return
    if state == ENGAGE and not target_visible:
        state = EVASION_COOLDOWN
        evasion_timer = EVASION_DURATION
        retain_last_seen_position()
    if state == EVASION_COOLDOWN:
        if new_strong_evidence: state = ENGAGE; return
        evasion_timer -= dt
        if evasion_timer <= 0: state = CALMING
    if state == CALMING:
        if any_evidence >= RE_UPGRADE_THRESHOLD: state = SEARCH
        else:
            calming_timer -= dt
            if calming_timer <= 0: state = PATROL; tier = UNSEEN; suspicion = 0
```

## 1. 怀疑度：连续累积，但任何单源都不能直通满值

⚠ **连续值负责解释"为什么"，离散等级负责解释"做什么"。**
只有离散等级 → 玩家难以理解"少看 0.2 秒是否安全"；
只有连续条 → 系统无限细分行为，守卫显得犹豫、频繁切换目标。

```gdscript
raw         = base_value(source) * visibility_factor * distance_attenuation \
              * familiarity_modifier * difficulty_modifier
contributed = clamp(raw, 0, per_source_cap[source.kind])
delta       = contributed - source_already_contributed[source.id]
suspicion   = clamp(suspicion + delta * dt, 0, 100)
source_already_contributed[source.id] += delta
```

⚠ **`per_source_cap` 是关键的反误杀参数。** 没有它，
一次爆炸、落地或同伴误报就会**立即**把守卫推进战斗。

| 证据源 | 基础贡献/秒 | 单源软上限 | 衰减 | 解释 |
|---|---:|---:|---|---|
| 视觉残影 | 12 | 20 | 停止后 1.5–2.5 s | 只证明有动静，不证明身份 |
| 清晰目击 | 45 | 50 | 脱离视线 0.5–1.0 s | 可快速升级，不能无限叠加 |
| 噪声 | 25 | 35 | 声音寿命结束即停 | 事件本身已有传播与寿命 |
| 尸体 | 8 | 70 | 30–90 s 缓慢衰减 | **持久证据**，不只是一次性事件 |
| 同伴消失 | 15 | 40 | 每 5–10 s 重新确认 | 应优先清点，不是立即认定玩家 |
| 灯/门/环境变化 | 10 | 25 | 按事件年龄加权 | 越新的异常越值得检查 |
| 禁区行为 | 20 | 50 | 被发现后 3–6 s | 制服不合法时立即升温 |

ⓘ 上表是**起始参数**，必须在具体关卡和人称视角下重调。

⚠ **衰减不是"发现后开始"，而是"证据失效后开始"，且取决于当前等级：**

| 状态 | 衰减行为 |
|---|---|
| `UNSEEN` / `OBSERVE` | 正常衰减 → "缩回掩体"成为有效操作 |
| `SEARCH` | **只停止新增同来源贡献**，不让怀疑度快速清零 |
| `ENGAGE` | 完全冻结玩家侧衰减，改用撤离冷却 |

⚠ 若"被发现后还能正常衰减"，玩家会卡视角反复刷新，**潜行变成安全漏洞**。

⚠ **旧变化不应再升温。** 对门、灯等状态用"事件距今时间"的寿命窗——
超过窗值的旧变化不该让守卫进入全面警戒。

## 2. 搜查：把世界切成待覆盖区域，不是按顺序访问噪声点

⚠ **只把"最后已知位置"当唯一目标** → 守卫在玩家曾站过的点反复停留；
⚠ **只朝噪声源移动** → 忽略玩家可能沿走廊转移。

```gdscript
class_name SearchProblem extends RefCounted
var origin             # 证据触发位置
var last_known         # 目标最后被确认的位置/方向
var threat_direction   # 证据暗示的逃离方向
var coverage_cells     # 房间/格子/导航区域
var visited_set
var candidate_points
var expires_at
```

**生成顺序：**
① 以 `last_known` 为圆心生成 3–6 个扇形候选点
② 以噪声源、被破坏的灯、开门方向、尸体位置补充分支点
③ 沿威胁逃离方向生成 1–2 个外推点
④ 对候选点按**导航可达性、视线断点、区域覆盖增量、重复度**评分
⑤ 删除已充分覆盖、导航失败或掉出搜索边界的点

⚠ **搜索不是"走到即完成"，而是对每个候选点完成一次局部检查。**
守卫抵达后应转向证据方向、播语音、检查柜子/掩体/脚下，再等 0.6–1.5 秒。
⛔ 只把路径点设为到达半径会造成"巡逻式搜索"——守卫穿场而过，玩家无法预测或利用。

⚠ **搜查必须能被玩家观察和利用**，否则玩家只会等待。
投石制造远端候选点 · 关门改变守卫预期路线 · 等待用于观察其检查节奏——
这些才是搜查作为**玩家工具**的意义。

**终止条件要同时看三件事（⛔ 不能只看时间或只看数量）：**

```gdscript
termination = coverage_ratio * 0.45 \
            + no_new_evidence_time / search_cooldown * 0.30 \
            + threat_confidence * 0.25
```

只按"全部查完"终止 → 生成三个点就无事可做；
只按超时终止 → 守卫在大型空间过早放弃。

⚠ **搜查与巡逻共用移动骨架，但不共用"当前目标"字段。**
巡逻消费固定路点（可预测、可循环）；搜查消费证据驱动的临时覆盖点（必须能失效）。
⛔ 共用字段会让存档、中断、行为树恢复和调试把两者混成同一种行为。

## 3. 玩家隐匿：连续化、可被看见、每种手段都能被反制

⚠ **可见度是连续暴露值，不是"在阴影中/不在阴影中"。**

```gdscript
exposure = lighting_at(point) * shadow_occlusion * material_or_stance * posture_exposure
```

最终可见度取**头部、躯干、脚部三个采样点的加权最大值**（或 `1 - 全部被遮挡比例`）。

⚠ **只检测玩家原点** → 卡进墙时消失；
⚠ **只检测中心点** → 露出手指也被发现。
跑动或探头时增补手部/武器采样点。
⚠ **必须把观察者 RID 加进射线排除参数** —— 遮挡命中自身骨骼是常见错误。

⚠ **软掩体与硬掩体影响的是暴露度，不是把玩家变隐形。**
硬掩体形成可靠视线断点；软掩体（灌木、铁丝网、透明隔板）只**降低视觉质量**，
仍可能看到轮廓、动作或武器。
⛔ 任何掩体都直接归零暴露度 → 玩家反复从同一墙角露出眼睛而守卫毫无反应。

**噪声是带位置、半径、寿命、表面与语义的事件。** 起始半径（须配合混响/材质/听觉曲线实测）：

| 行为 | 半径 |
|---|---:|
| 蹲走 | 1.5 m |
| 行走 | 4 m |
| 奔跑 | 9 m |
| 重落地 | 12 m |
| 关门 | 7 m |
| 拖尸 | 3 m |

⚠ **"完全无声"通常不是好设计** —— 否则高度差和路线选择失去价值。
⚠ **声源要与视觉证据分离**：守卫可以听见声音但**不识别身份**，
于是进入搜查，却不立即知道玩家是谁。

⚠ **气味/痕迹只有在能可视化时才值得加入。**
它应是空间标记（"潮湿走廊经过""沾血足迹""雪地痕迹"），
⛔ 不是绕开障碍的真实气体模拟。
ⓘ **是否需要气味层应由美术/关卡能否呈现足迹决定**，
而不是先写一套无法观察的机制（**待核实**）。

### 伪装的核心是"身份与权限"，不是服装模型

```gdscript
class_name Disguise extends Resource
@export var apparent_identity      # 外观身份
@export var legal_areas: int       # 位集
@export var legal_actions: int
@export var suspicious_items       # 持械、拖尸…
@export var tells                  # 步态、武器、血迹、语音
var suspicion_per_observer: Dictionary   # ⚠ 每个观察者独立
```

⚠ **每个观察者维护自己的怀疑度** ——
否则一个守卫看见武器后**全图立刻知道玩家伪装**。
⚠ 换装要有短暂的"更换中"状态（期间仍显示原身份），
⛔ 否则换装成为即时重置。
⚠ `suspicion_per_observer` **不能由客户端决定**，否则伪造外观可绕过检查。

## 4. 视野锥：价值不在美术，在把预测性交给玩家

⚠ **只存在于后台的圆锥无法让玩家回答"现在探头安全吗"**；
⚠ **固定角度、不受遮挡的锥会鼓励玩家贴着锥边反复刷新**。

分**中央清晰区**（累积快）+ **外围运动感知区**（主要响应移动），并对距离衰减。

⚠ **贴地投影通常比完整 3D 体积更适合玩家阅读。**
完整 3D 体积适合飞行单位、高层建筑或多层掩体，但增加填充与理解成本。
ⓘ Godot 的 `ImmediateMesh` 支持每帧重建简单几何体（**重建前要先 `clear_surfaces()`**）。

```gdscript
var points := []
for a in cone_ray_angles(facing, fov, resolution):
    var to := eye_position + Vector3(cos(a), 0, sin(a)) * cone_range
    var r := space.intersect_ray(eye_position, to, [observer_rid])
    points.append(clamp_to_floor(r.position if r else to))
build_floor_polygon(central_mesh, points, central_color)
build_outline(peripheral_mesh, points, peripheral_color)
```

⚠ **被遮挡处不要只把锥"拉回最短命中点"。**
对玩家最有用的是"视线可能从这里开始"的渐变边界：
墙体两侧保留阴影切口，被挡的远端标成**不确定区域**。
⛔ 把锥完全截止在墙根 → 玩家无法判断拐角后是否仍有视觉连接。

⚠ **多敌人叠加要显示"总暴露风险"，但保留个体贡献。**
✅ 用 `max(各守卫暴露率)` 红/黄双层叠加，并保留"主要威胁是谁"；
⛔ 全部平均 → 重叠区出现很亮却无人真正观察的**假热点**。

## 5. 潜行暗杀是状态条件，不是普通处决换皮

⚠ **必须同时满足六项**：
① 目标 `tier` 不高于阈值（通常 `< IDENTIFIED`，或虽起疑但背对且极近）
② 玩家自身暴露度低于阈值
③ 攻击方向在合法弧内（背后/侧后优先，正面需特殊能力）
④ 距离、高度差、动作标签、武器标签合法
⑤ 目标未被永久标记为不可暗杀（已警觉 Boss、机械单位）
⑥ 执行时不会把尸体留在被看见的位置

⚠ **普通战斗处决发生在公开冲突中**（失败可转伤害或格挡）；
**潜行暗杀成功则默认不暴露玩家**，失败应触发守卫转身、喊叫、发现尸体或进战斗。
⛔ 失败时仍播"必杀动画" → 潜行变成无风险赌博。

⚠ **"无声"是范围语义，不是全局开关。**
一次成功暗杀只保证**目标没机会发出声音**，不保证其他守卫看不见。
命中后要独立计算尸体落地、倒地、血迹、拖拽与观察者视线。
⛔ 把消音等同隐身 → 玩家站在灯下众目睽睽连续暗杀。

## 6. 尸体：持久证据，且必须进入对象预算

⚠ **尸体是玩法状态，不是死亡特效。** 至少包含：
位置 · 所属阵营 · 是否被发现 · 发现者集合 · 可见度遮挡 · 血迹 ·
噪音半径 · 可搬运状态 · **权威拥有者** · 死亡原因。

⚠ **尸体的可见性要像玩家可见性一样计算**（视线/距离/遮挡/光照/姿势），
⛔ 不能用固定半径替代——倒下的位置可能让原本的掩体关系完全改变。

⚠ **搬运是藏尸状态机，不是播一个动画：**
搬运者降速、持续产生小范围噪声且保持可见；目标尸体在搬运时**不能立即从世界消失**。
⛔ 藏尸点只靠标签判定 → 玩家把两米高的尸体塞进小箱子；
要对尸体 AABB、观察者方向和缝隙做射线检查。
⚠ **搬运完成是"改变证据位置与可见性"，不是"证据删除"。**

⚠ **尸体必须进对象预算** —— 每具独立做视锥/噪声/距离查询是 **O(敌人 × 尸体)**。
做法：① 空间哈希或按房间索引 ② 每区域 `max_active_bodies`
③ 远处尸体退化为低代价证据标记 ④ 离开区域或记忆过期后**睡眠**
⛔ **不要瞬间删除** —— 删除会破坏玩家已经制造的隐藏状态。
ⓘ 具体数量取决于平台、同屏敌人、骨骼数与导航成本，**必须 profiling**（**待核实**）。

## 7. 脱战必须继续惩罚，冷却期间仍可重新发现

⚠ **脱离视野只是进入撤离，不是重置。**
`EVASION_COOLDOWN` 期间守卫保留最后已知位置、搜索方向与较宽听觉；
看见玩家**即使只一帧**也可重新进 `ENGAGE`，无需怀疑度从零重累积。

ⓘ 起始值（设计起点，非标准）：`EVASION_DURATION = 6–10 s`，
`CALMING_DURATION = 15–30 s`，区域威胁恢复更慢。

⚠ **防"跑一圈就重置"的核心是持久后果。** 一旦进过 `IDENTIFIED` / `HOSTILE`，
至少留下**一项**：提高区域威胁 · 改变最近巡逻点 · 守卫交换最后已知位置 ·
临时封锁出口 · 记录玩家身份/外观 · 尸体继续存在 · 搜查区域扩大。

⚠ **关键反馈**：守卫的图标、头部转向和语音应明确显示"他还在找"，
⛔ 不是让玩家看统一的小感叹号。

## 8. Godot 实现：一个纯数据组件 + 事件接口

```
AlertProfile         阈值、衰减、听觉、搜查参数（可策划）
SuspicionState       连续值、来源缓存、冷却
AlertStateMachine    EvidenceTier / ActionState
SearchPlanner        SearchProblem 生成与终止
```

⚠ **感知结果只通过 `PerceptionEvent` 输入；
⛔ 动画、UI、寻路和导航代码不得直接修改怀疑度。**

```gdscript
class_name AlertComponent extends Node
signal suspicion_changed(value)
signal alert_state_changed(from, to)
signal search_point_added(point)
signal body_discovered(body)
```

**服务端权威**：证据注入 · 警戒等级 · 搜查点的权威状态 · 暗杀合法性裁决 · 尸体权威状态
客户端只做：输入、预测、表现渲染

## 9. 待核对项（运行时验证）

⚠ 待核对：怀疑度各项阈值（视觉残影 12/20、清晰目击 45/50、噪声 25/35、尸体 8/70） · 验证：**起始参数，非通用标准**，须在具体关卡与人称视角下重调

⚠ 待核对：噪声半径（蹲走 1.5 m、行走 4 m、奔跑 9 m、重落地 12 m） · 验证：须配合房间混响、地板材质与守卫听觉曲线实测

⚠ 待核对：`EVASION_DURATION` / `CALMING_DURATION` 取值 · 验证：本轮给的是设计起点（6–10 s / 15–30 s），须按关卡尺度实测

⚠ 待核对：是否需要气味/痕迹层 · 验证：**取决于美术与关卡能否呈现足迹**，先解决反馈再增加复杂度

⚠ 待核对：尸体对象预算的具体数量 · 验证：取决于平台、同屏敌人、骨骼数与导航成本，须 profiling

⚠ 待核对：Godot 4.7.1 各热修复对导航/渲染/多人的影响 · 验证：锁版本，升级前重跑导航、渲染与多人回归

## 10. 相关文档

- 感知机制本身（视觉三闸门、听觉事件、记忆、群体共享）→ `ai-perception.md`
- FSM / 行为树 → `ai-behavior.md`
- 寻路与导航 → `ai-navigation.md`
- 战斗处决（与潜行暗杀的区别）→ `combat.md`
- 射击与掩体 → `firearms.md`
- 视野锥渲染与 ImmediateMesh → `rendering-advanced.md`
