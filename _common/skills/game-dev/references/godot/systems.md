# Godot 4.x 通用系统

存档、场景切换、事件总线、对象池 —— 几乎每个项目都要写一遍的。
给完整实现，可直接抄。

## 1. 存档

### 选型

| 方案 | 适用 | 别用在哪 |
|---|---|---|
| **ConfigFile** | 设置项、简单进度（几十个键值） | 大量数据、二进制 |
| **Resource + ResourceSaver** | 结构化存档、需要版本字段 | 不可信来源的存档 |
| **JSON + FileAccess** | 需要人可读/可手工改 | 大数据量、要存对象引用 |

**推荐 Resource 方案**：有类型、能带版本号、Godot 原生。

### 完整实现（Resource 方案）

```gdscript
# save_data.gd —— 存档数据结构
extends Resource
class_name SaveData

const CURRENT_VERSION := 2

@export var version: int = CURRENT_VERSION
@export var player_position: Vector2
@export var player_health: int = 100
@export var level_name: String = ""
@export var inventory: Array[String] = []
@export var playtime_seconds: float = 0.0

## 从旧版本迁移。新加字段时在这里补，别删旧分支。
func migrate() -> void:
    if version == 1:
        # v1 → v2：新增了 inventory
        inventory = []
        version = 2
```

```gdscript
# save_manager.gd —— 挂成 Autoload（项目设置 → Autoload，名 SaveManager）
extends Node

const SAVE_PATH := "user://savegame.res"
const BACKUP_PATH := "user://savegame.bak"

var current: SaveData

func _ready() -> void:
    current = load_game()

## 原子写盘：先写临时文件，成功后再替换。
## 直接覆盖的话，写到一半崩溃 = 存档损坏且没有备份。
func save_game() -> bool:
    var tmp := SAVE_PATH + ".tmp"
    var err := ResourceSaver.save(current, tmp)
    if err != OK:
        push_error("存档写临时文件失败: %d" % err)
        return false

    # 把旧存档留作备份
    if FileAccess.file_exists(SAVE_PATH):
        DirAccess.copy_absolute(
            ProjectSettings.globalize_path(SAVE_PATH),
            ProjectSettings.globalize_path(BACKUP_PATH))

    DirAccess.rename_absolute(
        ProjectSettings.globalize_path(tmp),
        ProjectSettings.globalize_path(SAVE_PATH))
    return true

func load_game() -> SaveData:
    if not FileAccess.file_exists(SAVE_PATH):
        return SaveData.new()          # 新游戏

    var data := ResourceLoader.load(SAVE_PATH) as SaveData
    if data == null:
        push_warning("存档损坏，尝试备份")
        data = ResourceLoader.load(BACKUP_PATH) as SaveData
        if data == null:
            push_warning("备份也损坏，开新档")
            return SaveData.new()

    data.migrate()                     # 版本迁移
    return data

## 收集当前游戏状态 → SaveData
func capture(player: Node2D, level: String) -> void:
    current.player_position = player.global_position
    current.level_name = level
    save_game()

## 应用存档 → 游戏状态
func apply(player: Node2D) -> String:
    player.global_position = current.player_position
    return current.level_name

func has_save() -> bool:
    return FileAccess.file_exists(SAVE_PATH)

func delete_save() -> void:
    if FileAccess.file_exists(SAVE_PATH):
        DirAccess.remove_absolute(ProjectSettings.globalize_path(SAVE_PATH))
```

**用法**：

```gdscript
# 存档
SaveManager.capture(player, "level_2")

# 读档
var level := SaveManager.apply(player)
get_tree().change_scene_to_file("res://scenes/%s.tscn" % level)
```

⚠ **路径必须是 `user://`，不能是 `res://`** —— 导出后 `res://` 是只读的，
写盘静默失败（不报错，但存档没了）。审查 GD43 会抓。

⚠ **不要对 Resource 调 `queue_free()`** —— Resource 是 `RefCounted`，
引用归零自动释放，调 Node 的释放 API 是错的。

### 设置项（ConfigFile 方案）

```gdscript
const SETTINGS_PATH := "user://settings.cfg"

func save_settings() -> void:
    var cfg := ConfigFile.new()
    cfg.set_value("audio", "master", 0.8)
    cfg.set_value("audio", "sfx", 0.6)
    cfg.set_value("video", "fullscreen", true)
    var err := cfg.save(SETTINGS_PATH)
    if err != OK:
        push_error("设置保存失败: %d" % err)

func load_settings() -> void:
    var cfg := ConfigFile.new()
    if cfg.load(SETTINGS_PATH) != OK:
        return                          # 首次启动，用默认值
    var master_vol := cfg.get_value("audio", "master", 1.0) as float
    AudioServer.set_bus_volume_db(
        AudioServer.get_bus_index("Master"), linear_to_db(master_vol))
```

## 2. 场景切换

### 带过场（淡入淡出）

```gdscript
# scene_manager.gd —— Autoload，名 SceneManager
extends CanvasLayer

signal transition_finished

@onready var _fade: ColorRect = $ColorRect
@onready var _anim: AnimationPlayer = $AnimationPlayer

func goto_scene(path: String) -> void:
    _anim.play("fade_out")
    await _anim.animation_finished
    var err := get_tree().change_scene_to_file(path)
    if err != OK:
        push_error("场景切换失败 %s: %d" % [path, err])
        return
    _anim.play("fade_in")
    await _anim.animation_finished
    transition_finished.emit()
```

**场景结构**：

```
SceneManager (CanvasLayer)  ← Autoload
├── ColorRect               ← 全屏黑色，mouse_filter = Ignore
└── AnimationPlayer         ← fade_out / fade_in 两个动画，改 ColorRect 的 color.a
```

`ColorRect` 的 `mouse_filter` 必须设 `Ignore`，否则过场期间挡住所有点击。

### 切换时保留数据

```gdscript
# 方式一：Autoload 持有（推荐，简单）
GameState.player_health = 50
get_tree().change_scene_to_file("res://level2.tscn")

# 方式二：切场景前捕获到存档
SaveManager.capture(player, "level2")
```

⚠ `change_scene_to_file` 会**销毁当前场景所有节点**。
要在切之前把需要的数据存到 Autoload 或存档里，不能指望局部变量。

## 3. 事件总线（Autoload）

避免节点之间互相持有引用 —— 那会形成引用环，节点释放了但被环吊住。

```gdscript
# events.gd —— Autoload，名 Events
extends Node

signal player_died
signal score_changed(new_score: int)
signal item_collected(item_id: String, count: int)
signal level_completed(level_name: String, time_seconds: float)
```

**发送方**：

```gdscript
func die() -> void:
    Events.player_died.emit()
```

**接收方**：

```gdscript
extends Node

func _ready() -> void:
    Events.player_died.connect(_on_player_died)
    Events.score_changed.connect(_on_score_changed)

func _exit_tree() -> void:
    # 必须断开！Events 是 Autoload，比本节点活得久，
    # 不断开 = 本节点被 Events 吊住，永远释放不掉
    Events.player_died.disconnect(_on_player_died)
    Events.score_changed.disconnect(_on_score_changed)

func _on_player_died() -> void:
    pass

func _on_score_changed(new_score: int) -> void:
    pass
```

⚠ **Autoload 的信号必须手动断开**。同树父子节点之间，任一方释放时
Godot 会自动断开；但 Autoload 不会自动断（审查 GD15）。

⚠ **C# 不要用 lambda 订阅需要取消的信号** —— 委托身份不保留，
之后没法 `-=`。用具名方法（审查 GD10）。

## 4. 对象池

频繁生成/销毁（子弹、粒子、伤害数字）必须池化，否则 GC 压力明显。

```gdscript
# object_pool.gd
extends Node
class_name ObjectPool

@export var scene: PackedScene
@export var prewarm_count: int = 20

var _available: Array[Node] = []

func _ready() -> void:
    for i in prewarm_count:
        var obj := _create()
        _available.append(obj)

func _create() -> Node:
    var obj := scene.instantiate()
    add_child(obj)                 # 必须入树，否则 _ready 不触发
    obj.set_process(false)
    obj.visible = false
    return obj

func acquire() -> Node:
    var obj: Node
    if _available.is_empty():
        obj = _create()            # 池空了就扩容
    else:
        obj = _available.pop_back()
    obj.set_process(true)
    obj.visible = true
    return obj

func release(obj: Node) -> void:
    # 不要 queue_free！放回池里复用
    obj.set_process(false)
    obj.visible = false
    # 重置状态：池化对象最容易出的 bug 就是残留上一轮的状态
    if obj.has_method("reset"):
        obj.reset()
    _available.append(obj)
```

**子弹用法**：

```gdscript
# bullet.gd
extends Area2D

var _velocity := Vector2.ZERO
var _pool: ObjectPool

func reset() -> void:
    _velocity = Vector2.ZERO
    position = Vector2.ZERO

func launch(from: Vector2, dir: Vector2, speed: float, pool: ObjectPool) -> void:
    position = from
    _velocity = dir * speed
    _pool = pool

func _physics_process(delta: float) -> void:
    position += _velocity * delta

func _on_lifetime_timeout() -> void:
    _pool.release(self)            # 回收，不是 queue_free

func _on_body_entered(_body: Node) -> void:
    _pool.release(self)
```

⚠ 池化对象**必须重置状态**，否则会出现"复用后还带着上一次的速度/血量"。

⚠ `release` 用 `set_process(false)` 而不是 `queue_free()` —— 后者就失去池化意义了。

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/systems.md`

