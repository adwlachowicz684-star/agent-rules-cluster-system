# 03 Idle 与状态转移（AI 域）

> **前置**：01 感知已接入，02 决策结构已定
> **本步交付**：Idle **不是空状态**，且所有转移集中在转移表里
> **对应**：做法 `howto/godot/ai-behavior.md` `ai-perception.md` · 审核 `audit/godot/ai-behavior.md`

## 0. 交付物定义

⚠ **待机是最容易被写成空状态的一个状态。**
写空之后两个后果：
- 单位看起来是**死的**（站着不动、不转头、无微小动作）
- 从 Idle 转出时**没有自然过渡**，表现为"突然弹起来追人"

⚠ 更隐蔽的一条：**感知写在 Chase 分支里**，
导致 Idle 时根本没在检测——表现为"背对玩家永远发现不了"，
排查时你会去调视野角度，**其实与角度无关**。

做完这一步，应该能**当场演示**：

1. 待机单位**有微动作**（转向/呼吸/环视），不是定格
2. ⚠ Idle 里**也在跑感知**
3. Idle ↔ Alert **不抖动**（有最短驻留）
4. 转移条件集中在一处，能一眼看全
5. 进入/退出钩子统一，⛔ 不散落

**产出物**（下游按名字对接）：

```text
_on_enter(state) / _on_exit(state)
转移表（当前态 × 条件 → 目标态）
MIN_IDLE_TIME 实测值
```

## 1. 前置检查清单

- [ ] 02 的状态枚举已定
- [ ] ⚠ 已确认 Idle 的三项职责（见 S1）
- [ ] 已确认感知**在 Idle 里也会跑**
- [ ] 已列出转移表

## 2. 工序

### Step 1　Idle 的三项职责　`[ai/03#S1]`

【读】`howto/godot/ai-behavior.md#5. Idle 不是"什么都不做"`

【做】✅ Idle 至少要负责三件事：

| 职责 | 说明 |
|---|---|
| **朝向** | 缓慢转向巡逻方向 / 最后已知方向 / 随机环视 |
| **微动作** | 呼吸、重心、偶尔的 idle 动画变体 |
| **退出条件** | 明确写出"满足什么就离开 Idle" |

⛔ 三项都缺的话，玩家对"这个怪是活的"的感知会明显下降。

【产出】Idle 实现了朝向 + 微动作 + 退出条件

【判据】⚠ 盯着待机敌人看 10 秒，**能观察到至少 2 次动作变化**

【审】`audit/godot/ai-behavior.md#11`
【品】`craft/godot/cheapness.md#1. 动效类廉价感`

### Step 2　⚠ Idle 里也要跑感知　`[ai/03#S2]`

【读】`howto/godot/ai-perception.md#0. 为什么感知要独立成层`

【做】⚠ 很多实现把感知写在 Chase 分支里，
结果"没发现玩家"是因为**根本没在检测**，而不是"检测了没看到"。

ⓘ 这正是 01 S1 "感知独立成层"的回报——
感知层独立后，Idle 只要照常调用它即可。

【产出】Idle 的 tick 里调用了感知

【判据】⚠ 从背后接近待机敌人，**进入视野后能被发现**

【审】`audit/godot/ai-perception.md#1`

### Step 3　最短驻留防抖动　`[ai/03#S3]`

【读】`howto/godot/ai-behavior.md#5. Idle 不是"什么都不做"`

【做】⚠ **Idle 的退出要有最短驻留**，
否则在阈值边界会 Idle ↔ Alert **每帧抖动**（表现为敌人原地抽搐）。

```gdscript
const MIN_IDLE_TIME := 0.4

func _tick_idle(delta: float) -> void:
    _idle_time += delta
    _scan()                       # ⚠ Idle 也要感知
    if _idle_time >= MIN_IDLE_TIME and _can_see_player():
        _set_state(State.CHASE)   # ⚠ 最短驻留后才允许转出
```

⚠ 同样的原则适用于**所有**状态（不只是 Idle）：
Chase ↔ Attack 在攻击距离边界也会抖。

【产出】每个状态都有最短驻留

【判据】⚠ 让敌人在阈值边界停留 10 秒，
　　　**状态切换次数 < 3**（⛔ 不是每帧切）

【审】`audit/godot/ai-behavior.md#13`

### Step 4　转移集中成表　`[ai/03#S4]`

【读】`howto/godot/ai-behavior.md#0. 先选对方案，别一上来就上行为树`

【做】⚠ 转移条件要**集中**，
⛔ 不要在每个状态的 `_process` 里各自判断转移——
那会让"哪些转移存在"无法一眼看全。

ⓘ 集中之后才能回答关键问题：
"DEAD 状态能被转移出来吗？""STAGGER 能直接进 ATTACK 吗？"

【产出】转移表（当前态 × 条件 → 目标态）

【判据】⚠ 指着转移表，**能回答任意两个状态间是否存在路径**

【审】`audit/godot/ai-behavior.md#12`

### Step 5　进入/退出钩子统一　`[ai/03#S5]`

【读】`howto/godot/ai-behavior.md#0. 先选对方案，别一上来就上行为树`

【做】⚠ 用统一的 `_on_enter` / `_on_exit`，
⛔ 不在散落各处写"开始时清一下、结束时停一下"。

ⓘ 散落的典型后果：从 Chase 被打断进 STAGGER 时，
忘记了停寻路 → 硬直中还在滑行。

【产出】所有进入/退出逻辑在钩子里

【判据】⚠ 从**任意**状态进入 STAGGER，表现一致（⛔ 不只是从 Chase 进）

【审】`audit/godot/ai-behavior.md#14`

### Step 6　死亡不是状态之一那么简单　`[ai/03#S6]`

【读】`howto/godot/ai-behavior.md#5. Idle 不是"什么都不做"`

【做】⚠ DEAD 要处理：停止所有 tick、释放令牌（见 05）、
释放预约的掩体（见 05）、从感知候选里移除。

⛔ 只把它当"一个不再转移的状态"，
会让死亡单位继续占用战术资源（这是"AI 集体发呆"的源头之一）。

【产出】DEAD 的清理清单已实现

【判据】⚠ 杀死一个正在攻击的敌人后，
　　　**其余敌人立即能补上攻击位**（⛔ 不是集体停下）

【审】`audit/godot/ai-behavior.md#15`

## 3. 参考实现

```gdscript
enum State { IDLE, PATROL, CHASE, ATTACK, STAGGER, DEAD }

const MIN_STATE_TIME := {
    State.IDLE:    0.4,
    State.CHASE:   0.3,
    State.ATTACK:  0.0,     # 攻击由动画长度决定，不额外限制
}

var _state := State.IDLE
var _state_time := 0.0

func _change_state(to: State) -> void:
    if _state == to:
        return
    _on_exit(_state)
    _state = to
    _state_time = 0.0
    _on_enter(to)

func _can_leave() -> bool:
    return _state_time >= MIN_STATE_TIME.get(_state, 0.0)   # ⚠ 最短驻留

func _on_exit(s: State) -> void:
    match s:
        State.CHASE:
            _agent.clear_target()      # ⚠ 退出时清，⛔ 不靠进入新状态时覆盖
        State.ATTACK:
            _tokens.release(self)      # ⚠ 任何路径离开攻击都释放
```

⚠ 注意 `_on_exit(ATTACK)` 里释放令牌——
⛔ 只在"攻击动画正常结束"时释放，被打断就会泄漏（见 05）。

## 4. 验收清单

- [ ] 待机有微动作，10 秒内至少 2 次变化
- [ ] Idle 里在跑感知（背后接近能被发现）
- [ ] 每个状态有最短驻留，边界不抖动
- [ ] 转移集中成表，能回答任意两态间路径
- [ ] 进入/退出钩子统一，任意态进 STAGGER 表现一致
- [ ] DEAD 释放了令牌与掩体预约

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 敌人像雕塑 | Idle 是空状态 | S1 |
| 背对永远发现不了 | 感知没在 Idle 跑 | S2 |
| 敌人在原地抽搐 | 无最短驻留 | S3 |
| 说不清有哪些转移 | 转移散落各处 | S4 |
| 硬直中还在滑行 | 退出时没停寻路 | S5 |
| 杀一个怪后集体发呆 | DEAD 没释放令牌 | S6 |

## 6. 下一步

→ **04 目标选择与仇恨**（多目标）
→ **05 阵型 / 掩体 / 协同**（有小队）

## 7　整体审核（功能点级收尾）

ⓘ 各 Step 的【审】是**步骤级即时检查**；本节是**功能点级复查**，两级都要走。

- [ ] 逐条过 `audit/godot/ai-behavior.md`，每条说出"我们是怎么避免的"
  - ⛔ 不能"应该没这个问题"
- [ ] 步骤级【审】列过的条目**再过一遍**
- [ ] ⚠ 实测参数已回填，⛔ 不留示例值
- [ ] 若属大功能 → ⚠ **还要集成验收**：各部件合格 ≠ 拼起来能用
