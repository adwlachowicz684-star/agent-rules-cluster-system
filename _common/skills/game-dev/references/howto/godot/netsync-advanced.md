# Godot 4.x 网络同步进阶

基础 `@rpc` 与节点用法见 `multiplayer.md`。
本文讲**同步模型选型、延迟补偿、传输层取舍**——
联机游戏真正难的部分，也是 Godot 内置组件**不覆盖**的部分。

## 0. 一句话定位

**Godot 解决"把状态送到对端"，但不替你消除网络往返。**

`MultiplayerSpawner` / `MultiplayerSynchronizer` 只是**状态同步的自动复制器**。
预测、回滚、插值、锁步、时钟同步——**全部没有内置**，要自己写。

| 需求 | 内置能做 | 要自建 |
|---|---|---|
| 生成/销毁同步 | ✅ | 权限、白名单、断线清理 |
| 同步已配置属性 | ✅ | tick、压缩、增量、插值 |
| **本地玩家零等待移动** | ❌ | 客户端预测 + 输入历史 |
| **服务器纠正错误预测** | ❌ | 序号、确认、回滚重放 |
| **远端玩家平滑** | ❌ | 固定延迟缓冲 + 插值 |
| **命中回滚判定** | ❌ | 历史快照 + 延迟估计 |
| 客户端输入收集 | ❌ | 输入快照、序号、节流 |

## 1. 同步模型选型

| 模型 | 传什么 | 适合 | 代价 |
|---|---|---|---|
| **权威状态同步** | 位置/朝向/血量等结果 | FPS、MMO、生存、大世界 | 快照带宽、纠错 |
| **确定性锁步** | 每 tick 输入 + 种子 | RTS、回合制、棋牌 | 等最慢玩家、浮点极敏感 |
| **输入同步 + 预测回滚** | 输入 + 序号 + 确认 | FPS、MOBA、格斗 | 历史保存、重放、调试成本 |
| **客户端权威** | 角色状态 | 同机、休闲合作 | **极易被篡改**，不适合竞技 |
| **纯事件 RPC** | "造成伤害""拾取" | UI、动画、低频事件 | 不能单独消除抖动 |

⚠ **模型名称只是架构缩写，实际项目经常是混合体**：
服务器权威计算 + 客户端本地预测 + 远端实体插值 + 技能按固定 tick + 生成事件用可靠 RPC。

### 为什么 RTS 用锁步而 FPS 用状态同步

**RTS**：单位成百上千，逐属性发位置会吃光带宽；只发输入包量极小。
而且 RTS 常需要回放/观战，确定性模拟天生提供。

**FPS**：等最慢玩家 = 快玩家替慢玩家卡顿。
玩家更容忍"看到的快照略微过期"，所以服务器持有权威世界、客户端预测自己、远端插值。

⚠ **Godot 没有承诺跨平台跨版本逐帧确定性**。
浮点、容器遍历顺序、加载顺序、`_process` 与 `_physics_process` 差异、
信号触发顺序都可能改变结果。**锁步要自己做确定性保证**，引擎不会帮你。

### 内置组件的硬限制

⚠ `MultiplayerSynchronizer` **不能同步 `Resource` 等 `Object` 类型属性**，
也不能同步每端唯一的实例 ID 或 `RID`。

要把背包 Resource、另一个 Node、物理 RID 拆成**可序列化 ID / 字典 / 数组**，
让两端各自查回来。

## 2. 延迟补偿（核心）

### 2.0 ⚠ 回滚时哪些东西不能回滚

**音效、粒子、镜头震动、伤害数字、任务计数、UI 提示是纯副作用，
不能跟随模拟状态回滚。**

⚠ 客户端在预测第 1002 帧播放"开火声"，回滚到 998 帧重放 1002 帧，
**同一个输入又会触发一次开火声** → 音效重复、粒子重复、震屏叠加。

应对：
- 音效 ID 用 `(player_id, input_seq, effect_type)`，**服务器确认后才真正播放**
- 若需要"按下即反馈"，区分 `predicted_sfx` 与 `confirmed_sfx`：
  预测音效只播**短促、可打断、无持续逻辑**的声音
- ⚠ **绝不能把射击命中结算、任务奖励、冷却开始等可累加逻辑放进预测副作用**

**回滚快照的内容**：模拟 tick、随机生成器状态、确定实体数组、
输入游标、计时器、事件队列。
⚠ 纹理/模型/节点引用/音频总线/粒子状态**不参与**确定模拟，
完整场景序列化既慢又容易包含不可序列化对象。

### 2.0.1 快照必须打发送端时钟

⚠ **快照在发送端打上模拟时钟，不能让接收端用到达时间** ——
否则网络早到/晚到/乱序会直接改变世界。

包内携带 `tick` / `server_time` / `entity_id` / 位置 / 速度 / 状态 / 版本号。
接收时刻只用于统计 RTT/抖动。

**缓冲时长的权衡**：⚠ 缓冲越小越"实时"，越容易抖动；越大越稳，越放大控制误差。
10Hz 快照在 5% 丢包、两帧抖动下经验值约 **350ms**（其中 300ms 用于容忍连丢两包）
—— 这是经验值不是 Godot 默认值。

### 2.0.2 ⚠ ENet 的 MTU 与最大包大小是两个概念

`ENET_HOST_DEFAULT_MTU = 1400`（影响链路层如何分片/传输单个数据报），
`ENET_HOST_DEFAULT_MAXIMUM_PACKET_SIZE = 32MB`（只是 ENet 层允许的上限）。
⚠ **不能混读** —— 前者是实际传输的分片单位，后者只是保护性上限。

### 2.1 客户端预测

本地玩家按键后**不等服务器**就先动，手感零延迟。

```gdscript
func _process_local_prediction(delta: float) -> void:
    var input := _read_input()
    _input_seq += 1
    _predicted_tick += 1

    # 存未确认输入，供回滚重放
    _unacked.append({"seq": _input_seq, "input": input, "tick": _predicted_tick})
    _apply_movement(input, delta)

    _send_accum += delta
    if _send_accum >= SEND_INTERVAL or _unacked.size() > MAX_UNACKED:
        _send_accum = 0.0
        _client_input.rpc_id(1, {
            "seq": _input_seq,
            "client_tick": _predicted_tick,
            "input": input,
            "ack_server_tick": _latest_server_tick,
        })

    while _unacked.size() > MAX_UNACKED:
        _unacked.pop_front()
```

⚠ **必须存输入历史**，否则服务器纠偏后无法重放。
`_unacked` 就是回滚的原料。

### 2.2 服务器回滚（reconciliation）

收到服务器确认后，如果差太多，把状态退回服务器给的那一刻，
再用未确认输入**重放**一遍。

```gdscript
func _on_server_state(state: Dictionary) -> void:
    # 1) 丢弃已确认的输入
    while _unacked.size() > 0 and _unacked[0]["seq"] <= state["last_seq"]:
        _unacked.pop_front()
    _latest_server_tick = state["tick"]

    # 2) 误差小就忽略（避免抖动）
    var err := global_position.distance_to(state["pos"])
    if err < RECONCILE_THRESHOLD:
        return
    misprediction_detected.emit(err)

    # 3) 退回服务器状态，重放剩余输入
    global_position = state["pos"]
    velocity = state["vel"]
    for rec in _unacked:
        _apply_movement(rec["input"], FIXED_DT)
```

⚠ **必须有阈值**（`RECONCILE_THRESHOLD`）。
浮点误差每次都重放会让角色持续抖动。

⚠ **重放必须用固定 dt**（`FIXED_DT`），不能用帧 delta ——
否则重放结果与服务器不一致，会陷入"纠正→再错→再纠正"。

### 2.3 远端实体插值

远端玩家的状态包**到达时间不均匀**，直接照用会抖。
做法是延迟一小段时间再渲染，在快照之间插值：

```gdscript
func _process_remote_rendering(_delta: float) -> void:
    if _snapshots.size() < 2:
        return
    var render_time := _server_now_ms() - INTERPOLATION_DELAY_MS
    # 找 render_time 两侧的两个快照，插值
    _interpolate_to(render_time)
```

⚠ **代价是额外的显示延迟**（典型 100ms）。
预测/回滚/插值三者要共用**同一套输入序号 + tick 时钟链**，缺一不可。

## 3. `@rpc` 深入

### 默认值（官方文档明确）

```gdscript
@rpc
# 等价于：
@rpc("authority", "call_remote", "reliable", 0)
```

⚠ **默认 `reliable` 是性能陷阱**。
每帧位置同步忘了写 `unreliable_ordered` 就走可靠通道——
丢包重传会让位置**越来越滞后**。高频同步必须显式声明传输模式。

⚠ 默认 `authority` 意味着**客户端调用会被静默忽略**，不报错。
要客户端上报输入必须显式写 `@rpc("any_peer", ...)`。

### 各参数

| 参数 | 取值 | 含义 |
|---|---|---|
| mode | `authority` / `any_peer` | 谁有权调用 |
| sync | `call_remote` / `call_local` | 本地是否也执行 |
| transfer | `reliable` / `unreliable` / `unreliable_ordered` | 可靠性与顺序 |
| channel | `0` | 通道（**必须放最后**） |

前三个顺序任意，`transfer_channel` 必须最后。

| 场景 | 用什么 |
|---|---|
| 每帧位置/朝向 | `unreliable_ordered` + 带序号 |
| 输入流 | `unreliable_ordered` + 确认/重放兜底 |
| 命中、死亡、生成、拾取 | `reliable` |

### `get_remote_sender_id()` 的坑

```gdscript
@rpc("any_peer", "call_remote", "reliable")
func submit_input(data: Dictionary) -> void:
    var sender := multiplayer.get_remote_sender_id()   # ✅ 这里有效
    await get_tree().process_frame
    var s2 := multiplayer.get_remote_sender_id()       # ❌ 变回 0
```

⚠ **只在 RPC 处理函数内有效**，`await` 之后或函数外会失效（变成 0）。
要跨帧使用必须**先存成局部变量**。

## 4. 传输层：ENet / WebSocket / WebRTC

| | 适合 | 限制 |
|---|---|---|
| **ENet**（默认） | 原生桌面、低延迟 | UDP 之上，同时提供可靠/不可靠通道 |
| **WebSocket** | Web 导出的常用选择 | 底层 TCP，**队头阻塞** |
| **WebRTC** | 绕开防火墙、P2P | 必须自建信令、ICE、STUN/TURN |

⚠ **Web 平台基本只能用 WebSocket 或 WebRTC**，ENet 不可用。
导出到 Web 前就要定传输层，不能后期换。

⚠ WebSocket 的 TCP 队头阻塞会让"丢了的位置包"堵住后面的关键包。

## 5. 部署与 NAT

⚠ **住宅网络可以跑服务器，但"能连接"≠"可运维"**。
家用宽带通常没有公网 IP、有 CGNAT、动态 IP、运营商封端口。

| 方案 | 说明 |
|---|---|
| 专用服务器 | 最可控，成本最高 |
| 中继（relay） | 简单，有带宽成本和额外延迟 |
| 打洞（STUN） | 无中继成本，但不是所有网络都能成功 |

⚠ **先定服务器部署方式再写网络代码**。
P2P 和专用服务器的权威模型完全不同，中途切换基本等于重写。

## 6. 服务器权威（网络侧）

存档加密/客户端防作弊见 `security.md`，本节只讲网络侧。

⚠ **`any_peer` 是攻击面，不是便利**。任何人都能调，必须校验发送者 + 校验合法性：

```gdscript
@rpc("any_peer", "call_remote", "reliable")
func submit_action(data: Dictionary) -> void:
    var sender := multiplayer.get_remote_sender_id()
    if not _is_valid_sender(sender):      return
    if not _is_action_legal(sender, data): return
    _apply_action(sender, data)
```

⚠ 常见漏洞：
- 只校验"是谁"，不校验"能不能做"（穿墙、无限技能、超速）
- 把判定结果信任客户端上报的（伤害数字由客户端算）
- 用 `reliable` 传高频数据导致可被用于放大攻击

> **反模式清单（不能怎么做，审核用）** → `audit/godot/netsync-advanced.md`


## 7. 相关文档

- 基础 RPC 与节点 → `multiplayer.md`
- 存档加密与客户端防作弊 → `security.md`
- 版本相关 → `version-47-48.md`
- 性能 → `performance.md`
