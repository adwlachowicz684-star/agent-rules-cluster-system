# 宠物 / 坐骑 / 召唤物 / 孵化合成（Godot 4.7.2）

**此前文档里「宠物 / 坐骑 / 召唤 / 孵化 / 合成台」全部 0 命中。**

> 装备养成与掉落见 `economy.md`；AI 与寻路见 `ai-behavior.md`、`ai-navigation.md`；
> 群集与避障见 `boids-swarm.md`；多人生效与同步见 `multiplayer.md`。

⚠ **Godot 没有 `PetNode`、`MountNode`、`SummonNode`。** 这些全是项目层组合出来的。
但这不意味着随便拼——下面几处是**拼错必然炸**的地方。

> 审核用反模式清单见 `audit/godot/companion.md`

## 0. 第一个要纠正的抽象

⚠ **"宠物就是会动的装备"是错误的。**

| 维度 | 装备 | 宠物 |
|---|---|---|
| 形态 | 背包里的格子数据 | 场景里的**活体节点** |
| AI | 无 | 跟随 / 索敌 / 技能 / 避险 |
| 生命周期 | 无 | 出生 → 成长 → 死亡 → 复活 |
| 状态机 | 无 | Idle / Follow / Combat / Dead / Return |
| 归属 | 持有者 | 主人 + 忠诚度 + 亲密度 |
| 同步 | 同步背包即可 | 位置 + AI 状态 + 动画 + 技能 |

当成装备的后果：AI 无处安放、死亡状态与背包数据耦合、多人同步时动画没处同步。

**正确分层（模板 / 实例 / 节点 三层）：**

```
SpeciesTemplate (Resource)   # 只读、共享：物种属性、成长率、进化链、模型
CompanionInstance (Resource)  # 存档、每宠唯一：等级、经验、忠诚度、饱食度、出战位
CompanionNode (场景)          # 活体：CharacterBody3D + 状态机 + NavigationAgent3D
```

⚠ **SpeciesTemplate 是共享 Resource，直接改它会影响所有同类宠物。**
个体数据要么 `duplicate()`，要么用 `resource_local_to_scene`。
（这与装备模板不能内嵌存档是同一个坑，见 `economy.md`。）

## 1. 宠物

### 状态机必须显式

```
Idle → Follow ⇄ Combat → Dead → (复活冷却) → Idle
              ↘ Return ↗        ↘ Stunned
```

⚠ **复活冷却不能用 `Timer`** —— 退出进程就丢。存 **UTC 时间戳**（`cooldown_until`），
登录时用时间差判断。这与孵化计时、生产队列是同一条规则（见 `time-progression.md`）。

### AI 协同

⚠ **多宠同帧索敌容易集火同一目标** —— 要做索敌分区或优先级分配，
否则三只宠物永远打同一个敌人，玩家感知是"AI 很蠢"。

⚠ **宠物 AI 优先级低于主人**：主人的强制移动/过场动画期间，宠物应进入 `Return` 而非继续追击。

### 饱食度与忠诚度的离线衰减

⚠ **离线期间的衰减必须在登录时按时间差补算**，否则上线后忠诚度"断崖式下降"。
⚠ 但补算要**封顶**（见 `time-progression.md` 的封顶原则）——
不封顶等于惩罚长时间离线，会让玩家不敢下线。

## 2. 坐骑：核心是"谁在驱动移动"

⚠ **错误做法：两个 `CharacterBody3D` 各自 `move_and_slide()`，再把角色位置贴到坐骑上。**
→ 一帧延迟、穿模、碰撞不一致。

✅ **正确做法：骑乘期间只有一个 `CharacterBody3D` 在驱动移动——坐骑本体。**
角色成为坐骑的子节点，不再独立移动。

```
Mount (CharacterBody3D)
├── CollisionShape3D
├── SaddlePoint (Node3D)      # 骑乘锚点
├── StateMachine (Idle/Walk/Run/Turn/Swim/Fly)
└── MountMovementComponent    # 加速度 / 转向 / 惯性
```

### reparent 的三个坑

⚠ **在信号回调里直接 reparent → 物理引擎崩溃。** 用 `call_deferred` 或延迟到 `_physics_process`。

⚠ **关于"reparent 会丢全局变换"：官方默认恰恰相反，这里是此前写错的地方。**

官方签名：`reparent(new_parent: Node, keep_global_transform: bool = true)` ——
`keep_global_transform` **默认就是 `true`**，即默认**保留**全局变换。
所以 `reparent(p)` 不传参**不会**把骑手瞬移到原点。

⛔ 真正会丢全局变换的是这两种：
1. 手动 `remove_child()` + `add_child()` 的老写法（Godot 3.x 的 reparent 模式）——
   这才是"瞬移到原点"的实际来源，⛔ 但它是**手写两步**造成的，不是 `reparent()` 的行为；
2. ⛔ `keep_global_transform` 只对 `Node2D` / `Node3D` / `Control` 生效
   （官方：`Node2D, Node3D and Control support this argument`，且 `Control` **只保留 position**）。
   在普通 `Node` 上显式传 `true` 也不会有效果。

ⓘ 所以"要显式传 `true`"这句建议**无害但多余**；
⛔ 真正的风险是误以为默认丢、从而去手写 `remove_child` + `add_child` 来"补偿"——
那反而会真的丢。

⚠ **reparent 之后必须 `reset_physics_interpolation()`**（官方 Warning）：
若 `ProjectSettings.physics/common/physics_interpolation` 开启，且 reparent 导致
全局变换发生较大变化，物体会**在下一个物理帧从旧位置"滑"到新位置**。
表现为"上马瞬间角色从原位置拖影滑到马鞍上"。
⛔ 且官方注明：该方法**必须在移动之后调用**，调用早了会按旧位置重置快照、照旧插值。

⚠ **骑乘后必须关闭角色的碰撞层** —— 两个碰撞体互相挤压会穿模。
下马时要恢复，并**预检测下马点是否安全**（`PhysicsShapeQueryParameters3D`），否则骑手被卡进墙里。

### 多人同步

⚠ **坐骑的 authority 转移有延迟，期间骑手和坐骑会各自移动。**
要用**两阶段确认协议**：请求上马 → 服务端转移 authority → 确认后才切换到骑乘状态机。

⚠ 骑手与坐骑是**两个需要同步的实体**，不能假设"同步了骑手位置就等于同步了坐骑"。

## 3. 召唤物：数量是性能死穴

⚠ **不能每个召唤物都是独立节点。** 独立节点意味着独立的
`_physics_process`、独立的 CollisionShape 注册、独立的 draw call、独立的 AnimationPlayer。
50+ 个时线性叠加。

| 类型 | 渲染 | AI | 适用 |
|---|---|---|---|
| 重型（Boss 级） | 独立 MeshInstance3D | 独立状态机 | 1–3 个 |
| 中型（战士/法师） | 独立节点 + 共享材质 | 简化 FSM | 4–16 个 |
| 轻型（小鬼/元素） | MultiMesh / GPUParticles | 无 AI，运动学 | 16–100 个 |
| 超轻型（幻象） | RenderingServer 直绘 | 纯数据 | 100+ 个 |

⚠ **MultiMesh 不支持骨骼动画**（每个实例无独立动画状态）——需要动画的召唤物不能走 MultiMesh。
  ⓘ 官方 issue 至今仍是 proposal 状态（未实现）。可行变通是 **VAT（顶点动画贴图）**：
  把动画烘进顶点/法线贴图，用 `INSTANCE_CUSTOM` 传每实例的动画索引与帧号，
  在 `vertex()` 里手工采样。**代价是失去动画混合与 IK**，
  ⛔ 所以"需要动画的召唤物"要按"是否要混合"再分一层，不是简单二分。

⚠ **必须有数量上限，且服务端强制。** 客户端上限只是防误操作，挡不住篡改。

### 对象池

```gdscript
func acquire(scene_path: String) -> SummonNode:
    var pool: Array = _pools.get(scene_path, [])
    if pool.is_empty():
        push_error("Pool exhausted: %s" % scene_path)
        return null          # ⚠ 调用方必须检查返回值
    var n := pool.pop_back() as SummonNode
    n.visible = true
    n.set_physics_process(true)
    n._reset()               # ⚠ 不清状态会让新召唤物以 100m/s 飞出去
    return n
```

⚠ **池中节点永不被 `queue_free()`** —— `queue_free` 与对象池混用会留下野指针。
⚠ **`MultiplayerSpawner` 期望 `instantiate()`/`queue_free()`，与对象池的 show/hide 语义冲突。**
解法：池子只在服务端维护，客户端通过同步属性控制可见性，否则客户端看到幽灵节点。

⚠ **伤害归属必须存 `caster_id`**，并在释放时清理仇恨表 ——
否则召唤物消失后目标仍向召唤者报仇恨。

## 4. 孵化与合成

⚠ **结果必须在"开始时"就 roll 并存储，不能在"领取时"才随机。**
在领取时随机的后果：玩家可以反复读档/重发请求刷稀有度。

⚠ **合成开始时必须立即扣材料**，不能等完成时扣 —— 否则同一批材料被多个合成台重复利用。

⚠ **多槽孵化要遍历全部槽**，只更新第一个会导致其他槽永远不完成。

⚠ **取消合成返还材料时，若背包已满要检查空间或存临时区** —— 直接返还失败等于材料凭空消失。

⚠ **多台合成台并发是竞态** —— 服务端串行或加互斥，客户端的"同时点两台"必然出问题。

⚠ **合成队列上限检查要算 `queue + active` 总数**，只算其中一个会溢出。

## 5. 服务端权威边界

必须服务端：`宠物成长/进化` · `忠诚度与饱食度衰减` · `死亡与复活判定` ·
`上下马判定（距离、条件）` · `召唤物创建/销毁/数量上限` · `召唤物伤害与归属` ·
`孵化计时与结果` · `合成材料与结果` · `合成队列`

客户端只能预测：宠物跟随动画（纯表现）· 坐骑移动输入（服务端校验最终位置）· UI 进度条

## 6. 待核对项（运行时验证）

⚠ 待核对：`reparent()` 在 4.7.2 的默认行为与是否保留全局变换 · 验证：目标版本实测 `reparent(p)` 与 `reparent(p, true)` 的位置差异，本轮按官方语义书写

⚠ 待核对：`MultiMesh` 对骨骼动画的支持边界 · 验证：官方文档确认无独立实例动画；如需动画的召唤物另选方案（本轮已按"不支持"书写）

⚠ 待核对：飞行坐骑用 `MOTION_MODE_FLOATING` 的碰撞行为 · 验证：真机实测水面/空中切换时的物理表现
  ⓘ 官方已明确的语义（不再属于未知）：`MOTION_MODE_FLOATING` 下
  **所有碰撞都报告为 `on_wall`**，且滑动时**速度恒定**（不因坡度加减速）。
  ⛔ 后果：`is_on_floor()` 在该模式下**永远返回 false** ——
  飞行坐骑若沿用地面状态的落地判定，会永远判不到"落地"，
  表现为"切换回地面模式前一直在空中飘"，而 `velocity` 与碰撞都看着正常。

⚠ 待核对：`MultiplayerSpawner` 与对象池的兼容方案 · 验证：社区方案非官方支持，需在目标版本实测
  ⓘ 官方已明确的机制（可直接用，不必等社区方案）：
  - `MultiplayerSpawner.spawn_function` 在**所有 peer 上**被调用，接收 `data` 并返回**一个不在场景树中的 Node**；
    ⛔ 官方明确：**返回的节点不要自己 `add_child()`，引擎会自动加**。
    这正是对象池的接入点 —— `spawn_function` 里从池中取节点返回即可，
    ⛔ 但取出的节点**必须不在树中**（池化的"隐藏复用"要改成"先移出树再返回"）。
  - `MultiplayerSpawner.spawn_limit` 是**官方内置上限**（默认 `0` 表示无限制），
    包含可生成场景与自定义 spawn 的总和。
    ⛔ 但它是**客户端侧的复制上限**，⛔ 不能替代服务端对"能否召唤"的权威判定 ——
    改包就能绕过，服务端仍必须自己数。

## 7. 流程：按什么顺序做

> 完整功能点拆解、接缝契约与敌意环境验收见 `flow/godot/companion/`。

⛔ **先定"谁驱动移动"再坐骑**：骑乘是**移动驱动权**的转移，
不是"把角色贴到坐骑上"。先做表现后定驱动权，会在
上下马、过场、断线重连时成片返工。

⛔ **召唤物先定数量分层再写 AI**：数量决定渲染与 AI 方案（独立节点 / MultiMesh / RenderingServer 直绘），
⛔ 先写完"每个召唤物一个带 AI 的节点"再改分层，等于整块重写。

⛔ **孵化/合成先定"开始时 roll 并落库"再写 UI**：
结果在领取时才随机 = 可反复读档刷稀有度，
⛔ 这是发版后靠补日志无法定位的漏洞（日志里每一次都是"正常随机"）。

## 8. 相关文档

- 装备养成与掉落 → `economy.md`
- 离线结算、生产队列、体力 → `time-progression.md`
- AI 行为与寻路 → `ai-behavior.md`、`ai-navigation.md`
- 群集与避障 → `boids-swarm.md`
- 多人生效与 authority → `multiplayer.md`
