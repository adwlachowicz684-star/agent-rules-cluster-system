# Godot 4.x GDScript 热路径与生命周期

语言层的坑。这些不是风格问题，错了会**静默掉性能或静默出错**。

## 1. 类型系统

### 静态类型的收益

```gdscript
var speed: float = 200.0        # 静态类型
var speed := 200.0              # 类型推断（推荐，简洁）
var speed = 200.0               # 动态类型
```

⚠ `:=` 是**类型推断**，不是动态类型。它拿到确定的类型，有完整优化和补全。
只有 `var x = ...` 无冒号无等号推断的才是动态。

**动态类型的代价**：

- 运行时才解析，慢
- 无编译期检查，拼错属性不报错
- 无补全

**该用静态类型的地方**：函数参数、返回值、成员变量、热路径局部变量。

```gdscript
func take_damage(amount: int) -> void:      # 参数和返回值都标
    _hp -= amount

@onready var _sprite: Sprite2D = $Sprite   # 成员变量标
```

⚠ **不标类型的 `@onready` 没有补全** —— 写了等于白缓存。

### 类型转换

```gdscript
# 安全转换：失败返回 null
var p := get_node("Player") as Player
if p:                              # 必须判空
    p.take_damage(10)

# 强制转换：失败直接崩
var p := get_node("Player") as Player      # as 是安全的
```

⚠ `as` 转换失败返回 **null**，不判空直接用 = 空引用崩溃。
Godot 编辑器会给 `UNSAFE_CAST` 警告，别忽略。

⚠ **`is_instance_valid()` 判的是"对象是否已释放"**，
而 `if x` 判的是"是否非空"。对象被 `queue_free` 后引用非空但已失效：

```gdscript
if _target:                          # 可能是已释放对象，返回 true
    _target.do_something()           # 崩溃

if is_instance_valid(_target):       # 正确
    _target.do_something()
```

### 类型化数组

```gdscript
var items: Array[Item] = []          # 类型化
var pos: PackedVector2Array = ...    # 打包数组，最省

# 反例
var items = []                       # 无类型，元素任意，慢
```

⚠ 热路径用 `Packed*Array`（`PackedVector2Array` / `PackedFloat32Array` …），
内存连续，比 `Array` 快很多。

## 2. 热路径：每帧都跑的代码

`_process` / `_physics_process` 里每一行都 ×60（或更多）。

### 禁止清单

| 禁止 | 改法 |
|---|---|
| `get_node()` / `$` | `@onready` 缓存或场景唯一名 `%X` |
| `.new()` / `instantiate()` | 对象池 |
| `load()` | `preload` 或提前加载 |
| 字符串比较 | StringName `&"x"` |
| `distance_to()` 比较 | `distance_squared_to()` |
| 字符串拼接/`%` 格式化 | 只在值变化时更新 |
| 新建 Array/Dictionary | 复用成员容器，`.clear()` |
| 材质新建 | 共享实例，只改参数 |
| `print()` | 删掉或 `print_debug` |

### 每帧分配最常见的写法

```gdscript
# 反例：每帧新建数组
func _process(_d: float) -> void:
    var nearby := get_tree().get_nodes_in_group("enemy")   # 新建 Array
    for e in nearby: ...

# 正例：缓存组引用，只在校准点刷新
var _nearby: Array[Node] = []
var _refresh := 0.0

func _process(delta: float) -> void:
    _refresh -= delta
    if _refresh <= 0.0:
        _nearby.clear()                                   # 复用容器
        _nearby.assign(get_tree().get_nodes_in_group("enemy"))
        _refresh = 0.5
    for e in _nearby: ...
```

### 值变化才更新 UI

```gdscript
# 反例：每帧赋值，每帧重排
func _process(_d: float) -> void:
    _hp_label.text = "%d / %d" % [_hp, _max_hp]

# 正例
var _last_hp := -1
func _process(_d: float) -> void:
    if _hp != _last_hp:
        _last_hp = _hp
        _hp_label.text = "%d / %d" % [_hp, _max_hp]
```

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/gdscript-advanced.md`


## 3. 生命周期：哪个回调做什么

| 回调 | 时机 | 放什么 |
|---|---|---|
| `_init()` | 对象构造，未进树 | 纯数据初始化，**碰不到场景树** |
| `_enter_tree()` | 进树（子节点可能还没好） | 与树相关的早期绑定 |
| `_ready()` | 自己和子节点都就绪 | 拿子节点、连信号、初始化依赖 |
| `_process(d)` | 每渲染帧 | 输入、动画、UI |
| `_physics_process(d)` | 每物理帧（默认 60） | 移动、物理、碰撞 |
| `_exit_tree()` | 离树 | 断信号、清引用 |
| `_notification()` | 引擎通知 | 窗口事件（如返回键） |

```gdscript
func _init() -> void:
    _data = {}                  # 纯数据，安全

func _ready() -> void:
    _sprite = $Sprite           # 子节点已就绪
    Events.player_died.connect(_on_died)

func _exit_tree() -> void:
    if Events.player_died.is_connected(_on_died):
        Events.player_died.disconnect(_on_died)
```

⚠ **`@onready` 在 `_ready()` 时求值**。在 `_init()` 里用它是 null。

⚠ **Autoload 的信号必须手动断开** —— 普通父子节点会自动断，
Autoload 生命周期是整个程序，不会断（会吊住你的节点不释放）。

## 4. `@tool` 脚本

在编辑器里运行的脚本。

```gdscript
@tool
extends Node2D

func _ready() -> void:
    if Engine.is_editor_hint():
        _setup_preview()        # 只在编辑器里做
    else:
        _setup_game()

func _process(delta: float) -> void:
    if Engine.is_editor_hint():
        return                  # 编辑器里别跑游戏逻辑
```

⚠ `@tool` 脚本里**任何在 `_ready`/`_process` 里跑的代码都会影响编辑器**。
改动节点可能触发无限循环或污染场景文件。

⚠ 编辑器里的修改**会存进 `.tscn`**。用 `Engine.is_editor_hint()` 隔开。

## 5. 信号写法（4.x）

```gdscript
signal health_changed(new_hp: int)      # 4.x：带类型的声明

func _ready() -> void:
    health_changed.connect(_on_health_changed)     # 4.x：Callable 形式

func _on_health_changed(hp: int) -> void:
    _label.text = str(hp)

func _exit_tree() -> void:
    if health_changed.is_connected(_on_health_changed):
        health_changed.disconnect(_on_health_changed)
```

⚠ 3.x 的 `emit_signal("name", arg)` 和 `connect("name", target, "method")`
在 4.x **编译通过但不生效** —— 静默失效，最难查（审查 GD72）。

⚠ 一次性信号用 `CONNECT_ONE_SHOT`：

```gdscript
_tween.finished.connect(_on_done, CONNECT_ONE_SHOT)
```

## 6. 资源与 duplicate

```gdscript
@export var base_stats: CharacterStats     # Resource

func _ready() -> void:
    # 必须 duplicate！否则所有实例共享同一份，改一个全变
    stats = base_stats.duplicate() as CharacterStats
```

⚠ 这是 **Godot 4 最常见的 #1 新手 bug**。`.tres` 资源默认是共享的，
十个敌人用同一个 `stats.tres`，改一个的血量，十个一起变。

⚠ `duplicate()` 默认**浅拷贝** —— 嵌套的 Resource 还是共享的。
要深拷贝用 `duplicate(true)`（审查 GD73）。

