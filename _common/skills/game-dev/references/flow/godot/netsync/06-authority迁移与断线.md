# 06 authority 迁移与断线（网络同步域）

> **前置**：02 连接已建立，03 authority 关系已建立
> **本步交付**：载具换手、观战接管、断线清理——**不留孤儿实体、不出现"无人控制"**
> **对应**：做法 `howto/godot/multiplayer.md` · 审核 `audit/godot/multiplayer.md`

## 0. 交付物定义

⚠ 断线是**必然会发生的**，不是异常路径。
处理不好会留下孤儿实体（玩家走了角色还在）、
或让实体短暂"无人控制"（谁都操作不了）。

做完这一步，应该能**当场演示**：

1. 强杀客户端，服务端**清理干净**（无孤儿实体）
2. 载具换手：authority 迁移后，新控制者能操作
3. ⚠ 迁移消息到达前的**空窗期**有处理（不崩、不乱动）
4. 断线走 `peer_disconnected` 清理，⛔ **不靠 RPC 失败**
5. 父节点设了 authority 后，**新增子节点也显式设了**

**产出物**（下游按名字对接）：

```text
_on_peer_disconnected(id) 清理逻辑
transfer_authority(node, new_id) -> void
pending_transfer 状态（空窗期守卫）
```

## 1. 前置检查清单

- [ ] 02 的四个连接回调已接（尤其 `peer_disconnected`）
- [ ] ⚠ 已确认 `set_multiplayer_authority()` **不会广播**
- [ ] 已确认新增子节点**不会自动继承**父节点的 authority
- [ ] ⛔ 已确认清理**不依赖** RPC 失败检测
- [ ] 已列出哪些实体需要迁移（载具、观战目标、AI 接管）

## 2. 工序

### Step 1　断线清理走 peer_disconnected　`[netsync/06#S1]`

【读】`howto/godot/multiplayer.md#1. 基础 API` 与 `#上线前检查`

【做】⚠ 断线走 `peer_disconnected` 清理，⛔ **不靠 RPC 失败**。

RPC 失败是"某次调用没成功"，不是"对方走了"——
靠它做清理会漏，且时序不可控。

【产出】`_on_peer_disconnected(id)` 清理该 peer 的全部实体与状态

【判据】⚠ 强杀客户端进程，服务端实体数**回到断开前**（⛔ 不是留一个）

【审】`audit/godot/multiplayer.md#12`

### Step 2　authority 迁移要自己广播　`[netsync/06#S2]`

【读】`howto/godot/multiplayer.md#5. authority 迁移（载具、观战、断线接管）`

【做】
```gdscript
func transfer_authority(node: Node, new_id: int) -> void:
    if not multiplayer.is_server():
        return
    if node.get_multiplayer_authority() != multiplayer.get_unique_id():
        push_error("只有当前 authority 能发起转移")
        return
    node.set_multiplayer_authority(new_id, true)
    authority_changed.rpc(node.get_path(), new_id)
```

⚠ `set_multiplayer_authority()` **只改本地关系，不会广播**。
必须自己用 RPC 通知，或走 Synchronizer 复制。

【产出】迁移后**所有端**的 authority 一致

【判据】⚠ 迁移后在另一个客户端打印该节点 authority，**是新的 id**

【审】`audit/godot/multiplayer.md#7`

### Step 3　⚠ 空窗期要标 pending_transfer　`[netsync/06#S3]`

【读】`howto/godot/multiplayer.md#5. authority 迁移（载具、观战、断线接管）` 的 ⚠ 提示

【做】⚠ 迁移消息到达前，客户端可能**短暂没有合法输入者**。
要标 `pending_transfer` 状态，拒绝预测或缓存最后合法输入。

⛔ 不处理的话，空窗期的输入会被当成"别人的输入"应用，
或者预测出一个没人认领的位置，迁移完成后瞬移。

【产出】空窗期有明确行为（拒绝 or 沿用最后合法输入）

【判据】⚠ 人为延迟迁移消息 500ms，空窗期**无异常移动**

【审】`audit/godot/netsync-advanced.md#25`

### Step 4　本地不一致时等权威纠正　`[netsync/06#S4]`

【读】`howto/godot/multiplayer.md#5. authority 迁移（载具、观战、断线接管）`

【做】
```gdscript
if node.get_multiplayer_authority() != new_id:
    push_warning("本地 authority 不一致，等权威状态纠正")
```

⚠ 收到迁移消息但本地还没同步完（节点还没生成）时，
要**记下来等**，⛔ 不是报错崩溃也不是静默忽略。

【产出】节点不存在时安全返回，不一致时打警告并等纠正

【判据】⚠ 迁移消息先于节点生成到达，**不崩溃**且后续自动一致

【审】`audit/godot/netsync-advanced.md#26`

### Step 5　新增子节点要显式设 authority　`[netsync/06#S5]`

【读】`howto/godot/multiplayer.md#1. 基础 API` 的 ⚠ 提示

【做】⚠ 父节点设了 authority，**后来新增的子节点不会自动继承** —— 要显式设。

`set_multiplayer_authority(id, true)` 的 `true` 是**递归当前已有的子节点**，
对之后才 `add_child` 的无效。

【产出】运行时动态生成的子节点都显式设了 authority

【判据】⚠ 迁移父节点后**再**生成子节点，子节点 authority **正确**

【审】`audit/godot/multiplayer.md#8`

### Step 6　只有服务端能发起迁移　`[netsync/06#S6]`

【读】`howto/godot/multiplayer.md#5. authority 迁移（载具、观战、断线接管）`

【做】⚠ 迁移必须由**服务端**发起并校验。
⛔ 允许客户端自己调 `set_multiplayer_authority()`
= 任何人都能夺取任何实体的控制权。

【产出】客户端侧没有直接调 `set_multiplayer_authority()` 的路径

【判据】⚠ 伪造 RPC 请求迁移别人的载具，**被拒**且有日志

【审】`audit/godot/netsync-advanced.md#27`

## 3. 参考实现

```gdscript
func _on_peer_disconnected(id: int) -> void:
    # ⚠ 清理不靠 RPC 失败，靠这个回调
    for entity in _entities_by_peer.get(id, []):
        if is_instance_valid(entity):
            entity.queue_free()
    _entities_by_peer.erase(id)
    _last_seq.erase(id)
    _input_history.erase(id)
    _reassign_orphans(id)          # 载具/AI 接管

@rpc("authority", "call_remote", "reliable")
func authority_changed(node_path: NodePath, new_id: int) -> void:
    var node := get_node_or_null(node_path)
    if node == null:
        _pending_authority[node_path] = new_id    # ⚠ 节点还没生成，记下来
        return
    if node.get_multiplayer_authority() != new_id:
        push_warning("本地 authority 不一致，等权威状态纠正")
```

⚠ `_reassign_orphans()` 容易被漏：断线的是载具驾驶员，
载具本身还在世界里——要么销毁、要么交给 AI/其他人，
⛔ 不能让它永远停在那里没人能开。

## 4. 验收清单

- [ ] 强杀客户端后无孤儿实体
- [ ] 迁移后所有端 authority 一致
- [ ] 空窗期无异常移动
- [ ] 迁移消息先到不崩溃
- [ ] 动态子节点 authority 正确
- [ ] 伪造迁移请求被拒

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 玩家走了角色还在 | 靠 RPC 失败清理 | S1 |
| 换手后别人开不了车 | 迁移没广播 | S2 |
| 换手瞬间角色抽搐 | 空窗期没处理 | S3 |
| 迁移消息先到就崩 | 没判节点是否存在 | S4 |
| 动态子节点失控 | 没显式设 authority | S5 |
| 任何人能抢载具 | 客户端可发起迁移 | S6 |

## 6. 下一步

→ **07 上线验收**

## 7　整体审核（功能点级收尾）

ⓘ 各 Step 的【审】是**步骤级即时检查**；本节是**功能点级复查**，两级都要走。

- [ ] 逐条过 `audit/godot/multiplayer.md`，每条说出"我们是怎么避免的"
  - ⛔ 不能"应该没这个问题"
- [ ] 步骤级【审】列过的条目**再过一遍**
- [ ] ⚠ 实测参数已回填，⛔ 不留示例值
- [ ] 若属大功能 → ⚠ **还要集成验收**：各部件合格 ≠ 拼起来能用
