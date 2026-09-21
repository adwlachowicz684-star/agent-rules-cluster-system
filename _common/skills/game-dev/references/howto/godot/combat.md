# Godot 4.x 战斗系统

战斗的核心是**"谁的请求被权威结算器批准"**，不是"谁碰到了谁"。
这条区分决定了架构能不能扩展。

## 0. 四层分离

| 层 | 职责 |
|---|---|
| **意图层** | 读输入、请求攻击 |
| **表现层** | 动画、特效、音效、相机 |
| **几何层** | 产生候选命中 |
| **结算层** | 校验并改写状态 |

⚠ **`Area2D` 的职责只是"这里现在重叠了什么"**。
不要让它同时承担消耗资源、应用伤害、生成 UI、广播死亡。
否则策划加一条"被格挡时不耗蓝、触发弹反且不进冷却"，
你要把所有武器的碰撞回调改一遍。

**事件流**：

```
Input → Brain → StateMachine → Ability.try_cast()
  → 播动画 → Call Method Track 开 hitbox/发射线
    → 收集候选目标 → CombatResolver.resolve_hit()
      → 属性与状态 → 伤害信号 → 受击反馈
```

## 1. AttackContext —— 几何与伤害之间的协议

```gdscript
# attack_context.gd
class_name AttackContext
extends RefCounted

enum HitResponse { ACCEPTED, BLOCKED, DODGED, IMMUNE, DEAD, CONSUMED }

var attacker: Node
var ability: Ability
var base_amount: float
var damage_tag: StringName = &"physical"
var direction: Vector2 = Vector2.RIGHT
var knockback: float = 120.0
var can_be_blocked: bool = true
var can_crit: bool = true
var attack_id: int = 0
var hit_targets: Array[Node] = []

func already_hit(target: Node) -> bool:
    return target in hit_targets
```

⚠ **`attack_id` / 已命中集合是必须的**。
一次旋转斩可能在同一物理帧产生多个重叠，一次穿透射击可能命中多个目标——
没有去重就会出现"一次攻击触发两次、四段伤害"。

⚠ 把几何结果包成 `AttackContext` 后，
无论是 Area 命中、射线命中还是服务端回滚命中，**都走同一条结算管线**。

## 2. 命中判定：三种方式按内容分层

| 方式 | 适合 | 关键点 |
|---|---|---|
| **Area2D/3D** + `body_entered` | 持续接触、范围持续伤害 | 只回答"重叠了什么" |
| **射线** `intersect_ray` | 即时命中武器（枪、激光） | 要 `force_raycast_update()` |
| **形状查询** `intersect_shape` | 范围攻击（爆炸、横扫） | 拿到的是数组 |

⚠ **命中判定必须放在 `_physics_process`**（固定步长），
表现层可以插值，但判定不能跟着渲染帧漂移。

⚠ `RayCast` 改了 `target_position` 之后**必须 `force_raycast_update()`**，
否则用的是上一帧的结果——这是最常见的"射线打不中"。

### hitbox / hurtbox 三层

```
攻击框 hitbox    只在 active 帧启用
受击框 hurtbox   常驻
防御框 blockbox  有朝向，背后攻击不算格挡
```

⚠ hitbox **默认必须关闭**，由动画的 Call Method Track 在 active 帧打开。
常开的 hitbox = 走路也在造成伤害。

## 3. 帧数据（动作游戏的地基）

```
startup（前摇） → active（判定帧） → recovery（后摇）
```

| 段 | 手感意义 |
|---|---|
| startup | 太长 = 迟钝；太短 = 无预兆 |
| active | 决定"能不能打中" |
| recovery | 太长 = 惩罚重；可取消 = 连招空间 |

⚠ **判定必须服从固定步长，表现可以容忍插值** ——
判定跟渲染帧走会导致高刷屏和低帧机器手感不一致。

## 4. 伤害公式：先定顺序，再定数值

推荐结算顺序（顺序定错了，后面所有数值都是错的）：

```
1. 是否命中    （闪避判定）
2. 是否格挡    （防御框 / 朝向）
3. 是否暴击
4. 基础×加成   （乘区）
5. 减抗性      （加区/乘区）
6. 应用伤害
7. 触发后续    （反击、吸血、连击计数）
```

⚠ **先判闪避再判格挡还是反过来，是设计决策，但必须写死**。
两边都写"随机判定"会让玩家无法形成预期。

⚠ **乘区和加区要分开**。全用乘区会指数爆炸，全用加区后期无成长感。

## 5. Buff / Debuff：状态是数据，反馈由监听者负责

**属性修改器的结算顺序**：

```
最终值 = (基础 + flat 加成) × (1 + percent 加成)
```

⚠ 混在一起算会导致"两个 +50% 的 buff 叠成 +125%"这类意外。

**状态叠加规则**要在设计阶段定死，四种只能选一种：

| 规则 | 行为 |
|---|---|
| 覆盖 | 新的替换旧的 |
| 叠加 | 同类效果数值相加 |
| 刷新 | 不叠加，只刷新持续时间 |
| 独立层数 | 每层独立计时（如中毒 5 层） |

⚠ **DoT/HoT 的结算要独立计时**，不要挂在 `_process` 里每帧扣血
（帧率不同结果不同）。用固定间隔 tick。

⚠ **状态不要自己播特效** —— 状态是数据，由监听者负责表现。
否则"移除 buff"时要记得清理特效，忘了就是残留特效 bug。

## 6. 技能系统：Resource 装数据，Node 执行

```
SkillData (Resource)   纯数据：伤害、冷却、消耗、动画名、hitbox 形状
SkillExecutor (Node)   执行：播动画、开判定、走结算
场景树                 只负责表现
```

⚠ 把技能做成 Resource 是 Godot 的强项——
策划可以在 Inspector 里配技能，不用改代码。

⚠ **动画与判定的联动用 Call Method Track**，不要用计时器猜时间。
动画改了时长，计时器的时间点就全错了。

## 7. 打击感：一组同步反馈，不是一个大数字

| 手段 | 说明 |
|---|---|
| **顿帧 hitstop** | 命中瞬间冻结几十毫秒（**最关键**） |
| **击退** | 受击方位移 |
| **屏震** | trauma 模型（见 `camera-cutscene.md`） |
| **命中特效** | 粒子、闪光、拖尾 |
| **音效** | 与特效同步 |
| **输入缓冲 / 取消** | 让"正确输入"在不可执行窗口仍然有效 |

### hitstop 实现

```gdscript
# hit_stop.gd
class_name HitStop
extends Node

const MIN_DURATION := 0.03
const MAX_DURATION := 0.12

var _remaining := 0.0
var _original_scale := 1.0
var _active := false

func trigger(duration: float, scale_override := 0.0) -> void:
    var clamped := clampf(duration, MIN_DURATION, MAX_DURATION)
    if _active and clamped <= _remaining:
        return
    if not _active:
        _original_scale = Engine.time_scale
        _active = true
    _remaining = clamped
    Engine.time_scale = scale_override if scale_override > 0.0 else 0.0

func _process(delta: float) -> void:
    if not _active:
        return
    _remaining -= delta          # 注意：真实时间，不受 time_scale 影响
    if _remaining <= 0.0:
        Engine.time_scale = _original_scale
        _active = false
```

⚠ **`Engine.time_scale = 0` 会冻结物理、计时器、动画和输入**，
期间**不能用普通 `await`** 等待恢复（await 也被冻了）。

⚠ 更可控的方式是只冻结战斗相关的动画与物理 tick。
首次实现可以围绕 `Engine.time_scale`，后期替换成自定义 `CombatTimeScale`。

⚠ **4.7 修了"粒子在 timescale=0 时仍移动"的问题** ——
顿帧期间的粒子表现会变，升级后要重测（见 `version-47-48.md`）。

⚠ **输入缓冲与取消是"手感"的隐藏一半**：
玩家在 recovery 里按下的攻击键应该被记住并在可取消时执行，
不缓冲会让连招感觉"吃键"。

## 8. ⚠ 对抗层：命中之后，双方进入什么状态

> 前面讲的是"单次攻击怎么判定、怎么算伤害"。
> 但**硬直 / 霸体 / 破防 / 招架 / 处决 / 部位破坏**是另一套系统——
> 扫描确认这些词此前**全部 0 命中**。
>
> ⚠ **这三者的共同本质是对"行动权（turn）"的争夺，不是数值增减。**
> 攻击方的 startup/active/recovery 决定"能不能打"，
> 硬直决定"打中之后对方能不能还手"，霸体决定"被打时能不能继续打"，
> 格挡与招架决定"打中之前能不能化解"。

### 8.1 硬直：行动权的租借，不是"受伤动画的时长"

⚠ **硬直时长的两个来源必须分开建模，这是所有后续机制的起点。**
攻击招式带 Attack Level 对应基础硬直（**攻击方给的**），
连招持续期间按 combo scaling 打折（**受击方算的**）。

```gdscript
effective_hitstun = base_hitstun * hitstun_scaling.factor
```

只放攻击方 → 无法实现"同一招在连招第一段和第五段硬直不同"；
只放受击方 → 无法区分轻拳与重拳的硬直差异。

⚠ **出招硬直（recovery）与受击硬直（hitstun）是两种完全不同的状态，
共用一个 `stun` 字段是最常见的设计混乱。**
攻击者在自己的 recovery 阶段被打断 ≠ 恢复时间变短，
而是**整个攻击动作被中断、转入受击状态**，恢复帧不再执行。
实现是状态机收到 `interrupt()` 后强行 `transition("Hitstun")`，
⛔ 不是把两个计时器相加。

⚠ **硬直不递减 → 无限连。**
修复不是"加连段上限"（那样连段断得很突兀），
而是配 `HitstunDecayTable` 按**真实时间**衰减并设 floor：

```gdscript
# 按 elapsed 查表，不是按命中数乘系数
tiers = [(0.0, 1.00), (3.0, 0.95), (5.0, 0.90), (7.0, 0.80), (10.0, 0.70), (14.0, 0.60)]
floor_factor      = 0.25      # 防止衰减到 0 后根本接不上
per_hit_min_stun  = 0.20
separate_air_timer = true
```

⚠ **空中 / 地面两套衰减计时器必须独立。**
落地瞬间若不清零或暂停，空中连段落地后会自动变成地面长连段。

⚠ **暴击 / 终结技要有"豁免衰减"通道**（`ignore_decay = true`）。
有真实事故：暴击的设计价值是"打断敌人动作"，但它走了同一条衰减链路，
结果连段越深暴击越打不出硬直——**暴击的战略意义被自己的衰减系统吃掉**。
衰减必须可标注开关，⛔ 不能全局写死在计时器里的除法。

### 8.2 霸体 / 韧性：延迟硬直，不是消灭硬直

⚠ **霸体的本质是"这段时间被打不进入硬直"，不是减伤。**
期间**仍然掉血、仍然吃状态效果**。
⛔ 霸体与减伤混在一起，会让玩家无法从"我被打出硬直"
推断"我该堆韧性还是堆护甲"。

⚠ **正确语义是"延迟结算"：受击时先累计，霸体窗口结束再统一判定。**

```gdscript
func on_hit(ctx) -> int:
    if not is_active: return PASS_THROUGH       # 交给正常硬直结算
    absorbed = ctx.poise_damage * (1 - ctx.attacker.poise_armor_pierce)
    poise_damage_received += max(0, absorbed)
    ctx.damage.apply()                          # ⚠ 伤害照算，不减伤
    if ctx.ignore_poise: return BREAK_IMMEDIATELY        # 抓取、特定状态异常
    if poise_health - poise_damage_received <= 0:
        return BREAK_IMMEDIATELY                # 窗口内提前击破
    return ABSORBED                             # 动画继续，不进硬直

func on_window_end() -> void:
    if poise_health - poise_damage_received <= 0:
        fsm.force_transition("Stagger", {broken = true})
    poise_damage_received = 0                   # ⚠ 重置累计，不是重置血量
```

这个模型同时解释三个现象：轻击可"蹭破韧"但不打断动画（累计未满）·
重击一击破韧（单发超阈值）· 霸体结束后若已被破立刻结算硬直。
⛔ 实现成"每帧重新判定是否进硬直"，会出现轻击一下把霸体打掉、
霸体状态却还挂着的逻辑错乱。

⚠ **韧性回复是"瞬时回满"而非"缓慢回血"** ——
避免战斗中出现模糊的半恢复态。两个可抄的细节：
上次受击后 **连续 X 秒未受击**才回满（这本身就构成战术节奏：
一直被打就一直破，拉开距离才能重整）；部分战技只回满到 80%。
若你的霸体是"按一个键就无敌"，那它不是霸体而是无敌帧，
应走单独的 i-frame 状态并单独限制次数与时长。

⚠ **霸体必须有代价，否则就是无脑站桩。** 代价至少含一项：
动作本身慢（长 startup/recovery 提供天然惩罚窗口）·
占用资源（架势条 / 专注值 / 耐力）·
有可视的硬直窗口（玩家能读出"他现在霸体"）·
附带可被抓取的弱点。

### 8.3 格挡 / 破防 / 招架：三个状态，一条时间线

⚠ **格挡与招架消耗的是不同资源，不能共用一个"防御条"。**
格挡消耗**耐力 / 架势条**（持续资源，松开即停止消耗、空闲即回复）；
招架消耗的是**时间窗口**（不可再生，按次判定、失败进惩罚恢复）。
招架的收益不是"不掉血"，而是**把伤害转化为对方的破防进度**。

⚠ **破防后的窗口必须给攻击方明确收益，否则破防系统不成立。**
可量化约束：破防窗口应足够让**一次**完整攻击落地，
但不足以让**两次**落地；破防期间目标不可格挡、不可招架、
**但仍可移动**（让攻击方必须追上去，而不是白送命中）；
结束时给短暂的"恢复起身"动作而非瞬切回 Idle，作为可被打断的过渡。

⚠ **格挡与招架的判定路径必须分叉，招架先于伤害结算。**

```gdscript
func on_hitbox_overlap() -> int:
    if defender.is_dead(): return IGNORED
    if defender.has_iframes(): return IGNORED
    if attack.is_dodged(): return DODGED
    match defender.query_defense(this_frame).kind:
        PARRY_ATTEMPT:
            if attack.tag in parry.cannot_parry: goto BLOCK_OR_HIT
            if not parry.in_window(this_frame):   goto BLOCK_OR_HIT
            damage.cancel()          # ⚠ 在伤害结算之前 return
            attacker.apply_poise_damage(parry.poise_damage)
            camera.freeze_frame(0.05)
            return PARRIED
        BLOCK:
            damage.scale(block_multiplier)
            guard.drain(attack.guard_pressure)
            if guard.is_depleted(): defender.transition("GuardBroken")
            else:                    defender.transition("BlockStun")
            return BLOCKED
        _:
            apply_damage_and_stagger(); return HIT
```

⚠ 最容易错的是把"招架成功"写成 `damage.apply()` 之后的回调——
那时伤害已扣、韧性已扣、硬直已进，再撤销就是一堆 flag 互相抵消。
**招架是命中管线的分支，不是伤害的修正。**

⚠ **招架不能是概率触发。** "按对了但有 30% 失败" →
玩家无法判断是自己按错了还是系统判定错了；
"按早了也有机会成功" → 玩家会一直按住招架键，结果就是无脑站桩。
可靠性必须由**时间窗口**决定。概率最多出现在"招架成功后的收益大小"上，
⛔ 绝不能出现在"是否招架成功"上。

⚠ **招架失败必须有真实代价**（较长的招架恢复状态 / 承受全额伤害），
否则它是无风险选项。`fail_recovery` 要显式配表，
⛔ 不能让状态机自然回落到 Idle。

⚠ **招架窗口的起止用攻击方的当前帧索引定位**（招架发生在 active 期间），
这样窗口可随不同攻击独立配置（如某 Boss 红光技的窗口比普攻更宽松），
也便于训练模式可视化。

### 8.4 处决：状态切换的"事务"，不是一段动画

⚠ **触发条件要有固定优先级，不是"血量低就触发"。**
推荐 `背后未警觉 > 破防 > 血量阈值`。
血量阈值是**最弱**的条件——它只在对方已残血时才触发，
玩家会觉得"处决是奖励而不是技巧"。
更推荐让处决成为**攻击方通过破防 / 潜行主动制造出来的权利**。

⚠ **处决期间攻击者无敌、目标不可打断——这不是便利而是必需。**
处决动画期间攻击方不能闪避、不能取消，若同时可被任何攻击打断，
那处决就是**自伤动作**；目标若能在动画途中恢复行动，破防窗口就没有意义。

⚠ "不可打断"只覆盖**伤害与状态切换**，
不应阻止玩家主动取消（留出手动跳过处决的口子）。
目标侧的 `BeingExecuted` 也不应禁止 AI 思考——
AI 仍可播动画与音效，只是不能切换行动状态。

⚠ **多人游戏的处决必须短或允许被打断取消** ——
一段 4~6 秒的处决在多人里就是 4~6 秒的锁。
单人可以更长更华丽。
⚠ 镜头切换要带插值（0.2~0.5 秒），硬切会晕眩；
处决期间粒子与屏幕特效应**降配**（焦点在镜头动画上，多余打击感反而干扰可读性）。

### 8.5 部位破坏：独立实体 + 独立状态 + 独立 hitbox

⚠ **部位的核心是可被单独命中的实体，不是"伤害结算里加个 flag"。**
部位有自己的 HP 条，**与本体 HP 分离**；
"对部位的累积伤害"不影响对本体伤害（这是两个管线）。

```gdscript
class_name PartDefinition extends Resource
@export var part_id: StringName
@export var hp: float                  # 部位独立血量
@export var parent_bone: StringName    # 挂接骨骼，跟随动画
@export var break_threshold: float
@export var drop_table: Array[DropEntry]
@export var broken_mesh: PackedScene
@export var residual_fx: PackedScene
@export var ai_flags_on_break: PartAIFlags
@export var damage_multiplier_from_broken_part: float
```

**hitbox 三层**：① 整体 body hurtbox（吃任何攻击、进硬直）
② 装备/部件 hurtbox（盾牌吃攻击、触发格挡）
③ 部位 hitbox（尾巴/角/翅膀，可破坏）。
单次攻击与所有层级求交，结果按优先级归一到**一个** AttackContext
（"打到尾巴"优先于"打到身体"），再由它携带 `hit_part_id` 进双管线。

⚠ **部位破坏必须反向影响 AI，否则它只是一套美术。**
`ai_flags_on_break` 可关闭某种攻击（"断尾后不能再甩尾"）、降抗性、解锁破绽动作。
✅ 实现上让 `PartComponent` 在破坏时发 `part_broken(part_id, flags)` 信号，
AI 行为树监听并切分支 —— **部位系统与 AI 解耦，新增部位不必改 AI 代码**。
⛔ 不要让 AI 脚本直接读 `part.hp`。

⚠ 破坏表现是**三件事的组合**，不是"换模型"：
掉落物（可拾取实体，带独立物理）+ 模型切换（含残端网格）+ 残留表现（粒子/音效/震屏）。
⚠ 残留表现要与"本体是否还活着"解耦——怪物死后部位状态应保留，避免复活或重置时跳变。
⚠ 断尾这类可拾取部位还要考虑**同一场战斗中只能断一次**的唯一性约束。

### 8.6 连招与取消：窗口是区间，表是配置

⚠ **取消窗口是攻击时间轴上的一段区间，不是一个布尔。**
两类手感要分开：
- **缓冲取消**（BUFFER）：允许提前输入，系统在该帧生效
- **瞬时取消**（INSTANT）：要求输入恰好落在窗口内

```gdscript
class_name CancelEntry extends Resource
@export var from_state: StringName
@export var to_state: StringName
@export var condition: int          # ON_HIT / ON_BLOCK / ON_WHIFF / ALWAYS
@export var cancel_type: int        # BUFFER / INSTANT
@export var window_start: float     # 帧（相对攻击动画）
@export var window_end: float
@export var priority: int
```

⚠ **取消表必须显式配置，不能靠"动画播完自动连"或硬编码 input 字符串。**
理由：招式间的合法派生是**设计内容**，不该散落在状态脚本里；
不同武器应有各自的取消表，换武器只换数据；便于策划在编辑器里调窗口而不动代码。

⚠ **优先级表解决"同一帧多个合法输入"的二义性。**
推荐默认：防御类 > 位移类 > 攻击派生 > 移动取消
（想让攻击手感更连贯就把攻击派生提到位移类之上）。
⚠ 关键是写成**常量数组**，⛔ 不是一堆 if-else 的书写顺序。

⚠ **`InputBuffer` 应全局唯一**（由战斗输入层写入、各状态读取并消费），
⛔ 不是每个状态各存一份。每个动作只记最近一次有效输入、触发后消耗、过期清除。
窗口过短玩家觉得"吃键"，过长导致误触排队。

### 8.7 Godot 实现：两棵树、一份数据、一个权威源

⚠ **不要做成扁平大列表（每个状态一个节点），要拆成两层：**

```
CharacterBody3D
├── ActionStateMachine        # 主动行为层：Idle/Attack/Dodge/Block + ComboResolver
├── StaggerStateMachine       # 被动失衡层（独立树、独立 tick）
│   ├── Healthy / Hitstun / Blockstun / GuardBroken
│   └── ParryReact / ParryFailRecover / Execution / BeingExecuted
├── StatsComponent            # HP / Poise / Guard（纯数据）
├── InputBufferComponent
└── HitboxRoot / HurtboxRoot (+ 各部位 PartComponent)
```

⚠ **为什么两层**：主动层与被动层的切换规则、计时器、可被谁打断都不同。
合成一棵大树，`Attack → Hitstun → Attack` 会被写成一堆散边，
**无法表达"霸体期间受击不切换"**。
两层之间用 `StaggerLayer.immunity_level` 决定 ActionLayer 是否响应 interrupt，
比在 ActionLayer 里写 `if has_super_armor` 干净得多。

| 配置资源 | 持有方 | 关键字段 |
|---|---|---|
| `AttackFrameData` | 攻击方 | startup/active/recovery、base_hitstun、poise_damage、parry_window、cancel_table |
| `HitstunDecayTable` | 受击方/全局 | 按 elapsed 的 factor 阶梯、floor |
| `PoiseProfile` | 受击方 | base/max、recover_delay、技能后回满比例 |
| `GuardProfile` / `ParryProfile` | 受击方 | 资源条 / 窗口与惩罚 |
| `CancelTable` | 每个攻击或武器 | CancelEntry 数组 |
| `PartDefinition` | 部位节点 | 独立 HP、hitbox、破坏表现、AI 标记 |

⚠ **Godot 加载同一资源路径只返回同一份实例，场景实例间共享。**
运行时要改部位 HP、韧性值等状态，必须 `duplicate()` 或改用 Node 上的运行时字段，
⛔ 否则改一处会影响所有实例。（与 `economy.md` 的"共享 Resource 不能改"是同一条。）

⚠ **攻防双方靠事件与 AttackContext 解耦，不靠互相持引用。**
攻击方不调 `enemy.enter_hitstun()`，而是发 `hit_landed(ctx)`；
受击方监听并由自己的 StaggerLayer 决定是否进硬直。
"是否招架成功 / 是否破防"通过 AttackContext 的**返回码**回流给攻击方，
以推进连段与节奏。

**服务端权威清单（无例外）：**

| 判定 | 权威方 | 理由 |
|---|---|---|
| 命中判定 | 服务端 | 决定伤害与硬直，经济核心 |
| 硬直时长与 combo scaling | 服务端 | ⛔ 防无限连的数值不能被客户端改 |
| 韧性扣减与破韧 | 服务端 | 决定"霸体被打断"这一行动权 |
| 格挡 / 招架判定 | 服务端 | 窗口与结果不得由客户端自决 |
| 破防状态与处决所有权 | 服务端 | 处决是独占事件，防双端同时触发 |
| 部位 HP 与破坏状态 | 服务端 | 掉落归属与 AI 分支都由它驱动 |
| 取消表解析结果 | 服务端 | ⛔ 防客户端自造连招 |
| 位置 / 朝向 / 动画播放位置 | 客户端预测 + 服务端校正 | 高频，可插值 |
| hitstop / 震屏 / 音效 | 客户端本地 | 纯表现 |

⚠ **服务端权威下的招架手感必须用客户端预测补。**
客户端按下招架键立刻进 `Parrying` 并播动画，同时把
"输入时间戳 + 攻击帧索引"用 `any_peer` RPC 发给服务端；
服务端用自己的模拟时钟判定，回结果事件；未命中则客户端回滚到失败惩罚状态。
⛔ **若等服务端确认才表现招架，60ms 延迟就足以让一个短窗口完全不可用。**

## 9. 网络战斗（方向，不展开）

- 客户端预测 + 服务器权威
- **命中判定的权威归属**：作弊敏感的项目服务端判定，
  手感优先的项目客户端判定 + 服务端校验
- 延迟补偿（rewind）：服务端回滚到玩家看到的位置再判
- 详细见 `multiplayer.md` 与 `netsync-advanced.md`



## 10. 相关文档

- 输入 → `input-audio.md`
- 部位破坏与掉落表 → `economy.md`
- 时间与 hitstop → `timescale.md`、\`vfx-feel.md\`
- 动画与帧事件 → `animation.md` / `animation-advanced.md`
- 屏震与相机 → `camera-cutscene.md`
- AI 行为 → `ai-behavior.md`
- 网络同步 → `multiplayer.md`
- 性能（大量单位）→ `performance.md`

> **反模式清单（不能怎么做，审核用）** → `audit/godot/combat.md`
