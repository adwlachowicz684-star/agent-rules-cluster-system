# 04 Buff 与状态（战斗结算域）

> **前置**：02 伤害结算已能读 `stats.get_modifiers(tag)`（本步实现它）
> **本步交付**：状态是**纯数据**，叠加规则明确，DoT 独立 tick，表现由监听者负责
> **对应**：做法 `howto/godot/combat.md` · 审核 `audit/godot/combat.md`

## 0. 交付物定义

做完这一步，应该能**当场演示**：

1. 给角色加一个 +50% 攻击的 buff，伤害按乘区规则变化
2. 中毒 3 层，每层独立计时，到期各自移除
3. 移除 buff 时，**没有残留特效**（因为状态本身从不播特效）
4. ⚠ 帧率从 30 到 240，DoT 的总伤害完全一致

**产出物**（下游按名字对接）：

```text
StatusEffect (Resource)   纯数据：tag / 数值 / 时长 / 叠加规则 / 是否 percent
StatusContainer           挂在角色上，持有并结算所有状态
stats.get_modifiers(tag) -> Array[Modifier]   供 02 调用
status_changed 信号        供表现层订阅
```

## 1. 前置检查清单

- [ ] 02 的 `DamageFormula` 已经调用 `get_modifiers()`（哪怕是空实现）
- [ ] ⚠ 已确认**四种叠加规则只能选一种**并写进设计
- [ ] 已确认 DoT 用固定 tick，⛔ 不挂 `_process`
- [ ] ⛔ 已确认状态类里**没有任何**特效/音效代码

## 2. 工序

### Step 1　定死叠加规则（四选一）　`[combat/04#S1]`

【读】`howto/godot/combat.md#5. Buff / Debuff：状态是数据，反馈由监听者负责`

【做】四种只能选一种，⚠ **在设计阶段定死**：

| 规则 | 行为 |
|---|---|
| 覆盖 | 新的替换旧的 |
| 叠加 | 同类效果数值相加 |
| 刷新 | 不叠加，只刷新持续时间 |
| 独立层数 | 每层独立计时（如中毒 5 层） |

⚠ "中毒"这类通常要**独立层数**，而"攻击力提升"通常是**覆盖**或**刷新**。
⛔ 用错规则会出现"喝 5 瓶药水叠成 5 倍"或"叠了但只算一层"两种相反 bug。

【产出】每种状态在 `StatusEffect` 里显式标注 `stack_rule`

【判据】⚠ 连喝 3 瓶同种药水，结果符合所选规则（是 3 层，不是 1 层也不是 3 倍）

【审】`audit/godot/combat.md#7`（flat 与 percent 要分顺序）

### Step 2　修改器顺序：先加后乘　`[combat/04#S2]`

【读】`howto/godot/combat.md#5. Buff / Debuff` 的修改器结算顺序

【做】
```text
最终值 = (基础 + flat 加成) × (1 + percent 加成)
```

⚠ 混在一起算会导致"两个 +50% 的 buff 叠成 +125%"这类意外。

【产出】`get_modifiers()` 返回的列表，被 02 按先 flat 后 percent 消费

【判据】两个 +50% percent → ×2.0，⛔ 不是 ×2.25

【审】`audit/godot/combat.md#7`

### Step 3　DoT / HoT 独立计时　`[combat/04#S3]`

【读】`howto/godot/combat.md#5. Buff / Debuff` 的 DoT ⚠ 提示

【做】DoT/HoT ⛔ **不要挂在 `_process` 里每帧扣血**（帧率不同结果不同）。
用**固定间隔 tick**。

【产出】一个固定 tick 的 DoT 计时器（如每 0.5 秒跳一次）

【判据】⚠ **帧率 30 与 240 下，10 秒 DoT 的总伤害完全一致**
（每帧扣血的做法在这里会明显不一致）

【审】`audit/godot/combat.md#8`（DoT 每帧扣血 → 帧率影响结果，要固定 tick）

### Step 4　状态不播特效　`[combat/04#S4]`

【读】`howto/godot/combat.md#5. Buff / Debuff` 的 ⚠ 提示

【做】状态是**数据**，由监听者负责表现。
⛔ 状态类里不出现 `particles`、`audio`、`tween` 任何一样。

【产出】移除 buff 时不需要"记得清理特效"——因为从没创建过

【判据】⚠ **加一个只打印日志的监听者**，验证"施加/移除"都能收到信号；
然后移除状态，确认没有任何残留节点

【审】`audit/godot/combat.md#9`（buff 自己播特效 → 移除时容易残留）

### Step 5　技能做成 Resource　`[combat/04#S5]`

【读】`howto/godot/combat.md#6. 技能系统：Resource 装数据，Node 执行`

【做】分离：
```
StatusEffect / SkillData (Resource)   纯数据
SkillExecutor (Node)                  执行
场景树                                只负责表现
```

⚠ 这是 Godot 的强项——策划在 Inspector 里配，⛔ 不用改代码。

【产出】新建一个状态不需要写新类，只需新建 Resource 实例

【判据】⚠ 让策划（或你自己）**只通过 Inspector** 加一个新 buff，全程不改代码

【审】`audit/godot/combat.md#10`（技能写死在代码里 → Resource 数据驱动）

## 3. 参考实现

```gdscript
# status_effect.gd —— ⚠ 纯数据，不含任何表现
class_name StatusEffect
extends Resource

enum StackRule { OVERRIDE, ADD, REFRESH, INDEPENDENT }
enum ModifierKind { FLAT, PERCENT }

@export var id: StringName
@export var tag: StringName = &"physical"
@export var kind: ModifierKind = ModifierKind.PERCENT
@export var value: float = 0.0
@export var duration: float = 5.0
@export var stack_rule: StackRule = StackRule.OVERRIDE
@export var tick_interval: float = 0.0      # >0 表示是 DoT/HoT
@export var tick_amount: float = 0.0

# status_container.gd
extends Node
class_name StatusContainer

signal status_changed(effect_id, applied)

var _active: Array[StatusEffect] = []
var _tick_accum: Dictionary = {}

func get_modifiers(tag: StringName) -> Array:
    var out := []
    for e in _active:
        if e.tag == tag:
            out.append({"is_percent": e.kind == StatusEffect.ModifierKind.PERCENT,
                        "value": e.value})
    return out

func _physics_process(delta: float) -> void:
    # ⚠ DoT 用固定步长累加，⛔ 不是每帧扣血
    for e in _active:
        if e.tick_interval <= 0.0: continue
        var acc: float = _tick_accum.get(e.id, 0.0) + delta
        while acc >= e.tick_interval:
            acc -= e.tick_interval
            owner.stats.hp -= e.tick_amount      # 固定间隔跳一次
        _tick_accum[e.id] = acc
```

⚠ `_physics_process` 里用 `while` 而不是 `if`——
掉帧时（delta 大）要补跳，否则低帧机器 DoT 变慢。

## 4. 验收清单

- [ ] 每种状态显式标注叠加规则，连喝 3 瓶结果符合预期
- [ ] 两个 +50% percent → ×2.0（不是 2.25）
- [ ] DoT 在帧率 30 / 240 下总伤害一致
- [ ] 状态类里没有任何特效/音效代码
- [ ] 移除状态无残留节点
- [ ] 只通过 Inspector 能加一个新 buff（不改代码）

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 喝药叠成几倍 | 叠加规则选错 | S1 |
| 两个 +50% 变 2.25 倍 | percent 连乘 | S2 |
| 低帧机器上 DoT 变慢 | 每帧扣血 / 用 if 不用 while | S3 |
| 移除 buff 后特效还在 | 状态自己播了特效 | S4 |
| 加个 buff 要写新类 | 没做成 Resource | S5 |

## 6. 下一步

→ **05 打击感反馈**
→ **06 对抗层**（硬直/霸体也都是状态，本步的容器可直接复用）

## 7　整体审核（功能点级收尾）

ⓘ 各 Step 的【审】是**步骤级即时检查**；本节是**功能点级复查**，两级都要走。

- [ ] 逐条过 `audit/godot/combat.md`，每条说出"我们是怎么避免的"
  - ⛔ 不能"应该没这个问题"
- [ ] 步骤级【审】列过的条目**再过一遍**（做完再看的视角不同）
- [ ] ⚠ 实测参数已回填，⛔ 不留示例值
- [ ] 若属大功能 → ⚠ **还要集成验收**：各部件合格 ≠ 拼起来能用
