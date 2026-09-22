# Godot 4.x AI 决策：FSM / 行为树 / GOAP / 效用函数

## 0. 先选对方案，别一上来就上行为树

**BT 不是 FSM 的升级版，是维护对象不同。**

| 方案 | 最适合 | 不适合 | 主要成本 |
|---|---|---|---|
| 枚举 FSM | 3–8 个互斥状态、动画驱动 | 共享行为多、跨对象复用 | 状态一多，转移爆炸 |
| 分层/并行状态机 | 玩家、载具模式、明确阶段 | 复杂反应性条件 | 历史栈、转换守卫复杂 |
| **行为树** | 共享子行为、可视调试、可中断任务 | 简单状态机可解决的东西 | 黑板、tick、自定义 Task 维护 |
| GOAP | 多目标、多动作、动态世界 | 目标固定的 Boss 套路 | 规划器、状态同步、调试 |
| 效用/权重 | 多选项、偏好型 AI | 强顺序、硬条件、严格战术 | 数值敏感、难以审查 |

**一个近战小怪通常只有 Idle / Patrol / Chase / Attack / Stagger / Dead。**
这些状态互斥，转移由玩家距离、血量、受击触发 —— 用 `match state` 最清楚。
拆成行为树只会得到"条件链 + 顺序节点"的扁平树，**读起来比 match 更长**。

**BT 开始变现的信号**：
- 一棵子树能被巡逻、Boss 阶段、炮台、NPC 任务**共同复用**
- 策划需要**反复调整优先级**而不碰代码

工程上常见的是「**外层效用/GOAP 选目标，内层 BT 执行动作**」。

### 三类典型的过度设计

1. 只有一个根 Selector 和线性 Sequence —— 本质是 `if/elif/else`
2. 为每个敌人复制整棵树 —— 节点数增长但没复用，不如继承组件
3. 把寻路、动画状态机、伤害结算全塞进 Task —— 树变成大型回调壳

**判断标准**：如果策划从没改过树，树也从没被复用，
只是 AI 程序员独自维护 —— **FSM 或组合式组件通常更快**。

## 1. 节点返回值不是"成功/失败"两个布尔

```
SUCCESS   完成
FAILURE   合法路径信息，不是错误
RUNNING   当前 tick 无法完成，父节点下次 tick 继续交给同一节点
```

⚠ **FAILURE 是正常路径**。"目标不在视野"失败，让 Selector 尝试下一分支。

⚠ **忘记返回 RUNNING** → 播放动画、寻路、计时器会**每帧从头执行**。

⚠ **RUNNING 没有 abort 机制** → 低优先级长任务永远阻塞高优先级反应
（比如正在巡逻时被攻击却不能打断）。

⚠ **FAILURE 不要用 `push_error`** —— FAILURE 每 tick 都可能发生，
刷屏会把真正的错误**淹没在噪音里**。
⛔ 用 `push_error` 表达"没找到目标"，日志里全是红色，出真故障时就找不到了。

ⓘ 判据：这条失败**需要人去修吗**？需要 → `push_error`；
不需要（只是本次路径不通）→ 静默返回 FAILURE，最多 `print_verbose`。

## 2. 不依赖插件的最小行为树

```gdscript
# bt_node.gd —— 所有节点基类
class_name BTNode
extends RefCounted

enum Status { SUCCESS, FAILURE, RUNNING }

func tick(_ctx: Dictionary) -> int:
    return Status.FAILURE
```

```gdscript
# 组合节点
class_name BTComposite
extends BTNode

var children: Array[BTNode] = []

func add(child: BTNode) -> BTComposite:
    children.push_back(child)
    return self
```

```gdscript
# Selector：依次尝试，第一个非 FAILURE 就返回（优先级）
class_name BTSelector
extends BTComposite

func tick(ctx: Dictionary) -> int:
    for c in children:
        var s := c.tick(ctx)
        if s != Status.FAILURE:
            return s
    return Status.FAILURE
```

```gdscript
# Sequence：依次执行，第一个非 SUCCESS 就返回（并且）
class_name BTSequence
extends BTComposite

func tick(ctx: Dictionary) -> int:
    for c in children:
        var s := c.tick(ctx)
        if s != Status.SUCCESS:
            return s
    return Status.SUCCESS
```

```gdscript
# Inverter：反转结果
class_name BTInverter
extends BTComposite

func tick(ctx: Dictionary) -> int:
    if children.is_empty():
        return Status.FAILURE
    var s := children[0].tick(ctx)
    if s == Status.SUCCESS:
        return Status.FAILURE
    if s == Status.FAILURE:
        return Status.SUCCESS
    return Status.RUNNING
```

```gdscript
# 条件节点：用 Callable 包一个判定
class_name BTCondition
extends BTNode

var _fn: Callable

func _init(fn: Callable) -> void:
    _fn = fn

func tick(ctx: Dictionary) -> int:
    return Status.SUCCESS if _fn.call(ctx) else Status.FAILURE
```

```gdscript
# 动作节点：用 Callable 包一个行为，返回状态
class_name BTAction
extends BTNode

var _fn: Callable

func _init(fn: Callable) -> void:
    _fn = fn

func tick(ctx: Dictionary) -> int:
    return int(_fn.call(ctx))
```

### 用法示例

```gdscript
extends CharacterBody2D

var _tree: BTNode

func _ready() -> void:
    var ctx := {"self": self}
    _tree = BTSelector.new().add(
        # 1) 血低就逃
        BTSequence.new()
            .add(BTCondition.new(func(c): return c.self.hp < 30))
            .add(BTAction.new(func(c): return _flee(c)))
    ).add(
        # 2) 看到玩家就追击
        BTSequence.new()
            .add(BTCondition.new(func(c): return c.self._can_see_player()))
            .add(BTAction.new(func(c): return _chase(c)))
    ).add(
        # 3) 否则巡逻（永远 SUCCESS，兜底）
        BTAction.new(func(c): return _patrol(c))
    )

func _process(_d: float) -> void:
    _tree.tick({"self": self})

func _flee(_c) -> int: return BTNode.Status.RUNNING
func _chase(_c) -> int: return BTNode.Status.RUNNING
func _patrol(_c) -> int: return BTNode.Status.RUNNING
```

⚠ 这个最小实现**没有黑板**，ctx 每次现场构造。
正式项目要抽成黑板对象（见下）。

⚠ 最小实现**没有 abort/中断**。要做中断得在每个节点记 RUNNING 状态并在条件变化时重置。

## 3. 黑板（Blackboard）

黑板是 BT 的共享状态区，避免所有数据都塞进 ctx。

```gdscript
class_name Blackboard
extends RefCounted

var _data: Dictionary = {}

func get_value(key: StringName, default = null):
    return _data.get(key, default)

func set_value(key: StringName, value) -> void:
    _data[key] = value

func has(key: StringName) -> bool:
    return _data.has(key)

func clear() -> void:
    _data.clear()
```

⚠ 黑板**不要塞引擎对象引用**（Node / Resource），
否则存档时无法序列化，且对象释放后留悬空引用。
**存 id / 路径，需要时再查**。

## 4. 现成插件

| 插件 | 特点 | 状态 |
|---|---|---|
| **LimboAI** | Godot 官方推荐的行为树插件。`BTPlayer` 节点 + `BehaviorTree` 资源，自定义 Task，黑板，可视化调试 | ⚠ 待核对：LimboAI 仓库地址与 4.7.2 版本兼容 · 验证：查插件仓库最新 release 并在目标版本导入 demo |
| **Beehave** | 树就是 Godot 场景树节点，可挂任意节点。生命周期/继承/Inspector 都能沿用 | 官方确认含 3.x / 4.0.x / 4.1.x / 4.5+ |

⚠ **版本兼容以各仓库的兼容表为准**，本文不推断具体版本支持范围。

### Beehave 安装（官方确认流程）

1. 下载最新 release
2. `addons/beehave` 解包到项目 `addons` 目录
3. `Project > Project Settings > Plugins` 启用
4. `script_templates` 移到项目目录

⚠ **CI 中应锁定 commit 或 release 资产**，不要 `git pull` 主分支后上线。

### 选哪个

- 要**官方推荐 + 完整功能** → LimboAI（先核对版本兼容）
- 要**树就是节点、编辑器内可见** → Beehave
- 只有几个简单 AI → **别加依赖**，用上面的最小实现

> **反模式清单（不能怎么做，审核用）** → `audit/godot/ai-behavior.md`


## 5. Idle 不是"什么都不做"

⚠ **待机是最容易被写成空状态的一个状态。**
写空之后的两个后果：
- 单位看起来是**死的**（站着不动、不转头、无微小动作）
- 从 Idle 转出时**没有自然的过渡**，表现为"突然弹起来追人"

✅ Idle 至少要负责三件事：

| 职责 | 说明 |
|---|---|
| **朝向** | 缓慢转向巡逻方向 / 最后已知方向 / 随机环视 |
| **微动作** | 呼吸、重心、偶尔的 idle 动画变体 |
| **退出条件** | 明确写出"满足什么就离开 Idle" |

⚠ **Idle 里也要跑感知** —— 很多实现把感知写在 Chase 分支里，
结果"没发现玩家"是因为**根本没在检测**，而不是"检测了没看到"。
⛔ 这个 bug 的表现是"敌人背对玩家时永远发现不了"，
而排查时你会去调视野角度，其实与角度无关。

⚠ **Idle 的退出要有最短驻留**，否则在阈值边界会
Idle ↔ Alert 每帧抖动（表现为敌人原地抽搐）。

```gdscript
const MIN_IDLE_TIME := 0.4

func _tick_idle(delta: float) -> void:
    _idle_time += delta
    _scan()                       # ⚠ Idle 也要感知
    if _idle_time >= MIN_IDLE_TIME and _can_see_player():
        _set_state(State.CHASE)   # ⚠ 最短驻留后才允许转出
```

ⓘ 相关：感知的警戒等级与传播见 `ai-perception.md` 第 4 节；
潜行玩法的警戒两段语义见 `stealth-ai.md` 第 0 节。

### 两个容易被当成"普通状态"的状态：DEAD 与 STAGGER

⚠ **`DEAD` 不是"一个不再转移的状态"，它是一个清理入口。**
只把它当成转移表的终点，死亡单位会继续占用：
攻击令牌、预约的掩体、感知候选、威胁表条目。

⛔ 这是"AI 集体发呆"最常见的源头之一 ——
令牌没回收，其他单位全在等一个永远不来的释放。

```gdscript
func _on_enter_dead() -> void:
    _stop_all_ticks()          # ⚠ 不再 tick 决策/感知/移动
    _release_attack_token()    # → ai-tactics.md
    _release_reserved_cover()  # → ai-tactics.md
    _perception.unregister(self)
    _threat_table.remove(_id)
```

⚠ **`STAGGER`（硬直/受击）的重点是"打断什么"，不是"播放什么动画"。**
进入时必须显式停掉那些**不会自己停**的东西：
寻路（`velocity` 不清零会滑行）、当前 Task、正在播放的 Tween。

⛔ 只播动画不停寻路的后果：硬直中单位**顺着惯性滑行**，
看起来像"被打了还往前冲"。

ⓘ 因此进入/退出逻辑要统一走 `_on_enter` / `_on_exit`，
⛔ 不要散落在各处写"开始时清一下、结束时停一下"——
散落的典型后果正是上面这个：`Chase → STAGGER` 忘了停寻路。

## 6. 战术层不在这里

⚠ **"我们怎么打"不是决策层的事。**
目标选择迟滞、仇恨表、阵型槽位、掩体预约、攻击令牌、AI 的 LOD 与性能预算、
调试可视化 → 全部见 `ai-tactics.md`。

ⓘ 判据：只留一个敌人时还成立的规则才放决策层。

## 7. 与已有文档的关系

战术层（目标/阵型/掩体/协同/LOD/调试） → **`ai-tactics.md`**


- 巡逻/追击/状态机基础 → `ai-navigation.md`
- 寻路（NavigationAgent2D / AStarGrid2D）→ `ai-navigation.md`
- 群体避障（RVO）→ `ai-navigation.md`

本文档只讲**决策层**（选什么行为），不重复寻路和执行细节。
战术层见 `ai-tactics.md`。

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-01`　状态机优于 if 嵌套
【读】 `common/howto/principles.md#GC-06`　性能：先定位再优化
