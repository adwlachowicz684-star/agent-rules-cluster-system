# 自动战斗 / 扫荡 / 离线挂机 / 录像回放（Godot 4.7.2）

**此前文档里「自动战斗 / 挂机战斗 / 扫荡 / 快速战斗 / 重玩 / 录像回放」全部 0 命中。**

> ⚠ **与 `combat.md` 的分工**：那篇回答"**一次战斗怎么打**"
> （四层分离、AttackContext、命中判定、帧数据、伤害公式、Buff/Debuff、技能系统、
> 打击感、对抗层的硬直/霸体/破防/招架/处决）；
> 本篇回答"**同一套战斗逻辑，在四种输入源下怎么复用**"。
> 两者共享战斗核心，⛔ 不要写第二套战斗系统。

⚠ **一句话定调**：这四类不是四个"播放功能"，而是**同一个战斗模拟器**
在四种输入源、时间尺度与权威域下的复用。

> 审核用反模式清单见 `audit/godot/auto-battle.md`

## 0. 四种模式：只是输入源与权威域不同

| 模式 | 输入 | 跑完整战斗 | 权威域 | 必须保证 |
|---|---|---|---|---|
| **手动战斗** | 玩家实时 `Intent` | 是 | 单机 PVE 可本地；**竞技必须服务端** | 输入及时采样、表现不影响结果 |
| **自动战斗** | AI 策略生成 `Intent` | 是 | 同上；PVE 服务端重算更稳 | ⚠ **AI 只见玩家可见信息** |
| **扫荡 / 快速战斗** | 空或高层摘要 | **否** | **服务端** | 结果预告与发放一致、次数消耗幂等 |
| **录像回放** | 历史 `Intent` 重放 | 是 | 录制端（通常服务端） | 同版本、同配置、确定性重演 |
| **离线挂机** | 无实时输入，按周期推进 | **原则上不逐帧跑** | **服务端** | 一次性结算、事件分段、可审计 |

⚠ **"扫荡"不是把战斗加速 1000 倍，而是把战斗换成不带位置/碰撞/动画的结算函数。**
⛔ 真的跑完整战斗会有三类成本：大量单位持续寻路/碰撞/技能模拟 · 逐场等动画物理渲染 ·
每场都产生 RNG、事件和录像。更重要的是，**实时战斗的结果无法被客户端低成本稳定预测**。

## 1. 模拟器合同：只接受 Intent

```gdscript
CombatSimulation
  inputs : IntentSource       # LIVE_PLAYER / AUTO_AI / REPLAY / NULL(SWEEP)
  time   : FixedTickClock     # 仅逻辑 tick，⛔ 不读帧 delta / 系统时间
  rng    : SeededRngBank      # 战斗、掉落、表现各自独立
  config : VersionedRuleSet   # 公式、技能、关卡、活动、平衡版本
  world  : SimState           # 单位、CD、Buff、事件队列
  view   : SimEventSink       # 只订阅，⛔ 绝不回写模拟器
```

⚠ **`Intent` 必须是领域动作语义**，⛔ 不能是 `Input.is_action_pressed("jump")`、
鼠标坐标、UI 按钮索引或节点路径。

```gdscript
enum IntentType { MOVE, SELECT_TARGET, BASIC_ATTACK, SKILL,
                  CANCEL, GUARD, ITEM, RETREAT }
struct Intent { tick: int; actor_id: int; type: IntentType;
                target_id: int; skill_id: int; payload: bytes; }
```

⚠ 玩家输入、AI 决策、回放录制、测试脚本**都转换成同一个结构**；
模拟器从不读取真实输入设备。这样回放也不必把操作绑到具体分辨率、设备按钮或节点树。

## 2. 自动战斗：是 AI 策略适配器，不是第二个战斗系统

⚠ **自动 AI 必须消费与玩家相同的目标可见性、技能范围、冷却、资源、视野与随机性暴露规则。**

⛔ AI 不能读 `enemy.current_hp`、`enemy.intent_next_turn` 或任何 `combat._debug`。
⛔ 若 AI 能读隐藏血量、完整行动计划、碰撞体内部标签或未发生的随机数，
它就不仅更省力，而且**客观上更强** —— 这会把"一键托管"变成隐性强制。

AI 只应持有 `Observation`：可见血量区间、可见目标、自己技能 CD、自己能合法知道的状态。

⚠ **决策点必须对齐固定 tick，⛔ 不是每渲染帧扫描。**
优先级（稳定终极排序）、条件树（可读战术）、CD/资源感知（避免抖动）**三者分开**：

```gdscript
candidates = skills where preconditions(actor, observation) and not on_cooldown
if survival_low and heal_available:          issue HEAL
elif threat_high and control_available:      issue CONTROL
elif execute_condition_met:                  issue EXECUTE
elif highest_value(candidates, observation): issue SKILL(candidate)
else:                                        issue BASIC_ATTACK / MOVE
```

⛔ 不要只写"大招优先级最高"（优先级表达不了条件），
⛔ 也不要只写巨量 `if`（配置变更会迫使改代码）。
⚠ 决策后必须**写回"为什么选它"**，用于复盘、观战标签与后续调弱。

⚠ **设计开关比算法更能决定玩家是否还愿意手动玩** ——
`auto_enabled`、角色级策略、技能黑名单、血线、资源下限、目标偏好要在运行时可配。
真正有效的不是把 AI 写"笨"，而是把**玩家知识与执行能力分开**：
AI 可做精确计时和反应，但⛔ 不获得隐藏信息；关键决策仍由玩家承担。

## 3. 扫荡：预告与发放必须是同一笔事务

⚠ **扫荡只保留会影响产出的变量**：玩家阵容/战力、敌人阵容、关卡配置版本、
随机种子、次数、活动/VIP/道具倍率、掉落规则。

### 两种结果算法：确定性模型 vs 代理预测

| 算法 | 公式 | 优势 | 公平风险 |
|---|---|---|---|
| **复用简化战斗公式** | `result = sweep_resolve(stage, snapshot, rules, seed)` | 与玩家体验过的战斗同一套规则子集，胜率与产出自然 | 简化模型⛔ 不能漏掉破防、部位破坏、处决、抗性、仇恨、目标切换、连击，否则"明明能过却扫失败" |
| **按战力推算** | `p_win = sigmoid((atk_pow - def_pow) / scale)` | 稳定、快速、易控体验 | 战力⛔ 不是真实技能表达：养成虚高、克制关系、手动操作空间都会让"数值说该赢"但玩家复现不了 |

✅ 推荐产品策略：**已通关且已解锁扫荡的关卡用简化战斗规则；
未通关、特殊机制关、活动关必须手动通过后再开放；
战力曲线只用于失败惩罚、奖励降级或排队匹配，⛔ 不替代战斗结果。**

### 预告不是"展示一个期望"

⚠ **预告是把服务端审批过的结果摘要先发给客户端，发放必须复用它。**

```gdscript
# 客户端请求预览
SweepPreview(stage_id, count, ticket_id, options)
    → 服务端：只校验，⛔ 不预留资源
      snapshot = player.versioned_snapshot()
      for i in 1..count:
          seed_i = derive_sweep_seed(master_seed, stage_id, snapshot.version, i)
          result_i = resolve(snapshot, stage_id, seed_i, rules, multipliers)
      持久化 pending batch，返回 preview_id + 结果 + 总消耗

# 客户端确认
SweepCommit(preview_id, ticket_id)
    → idempotency = first(REQUEST, ticket_id, player, preview_id)
      已提交 → 返回缓存的首次结果
      已过期/撤销 → 拒绝
      ⚠ 同一事务内：扣体力 → 按 source 键发奖 → 标记 committed
```

⚠ **`preview_id` 要绑定舞台、次数、配置版本、倍率、种子与玩家快照** ——
任何关键变量变化都使旧预览作废。
⛔ 两次调用不能让客户端"先看、再改难度、再领"。

⚠ **奖励每一项用 `source_type:source_id:player:item:seq` 幂等键**，
重复投递只返回首次结果，**⛔ 不能重新抽掉落**。

⚠ 扫荡次数、体力/票券、VIP 次数、活动加成、掉落概率、通关条件、奖励上限
**全部服务端权威**；客户端可提前拉规则做费用面板，但⛔ 面板不是结算结果。

## 4. 离线挂机：一次性推导，不能按真实时间跑循环

⚠ **玩家离线时服务端不会让每个角色持续寻路、碰撞和渲染。**
⛔ 按真实时间跑循环：N 个离线玩家线性放大 CPU，且重启、扩容、补算、跨日活动会重复或遗漏。

按 `time-progression.md` 的锚点原则，**速率变化写成事件日志**：

```gdscript
events = [(t0, scene, power, rate), (t1, new_unit),
          (t2, buff_expire), (t3, config_hotfix)]
cut    = clamp(now - last_settled_at, 0, CAP)
cursor = 0
for seg in segments_while(cursor < cut):
    end    = min(seg.end, last_settled_at + cut)
    dur    = end - cursor
    rewards += rate(last_settled_at + cursor) * dur
    cursor = end
last_settled_at = now
remain = max(0, cut - cursor)      # ⚠ 余数留在当前未完整结算周期
```

⚠ **战斗场次数不是"打一场等若干秒再打一场"。**
⛔ 不要在每次 tick 用 `if accumulator >= interval: spawn_battle()` 累积浮点误差。
要按连续产出率积分；必须离散化时用整数毫秒、定点或最小可结算单位，
对边界统一采用"**满一场才结算，余数留给下次**"。

⚠ **离线掉落要可审计就必须有结构化事件日志，⛔ 不能只存总金币：**
`event_id, player, scene, start, end, config_version, seed, formula_version,
snapshots[], rewards{}, reason, prev_anchor, next_anchor, request_id`。

⚠ **客户端不得根据本地时间算"离线了多久"** ——
设备时钟可改、后台进程会被杀、热更会改变规则。
客户端可展示"预计离线收益"，但到账数量**以服务端结算单为准**。

⚠ 重大配置热更要绑定版本，⛔ 避免回补离线时用新规则改写旧窗口。

## 5. 回放与观战：见专门文档，本篇只用它们

⚠ 回放与观战**已有专门文档**，本篇不重复展开，只说明它们与本篇的接口关系：

| 需求 | 去哪 |
|---|---|
| 录什么（输入 / 状态 / MovieMaker 三条路线）、确定性、回放文件格式 | → `replay.md` |
| 观战、断线重连、主机迁移、延迟补偿、可见性过滤、观战延迟 | → `spectate-reconnect.md` |

⚠ 但下面三条是**本篇独有的**，专门文档里没有：

**① 扫荡结果也要能"被复现"。**
扫荡虽然不跑完整战斗，但它的 `preview_id` 绑定了 seed、配置版本与玩家快照 ——
运营要能用同一批参数重算出"当时为什么发这些奖励"。
⛔ 如果扫荡用了全局随机或运行时读配置，客诉就无法复现。

**② 离线挂机的结算单就是一份"结果录制"。**
它记录了 `config_version / seed / formula_version / prev_anchor / next_anchor`，
⚠ 这与回放的五类元数据是同一套思路 —— 差异只是它不存输入序列。

**③ 自动战斗的记录用于校验，不用于展示。**
⚠ 服务端**不必完整重放整场自动战斗**，但应保存**输入摘要、seed、版本和关键事件**，
在异常或举报时做确定性校验 —— 判定标准见 `replay.md` 第 1 节的两个保证级别。

## 7. Godot 实现：固定 tick 是自动战斗与扫荡的共同底座

⚠ **`_physics_process` 是正确入口，但它不是跨平台确定性承诺。**
官方说明它默认按固定间隔调用，而 `_process()` 与硬件帧率耦合。
若项目不用 Godot 物理，也可单独维护固定步长累加器，
⛔ 避免动画、音频或 GUI 回调进入模拟。

```gdscript
const STEP_MS := 1000 / 60.0
var accumulator_ms := 0.0
var sim_tick := 0

func _physics_process(delta: float) -> void:
    accumulator_ms += delta * 1000.0
    while accumulator_ms >= STEP_MS:
        accumulator_ms -= STEP_MS
        sim_tick += 1
        input_port.begin_tick(sim_tick)
        simulation.step(STEP_MS)     # 自动战斗：喂 AI 意图
        event_sink.flush(sim_tick)
```

⚠ **AI 决策与扫荡结算都对齐这个 `sim_tick`，⛔ 不是每渲染帧扫描一次。**

⚠ **随机必须来自独立 seeded RNG bank**，⛔ 禁止 `randf()` / 全局随机 / `Time` / 节点 ID：
`combat_rng`（命中暴击）、`drop_rng`（掉落）、`spawn_rng`（生成）、`cosmetic_rng`（表现，可本地实时）。

> 回放场景下的 RngBank 快照/恢复、确定性五个杀手、跳转与校验和 → `replay.md`

## 8. 服务端权威清单

凡影响**资产、进度、公平或跨端一致性**的量，⛔ 都不能由客户端最终决定：

- 扫荡的胜败、评价、掉落、金币、经验、物品
- 扫荡次数、剩余次数、体力/票券/能量消耗与恢复
- VIP、活动、首通、新手、广告、公会等**所有倍率与上限**
- 离线锚点、时长上限、速率、配置热更、结算结果
- 竞技录像的种子、配置摘要、结果、校验和、排名
- AI 是否有权用某技能、目标是否合法、CD 与资源是否够
- 观战延迟、可见性过滤、观众是否可参与

⚠ 客户端可缓存配置并算预览，**但结果必须服务端重新评估**；
客户端改内存后"提交结果"的请求必须被拒绝。

⚠ 服务端**不必完整重放整场自动战斗**，但应保存输入摘要、seed、版本和关键事件，
在异常或举报时做确定性校验。

## 9. 待核对项（运行时验证）

⚠ 待核对：本项目 Godot 4.7 的编译选项与 `physics_ticks_per_second`、`physics_jitter_fix`、`max_physics_steps_per_frame`、物理插值设置 · 验证：**待核实**，须联调前写入配置契约

⚠ 待核对：Godot 4.7 的 PCG/随机实现是否沿用旧版、是否随小版本变化 · 验证：官方明确算法是实现细节，**不能依赖跨版本复现**；需长期稳定则自实现已知算法

⚠ 待核对：`Dictionary` 在 GDScript 4 具体版本中的插入顺序承诺 · 验证：官方警告迭代时删除不可预测，**不要依赖顺序**

⚠ 待核对：项目用 GDScript / C# / GDExtension，各自浮点与数学库差异不同 · 验证：须按实际技术栈确认

⚠ 待核对：离线效率曲线、扫荡概率、战斗场次时长、回放检查点间隔、保留期限、观战延迟与可见字段 · 验证：**均为策划/产品参数**，须按本项目平衡表确认

⚠ 待核对：服务端数据库与事务隔离级别 · 验证：影响幂等与并发结算

## 10. 相关文档

- 战斗核心（四层分离、命中判定、帧数据、伤害公式、对抗层）→ `combat.md`
- 离线结算的锚点原则 → `time-progression.md`
- 放置品类的挂机/离线收益 → `genres-idle-sim.md`
- 战报与竞技回放的限制 → `social.md`
- 网络同步与 RPC 模式 → `multiplayer.md`、`netsync-advanced.md`
- 随机数与种子可复现 → `procedural-generation.md`
- 补偿幂等 → `ops.md`
- 反作弊与服务器权威 → `security.md`
