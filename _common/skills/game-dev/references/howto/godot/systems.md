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

### ⚠ 官方的切换时序：旧场景立刻出树，**新场景帧末才入树**

`change_scene_to_file` / `change_scene_to_packed` / `change_scene_to_node`
三者的操作顺序是同一份（官方在 `change_scene_to_node()` 里写明）：

1. **当前场景节点立即从树中移除** —— 从这一刻起，
   旧场景里调用 `get_tree()` 返回 **null**，`current_scene` 也是 null
2. **到帧末**才删除旧场景，然后把新场景加入树
3. 之后 `get_tree()` / `current_scene` 恢复正常

⚠ 这条解释了一类常见崩溃：**在旧场景的 `_exit_tree()` / 通知回调里调
`get_tree()`，拿到的是 null**。⛔ 不要在那里做"退出前再存一次盘"之类的事。

✅ 要可靠地访问新场景，必须等 `scene_changed` 信号：

```gdscript
func goto(path: String) -> void:
    get_tree().change_scene_to_file(path)
    await get_tree().scene_changed        # ⚠ 不等这行，新场景还没入树
    var lvl := get_tree().current_scene
```

ⓘ 官方保证"两个场景不会同时运行"，所以⛔ 不要试图在切换期间跨场景传引用。

### reload_current_scene 与 Autoload 的重载边界

官方口径：它只是"用原始 PackedScene 的新实例替换 current_scene"。
Autoload **不在重载范围内**，因此不会被重新执行 `_ready()`。

⛔ 后果：Autoload 里用 `@onready var X = $"../Main/..."` 持有 current_scene
内部节点的引用，重载后**全部失效**（指向已释放的对象），
而 Autoload 自己不会重新赋值 —— 表现为"重开一局后各种空引用"。

✅ 正确做法：Autoload 只持有**数据**，节点引用在进入场景时显式注册：

```gdscript
# ❌ Autoload 里这样写，重载后必然失效
@onready var _level: Node = $"../Main/Level"

# ✅ 由场景自己注册，退出时注销
func _enter_tree() -> void:
    GameState.level = self

func _exit_tree() -> void:
    if GameState.level == self:
        GameState.level = null
```

### 异步加载：进度来自 `load_threaded_get_status()` 的 progress 数组

`change_scene_to_file` 会同步加载，大场景会**卡一帧**。要走进度条就得自己来：

```gdscript
var _path := "res://levels/level_2.tscn"
var _progress: Array = []

func start_async_load(path: String) -> void:
    _path = path
    # ⚠ 返回值要接：重复对同一路径请求会返回 ERR_ALREADY_IN_USE
    var err := ResourceLoader.load_threaded_request(_path)
    if err != OK and err != ERR_ALREADY_IN_USE:
        push_error("异步加载请求失败 %s: %d" % [_path, err])

func _process(_d: float) -> void:
    var st := ResourceLoader.load_threaded_get_status(_path, _progress)
    match st:
        ResourceLoader.THREAD_LOAD_IN_PROGRESS:
            if not _progress.is_empty():
                _bar.value = _progress[0] * 100.0   # ⓘ 官方：0.0–1.0 的单元素数组
        ResourceLoader.THREAD_LOAD_LOADED:
            var ps: PackedScene = ResourceLoader.load_threaded_get(_path)
            get_tree().change_scene_to_packed(ps)
            set_process(false)
        ResourceLoader.THREAD_LOAD_FAILED, ResourceLoader.THREAD_LOAD_INVALID_RESOURCE:
            push_error("场景加载失败 %s" % _path)
            set_process(false)
```

⚠ **`load_threaded_get()` 在未完成时会阻塞调用线程**直到加载结束
（见 `howto/godot/openworld.md`）。⛔ 在轮询之外"顺手调一下"，
异步就退化成同步，白做。

ⓘ 小场景几毫秒就加载完，进度条会**闪一下就消失** —— 观感上像卡了一下。
设一个最小展示时间（0.5–1 秒）比"立刻切"更稳。

⚠ `instantiate()` **必须在主线程**。真正的大头常常不是加载而是实例化
（见 `howto/godot/openworld.md#Chunk 流式加载`）。

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

> **反模式清单（不能怎么做，审核用）** → `audit/godot/systems.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-08`　常见架构模式速查
