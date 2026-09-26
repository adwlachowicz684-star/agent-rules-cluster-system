# 01 射击模型与 FireContext（枪械 / 射击系统域）

> **本步交付**：射击模型定性 + 单一事实源 FireContext + 武器状态机
> **对应**：流程 `howto/godot/firearms.md` · 审核 `audit/godot/firearms.md`

## 0. 交付物定义

1. 已定性本次是 **hitscan** 还是 **projectile**（依据是手感，不是技术优劣）
2. 所有射击参数从**同一份 FireContext** 派生，不存在散落的独立字段
3. 有明确的武器状态机，开火 / 换弹 / 切换各有独立门限

## 1. 前置检查清单

- [ ] 已定性射击模型（hitscan / projectile）
- [ ] ⚠ 已确认"参数来源是 FireContext 而非各写各的"
- [ ] 有一把能开火的最小武器可测

## 2. 工序

### Step 1　按手感定性射击模型　`[firearms/01#S1]`

【读】`howto/godot/firearms.md#1. hitscan 与 projectile：选择依据是手感，不是优劣`

【做】
判定依据写清：玩家**需不需要感知弹丸飞行**。
⛔ 拿 hitscan 和 projectile 比技术优劣 —— 那是两个不同的手感取向，不是高低之分。

【产出】一句话模型定性 + 选择理由（写清"玩家要不要看到弹丸"）

【判据】能说出"选它是因为玩家需要/不需要看到弹丸飞行"，而不是"它更准/更真实"。

【审】`audit/godot/firearms.md#4`

### Step 2　建 FireContext 作为唯一事实源　`[firearms/01#S2]`

【读】`howto/godot/firearms.md#0. FireContext：所有射击参数从同一份状态派生`

【做】
所有射击参数（射速 / 伤害 / 扩散 / 后坐力 / 弹速）从同一份 `FireContext` 派生。
⛔ 动画通知里写 `current_ammo` —— 换弹取消、快速切换、预测回滚会**失去唯一事实源**。

【产出】`FireContext` 数据结构 + 派生函数

【判据】改一个参数，所有用到它的地方同步变化；不存在"改了这里那里没变"。

【审】`audit/godot/firearms.md#1`

### Step 3　参数全部走派生，不留独立字段　`[firearms/01#S3]`

【读】`howto/godot/firearms.md#0. FireContext：所有射击参数从同一份状态派生`

【做】
扩散、后坐力、伤害都从 FireContext 算出来。
⛔ 在武器脚本里另存一份 `damage` —— 加成系统一来就对不上。

【产出】派生函数清单（输入 FireContext，输出各参数）

【判据】给武器加一个 buff，全部派生参数随之变化，没有遗漏项。

【审】`audit/godot/firearms.md#64`

### Step 4　输入用 BufferedAction，不只在按下瞬间消费　`[firearms/01#S4]`

【读】`howto/godot/firearms.md#5. 换弹：逻辑门限 / 动画 / 可取消窗口 三件事分开`

【做】
开火请求进缓冲区，状态机就绪时消费。
⛔ 输入只在按下瞬间消费 —— 连按两次只开一枪，玩家感觉"吞输入"。

【产出】`BufferedAction` + 消费时机（状态机 READY）

【判据】连按两次开火键，射出两发（受射速限制而非被吞掉）。

【审】`audit/godot/firearms.md#3`
【品】`craft/godot/feel-params.md#6. 输入到画面的延迟预算`

### Step 5　武器状态机：开火 / 换弹 / 切换各有门限　`[firearms/01#S5]`

【读】`howto/godot/firearms.md#5. 换弹：逻辑门限 / 动画 / 可取消窗口 三件事分开`

【做】
状态机至少含 `READY / FIRING / RELOADING / SWAPPING`。
⛔ 开火能在换弹任意阶段打断 —— "换弹不能开火"的窗口被废掉。

【产出】状态机定义 + 各状态允许的动作表

【判据】在 RELOADING 中按开火，不会提前射出。

【审】`audit/godot/firearms.md#29`

## 3. 参考实现

```gdscript
# ⓘ 承接 Step 2/3：FireContext 是唯一事实源，以下字段全部从它派生
class_name FireContext extends Resource

@export var fire_rate := 600.0        # 发/分
@export var base_damage := 25.0
@export var spread_base := 0.6        # 度
@export var recoil_pattern: PackedVector2Array
@export var projectile_speed := 0.0   # 0 = hitscan

func damage_at(_dist: float) -> float:
    return base_damage

# 状态机：开火/换弹/切换各有独立门限
enum S READY, FIRING, RELOADING, SWAPPING

```

## 4. 验收清单

- [ ] 射击模型已按手感定性（不是按技术优劣）
- [ ] 所有参数从 FireContext 派生
- [ ] 输入进缓冲，不被吞
- [ ] 状态机各状态门限明确
- [ ] 加一个 buff 能验证派生链路完整

## 5. 常见返工

| 症状 | 回到 |
|---|---|
| 加成系统改了伤害，扩散没跟着变 | S3 |
| 玩家抱怨"吞输入" | S4 |
| 换弹中能开火 | S5 |

## 6. 下一步

→ [`02-命中判定与统一命中源.md`](02-命中判定与统一命中源.md)

## 7　整体审核（功能点级收尾）

ⓘ 各 Step 的【审】是**步骤级即时检查**；本节是**功能点级复查**，两级都要走。

- [ ] 逐条过 `audit/godot/firearms.md` 的**全部条目**，每条说出"我们是怎么避免的"
  - ⛔ 不能"应该没这个问题"
- [ ] 步骤级【审】列过的条目**再过一遍**（做完再看的视角不同）
- [ ] ⚠ 参数派生链路已完整，⛔ 不留"改了这里那里没变"的字段
