# Godot 4.x 多人游戏与服务器权威

**客户端权威 = 默认可作弊。** 多人游戏的第一原则是：客户端只发"我做了什么"，服务端算结果。

## 0. 先定架构

```
客户端权威（错）               服务器权威（对）
─────────────────             ─────────────────
客户端算结果 → 广播            客户端发意图 → 服务端算 → 同步状态
"我打死了 Boss，扣 100 血"      "我在这个位置按了攻击"
        ↓                              ↓
   谁都能改   

    服务端校验合法性
```

**任何从客户端来的数据都不可信** —— 这不是建议，是架构约束。

⚠ 单机游戏"防作弊"靠提高修改成本（见 `security.md`）；
联网游戏唯一可靠的是服务端权威。两者不是一回事。

## 1. 基础 API

```gdscript
# 建立连接（ENet）
func _ready() -> void:
    multiplayer.peer_connected.connect(_on_peer_connected)
    multiplayer.peer_disconnected.connect(_on_peer_disconnected)
    multiplayer.connected_to_server.connect(_on_connected_ok)
    multiplayer.server_disconnected.connect(_on_server_disconnected)

func host(port: int = 7000) -> void:
    var peer := ENetMultiplayerPeer.new()
    var err := peer.create_server(port)
    if err != OK:
        push_error("监听失败: %d" % err)
        return
    multiplayer.multiplayer_peer = peer

func join(addr: String, port: int = 7000) -> void:
    var peer := ENetMultiplayerPeer.new()
    if peer.create_client(addr, port) != OK:
        push_error("连接失败")
        return
    multiplayer.multiplayer_peer = peer
```

**常用查询**：

```gdscript
multiplayer.is_server()                  # 是否是服务端
multiplayer.get_unique_id()              # 自己的 peer id（服务端恒为 1）
multiplayer.get_peers()                  # 其他 peer id 列表
node.get_multiplayer_authority()         # 该节点由谁控制
node.set_multiplayer_authority(id, true) # 转移控制权（true=递归子节点）
```

⚠ `set_multiplayer_authority()` **只改本地关系，不会广播**。
必须自己用 RPC 通知，或走 Synchronizer 复制。

⚠ 父节点设了 authority，**后来新增的子节点不会自动继承** —— 要显式设。

### @rpc 注解

```gdscript
@rpc("any_peer", "call_remote", "unreliable_ordered", 0)
func submit_input(seq: int, dir: Vector2) -> void:
    ...
```

| 参数 | 取值 | 含义 |
|---|---|---|
| mode | `authority`（默认）/ `any_peer` | 谁有权调用 |
| call | `call_remote`（默认）/ `call_local` | 是否在本地也执行 |
| transfer | **`reliable`（默认）** / `unreliable` / `unreliable_ordered` | 传输模式 |
| channel | `0`（默认） | 通道 |

⚠ **默认值是 `authority` + `call_remote` + `reliable`**（官方文档明确：
`@rpc` 等价于 `@rpc("authority", "call_remote", "reliable", 0)`）。

⚠ **客户端调用 authority 的 RPC 会被静默忽略** —— 不报错，什么也不发生。
想让客户端上报输入，必须显式写 `@rpc("any_peer", ...)`。

⚠ **默认 `reliable` 是个性能陷阱**：每帧位置同步如果忘了写
`unreliable_ordered`，会走可靠通道 —— 丢包重传会让位置越来越滞后。
高频同步**必须显式声明**传输模式。

⚠ `any_peer` 是**攻击面**，不是便利。任何人都能调，必须校验发送者：

```gdscript
@rpc("any_peer", "call_remote", "reliable")
func request_buy(item_id: StringName) -> void:
    var sender := multiplayer.get_remote_sender_id()
    if sender == 0:
        return                        # 0 = 本地调用，不是远程
    if not _can_buy(sender, item_id):
        return                        # 服务端校验：余额、冷却、合法性
    _grant(sender, item_id)
```

⚠ **`await` 之后 `get_remote_sender_id()` 会变回 0**。
RPC 一进来就要存下 sender，别等 await 完再取。

⚠ RPC 的**节点路径 + 方法名 + 参数**两端必须完全一致。
动态 `add_child()` 的节点要用可读的固定名字，别用自动生成的 `@Node@2`。

### 传输模式怎么选

| 场景 | 模式 | 理由 |
|---|---|---|
| 每帧位置/朝向 | `unreliable_ordered` | 丢一帧无所谓，下一帧就补上 |
| 输入流 | `unreliable_ordered` | 但要带序号，靠确认+重放兜底 |
| 聊天、交易、开箱 | `reliable` | 不能丢 |
| 技能释放 | `reliable` | 不能丢，且频率低 |

⚠ **别把所有东西都设 `reliable`** —— 重传和队头阻塞会放大延迟，
高频数据用 reliable 会让卡顿雪崩。

⚠ **`WebRTCMultiplayerPeer` 默认是全网格（mesh）**，⛔ 不能当 ENet 用。
每个 peer 都要和其他所有 peer 建立连接，
连接数是 **N² 级** —— 4 人时 6 条，10 人时 45 条。
ⓘ 它适合**少量 peer 的 P2P**；人数一多，带宽和连接建立开销都会失控，
这时应走 ENet + 专用服务器的客户端-服务器模型。

## 2. 场景与状态复制

### MultiplayerSpawner

```gdscript
# 挂在服务端场景上，登记可生成的场景
@onready var _spawner: MultiplayerSpawner = $MultiplayerSpawner

func _ready() -> void:
    _spawner.spawn_path = NodePath(".")      # 生成到哪
    _spawner.add_spawnable_scene("res://scenes/player.tscn")

func spawn_player(id: int) -> void:
    var p := preload("res://scenes/player.tscn").instantiate()
    p.name = str(id)                          # 必须：名字要稳定
    add_child(p, true)
    p.set_multiplayer_authority(id, true)
```

⚠ `add_spawnable_scene()` 只登记"哪些场景可被生成"，
**不能用来远程删除**。`clear_spawnable_scenes()` 也不清已有实例。

### MultiplayerSynchronizer

```gdscript
# 挂在要同步的节点上
@onready var _sync: MultiplayerSynchronizer = $MultiplayerSynchronizer

func _ready() -> void:
    _sync.set_multiplayer_authority(1)        # 服务端权威
    _sync.replication_interval = 0.03         # 约 33Hz
```

⚠ **Synchronizer 不插值**。它只周期复制属性值，
收到的值直接套上去会抖 —— 平滑要自己做（见第 4 节）。

⚠ `replication_interval = 0` 表示**每个 network process 帧都同步**，
不是"最快最好" —— 会把带宽和 CPU 打满。

⚠ 属性可见性：`public` 所有人可见，`private` 只有 authority 可见。
用它做兴趣管理（比如只同步玩家附近的实体）。

## 3. 输入上报（服务器权威核心）

**最小单元是「序号 + 意图 + 采集时刻」**，裸 Vector 不够 —— 没有序号就没法回滚。

```gdscript
# ---- 客户端 ----
extends CharacterBody2D

const MAX_QUEUE := 120

var _input_seq := 0
var _pending: Array = []              # [{seq, input,}]
var _last_processed := -1
var _auth_state: Dictionary = {}

func _physics_process(delta: float) -> void:
    if not is_multiplayer_authority():
        return                         # 只处理本地控制的角色
    var dir := Vector2(
        Input.get_axis("ui_left", "ui_right"),
        Input.get_axis("ui_up", "ui_down")
    ).limit_length(1.0)

    _input_seq += 1
    _pending.push_back({"seq": _input_seq, "input": dir})
    if _pending.size() > MAX_QUEUE:
        push_warning("输入缓冲溢出，从权威状态重置")
        _pending = []
        _rewind()
    submit_input.rpc_id(1, _input_seq, dir)
    _apply_input(dir, delta)           # 客户端预测

@rpc("authority", "call_remote", "unreliable_ordered")
func apply_authorized_state(last_seq: int, pos: Vector2, vel: Vector2) -> void:
    _last_processed = last_seq
    _auth_state = {"position": pos, "velocity": vel}
    _pending = _pending.filter(func(it): return it["seq"] > last_seq)
    _rewind()

func _rewind() -> void:
    global_position = _auth_state.get("position", global_position)
    velocity = _auth_state.get("velocity", velocity)
    # 重放所有未确认输入
    for it in _pending:
        _apply_input(it["input"], get_physics_process_delta_time())

func _apply_input(dir: Vector2, delta: float) -> void:
    velocity = dir * 240.0
    move_and_slide()
```

```gdscript
# ---- 服务端 ----
extends CharacterBody2D

var _last_input_seq := 0

@rpc("any_peer", "call_remote", "unreliable_ordered")
func submit_input(seq: int, dir: Vector2) -> void:
    var sender := multiplayer.get_remote_sender_id()
    if sender == 0 or sender != get_multiplayer_authority():
        return                                   # 校验发送者
    if seq <= _last_input_seq:
        return                                   # 重放/乱序，丢弃
    dir = dir.limit_length(1.0)                  # 校验范数（防加速）
    if not (is_finite(dir.x) and is_finite(dir.y)):
        return                                   # 校验 NaN/Inf
    _last_input_seq = seq
    _apply_input(dir, get_physics_process_delta_time())
    apply_authorized_state.rpc_id(sender, seq, global_position, velocity)
```

⚠ 服务端必须先**校验范数**（`limit_length(1.0)`）——
客户端传 `Vector2(999,999)` 就是加速器。

⚠ 服务端模拟要**固定 timestep**（`Engine.physics_ticks_per_second`），
否则两端重放结果不一致，回滚会产生永久抖动。

## 4. 快照缓冲与插值

Synchronizer 同步的是**服务端过去某个时刻**的状态，直接套用会让画面回退。

```gdscript
class_name SnapshotBuffer
extends RefCounted

var _snaps: Array = []          # [{tick, state}]
var _delay := 0.1               # 缓冲 100ms，容忍抖动

func push(tick: int, state: Dictionary) -> void:
    _snaps.push_back({"tick": tick, "state": state})
    _snaps.sort_custom(func(a, b): return a["tick"] < b["tick"])
    while _snaps.size() > 64:
        _snaps.pop_front()

## 取"当前时间 - 延迟"处的插值状态
func sample(now: float) -> Dictionary:
    var render_time := now - _delay
    for i in range(_snaps.size() - 1):
        var a := _snaps[i]
        var b := _snaps[i + 1]
        if a["tick"] <= render_time and render_time <= b["tick"]:
            var t := (render_time - a["tick"]) / maxf(b["tick"] - a["tick"], 0.0001)
            return _lerp_state(a["state"], b["state"], t)
    if _snaps.is_empty():
        return {}
    return _snaps[-1]["state"]

func _lerp_state(a: Dictionary, b: Dictionary, t: float) -> Dictionary:
    var out := {}
    for k in a:
        var va = a[k]
        var vb = b.get(k, va)
        if va is Vector2 and vb is Vector2:
            out[k] = va.lerp(vb, t)
        elif va is float and vb is float:
            out[k] = lerpf(va, vb, t)
        else:
            out[k] = vb
    return out
```

⚠ **延迟是必要的代价**。缓冲越长越平滑但越滞后，
通常 100ms 是手感与平滑的折中点，要按实测调。

⚠ 自己的角色**不做插值时可以直接预测**，但其他玩家必须插值，
否则他们的移动会一跳一跳。

## 5. authority 迁移（载具、观战、断线接管）

```gdscript
func transfer_authority(node: Node, new_id: int) -> void:
    if not multiplayer.is_server():
        return
    if node.get_multiplayer_authority() != multiplayer.get_unique_id():
        push_error("只有当前 authority 能发起转移")
        return
    node.set_multiplayer_authority(new_id, true)
    authority_changed.rpc(node.get_path(), new_id)

@rpc("authority", "call_remote", "reliable")
func authority_changed(node_path: NodePath, new_id: int) -> void:
    var node := get_node_or_null(node_path)
    if node == null:
        return
    if node.get_multiplayer_authority() != new_id:
        push_warning("本地 authority 不一致，等权威状态纠正")
```

⚠ 迁移消息到达前，客户端可能**短暂没有合法输入者**。
要标 `pending_transfer` 状态，拒绝预测或缓存最后合法输入。

## 6. 专用服务器

```bash
# 导出
godot --headless --export-release "Linux/X11" build/server.x86_64
# 运行
./server.x86_64 --headless
```

⚠ **`--headless` 只是无显示模式，不会裁剪资源**。
要真正瘦身得用 Dedicated Server 导出预设（可 Strip Visuals）。

```gdscript
func _enter_tree() -> void:
    if OS.has_feature("dedicated_server"):
        _load_server_world()      # 只有逻辑
    else:
        _load_client_frontend()   # 有 UI / 相机 / 音效
```

⚠ 服务器场景**不要包含** UI、相机、输入捕获、粒子、音效。
推荐直接分两个场景文件：`WorldServer.tscn` / `WorldClient.tscn`，
逻辑节点路径保持一致。

⚠ 服务端别在 RPC 回调里做阻塞 IO / 睡眠 / 长循环。
数据库、验证、排行榜走队列，后台线程完成后回主线程应用。

## 7. 服务端校验什么

| 数据 | 校验 |
|---|---|
| 移动 | 速度上限、位置连续性（防瞬移） |
| 伤害 | 冷却、射程、弹药、合法性 |
| 经济 | 余额、物品是否存在、交易幂等 |
| 时间 | **用服务端时钟**，不收客户端时间 |
| 数值 | 上限（金币不能超过产出总和） |

⚠ **权威服务器 ≠ 自动反作弊**。它只是"你能执行服务端代码"。
仍需要：账号认证、限流、审计日志、服务端规则、幂等事务。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/multiplayer.md`


## 上线前检查

- [ ] 所有 `any_peer` RPC 都校验了 sender 与业务合法性
- [ ] 输入做了范数/NaN/序号校验
- [ ] 服务端固定 tick，客户端重放结果一致
- [ ] 其他玩家用了快照插值，不是直接套值
- [ ] 关键数据（经济、伤害、胜负）只在服务端计算
- [ ] 断线走 `peer_disconnected` 清理，不靠 RPC 失败
- [ ] 专用服务器不含 UI/相机/输入节点
- [ ] 用 `--headless` 导出并实测能跑
- [ ] 造过"客户端作弊"测试：改内存/伪造 RPC 应被服务端拒绝
- [ ] 高延迟（150ms+）和丢包（5%）下实测过手感
