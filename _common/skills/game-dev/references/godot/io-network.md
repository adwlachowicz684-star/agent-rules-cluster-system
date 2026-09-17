# Godot 4.x 资源加载与网络

存档与场景切换在 `systems.md`，本文件覆盖动态资源加载、HTTP 请求、多人联机基础。

## 1. 资源加载

### load vs preload

```gdscript
# preload：解析期加载，脚本一加载就好。必须是常量路径
const BULLET := preload("res://scenes/bullet.tscn")

# load：运行时加载，路径可以是变量
var tex := load("res://assets/%s.png" % name)
```

| | `preload` | `load` |
|---|---|---|
| 时机 | 解析期（脚本加载时） | 调用时 |
| 路径 | 必须字面量 | 可以是变量 |
| 失败 | 解析期就报错 | 返回 null |

⚠ 循环依赖：A `preload` B、B `preload` A 会报错。改用 `load` 打破。

### 缓存语义

**同路径的 `load()` 返回同一份资源对象**（有缓存）。
改了这个对象，所有用它的地方都受影响 —— 与 3D 共享材质是同一个坑。

```gdscript
var a := load("res://mat.tres")
var b := load("res://mat.tres")
print(a == b)        # true，是同一个对象
```

要独立副本：`.duplicate()`。

### 线程加载（大资源不卡主线程）

```gdscript
signal load_finished(res: Resource)

func load_async(path: String) -> void:
    var err := ResourceLoader.load_threaded_request(path)
    if err != OK:
        push_error("加载请求失败: %d" % err)
        return
    set_process(true)

func _process(_delta: float) -> void:
    var status := ResourceLoader.load_threaded_get_status(path)
    match status:
        ResourceLoader.THREAD_LOAD_LOADED:
            var res := ResourceLoader.load_threaded_get(path)
            set_process(false)
            load_finished.emit(res)
        ResourceLoader.THREAD_LOAD_FAILED:
            push_error("加载失败: %s" % path)
            set_process(false)
        _:
            pass       # 还在加载中，可以继续更新进度条
```

**带进度条的加载界面**：

```gdscript
func _process(_delta: float) -> void:
    var progress := []
    ResourceLoader.load_threaded_get_status(path, progress)
    if progress.size() > 0:
        _bar.value = progress[0]      # 0.0 .. 1.0
```

### CacheMode

```gdscript
# 默认 REUSE：有缓存就用缓存
ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_REUSE)

# REPLACE：强制重新加载并替换缓存（热更新用）
ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_REPLACE)

# IGNORE：不进缓存（一次性大图）
ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_IGNORE)
```

### 释放

资源是 `RefCounted`，引用归零自动释放。手动清缓存：

```gdscript
# 场景卸载后调用，避免内存常驻
func _exit_tree() -> void:
    # 让引用归零即可，不要对 Resource 调 queue_free()
    _loaded_tex = null
```

⚠ **不要对 Resource 调 `queue_free()` / `free()`** —— Resource 不是 Node，
它是 RefCounted，引用归零自动释放。调 Node 的释放 API 是错的。

## 2. 文件读写（补充 systems.md）

```gdscript
# 写
func write_text(path: String, content: String) -> bool:
    var f := FileAccess.open(path, FileAccess.WRITE)
    if f == null:
        push_error("打开失败: %d" % FileAccess.get_open_error())
        return false
    f.store_string(content)
    f.close()                  # 必须关
    return true

# 读
func read_text(path: String) -> String:
    if not FileAccess.file_exists(path):
        return ""
    var f := FileAccess.open(path, FileAccess.READ)
    if f == null:
        return ""
    var content := f.get_as_text()
    f.close()
    return content
```

⚠ `FileAccess.open()` 失败返回 **null**（4.x 不是返回对象再判 error）。
不判 null 直接 `f.store_string()` 会崩。

⚠ 路径规则：`res://` 导出后**只读**，`user://` 可写（审查 GD43）。

**各平台 user:// 实际位置**：

| 平台 | 路径 |
|---|---|
| Windows | `%APPDATA%\<项目名>\` |
| macOS | `~/Library/Application Support/<项目名>/` |
| Linux | `~/.local/share/<项目名>/` |
| Android | `/data/data/<包名>/files/` |
| Web | IndexedDB（有配额限制） |

```gdscript
print(ProjectSettings.globalize_path("user://"))    # 打印真实路径，调试用
```

## 3. HTTP 请求

```gdscript
# api_client.gd
extends Node

signal request_completed(data: Variant)
signal request_failed(code: int)

const BASE_URL := "https://api.example.com"

var _http: HTTPRequest

func _ready() -> void:
    _http = HTTPRequest.new()
    add_child(_http)                       # 必须入树，否则不处理请求
    _http.request_completed.connect(_on_completed)
    _http.timeout = 10.0

func get_json(path: String) -> void:
    var err := _http.request(BASE_URL + path,
                             ["Content-Type: application/json"],
                             HTTPClient.METHOD_GET)
    if err != OK:
        push_error("请求发起失败: %d" % err)

func post_json(path: String, body: Dictionary) -> void:
    var json := JSON.stringify(body)
    var err := _http.request(BASE_URL + path,
                             ["Content-Type: application/json"],
                             HTTPClient.METHOD_POST, json)
    if err != OK:
        push_error("请求发起失败: %d" % err)

func _on_completed(result: int, response_code: int,
                  _headers: PackedStringArray, body: PackedByteArray) -> void:
    if result != HTTPRequest.RESULT_SUCCESS:
        request_failed.emit(result)
        return
    if response_code < 200 or response_code >= 300:
        request_failed.emit(response_code)
        return

    var json := JSON.new()
    if json.parse(body.get_string_from_utf8()) != OK:
        push_error("JSON 解析失败")
        return
    request_completed.emit(json.data)
```

⚠ `HTTPRequest` **必须 `add_child()`** —— 不进树不会处理请求（审查 GD47）。

⚠ 回调签名是 `(result, response_code, headers, body)` 四个参数，顺序不能变。

### 下载文件

```gdscript
func download(url: String, save_to: String) -> void:
    _http.download_file = save_to          # 设置后直接写盘，不占内存
    _http.download_chunk_size = 65536      # 64KB 分块
    _http.request(url)
```

⚠ 大文件用 `download_file` 直接写盘，不要 `get_string_from_utf8()` 全读进内存。

### 取消

```gdscript
func cancel() -> void:
    _http.cancel_request()
```

## 4. 多人联机（基础）

Godot 4 的高层多人 API：`ENetMultiplayerPeer` + `@rpc` + `MultiplayerSpawner`。

### 建立连接

```gdscript
# network.gd —— Autoload
extends Node

const PORT := 7000
const MAX_PLAYERS := 4

var peer := ENetMultiplayerPeer.new()

func host() -> Error:
    var err := peer.create_server(PORT, MAX_PLAYERS)
    if err != OK:
        return err
    multiplayer.multiplayer_peer = peer
    multiplayer.peer_connected.connect(_on_peer_connected)
    return OK

func join(address: String) -> Error:
    var err := peer.create_client(address, PORT)
    if err != OK:
        return err
    multiplayer.multiplayer_peer = peer
    multiplayer.connected_to_server.connect(_on_connected)
    return OK

func _on_peer_connected(id: int) -> void:
    print("玩家加入: %d" % id)
```

### RPC

```gdscript
# 客户端调用，在所有端执行（由调用者的权限决定）
@rpc("any_peer", "call_local", "reliable")
func request_shoot(dir: Vector2) -> void:
    var sender_id := multiplayer.get_remote_sender_id()
    # 关键：any_peer 意味着任何人都能调，必须校验
    if not is_valid_shooter(sender_id):
        push_warning("非法调用 from %d" % sender_id)
        return
    spawn_bullet(dir)

# 只在服务器执行，结果同步
@rpc("authority", "call_remote", "reliable")
func apply_damage(amount: int) -> void:
    health -= amount
```

⚠ **`any_peer` 的 RPC 是不可信输入边界** —— 客户端可以任意构造参数。
服务端必须校验（权限、数值范围、冷却时间）。

### MultiplayerSpawner / Synchronizer

4.x 新增，省掉手写同步：

- `MultiplayerSpawner`：配置 `spawn_path` 与自动生成场景，服务器 `add_child` 时自动同步到客户端
- `MultiplayerSynchronizer`：配置要同步的属性，自动复制

```gdscript
# 服务器生成敌人 → 客户端自动出现
func spawn_enemy(pos: Vector2) -> void:
    if not multiplayer.is_server():
        return
    var e := ENEMY_SCENE.instantiate()
    e.position = pos
    _spawner_root.add_child(e, true)      # true = 强制名字，用于同步
```

⚠ 同步属性要配置在 `MultiplayerSynchronizer` 的 replication 列表里，
只写 `@export` 不会自动同步。

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| `HTTPRequest` 未 `add_child` | 请求不执行 | GD47 |
| `FileAccess.open()` 不判 null | 崩 | 人工 |
| `FileAccess` 未 `close()` | 句柄泄漏 | GD41 |
| 写 `res://` | 导出后静默失败 | GD43 |
| Resource 调 `queue_free()` | 错的，它是 RefCounted | 人工 |
| `any_peer` RPC 不校验 | 客户端可作弊 | 人工 |
| 大文件不用 `download_file` | 全读进内存 | 人工 |
| 循环 `preload` | 解析期报错 | 人工 |
| 改了 load 出来的共享资源 | 所有引用处一起变 | 人工 |
