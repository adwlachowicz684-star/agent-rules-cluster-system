# Godot 4.x 游戏系统：对话 / 任务 / 库存

三个系统共用同一个设计原则：**内容资产（定义）与运行时事实（进度）分开**。

```
定义层（Resource，不可变，进版本库）
  ↓ 引用
运行时层（进度 / 实例，可变，进存档）
```

定义层改了不影响存档结构，运行时层单独序列化 —— 这是存档能兼容的前提。

## 0. 共用的地基：命令解释器

**绝不能执行数据里的脚本字符串。**

对话文本、任务奖励、物品效果经常想写"做点什么"。本能写法是存个方法名再 `call()`，
或者更糟 —— 存一段脚本用 `str2var()` 执行。这两条都是**安全漏洞 + 无法本地化 + 无法测试**。

正确做法：动词白名单。

```gdscript
# command_interpreter.gd —— Autoload 或节点
class_name CommandInterpreter
extends Node

signal command_failed(verb: StringName, reason: String)

const MAX_ARGS := 8

var _verbs: Dictionary = {}     # StringName -> Callable

func register_verb(verb: StringName, handler: Callable) -> void:
    if not handler.is_valid():
        push_error("无效的 handler: %s" % verb)
        return
    _verbs[verb] = handler

func execute(cmd: CommandData, ctx: Dictionary = {}) -> bool:
    if cmd == null:
        return false
    var verb := cmd.verb
    if not _verbs.has(verb):
        command_failed.emit(verb, "未知动词")
        push_warning("未注册的动词: %s" % verb)
        return false
    if cmd.args.size() > MAX_ARGS:
        command_failed.emit(verb, "参数过多")
        return false
    _verbs[verb].call(cmd.args, ctx)
    return true
```

```gdscript
# command_data.gd
class_name CommandData
extends Resource

@export var verb: StringName = &""      # give_item / set_flag / start_quest ...
@export var args: Array = []            # 只放数据，不放代码

func _init(v: StringName = &"", a: Array = []) -> void:
    verb = v
    args = a
```

⚠ **未知动词必须报错，绝不回退到"猜一个方法"**。
静默回退 = 内容作者写错时游戏静默不生效。

⚠ `Callable(obj, method_name)` 签名不匹配会运行时报错 —— 它是受控调用，
不是"安全执行任意代码"。别用它绕过白名单。

## 一、对话系统

### 数据结构

```gdscript
# speaker_config.gd
class_name SpeakerConfig
extends Resource

@export var id: StringName = &""
@export var display_name_key: StringName = &""    # 存 key，不存文本
@export var portrait: Texture2D
@export var voice_bus: StringName = &"Master"
```

```gdscript
# dialogue_line.gd
class_name DialogueLine
extends Resource

@export var id: StringName = &""
@export var speaker_id: StringName = &""
@export var text_key: StringName = &""            # 本地化 key
@export var next_id: StringName = &""             # 下一行（空=结束）
@export var choices: Array[DialogueChoice] = []
@export var on_enter: Array[CommandData] = []     # 进入时执行
@export var on_exit: Array[CommandData] = []
```

```gdscript
# dialogue_choice.gd
class_name DialogueChoice
extends Resource

@export var text_key: StringName = &""
@export var condition: ConditionData             # 为空=总是显示
@export var next_id: StringName = &""
@export var on_select: Array[CommandData] = []
```

```gdscript
# dialogue_resource.gd
class_name DialogueResource
extends Resource

@export var id: StringName = &""
@export var start_id: StringName = &""
@export var speakers: Array[SpeakerConfig] = []
@export var lines: Array[DialogueLine] = []

func find_line(line_id: StringName) -> DialogueLine:
    for l in lines:
        if l.id == line_id:
            return l
    return null
```

### Runner

```gdscript
# dialogue_runner.gd
class_name DialogueRunner
extends Node

signal line_shown(speaker: String, text: String, choices: Array)
signal dialogue_ended(id: StringName)

var _res: DialogueResource
var _cur: DialogueLine

func start(res: DialogueResource) -> void:
    if res == null or res.lines.is_empty():
        push_error("对话资源为空")
        return
    _res = res
    _goto(res.start_id if res.start_id != &"" else res.lines[0].id)

func _goto(line_id: StringName) -> void:
    if line_id == &"":
        dialogue_ended.emit(_res.id if _res else &"")
        _res = null
        return
    _cur = _res.find_line(line_id)
    if _cur == null:
        push_error("对话节点不存在: %s" % line_id)
        dialogue_ended.emit(_res.id)
        return
    for c in _cur.on_enter:
        Commands.execute(c)
    # 过滤掉条件不满足的选项
    var visible := []
    for ch in _cur.choices:
        if ch.condition == null or Conditions.evaluate(ch.condition):
            visible.push_back(ch)
    line_shown.emit(
        tr(_speaker_name(_cur.speaker_id)),
        tr(_cur.text_key),
        visible)

func select(index: int) -> void:
    if _cur == null:
        return
    var visible := []
    for ch in _cur.choices:
        if ch.condition == null or Conditions.evaluate(ch.condition):
            visible.push_back(ch)
    if index < 0 or index >= visible.size():
        return
    var ch := visible[index] as DialogueChoice
    for c in ch.on_select:
        Commands.execute(c)
    for c in _cur.on_exit:
        Commands.execute(c)
    _goto(ch.next_id if ch.next_id != &"" else _cur.next_id)

func advance() -> void:
    if _cur == null or not _cur.choices.is_empty():
        return                          # 有选项时必须选，不能直接过
    for c in _cur.on_exit:
        Commands.execute(c)
    _goto(_cur.next_id)

func _speaker_name(id: StringName) -> StringName:
    var s := _res.find_speaker(id) if _res else null
    return s.display_name_key if s else &""
```

⚠ **存 `text_key` 不存文本**。否则加一门语言就要改所有对话资源。

⚠ 有选项时**不能允许"继续"跳过** —— 跳过了 `on_select` 就永远不执行。

⚠ 对话要能**中断与恢复**（战斗中突然进入对话、存档在对话中途）。
所以 runner 必须能序列化当前 `line_id`。

### 常见漏写

| 漏写 | 后果 |
|---|---|
| 文本直接写死 | 无法本地化 |
| 用字符串存方法名再 call | 安全漏洞 + 无法测试 |
| 选项条件在 UI 层算 | 逻辑与显示耦合，无法测试 |
| 对话中途不能存档 | 玩家关游戏丢失进度 |
| 无中断恢复 | 战斗中对话会卡死 |
| 未知节点 id 静默结束 | 内容错误变成"对话莫名结束" |

## 二、任务系统

### 结构三层

```
QuestDefinition（Resource，不可变）
  ├─ id / 前置条件 / 目标集合 / 奖励 / 本地化
  └─ 不含任何进度数据

QuestProgress（运行时，可序列化）
  ├─ quest_id / 状态 / 各目标当前值 / 开始时间

QuestManager（节点）
  └─ 持有所有 progress，监听事件更新
```

```gdscript
# quest_definition.gd
class_name QuestDefinition
extends Resource

enum State { AVAILABLE, ACTIVE, COMPLETED, FAILED }

@export var id: StringName = &""
@export var title_key: StringName = &""
@export var prerequisites: Array[StringName] = []    # 前置任务 id
@export var objectives: Array[ObjectiveDefinition] = []
@export var rewards: Array[CommandData] = []
@export var fail_conditions: Array[ConditionData] = []
@export var is_optional: bool = false
```

```gdscript
# objective_definition.gd
class_name ObjectiveDefinition
extends Resource

@export var id: StringName = &""
@export var description_key: StringName = &""
@export var event_name: StringName = &""      # 监听哪个事件
@export var target_amount: int = 1
@export var is_optional: bool = false          # 可选目标
```

### 事件驱动，不要轮询

```gdscript
# quest_manager.gd
class_name QuestManager
extends Node

signal quest_started(id: StringName)
signal quest_completed(id: StringName)
signal quest_failed(id: StringName)
signal objective_progress(id: StringName, obj_id: StringName, cur: int, need: int)

var _defs: Dictionary = {}          # StringName -> QuestDefinition
var _progress: Dictionary = {}      # StringName -> Dictionary

func _ready() -> void:
    Events.quest_event.connect(_on_event)

func register(def: QuestDefinition) -> void:
    _defs[def.id] = def

func start(id: StringName) -> bool:
    var def := _defs.get(id) as QuestDefinition
    if def == null:
        push_error("任务定义不存在: %s" % id)
        return false
    for p in def.prerequisites:
        if _state_of(p) != QuestDefinition.State.COMPLETED:
            return false                        # 前置未完成
    if _progress.has(id):
        return false                            # 已开始
    _progress[id] = {
        "state": QuestDefinition.State.ACTIVE,
        "objectives": {},
        "started_tick": Time.get_ticks_msec(),
    }
    for o in def.objectives:
        _progress[id]["objectives"][o.id] = 0
    quest_started.emit(id)
    return true

func _on_event(event: StringName, payload: Dictionary) -> void:
    for id in _progress:
        var pr := _progress[id]
        if pr["state"] != QuestDefinition.State.ACTIVE:
            continue
        var def := _defs[id] as QuestDefinition
        for o in def.objectives:
            if o.event_name != event:
                continue
            if not payload.has("amount"):
                continue
            _advance(id, o, int(payload["amount"]))

func _advance(quest_id: StringName, o: ObjectiveDefinition, amount: int) -> void:
    var pr := _progress[quest_id]
    var cur: int = pr["objectives"][o.id]
    cur = mini(cur + amount, o.target_amount)
    pr["objectives"][o.id] = cur
    objective_progress.emit(quest_id, o.id, cur, o.target_amount)
    if _all_done(quest_id):
        _complete(quest_id)

func _all_done(quest_id: StringName) -> bool:
    var def := _defs[quest_id] as QuestDefinition
    var pr := _progress[quest_id]
    for o in def.objectives:
        if o.is_optional:
            continue
        if int(pr["objectives"][o.id]) < o.target_amount:
            return false
    return true

func _complete(quest_id: StringName) -> void:
    var def := _defs[quest_id] as QuestDefinition
    _progress[quest_id]["state"] = QuestDefinition.State.COMPLETED
    # 奖励用幂等键，防止重复发放
    var key := "quest_reward_%s" % quest_id
    if not Flags.get_flag(&"rewarded", {}).has(key):
        for r in def.rewards:
            Commands.execute(r)
        Flags.set_flag(StringName(key), true)
    quest_completed.emit(quest_id)

func _state_of(id: StringName) -> int:
    var pr := _progress.get(id)
    if pr == null:
        return QuestDefinition.State.AVAILABLE
    return int(pr["state"])

func serialize() -> Dictionary:
    return _progress.duplicate(true)

func restore(data: Dictionary) -> void:
    _progress = data.duplicate(true)
```

⚠ **奖励必须幂等**。存档回读、事件重复触发都可能发两次。用任务 id 做去重键。

⚠ 目标用**事件驱动**，不要每帧轮询 `if enemy_count == 0`。
轮询在多个任务时是 O(任务数 × 帧)。

⚠ 定义层不能存进度 —— 否则两个存档共用一个 `.tres` 实例会互相污染
（同 `Resource` 共享问题，见 `gdscript-advanced.md`）。

⚠ 联网任务必须在**服务端**生成/更新/结算，客户端只显示。

### 常见漏写

| 漏写 | 后果 |
|---|---|
| 进度存在 Resource 里 | 多存档互相污染 |
| 奖励不幂等 | 重复发放 |
| 轮询判定目标 | 性能随任务数线性下降 |
| 无前置任务校验 | 玩家跳阶段 |
| 存档格式变更无迁移 | 老存档任务数据丢失 |
| 失败条件不监听 | 任务永远卡在 ACTIVE |

## 三、库存系统

### 四层

```
ItemDefinition   一类物品（Resource，共享，不可变）
ItemInstance     具体实例（唯一 id、耐久、附魔、自定义数据）
InventorySlot    只存 instance_id + count（不拥有物品）
Inventory        管理槽位数组 + 实例字典
```

```gdscript
# item_definition.gd
class_name ItemDefinition
extends Resource

enum ItemType { GENERIC, CONSUMABLE, MATERIAL, WEAPON, ARMOR, QUEST, CURRENCY }

@export var id: StringName = &""
@export var name_key: StringName = &""
@export var icon: Texture2D
@export var item_type: int = ItemType.GENERIC
@export var max_stack: int = 1
@export var weight: float = 0.0
@export var value: int = 0
@export var is_unique: bool = false
@export var tags: Array[StringName] = []
@export var use_command: CommandData

func can_stack_with(other: ItemDefinition) -> bool:
    if other == null:
        return false
    return id == other.id and max_stack > 1 and other.max_stack > 1
```

```gdscript
# item_instance.gd
class_name ItemInstance
extends RefCounted

var instance_id: StringName
var def_id: StringName
var durability: float = 1.0
var custom_data: Dictionary = {}

func _init(iid: StringName, did: StringName) -> void:
    instance_id = iid
    def_id = did
```

```gdscript
# inventory.gd
class_name Inventory
extends Node

signal changed

var _slots: Array[Dictionary] = []          # {instance_id, count}
var _instances: Dictionary = {}             # instance_id -> ItemInstance
var _capacity: int = 20
var _next_id: int = 1

func _new_instance(def_id: StringName) -> ItemInstance:
    var iid := StringName("it_%d" % _next_id)
    _next_id += 1
    var inst := ItemInstance.new(iid, def_id)
    _instances[iid] = inst
    return inst

## 返回实际放入数量（放不下会部分放入）
func add(def: ItemDefinition, count: int = 1) -> int:
    if def == null or count <= 0:
        return 0
    var left := count

    # 1) 先填已有可堆叠槽
    if def.max_stack > 1:
        for s in _slots:
            if left <= 0:
                break
            var inst := _instances.get(s["instance_id"]) as ItemInstance
            if inst == null or inst.def_id != def.id:
                continue
            if def.is_unique:
                continue
            var room: int = def.max_stack - int(s["count"])
            if room <= 0:
                continue
            var put: int = mini(room, left)
            s["count"] = int(s["count"]) + put
            left -= put

    # 2) 再开新槽
    while left > 0 and _slots.size() < _capacity:
        if def.is_unique and _has_def(def.id):
            break                            # 唯一物品不能重复
        var inst := _new_instance(def.id)
        var put: int = mini(def.max_stack, left)
        _slots.push_back({"instance_id": inst.instance_id, "count": put})
        left -= put

    if left != count:
        changed.emit()
    return count - left

func remove(instance_id: StringName, count: int = 1) -> int:
    for i in _slots.size():
        var s := _slots[i]
        if s["instance_id"] != instance_id:
            continue
        var have: int = int(s["count"])
        var take: int = mini(have, count)
        s["count"] = have - take
        if s["count"] <= 0:
            _slots.remove_at(i)
            _instances.erase(instance_id)
        changed.emit()
        return take
    return 0

func count_of(def_id: StringName) -> int:
    var total := 0
    for s in _slots:
        var inst := _instances.get(s["instance_id"]) as ItemInstance
        if inst and inst.def_id == def_id:
            total += int(s["count"])
    return total

func _has_def(def_id: StringName) -> bool:
    return count_of(def_id) > 0

func serialize() -> Dictionary:
    return {
        "slots": _slots.duplicate(true),
        "instances": _instances.duplicate(true),
        "capacity": _capacity,
        "next_id": _next_id,
    }
```

⚠ **槽位不拥有物品，只存 id**。否则移动/交换时要深拷贝整个物品，
而耐久附魔等数据会被复制出多份。

⚠ `max_stack = 1` 的装备类物品**不能走堆叠分支**。

⚠ 交易/移动要**先试算再提交**，不能改一半失败 —— 那是不可逆的脏数据。

⚠ 联网时库存权威在服务端，客户端的 `add()` 只是预测，要能被服务端回滚。

### 常见漏写

| 漏写 | 后果 |
|---|---|
| 槽位直接存物品对象 | 移动时数据被复制，耐久不同步 |
| 唯一物品可堆叠 | 出现两把同 id 神器 |
| 容量满了静默丢弃 | 玩家物品凭空消失 |
| 交易改一半失败 | 脏数据不可逆 |
| 实例 id 用随机数 | 存档回读后 id 冲突 |
| 客户端库存权威 | 改内存加物品 |
| UI 直接改库存数据 | 无法测试，逻辑散落 |
