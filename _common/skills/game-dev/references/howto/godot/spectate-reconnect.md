# 观战 / 断线重连 / 主机迁移 / 延迟补偿（Godot 4.7.2）

**此前文档里「观战 / spectator / 断线重连 / 迁移主机 / 插值缓冲 / lag」0 命中。**

> 回放录制与确定性本身见 `replay.md`，本文只讲**网络侧**：观战、重连、迁移、延迟补偿。
> 审核用反模式清单见 `audit/godot/spectate-reconnect.md`

## 0. 先立住边界

⚠ Godot 提供传输、RPC、场景复制、连接生命周期、认证骨架；
**回放、网络插值、延迟补偿、身份重连、状态恢复、主机选举全部要项目实现**。

⚠ **没有内置快照插值器，没有服务端回溯（rewind），没有回滚模拟器。**
`MultiplayerSynchronizer` 只同步 authority 的复制属性，不支持"查询历史帧并回滚物理世界"。

## 1. 回放三条路径

| 方案 | 录制量/小时 | 回放 CPU | 容错 | 最适合 |
|---|---:|---|---|---|
| **输入录制** | 0.5–1 MB | 重跑模拟，峰值在解码+物理 | 低：缺种子或一帧不同即漂移 | 本地死亡回放、确定性竞技复现 |
| **状态快照** | 10–20 MB | 解码重建实体，不重跑物理 | 中高：跳帧可恢复 | 非确定性项目、赛后分析 |
| **服务端录制下载** | 60–120 MB | 主要解码/渲染 | 高：服务器是事实源 | 在线比赛、防作弊、直播 |

⚠ **反模式：混合两种事实源。** 既录输入又录位置，播放器用输入推进却偶发用快照覆盖位置
→ 角色在重播中来回跳跃，且无法定位是输入序列错还是快照错。
**选一个权威源**：输入回放全量重跑；快照回放只做"加载初始状态→逐帧 setState"。

## 2. 确定性：见 replay.md

⚠ 确定性（浮点、`randi()` 全局流、遍历顺序、物理隔离、固定步长）的完整说明见 **`replay.md`**。
本文只补 replay.md 未覆盖的：回放文件格式、观战、断线重连、主机迁移、延迟补偿。

## 3. 回放文件格式

**头**：
```
magic: u32 = 0x4752504C          # 'GRPL'
format_version: u16
feature_flags: u16
game_version_major/minor/patch: u16 x3
engine_hex: u32                  # Engine.get_version_info().hex
schema_id: u16 / schema_version: u16
match_id: u64 / start_tick: u64 / tick_rate: f32
random_seed: u64 / first_rng_state_blob
header_crc32: u32 / payload_length: u64 / payload_crc32: u32
```

**帧**：`frame_type:u8 | tick:u64 | length:u32 | payload | crc16`

⚠ **版本号用整数**，写字符串 `"v3"` 会让 4 字节字段后所有帧错位。
⚠ **长度前缀用无符号**，有符号 int 收到超长文件会越界。
⚠ **CRC 不能覆盖未初始化尾部** —— 不同平台结果不同。

⚠ **压缩要在帧组边界做**（每 1–5 秒一块），不要一次性把 60 分钟压进内存（移动端 OOM）。

⚠ **循环读文件用 `get_position() < get_length()`**，不要用 `eof_reached()` 判断还有多少可读。

⚠ 加载顺序：magic → 版本协商 → 长度边界 → CRC → schema adapter → 解码。
⚠ 写入先写 `*.tmp` → flush → 重命名。

⚠ `FileAccess.store_var()` / `var_to_bytes()` **不是长期兼容契约**：
只序列化带 `PROPERTY_USAGE_STORAGE` 的属性，反序列化对象还可能执行代码 → 只用于同构建临时调试。

## 4. 观战

⚠ **观战者是状态接收者，不是普通玩家 authority。**
建一个无输入设备的 `SpectatorSession`，`set_multiplayer_authority(1)`（默认即 1），只订阅广播。

**服务器按可见性过滤**，别把所有玩家同步数据全量发一份：
`MultiplayerSynchronizer.set_visibility_for(spectator_id, visible)` 或 `add_visibility_filter()` + `update_visibility()`。

### `@rpc` 参数

⚠ **参数顺序可乱，但 `transfer_channel` 必须是第四个**，且前三个位置参数各用一次：
`@rpc("authority", "call_remote", "reliable", 2)`

| 参数 | 含义 |
|---|---|
| `any_peer` | 任意 peer **能调用**，不等于**可信** |
| `authority` | 非 authority 调用**不会执行** |
| `call_local` | 调用端是否本地执行，**不是"是否广播给所有人"** |
| `unreliable_ordered` | 迟到包可能丢，但**顺序错会瞬移** |

⚠ `call_local` 配在观战者的 `request_view()` 上，会让**主机本地也切视角**。

⚠ **`get_remote_sender_id()` 在 RPC 外返回 0，且 `await` 后会丢失**
→ 进 RPC 立刻把 id 存成局部变量或显式参数。

### 观战延迟既防窥屏也稳定插值

服务器给观战流打 `match_tick` + `server_time_ms`，客户端维护 **200–600ms 历史缓冲**，按固定显示 tick 插值。

⚠ **竞技项目必须在服务器隐藏未揭示信息** ——
"客户端不渲染"不能代替不可见，观战流只能包含裁判视角的遮挡结果。

### 视角切换是状态机

```gdscript
enum { FREE, FOLLOW, FIRST_PERSON, MAP }
```

⚠ 切换时先取消旧相机挂载、验证目标未退出、设插值起始帧，再启用 HUD。
⚠ 跟随相机读**目标上一渲染帧的插值结果**，不直接读权威快照（否则旧快照抖动）。
⚠ 观战 HUD 与玩家 HUD 分开：`is_spectator=true`、`is_predicting=false`；
观战者不拥有角色、不发移动输入、**不参与伤害请求、不触发命中事件**。

## 5. 断线重连

### Peer ID 是会话 ID，不是玩家身份

⚠ 服务器固定为 1，客户端 ID 是**服务器分配的随机正整数**，重连后**不应假定不变**。

会话身份至少要有：`account_id/device_id`、`match_id`、`session_token`（HMAC 或签名）、`player_slot`、`join_nonce`。

### 重连状态机

```
LIVE → CONNECTION_LOST → RECONNECTING → RESYNCING → LIVE
```

⚠ **客户端断线后不要立即销毁角色。**

重连请求：`reconnect_request.rpc_id(1, match_id, slot, prev_peer_id, token, last_ack_tick, client_schema_version)`

服务端校验：签名/有效期 → slot 仍属本局 → `prev_peer_id` 已识别为断开 → `last_ack_tick` 不晚于服务器已推进 tick（防重放）。

⚠ **`set_multiplayer_authority()` 不会自动复制到其他 peer** —— 旧 id 的 authority 不能直接留给新 id。

### 状态恢复默认全量快照

`snapshot_full(match_tick, base_schema, compressed_entity_list)` → 客户端加载后进可插值世界；
之后对已赶上的客户端切 `snapshot_delta(base_tick, changed_fields)`；落后超窗口立即退回全量。

⚠ **重连期间正在释放的弹幕、已结算的击杀不能靠增量补齐**
→ 窗口必须是"完整世界版本"，不是 RTP 式 GOP。

### 角色保留 + 受控 AI 托管

⚠ **默认策略是"保留 + AI 托管"，不是静默销毁**。
角色保留 `authority=1`，由确定性 AI 执行最后合法输入、停火或安全移动。

- 反模式 A：直接 `queue_free()` → 对方客户端物体突然消失、已发射抛射物变孤儿、计分不一致
- 反模式 B：永远保留 → 掉线玩家长期占据据点

### 超时三档

- 客户端：0.5s / 1s / 2s / 4s 指数退避，最长约 10–15s
- 服务器：每 slot 独立 `reconnect_grace_ms`（建议 20–60s）
- ⚠ **重连成功以"收到第一个连续权威快照且 match_tick 被确认"为准**，不是连接成功为准
- 应用层验证失败立即返回 `RECONNECT_INVALID` 并禁止同 nonce 重试

### 关闭连接两种语义

⚠ `MultiplayerPeer.close()` **立即**恢复到 DISCONNECTED，**不发射** `peer_disconnected`。
⚠ `disconnect_peer(peer, force=false)` 默认**会通知**对方；`force=true` 才不发射。

→ 退出大厅用 `disconnect_peer()`；服务器销毁房间才 `close()`。

### 信号覆盖要成对

⚠ 只接 `peer_disconnected` 会**泄漏等待认证的会话**（认证失败走 `peer_authentication_failed`）。
→ MatchSession 同时维护 `authenticating` 与 `connected` 两张表，两种断开信号跑同一幂等退出流程。

## 6. 主机迁移

⚠ **有权威专用服务器时不存在"迁移"** —— 服务器保持世界状态，客户端断开只触发保留/AI 托管。

⚠ **Godot 没有内建 host migration API。**

### P2P 选举

- 候选以**稳定外部 ID** 排序（字典序/数值序），**不用随机 peer ID**
- 每轮 `epoch` 与 `migration_id` 单调递增
- 广播 `migration_intent(epoch, candidate_id, last_match_tick, schema_version, state_hash)`，收集后选优先级最高且数据最前的
- ⚠ **不得仅凭"我是最大 peer id"抢占** —— 新 ID 随机且不可信

### 仲裁后一次性切换世界 authority

`migration_commit(epoch, winner_id, world_snapshot, entity_authorities, state_hash, signature)`
→ 其他节点验 epoch/签名/state hash/snapshot 版本 → `set_multiplayer_authority()` + 用可靠 RPC 重建复制关系。

⚠ 新主机要承担 ENet server 角色 —— 剩余 peer 须预先维护彼此 endpoint/relay token，
因为旧客户端只知道原主机地址。

⚠ **仲裁需要 quorum** —— 网络分区时两套主机都广播 commit 会形成双主。quorum 不可达就中止比赛。

⚠ **迁移失败兜底是停止判定**，不是让客户端自治：
返回大厅 / 剩余客户端纯观战 / 从最近全量快照恢复为协作局但关排名与战利品。

## 7. 延迟补偿

### 服务端回溯（rewind）

服务器维护环形历史 `HistoryFrame{tick, server_time, entities[]}`；
收到射击 RPC 时据 RTT/时钟估计客户端所见 tick，**只在该历史快照上做命中测试**，随后立即丢弃临时状态。

⚠ **只复制最小包围盒**（`pos/rot/half_extents/collision_layer/last_update_tick`），不要复制节点树。
⚠ **每次最多回溯 20–30 tick** 并受攻击速率限制。

### 三个不同的问题别混为一谈

| 机制 | 解决什么 |
|---|---|
| 客户端预测 | 消除本地操作延迟 |
| 服务器调和 | 权威校验并确认状态 |
| 插值 | 其他玩家实体不在渲染 tick snap |

插值比例：`a = clamp((now - recv_time_k) / (recv_time_{k+1} - recv_time_k), 0, 1)`
超过下一快照预期到达时间仍未收到 → 停止或外推一帧并标为不可靠。

### 拉回要平滑纠正

偏差超 `correction_threshold`（4–8cm，看手感）时：
先记 `client_pos_at_ack_tick` → 若干帧从旧显示位置朝服务器历史位置移动 → 重放确认 tick 之后的本地输入。
偏差极大（穿墙/传送/过期回包）才直接 snap 并清空预测缓冲。

```gdscript
x += (target - x) * (1 - exp(-dt * alpha))    # 临界阻尼/指数平滑
```

⚠ 反模式 A：每帧把 `global_position` 直接赋权威值 → "走路像橡皮筋"
⚠ 反模式 B：smoothing 过头 → 命中反馈延迟数百毫秒

### 缓冲与延迟是同一枚货币的两面

⚠ 缓冲越大越能容忍抖动丢包，但所有非本地实体更"旧"，本地玩家相对对手的有效延迟增加。
建议按 `ENetPacketPeer.get_statistic(PEER_ROUND_TRIP_TIME)`、抖动、连续丢包动态调节：
正常 100–200ms，丢包上升时增大，稳定后缓慢减小。

⚠ `MultiplayerSynchronizer.replication_interval = 0.0` 表示每次网络处理都同步
—— 适合小对象，**不适合大量实体的观战流**。

⚠ **不要把回溯用的包围盒回传给客户端当最终位置** —— 那会把延迟补偿变成作弊。
命中结果写 `confirmed/denied/reconciled_tick`，客户端只播特效；血量、击杀归属、排行榜由服务器快照收敛。

## 8. 分层实现栈

```
SimClock        — tick_rate / 当前 tick / 固定 step
SimRNG          — 独立 PRNG 实例
MatchState      — 稳定 entity id + 纯数据组件
InputRecorder   — 替换输入源
NetworkReplicator — 权威快照 → Synchronizer 或自定义 RPC
SessionManager  — 认证 / 重连 / 迁移
```

回放、观战、重连**共享同一模拟核心**，不要各自复制玩法逻辑。

⚠ **超时要分层**：ENet 的 `set_timeout(timeout, timeout_min, timeout_max)` 是传输层无响应超时，
**不是"玩家重连宽限"**。应用层还要维护 `last_input_ms`/`last_snapshot_ack_ms`/`connection_lost_ms`。
