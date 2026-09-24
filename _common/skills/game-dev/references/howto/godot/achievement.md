# 成就系统

> 上线必备，但很容易做一半就埋坑。本文讲**成就的定义、进度、解锁、奖励、展示、平台对接、历史回溯**。
> 流程层见 `flow/godot/achievement/`。
> 平台（Steam/Epic）能力本身见 `platform-services.md`。

## 0. 本域边界与四类成就

⚠ 先定性再做，否则"击杀 100"和"通关"会共用一套错误的结构。

| 类型 | 判定方式 | 进度字段 |
|---|---|---|
| 一次性 | 事件到达即达成 | `0 → 1` |
| 累计型 | 计数达到阈值 | `target_progress = N` |
| 条件型 | 单次事件带满足条件 | 无进度 |
| 复合型 | 多个子条件全部达成 | 每子条件独立进度 |

⛔ **复合型不要写成"每次事件全量重算所有子条件"** ——
事件高频时是 `O(子条件数 × 事件数)`，
且**子条件的中间态无处存放**（玩家满足了 A，三个月后满足 B，A 早忘了）。

## 1. 定义与状态分离

```gdscript
# achievement_definition.gd
class_name AchievementDefinition
extends Resource

@export var id: StringName = &""          # ⛔ 唯一稳定标识，绝不改名
@export var title: String = ""
@export var description: String = ""
@export var hidden: bool = false
@export var target_progress: int = 1
@export var platform_id: StringName = &""  # Steam/Epic 对应 ID
```

⛔ **定义（Resource）与运行时状态（存档）分开存** ——
否则策划改了 `target_progress`，旧存档会**带着旧目标值覆盖新定义**。

⚠ **`id` 必须是稳定标识** ——
用显示名或数组索引当 key 的话，
改名或重排后存档对不上，**进度全丢且不报错**。

## 2. 进度模型与持久化

```gdscript
# achievement_state.gd —— 只存这个进存档
class_name AchievementState
extends Resource

@export var progress: int = 0        # 已达成量（累计，跨会话）
@export var unlocked: bool = false
@export var unlock_timestamp: int = 0
@export var sub_progress: Dictionary = {}   # 复合型：子条件进度
```

⛔ **进度必须是跨会话累计值，不能是"本次会话计数"** ——
会话计数在重开后清零，
表现为"杀了一万只也解锁不了"，而单次游玩内看不出问题。

⚠ **进度是派生值还是权威值要定死** ——
若从统计系统派生（`stats.total_kills`），
则成就侧不存进度、只在解锁时落 `unlocked`；
两套都存会出现"统计 100 但成就进度 87"的对不上。

## 3. 事件驱动检测

⛔ **不要轮询** ——
`_process` 里每帧遍历所有成就判条件，
成就多了直接掉帧，且**无法捕捉瞬时事件**（"单次伤害过万"）。

```gdscript
func _ready() -> void:
    GameEvents.enemy_killed.connect(_on_enemy_killed)

func _on_enemy_killed(_who: Node) -> void:
    _advance(&"kill_100", 1)
```

⚠ **事件参数要带够判条件的信息** ——
只发 `enemy_killed` 不带伤害值，
"单次伤害过万"这类成就就只能回头改事件签名。

## 4. 解锁事务与奖励幂等

⛔ **顺序必须是：判达成 → 标记 unlocked → 发奖励 → 弹通知**。

反过来（先弹通知再发奖励）在奖励发放失败时，
玩家**看到解锁但没拿到东西**；
而先发奖励再标记，重放事件会**重复发奖**。

⚠ **奖励发放必须幂等** ——
以 `id` 为键记录已发放，
重放同一事件只发一次。
这是可直接刷取的漏洞，而正常流程下表现完全正常。

⛔ **标记与发奖要一起落盘** ——
标记后异步发奖，崩溃时表现为"成就显示已解锁但奖励没了"。

## 5. 隐藏成就与展示

| 元素 | 隐藏成就是否展示 |
|---|---|
| 标题 | ✅ 展示 |
| 描述 | ⛔ 解锁前不展示 |
| 进度 | ✅ 展示（"???" 之外给个进度条） |
| 是否已解锁 | ✅ 必须展示 |

⛔ **连"是否已解锁"都隐藏** ——
玩家无法确认自己拿没拿到，
表现为"隐藏成就永远像是没解锁"。

⚠ 隐藏成就的描述**不能靠客户端不显示来保证** ——
数据里带着，改包就能看到。
真要保密就把描述放服务端下发。

## 6. 平台成就对接

⚠ **Godot 核心没有内置成就/排行榜能力** ——
需要插件（GodotSteam 等），
维护状态与版本兼容要现查（见 `platform-services.md`）。

⛔ **平台同步失败必须能重试** ——
网络抖动时同步失败，若不重试则**永久丢失**，
表现为"本地已解锁，平台永远差一个"，
而玩家会认为是游戏 bug。

⛔ **每日/每周重置类成就不用系统时间** ——
`Time` 的 `_from_system` 用**用户可手动设置**的时钟，
官方明确要求精确计时改用单调的 `get_ticks_msec()`，
完整说明见 `environment-systems.md#8`。

⚠ **本地与平台以谁为准要定死** ——
通常以本地为准向平台推送；
反之（以平台为准）在平台不可用时本地解锁会**被回滚**。

## 7. 新增成就的历史回溯

⛔ **新增累计型成就不做 backfill** ——
老玩家已经击杀 500 只，
但成就从"新增后才开始记"，
表现为"老号永远拿不到"，
而新号正常，排查时会误判成"存档损坏"。

⚠ backfill 的做法：上线时用**已有的统计值**初始化 `progress`，
而不是从零开始记。

⚠ 若统计值本身没历史（早期没埋点），
则只能按"达成过一次即视为达成"的宽松口径补，
并接受这部分是估算。

## 8. 相关文档

- 平台成就插件 → `platform-services.md`
- 统计系统（进度常派生自统计）→ `onboarding-meta.md#6`
- 奖励发放走的经济通道 → `economy.md`
- 审核侧 → `audit/godot/achievement.md`（25 条）
- 流程层 → `flow/godot/achievement/`
- 摘要版见 `onboarding-meta.md#4`
