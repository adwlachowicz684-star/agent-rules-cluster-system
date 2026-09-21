# 投射物与弹道：子弹、抛射、弹道预测（Godot 4.7.2）

"弹道""投射物" 此前 **0 命中**。

## 0. ⚠ 没有"子弹节点"，先看三个问题

Godot 没有专供子弹的单一节点。选型的核心**不是"子弹多快"**，而是：

1. 轨迹是否可变
2. 是否需要影响其他刚体
3. 命中是否要求逐帧权威

| 路线 | 适用 | 优势 |
|---|---|---|
| **hitscan（射线）** | 狙击、激光、命中反馈强实时 | 手感最可控、最省带宽 |
| **RigidBody** | 火箭、榴弹、可推可弹 | 物理交互自然 |
| **手工积分**（CharacterBody/Node + `_physics_process`） | 弓箭、穿透弹、追踪弹、弹幕、预测-实际必须一致 | 轨迹完全可控、便于重放 |

⚠ **"火箭有尾迹"不是必须用 RigidBody 的理由** —— 尾迹只是视觉，判定仍可用射线/ShapeCast。

⚠ RigidBody 由物理模拟移动，**不适合被脚本每帧摆位**；经常改 transform/linear_velocity 会造成不可预测行为。

## 1. 高速穿透（tunneling）

官方把高速物体互相穿过称为 **tunneling**，并确认：

⚠ **Continuous CD "有时有效"**（官方原话）—— 不是万能解。

其余手段：加厚静态碰撞形状、按速度放大碰撞体、提高每秒物理周期。
⚠ **都不能替代射线扫描**，且提高 tick 会消耗更多 CPU。

### 最常用解法

**"上一帧位置 → 本帧位置"射线扫描** —— 直线点状弹首选。
有粗细时改 **ShapeCast**，但 ⚠ 它是扫描区域的**近似**而非精确胶囊碰撞。

⚠ 射线扫描的漏检：**起点或终点在墙内**、边缘情况。

## 2. ⚠ 预测线必须复用真实弹道函数

**预测线必须复用与真实弹道相同的重力、时间步和碰撞查询**，且只画到首个碰撞点。

⚠ 这是最常见的 bug：**显示和落点不一致**。
根因是预测写了一套简化公式、实际另一套。

## 3. 命中判定

- 命中框（hitbox）与受击框（hurtbox）分层
- ⚠ **分层与过滤**（友军伤害、穿透、多段）
- ⚠ **一帧多次命中的去重**
- 穿透弹 / 弹射（bounce）/ 追踪（homing）
- ⚠ 命中回调的执行时机（物理帧 vs 渲染帧）

⚠ 调试时 `exclude` 与 `collision_mask` 要同时打印，别只看射线结果。

## 4. ⚠ 网络：投射物尽可能不进快照

**优先服务器判定"开火事件"，而不是逐帧同步子弹 transform。**

客户端请求开火（或只发输入）→ 服务器用权威位置做射线/ShapeCast → 广播结果。

⚠ **4.7.2 未检索到引擎内置命中回溯 API** —— 延迟补偿/历史回滚是社区常见设计，**待核对**。

频繁生成销毁的投射物要**对象池化**。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/projectile.md`


## 5. ⚠ 射线扫描：三个默认属性就是三个坑

节点化射线（`RayCast3D`）与即时射线（`PhysicsDirectSpaceState3D`）的默认值不同用途，
但**三个默认属性几乎每个项目都会踩**。

### ① `collide_with_areas` 默认 `false`

⚠ **这意味着：hitbox 用 `Area3D` 时，射线默认打不中它。**

ⓘ 官方：`RayCast3D.collide_with_areas = false` / `collide_with_bodies = true`。

⛔ 症状：子弹穿人而过、控制台无报错、mask 看着也对。
排查方向很容易被引到"层设错了"，其实是**这条默认值**。

✅ 用 Area3D 做 hitbox 时必须显式打开：

```gdscript
var q := PhysicsRayQueryParameters3D.create(from, to)
q.collide_with_areas  = true      # ⚠ 必须显式开
q.collide_with_bodies = false     # ⛔ 都开会有两套命中结果
```

⚠ **不要两个都开** —— 会得到"先命中身体还是先命中区域"的顺序歧义，
表现为爆头判定时灵时不灵。

### ② `hit_from_inside` 默认 `false`

ⓘ 官方：*"If true, the ray will detect a hit when **starting inside shapes**. In
this case the collision normal will be `Vector3(0, 0, 0)`."*

⚠ 这正是第 1 节"起点在墙内会漏检"的官方属性解法。
但要注意代价：**从内部命中时法线是零向量**，
用它算反射/弹射会得到 `NaN` 或零方向。

✅ 弹射类投射物要处理这个：`if n == Vector3.ZERO: 用速度反向代替`。

### ③ `exclude_parent` 默认 `true`

ⓘ 官方：*"If true, collisions will be ignored for this RayCast3D's
**immediate parent**."*

⚠ **好处**：射击者就是父节点时，不用手动排除自己。
⚠ **坑**：发射者是**祖父节点**（如枪挂在角色下、射线挂在枪下）时
**不会被排除** → 打到自己。

✅ 判据：**射线节点的直接父级是否就是发射者**？不是就要手动 `add_exception()`。

### ④ 即时射线：什么时候不用节点

⚠ **`RayCast3D` 每物理帧算一次，结果保留到下一物理帧**
（官方原话：*"calculates intersection every physics frame, and it holds the
result until the next physics frame"*）。

✅ 在同一物理帧内要多次查询（穿透弹连续命中、子步进扫描），
必须用即时射线，**不能**靠节点：

```gdscript
var space := get_world_3d().direct_space_state
var q := PhysicsRayQueryParameters3D.create(from, to)
q.collide_with_areas = true
q.exclude = [shooter]                     # ⚠ 显式排除发射者
var hit := space.intersect_ray(q)
```

ⓘ 想保留节点形式又要立即更新，可 `force_raycast_update()`
（官方注明 **`enabled` 不需要为 true 也会生效**）。

## 6. 高速穿透：子步进的具体做法

⚠ **官方 troubleshooting 有专门一节**：*"Objects are passing through each other
at high speeds"*。
官方给的缓解手段之一仍是提高 `Physics Ticks per Second`，
且明确代价：*"increases CPU utilization and **may not be viable for
mobile/web platforms**"*，建议取 60 的倍数（120 / 180 / 240）。

⚠ **结论：提高 tick 是全局成本，子步进是局部成本。**
只让投射物做子步进，不必让整个世界跑 240Hz。

### 判据：先算这一帧走了多远

```gdscript
const MIN_OBSTACLE := 0.15      # 场景里最薄的墙/障碍物厚度

func _physics_process(delta: float) -> void:
    var step := velocity * delta
    var steps := ceili(step.length() / MIN_OBSTACLE)
    steps = clampi(steps, 1, MAX_SUBSTEPS)      # ⚠ 必须封顶
    var sub := step / steps
    for i in steps:
        var from := global_position
        var to   := from + sub
        var hit := _cast(from, to)
        if hit:
            _on_hit(hit)
            return                               # ⚠ 命中即停
        global_position = to
```

⚠ **`steps` 必须封顶。** 速度异常大（数值 bug、传送）时
`steps` 会变成几百上千，帧率直接崩——
而这恰恰是最难复现的那类线上卡顿。

⚠ **命中即停，⛔ 不要继续跑完剩余子步** ——
否则一发子弹在同一帧命中同一目标多次。

### ⚠ 形状缩放是无效的

⚠ **官方明确：Godot 目前不支持缩放物理体与碰撞形状**
（*"does not currently support scaling of physics bodies or collision shapes"*）。

✅ 要改碰撞体大小，**改 extents，不是改 scale**。

⚠ 还有一条连锁坑：**碰撞形状资源默认共享** ——
改 extents 会影响**所有**使用该资源的节点。
官方给的两种处理：编辑器里点碰撞形状资源下拉菜单改，
或脚本里先 `duplicate()` 再改。

⛔ 从对象池里取出的子弹共享同一个 shape 资源，
一个改了尺寸 → **全场子弹尺寸都变**。

## 7. 命中判定流程（可照做的顺序）

```text
1. 收集候选（ShapeCast / 射线 / Area 信号）
2. 过滤：发射者、已命中集合、同阵营、无敌帧
3. 排序：按距离取最近（⛔ 不是按返回顺序）
4. 结算伤害（→ combat.md）
5. 去重登记：hit_id 写入已命中集合
6. 决定去留：销毁 / 穿透继续 / 弹射 / 追踪转向
7. 回池（⛔ 不是 queue_free 完事）
```

⚠ **第 3 步必须按距离排序。** `intersect_shape` 的返回**不保证顺序**，
靠"第一个就是最近的"会在多目标重叠时随机选一个。

### 穿透弹的去重

⚠ **穿透弹必须带"已命中集合"，⛔ 不能只靠"命中后禁用碰撞"。**

禁用碰撞的方案在两个目标紧贴时会漏掉第二个目标
（同一帧、同一子步、两者都在扫描范围内）。

```gdscript
var _hit_ids := {}          # ⚠ 每个投射物实例一份，⛔ 不能是静态/全局

func _try_hit(target: Node) -> bool:
    var id := target.get_instance_id()
    if _hit_ids.has(id):
        return false
    _hit_ids[id] = true
    return true
```

⚠ **回池时必须清空这个集合** —— 复用时残留会导致"第二发打不中"。

### 弹射（bounce）

⚠ **弹射次数必须上限**，且每次弹射后**重置已命中集合**
（否则弹回来打不到同一个目标，看起来像 bug）。

⚠ 反射用 `bounce()` ⛔ 不是 `reflect()`（详见 `puzzle.md` 反射那一节）：
Godot 里 `bounce = -reflect`，混用得到**相反方向**。

### 追踪（homing）

⚠ **追踪改的是速度方向，不是直接设 position。**
直接设 position 会让子步进的"上一帧位置"失效 → 穿透检测形同虚设。

⚠ 转向要有**角速度上限**，否则高速目标会让弹丸瞬间掉头，
视觉上像瞬移。

## 8. ⚠ 预测线：唯一正确的做法

⚠ **预测线不能"另外写一套简化公式"。**
第 2 节说了原则，这里给可执行的做法：

✅ **真实弹道与预测线必须调用同一个 `step()` 函数，用同一份参数**：

```gdscript
# ✅ 唯一的状态推进函数，真实的与预测的都调它
func step(pos: Vector3, vel: Vector3, dt: float) -> Dictionary:
    vel += Vector3.DOWN * gravity * dt
    return {"pos": pos + vel * dt, "vel": vel}

func predict(from: Vector3, vel0: Vector3) -> PackedVector3Array:
    var pts := PackedVector3Array()
    var p := from
    var v := vel0
    for i in MAX_PREDICT_STEPS:
        var r := step(p, v, FIXED_DT)     # ⚠ 同一函数、同一 dt
        var hit := _cast(p, r["pos"])
        if hit:
            pts.append(hit.position)      # ⚠ 只画到首个碰撞点
            break
        p = r["pos"]; v = r["vel"]
        pts.append(p)
    return pts
```

⚠ **预测必须用 `FIXED_DT`，⛔ 不能用帧 delta** ——
帧率一变预测线就抖，且与实际落点产生系统性偏差。

ⓘ 这条与 `netsync` 域里"重放必须用 FIXED_DT"是**同一条原理**：
任何"预测/重放"要与真实一致，**时间步必须固定**。

⚠ **预测步数要封顶** —— 平射时永远打不到地面，
不封顶就是每帧几百次射线。

## 9. 生命周期与对象池

⚠ **投射物是典型的"频繁生成销毁"对象**，必须池化（→ `systems.md` 对象池）。

回池前必须清理的四类状态：

| 状态 | ⛔ 不清理的后果 |
|---|---|
| `_hit_ids` 已命中集合 | **第二发打不中** |
| 速度/方向残留 | 从池里取出就往旧方向飞 |
| 已连接的信号 | 回调打到旧目标 |
| 尾迹粒子/拖尾 | 视觉残留在新弹道上 |

⚠ **超距与超时都要有。** 只做超距的话，
朝天空射的箭会一直飞（永不超距）；只做超时的话，
慢速弹在超出场景前就被回收。

ⓘ 死亡/重生时也要清飞行中的投射物（→ `survival.md` 第 2 节）。

## 10. 待核对项（运行时验证）

⚠ 待核对：ShapeCast 与 CCD 在目标物理后端的实际表现 · 验证：Jolt / GodotPhysics 各跑一遍穿透回归

⚠ 待核对：4.7.2 是否存在命中回溯相关 API · 验证：检索 Class DB 与 PhysicsDirectSpaceState

## 11. 相关文档

> 本篇是**投射物**（穿透、预测线、网络不进快照）。枪械这一武器门类本身——后坐力、扩散、换弹、切换、ADS、掩体、命中权威 → 见 `firearms.md`


- 战斗系统基础 → `combat.md`
- 命中反馈与游戏感 → `vfx-feel.md`
- 网络同步进阶 → `netsync-advanced.md`
- 多人基础 → `multiplayer.md`
- 物理进阶 → `vehicle-physics.md`
- 对象池 → `systems.md`
- 服务器权威 → `security.md`
- 反射用 `bounce()` 而非 `reflect()` 的原因 → `puzzle.md`
- 重放/预测必须用 `FIXED_DT`（同一条原理） → `netsync-advanced.md`
- 死亡重生时清理飞行中投射物 → `survival.md`
- 枪械本体（后坐力/扩散/换弹/ADS） → `firearms.md`
