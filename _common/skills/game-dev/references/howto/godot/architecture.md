# Godot 4.x 架构规范

大型项目的组织方式。**越早定越省事**，后期改要动所有文件。

## 1. 脚本成员顺序（17 步）

统一顺序，导航和修改都快。这是官方 + 社区共识的顺序：

```gdscript
@tool                                    # 1. 工具注解
class_name PlayerController              # 2. 类名（PascalCase）
extends CharacterBody2D                  # 3. 继承
"""                                      # 4. 文档字符串
一句话说明这个类的职责。
"""

signal health_changed(new_hp: int)       # 5. 信号（snake_case，过去时）
signal died

enum State { IDLE, RUN, JUMP }           # 6. 枚举（类型 PascalCase，值 UPPER）
const MAX_SPEED := 300.0                 # 7. 常量（UPPER_SNAKE）
@export var speed: float = 200.0          # 8. 导出变量
var health: int = 100                     # 9. 公有变量
var _state: State = State.IDLE            # 10. 私有变量（_ 前缀）
@onready var _sprite: Sprite2D = $Sprite  # 11. @onready（放在 _ready 前）

func _init() -> void: pass                # 12. _init
func _enter_tree() -> void: pass          # 13. _enter_tree
func _ready() -> void: pass               # 14. _ready
func _process(d: float) -> void: pass     # 15. 其余虚方法
func _physics_process(d: float) -> void: pass
func _exit_tree() -> void: pass           #     （含断信号）

func take_damage(n: int) -> void: pass    # 16. 公有方法
func _update_state() -> void: pass        # 17. 私有方法
```

⚠ 为什么 `@onready` 放在变量区最后：`_ready()` 时求值，紧挨 `_ready` 便于对照依赖。

⚠ 顺序不一致不影响运行，但**影响所有人阅读和 diff 的成本**。
用 `gdlint` / `gdstyle` 可以自动检查（`class-definitions-order` 规则）。

## 2. 节点通信：call down, signal up

这是 Godot 最核心的架构原则。

```
父节点 ──直接调用──▶ 子节点        （call down：父知道子，可以调）
子节点 ──信号通知──▶ 父节点        （signal up：子不知道父，只能发信号）
```

```gdscript
# 父：直接调子的方法
func _on_attack() -> void:
    _weapon.fire()               # 父持有子引用，直接调

# 子：发信号，不关心谁听
signal hit(target: Node, damage: int)
func _on_body_entered(body: Node) -> void:
    hit.emit(body, 10)           # 子不认识父
```

**为什么**：子节点依赖父节点 = 耦合。改父节点的结构，子节点全崩。
反过来父调子是安全的，因为父本来就知道自己的子。

⚠ **反模式**：`get_parent().get_parent()` —— 孙子通过爷爷拿东西，改树结构就断。

```gdscript
# 反例
func _ready() -> void:
    get_parent().get_parent()._hp -= 10

# 正例：发信号
signal damaged(amount: int)
# 父节点自己连自己的信号来源
```

### 跨远距离通信：事件总线

```gdscript
# events.gd —— Autoload
extends Node

signal player_died
signal item_collected(item_id: StringName, count: int)
signal scene_requested(path: String)
```

```gdscript
# 发送方（任意节点）
Events.item_collected.emit(&"coin", 1)

# 接收方
func _ready() -> void:
    Events.item_collected.connect(_on_item)

func _exit_tree() -> void:
    if Events.item_collected.is_connected(_on_item):
        Events.item_collected.disconnect(_on_item)      # 必须断
```

⚠ **Autoload 的信号不会自动断开**。订阅的节点会被 Autoload 吊住，
永远不释放 —— 这是 Godot 内存泄漏的常见来源。

⚠ 别滥用事件总线。能直接连的（父子、同一场景内）就直接连，
全走总线会让调用链变得无法追踪。

## 3. 组合优于继承

```
# 反例：深继承链
Character → Enemy → FlyingEnemy → BossEnemy
（改 Character 影响所有；Boss 想要 Character 的某个特性只能全继承）

# 正例：组件组合
Enemy (CharacterBody2D)
├── HealthComponent      ← 血量（可复用给玩家、宝箱、建筑）
├── HitboxComponent      ← 受击判定
├── AIComponent          ← 行为（可换：巡逻 / 追击 / 静态）
└── LootComponent        ← 掉落
```

```gdscript
# health_component.gd
class_name HealthComponent
extends Node

signal died
signal changed(new_hp: int)

@export var max_hp: int = 100
var hp: int:
    set(v):
        hp = clampi(v, 0, max_hp)
        changed.emit(hp)
        if hp <= 0:
            died.emit()

func take_damage(n: int) -> void:
    hp -= n
```

```gdscript
# 敌人用
@onready var _health: HealthComponent = $HealthComponent

func _ready() -> void:
    _health.died.connect(_on_died)

func _exit_tree() -> void:
    if _health.died.is_connected(_on_died):
        _health.died.disconnect(_on_died)
```

⚠ 组件之间**不要互相直接引用**。需要协作时通过父节点中转或信号。

## 4. 数据驱动：用 Resource

**别把数据表写在脚本里。**

```gdscript
# weapon_data.gd
class_name WeaponData
extends Resource

@export var damage: int = 10
@export var attack_speed: float = 1.0
@export var icon: Texture2D
@export var sound: AudioStream
```

在编辑器里创建 `.tres` 文件，设计师改数值不用碰代码。

```gdscript
# 使用
@export var weapon: WeaponData

func _ready() -> void:
    _sprite.texture = weapon.icon
```

⚠ `@export` 的 Resource **默认共享**，需要按实例修改时 `duplicate()`：

```gdscript
func _ready() -> void:
    weapon = weapon.duplicate() as WeaponData    # 否则改一个全变
```

⚠ 深拷贝用 `duplicate(true)`。

## 5. 场景组织

```
res://
├── autoload/          全局单例（Events, SaveManager, AudioManager）
├── scenes/            场景
│   ├── levels/
│   └── ui/
├── components/        可复用组件（Health, Hitbox, StateMachine）
├── data/              .tres 数据资源
├── scripts/           纯脚本类（不挂节点）
└── assets/
```

**SceneTree 按逻辑关系组织，不按空间位置。**

```
Level
├── Environment        （地形、装饰）
├── Entities           （玩家、敌人、NPC）
│   ├── Player
│   └── Enemies
├── Systems            （非可视逻辑）
└── UI                 （CanvasLayer）
```

⚠ 需要空间解耦时设 `top_level = true`（子不跟随父的变换）。

⚠ **场景树深度别太深** —— 每层都增加遍历和变换计算成本。

## 6. 依赖注入

```gdscript
# 反例：脚本内部自己去全局找
func _ready() -> void:
    _player = get_tree().get_first_node_in_group("player")

# 正例：从外部注入（@export 或 setter）
@export var target: Node2D

func setup(t: Node2D) -> void:
    target = t
```

⚠ 内部自己找依赖 = 无法测试、无法复用、改结构就断。

## 7. 单脚本别太大

```
一个脚本 > 200-300 行 → 该拆了
```

拆法：
- 独立职责抽成子节点+组件脚本
- 状态多用状态机（见 `ai-navigation.md`）
- 数据表抽成 Resource

⚠ "God 脚本"（500 行处理移动+战斗+背包+UI）= 无法调试、无法复用。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/architecture.md`

