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

## 8. 网络战斗（方向，不展开）

- 客户端预测 + 服务器权威
- **命中判定的权威归属**：作弊敏感的项目服务端判定，
  手感优先的项目客户端判定 + 服务端校验
- 延迟补偿（rewind）：服务端回滚到玩家看到的位置再判
- 详细见 `multiplayer.md` 与 `netsync-advanced.md`



## 9. 相关文档

- 输入 → `input-audio.md`
- 动画与帧事件 → `animation.md` / `animation-advanced.md`
- 屏震与相机 → `camera-cutscene.md`
- AI 行为 → `ai-behavior.md`
- 网络同步 → `multiplayer.md`
- 性能（大量单位）→ `performance.md`

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/combat.md`
