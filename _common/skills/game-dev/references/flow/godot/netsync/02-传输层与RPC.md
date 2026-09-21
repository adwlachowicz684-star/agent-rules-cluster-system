# 02 传输层与 RPC（网络同步域）

> **前置**：01 已选定同步模型
> **本步交付**：连接能建立、RPC 参数**显式声明**、通道选型正确
> **对应**：做法 `howto/godot/multiplayer.md` `netsync-advanced.md` · 审核 `audit/godot/multiplayer.md` `netsync-advanced.md`

## 0. 交付物定义

⚠ 本步有两个"默认即错"的坑，是本域最高频的事故源：

1. `@rpc` 默认 `reliable` —— 高频同步走可靠通道会**越来越滞后**
2. `@rpc` 默认 `authority` —— 客户端调用**被静默忽略，不报错**

做完这一步，应该能**当场演示**：

1. 服务端能监听、客户端能连上、断线有回调
2. ⚠ 全项目**没有一个** `@rpc` 是裸写不写参数的
3. 高频数据（位置/输入）走 `unreliable_ordered`，关键事件走 `reliable`
4. `get_remote_sender_id()` 只在 RPC 函数内用，跨帧已存局部变量
5. 目标平台与传输层匹配（⛔ 不是到导出 Web 才发现 ENet 不能用）

**产出物**（下游按名字对接）：

```text
ENetMultiplayerPeer 的 host() / join()
每个 @rpc 的显式参数（mode / sync / transfer / channel）
_get_sender() 存局部变量的写法
```

## 1. 前置检查清单

- [ ] 01 的同步模型已选定
- [ ] ⚠ 已确认目标平台（Web 平台 **ENet 不可用**）
- [ ] ⛔ 已确认**没有**裸写 `@rpc`（不写参数）
- [ ] 已确认高频/低频数据的通道分工
- [ ] 已确认 `set_multiplayer_authority()` **不会广播**（要自己通知）

## 2. 工序

### Step 1　建立连接与四个回调　`[netsync/02#S1]`

【读】`howto/godot/multiplayer.md#1. 基础 API`

【做】
```gdscript
func _ready() -> void:
    multiplayer.peer_connected.connect(_on_peer_connected)
    multiplayer.peer_disconnected.connect(_on_peer_disconnected)
    multiplayer.connected_to_server.connect(_on_connected_ok)
    multiplayer.server_disconnected.connect(_on_server_disconnected)
```

⚠ 四个回调**都要接**。只接 `peer_connected` 的话，
断线时不会清理，会留下孤儿实体（见 06）。

【产出】连接/断开/连上/服务断 四个回调都有处理

【判据】⚠ 强杀客户端进程，服务端**收到** `peer_disconnected` 并清理

【审】`audit/godot/multiplayer.md`

### Step 2　⚠ @rpc 必须显式写参数　`[netsync/02#S2]`

【读】`howto/godot/netsync-advanced.md#3. `@rpc` 深入` 的「默认值（官方文档明确）」

【做】
```gdscript
@rpc   # ⛔ 等价于 @rpc("authority", "call_remote", "reliable", 0)
```

⚠ **默认 `reliable` 是性能陷阱**。每帧位置同步忘了写 `unreliable_ordered`
就走可靠通道——丢包重传会让位置**越来越滞后**。

⚠ 默认 `authority` 意味着**客户端调用会被静默忽略，不报错**。
要客户端上报输入必须显式写 `@rpc("any_peer", ...)`。

| 场景 | 用什么 |
|---|---|
| 每帧位置/朝向 | `unreliable_ordered` + 带序号 |
| 输入流 | `unreliable_ordered` + 确认/重放兜底 |
| 命中、死亡、生成、拾取 | `reliable` |

【产出】全项目 `@rpc` 均显式声明四参数

【判据】⚠ 全项目搜索 `@rpc\n`（后面直接换行）结果为 **0**

【审】`audit/godot/netsync-advanced.md`

### Step 3　channel 必须放最后　`[netsync/02#S3]`

【读】`howto/godot/netsync-advanced.md#3. `@rpc` 深入` 的「各参数」

【做】
```
mode: authority / any_peer
sync: call_remote / call_local
transfer: reliable / unreliable / unreliable_ordered
channel: 0        ← ⚠ 必须最后
```

前三个顺序任意，`transfer_channel` 必须最后。

【产出】所有注解的参数顺序合法

【判据】⚠ 项目能正常启动、RPC 不报解析错误

【审】`audit/godot/netsync-advanced.md`

### Step 4　get_remote_sender_id 只在函数内有效　`[netsync/02#S4]`

【读】`howto/godot/netsync-advanced.md#3. `@rpc` 深入` 的「`get_remote_sender_id()` 的坑」

【做】
```gdscript
@rpc("any_peer", "call_remote", "reliable")
func submit_input(data: Dictionary) -> void:
    var sender := multiplayer.get_remote_sender_id()   # ✅ 这里有效
    await get_tree().process_frame
    var s2 := multiplayer.get_remote_sender_id()       # ❌ 变回 0
```

⚠ **只在 RPC 处理函数内有效**，`await` 之后或函数外会失效（变成 0）。
要跨帧使用必须**先存成局部变量**。

【产出】所有跨帧使用处都已存局部变量

【判据】⚠ 在 RPC 里 await 一帧后打印 sender，**不是 0**

【审】`audit/godot/netsync-advanced.md`

### Step 5　传输层与平台匹配　`[netsync/02#S5]`

【读】`howto/godot/netsync-advanced.md#4. 传输层：ENet / WebSocket / WebRTC`

【做】三选一：

| | 适合 | 限制 |
|---|---|---|
| **ENet**（默认） | 原生桌面、低延迟 | UDP 之上，同时提供可靠/不可靠通道 |
| **WebSocket** | Web 导出的常用选择 | 底层 TCP，**队头阻塞** |
| **WebRTC** | 绕开防火墙、P2P | 必须自建信令、ICE、STUN/TURN |

⚠ **Web 平台基本只能用 WebSocket 或 WebRTC**，ENet 不可用。
**导出到 Web 前就要定传输层，不能后期换。**

⚠ WebSocket 的 TCP 队头阻塞会让"丢了的位置包"堵住后面的关键包。

【产出】传输层已选定且与导出平台一致

【判据】⚠ 实际导出到目标平台**能连上**（⛔ 不是只在编辑器里通）

【审】`audit/godot/netsync-advanced.md`

### Step 6　MTU 与最大包大小是两个概念　`[netsync/02#S6]`

【读】`howto/godot/netsync-advanced.md#2. 延迟补偿（核心）` 的「2.0.2 ⚠ ENet 的 MTU 与最大包大小是两个概念」

【做】`ENET_HOST_DEFAULT_MTU = 1400`（影响链路层如何分片/传输单个数据报），
`ENET_HOST_DEFAULT_MAXIMUM_PACKET_SIZE = 32MB`（只是 ENet 层允许的上限）。

⚠ **不能混读** —— 前者是实际传输的分片单位，后者只是保护性上限。
照 32MB 设计单个包，会在链路上被反复分片，丢一片就整个包废掉。

【产出】单个快照/输入包的大小控制在 MTU 量级

【判据】⚠ 打印单个数据包字节数，**远小于 1400**（或已确认分片策略）

【审】`audit/godot/netsync-advanced.md`

## 3. 参考实现

```gdscript
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

# ⚠ 显式四参数，缺一不可
@rpc("any_peer", "call_remote", "unreliable_ordered", 0)
func submit_input(seq: int, input: Vector2) -> void:
    var sender := multiplayer.get_remote_sender_id()   # ✅ 立刻存
    _validate_and_apply(sender, seq, input)            # 校验后交给服务端逻辑

@rpc("authority", "call_remote", "unreliable_ordered", 0)
func apply_authorized_state(last_seq: int, pos: Vector2, vel: Vector2) -> void:
    ...
```

⚠ `set_multiplayer_authority()` **只改本地关系，不会广播**——
必须自己用 RPC 通知，或走 Synchronizer 复制（见 06）。

⚠ 父节点设了 authority，**后来新增的子节点不会自动继承** —— 要显式设。

## 4. 验收清单

- [ ] 四个连接回调都接了
- [ ] 全项目无裸写 `@rpc`
- [ ] 位置/输入走 `unreliable_ordered`，关键事件走 `reliable`
- [ ] channel 参数在最后
- [ ] `get_remote_sender_id()` 跨帧处已存局部变量
- [ ] 传输层与导出平台匹配（⛔ 不是只在编辑器通）
- [ ] 单包大小远小于 MTU

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 位置同步越来越滞后 | 高频数据走了 reliable | S2 |
| 客户端调 RPC 没反应也不报错 | 默认 authority | S2 |
| await 后 sender 变 0 | 没存局部变量 | S4 |
| 导 Web 后连不上 | 用了 ENet | S5 |
| 大包丢一片全废 | 按 32MB 设计 | S6 |
| 断线后实体残留 | 没接 peer_disconnected | S1 |

## 6. 下一步

→ **03 服务器权威与输入上报**

## 7　整体审核（功能点级收尾）

ⓘ 各 Step 的【审】是**步骤级即时检查**；本节是**功能点级复查**，两级都要走。

- [ ] 逐条过 `audit/godot/multiplayer.md` 与 `audit/godot/netsync-advanced.md`，
      每条说出"我们是怎么避免的" — ⛔ 不能"应该没这个问题"
- [ ] 步骤级【审】列过的条目**再过一遍**
- [ ] ⚠ 实测参数已回填，⛔ 不留示例值
- [ ] 若属大功能 → ⚠ **还要集成验收**：各部件合格 ≠ 拼起来能用
