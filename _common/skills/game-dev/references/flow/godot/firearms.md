# 枪械 / 射击系统（Godot 4.7.2）

**此前文档里「后坐力 / 弹道下坠 / 武器切换 / 换弹 / 载弹量 / 瞄准 / 掩体 / 射击」全部 0 命中。**

> ⚠ **与既有文档的分工**：
> `combat.md` 是伤害公式与**对抗层**（硬直/霸体/破防/招架/处决）；
> `projectile.md` 是**投射物**（高速穿透、预测线复用真实弹道、命中判定、网络不进快照）；
> `vfx-feel.md` 是打击感。
> 本篇是**枪械这一武器门类本身**——射击状态机与它独有的四套时钟。

⚠ **枪械首先是一套「射击状态与规则层」，不是动画层。**

> 审核用反模式清单见 `audit/godot/firearms.md`

## 0. FireContext：所有射击参数从同一份状态派生

```text
InputRequest
  -> WeaponStateMachine.consume()
  -> validate(owner, weapon, ammo, cooldown, state, authority)
  -> create FireContext(muzzle, aim, spread, ads, seed/index, input_time, ammo_type)
  -> resolve_hit(ctx) | spawn_authoritative_projectile(ctx)
  -> apply recoil/spread cadence, consume ammo, emit events
  -> replicate confirmed result + cosmetic trace
```

| 资源 | 装什么 |
|---|---|
| `WeaponStats` | 只放**可策划数值** |
| `WeaponRuntime` | 弹匣、连发序号、后坐力累积、当前扩散 |
| `PlayerLoadout` | 按**弹药类型**或武器类型聚合的备弹 |

⛔ **动画不得保存"当前有几发"** —— 若 `AnimationPlayer` 在通知里写 `current_ammo`，
换弹取消、快速切换和预测回滚都会**失去唯一事实源**。

⚠ **输入不能只在按下瞬间消费一次。** 保留 `BufferedAction { type, request_time, payload }`：
闲置可立即执行；换弹/切换/ADS 过渡期缓存一个"最具意图"的请求。
否则玩家连按两次射击只开一枪，手感像丢输入。
⚠ 输入时间戳必须随请求进入服务端验证，⛔ 不能与网络到达时间混用。

## 1. hitscan 与 projectile：选择依据是手感，不是优劣

⚠ **唯一标准：玩家是否需要感知弹丸本身。**

| 选择 | 适用手感 | 必须承担的成本 |
|---|---|---|
| **hitscan** | 无飞行时间、瞬时反馈、激光/近距武器 | 无领先瞄准、无真实弧线 |
| **实体弹丸** | 飞行时间、领先瞄准、明显下坠、可躲避、可见轨迹 | 持续模拟、穿透/隧道、销毁边界、持续同步 |
| hitscan 裁决 + 投射物表现 | 既要瞬时可玩又想有飞行视觉 | ⚠ 表现若用不同积分器，玩家会把 tracer 当成实际弹道 |
| 短程 hitscan + 长程弹丸 | 不同开火模式或配件 | 两套命中规则要显式切换，⛔ 不能藏在动画里 |

⚠ **Godot 侧**：`RayCast3D` 是**持续检查**（上一物理帧的结果，位置变了要 `force_raycast_update()`）；
`PhysicsDirectSpaceState3D.intersect_ray()` 是**即时快照**，
且直接空间访问的安全期在 `_physics_process()`。

⚠ 不要每帧挂 `RayCast3D` 又只在开火时读；也不要在 `_process()` 里依赖过期节点射线。

```gdscript
func trace_shot(from: Vector3, to: Vector3, shooter_rid: RID, mask: int) -> Dictionary:
    var params := PhysicsRayQueryParameters3D.create(from, to, mask, [shooter_rid])
    params.collide_with_bodies = true
    params.collide_with_areas  = false   # 伤害实体关掉
    return get_world_3d().direct_space_state.intersect_ray(params)
```

⚠ **命中点必须归一化为权威源**：hitscan 起点是枪口、方向从摄像机准星反推；
projectile 起点是生成位置、方向是初速度方向。
⛔ **不要让摄像机射线先命中、再把"摄像机命中点"当子弹最终位置**——
贴墙、探头和部位判定都会错位。

## 2. 后坐力是三个独立变量，不是镜头抖动

⚠ **"后坐力 = 镜头抖动"是枪械实现最常见的错位。**

| 变量 | 职责 |
|---|---|
| **视觉后坐力** `viewkick` | 只驱动摄像机/枪模表现 |
| **模式后坐力** `pattern_offset` | 决定当前**弹道中心**相对瞄准中心的确定性偏移 |
| **扩散** `spread_radius` | 最终落点在模式中心周围的随机半径 |

```
final_aim = aim + pattern_offset + spread_sample
```

⚠ 玩家输入可以抵消**视觉**后坐力，但只能服从**模式**后坐力。
⛔ 直接改摄像机旋转生成子弹方向 → 准星与落点**永久错位**。

⚠ **固定模式让玩家建立"压枪—落点"的因果链**。
保存 `(pitch, yaw)` 数组或曲线，越界时进入稳态随机，⛔ 不是从第一发重新开始。
⛔ 纯随机横跳没有可学习性——压枪类枪的横向模式尤其不能每发完全随机。

```gdscript
func apply_shot_recoil() -> void:
    var i := mini(shot_index, pattern.size() - 1)
    pattern_offset += pattern[i]          # 实际弹道中心
    viewkick.vector += view_kick_table[i] # 只驱动摄像机
    shot_index += 1
```

⚠ **恢复不能每帧朝零插值** —— 开火期间应停止或削弱回中，
否则第一发上抬被立即抵消。停止射击后恢复才接管（`decay_delay` 后开始）。

⚠ **玩家压枪时**：记录玩家输入产生的相对旋转，与模式偏移**分别相加**；
停止射击只让模式回零，⛔ **不能从摄像机当前角度直接插值回正**
（玩家已经下压鼠标，枪口却停在准星下方）。

⚠ **视觉后坐力不可无限累积**：摄像机短期上抬、中期阻尼回零、长期 roll 扰动。
⛔ 动画师不能手工 key 一套与数据无关的动作。

## 3. 扩散必须可读、可收敛

⚠ **不可读的 Random Circle 只是随机惩罚。**

```gdscript
func current_spread_deg() -> float:
    var s := base_spread
    s *= ads_spread_mult if ads.active else 1.0
    s *= move_spread_mult(owner.velocity)
    s *= stance_spread_mult(owner.stance)
    return mini(s + bloom, max_bloom)
```

⚠ 命中半径要**同时进入两个出口**：真实方向 + **UI 准星尺寸**。
⚠ **准星只负责信息，不得反向参与命中** ——
否则缩放动画、画布宽高比会偷偷改变枪法。
⚠ 准星显示 2° 实际用 4° → 玩家认为系统骗他。

⚠ **首发精度不是"第一发散布为零"，而是一个可配置窗口。**
推荐 `first_shot_bloom_bonus = 0`（静止首发直接取基础值），
但基础值本身可保留极小扰动作为远距离技巧门槛。
连发按"每发固定增量 + 恢复折扣"，⛔ 不是无限叠加。

⚠ **恢复要分层**：移动时停止恢复；停止后先经小延迟再指数恢复；
ADS 期间更快收敛，但退出 ADS 不立即恢复全部腰射扩散。
⚠ 准星更新要在物理后或统一 tick 算一次，⛔ 每帧抖动会"越看越乱"。

## 4. 弹道下坠：必须与预测共用一个积分器

⚠ **近战/霰弹/室内冲锋枪通常不需要真实下坠**，中远距离精确武器才需要。
若最大交战距离短、弹速高，下坠只有零点几像素却增加参数耦合与命中争议 → **应直接归零**。

```gdscript
const G := 9.81
func step_ballistic(pos: Vector3, vel: Vector3, dt: float) -> Dictionary:
    vel.y -= G * gravity_scale * dt
    pos   += vel * dt
    return {"position": pos, "velocity": vel}
```

⚠ **sub-step 要用固定 `h` 与累加器**，⛔ 不能让帧率改变下坠量。
⚠ **服务端判定与客户端轨迹预览必须调用同一份 `step_ballistic()`。**
不同函数、不同重力缩放、忽略初速帧、把 `gravity_scale` 当艺术参数
→ "预测线穿过墙，实际弹丸却命中墙后"。

⚠ **穿透要独立成规则表**，⛔ 不能复用装饰性材质标签：
可穿透层数 · 每层厚度 · 材质硬度 · 角度阈值 · 每次穿透后的速度衰减与伤害衰减。
薄墙扫射与厚墙单点穿透是不同玩法，⛔ 不能靠一个布尔解决。

## 5. 换弹：逻辑门限 / 动画 / 可取消窗口 三件事分开

⚠ **"动画播完"与"换弹完成"不是同一事件。**

```
Idle -> Start -> SwappingMag -> Chambering -> Ready -> Recover
                     ↑真正改变弹匣和备弹的是这里
```

⚠ **战术换弹与空仓换弹的语义不能混**：
枪膛保留一发时，新弹量是 `弹匣容量 + 膛内一发`，备弹只扣弹匣容量；
空仓换弹扣完整弹匣容量并另做上膛。
⛔ 图省事统一 `reserve -= magazine.capacity` → **玩家白丢一发**。

```gdscript
func _physics_process(delta: float) -> void:
    if state != WeaponState.RELOADING: return
    logical_time += delta
    if logical_time >= MAG_SWAP_TIME and not mag_added: add_magazine()
    if logical_time >= CHAMBER_TIME  and not chambered: chamber()
    if logical_time >= READY_TIME     and not ready:     enter_ready()
```

ⓘ 示例门限（0.80 s / 1.20 s）**不是行业标准**，每个武器须按动画关键帧实测。

⚠ **取消策略要在四个对象上保持一致：动画、状态、弹药、输入。**
允许取消的条件通常是"**弹药已经加入**"，而不是"动画随便被打断"。
取消事件负责停动画、清除 chambering/ready、退出换弹状态；
⛔ **不得重新执行 `add_magazine()`，也不得跳过已发生的弹药变更**。

⚠ 最易出的 bug：**动画因切枪停止，逻辑函数却没运行** → "取消换弹但弹药没加"。

**推荐取消规则：**
1. 逻辑装填未完成时，切换/奔跑/近战只取消动作，**不获得弹药**
2. 逻辑装填完成后，可自由打断收尾并**保留新弹匣**
3. 开火打断只在 `READY` 阶段允许（否则"换弹不能开火"的窗口被废掉）
4. 每阶段由**状态机**推进，动画用 `seek`/cross-fade 跟状态，⛔ 不是动画通知反向驱动弹药
5. 死亡、丢弃武器、换包、网络回滚走**同一** `cancel(reason)` 路径

## 6. 武器切换：核心是"部署门限"

⚠ **切换不能瞬间完成，也不能让动画长度决定开火时间。**

| 阶段 | 作用 |
|---|---|
| `InputLock` | 禁止立即重复切枪 |
| `DeployAnim` | 武器抬起到可操作（**可以比可射击门限更长**） |
| `Ready` | 首个射击请求窗口 |

⚠ 等动画**完全结束**才允许射击 → 玩家感觉输入迟钝。

⚠ **切换期间的射击请求只有三种合法策略：丢弃 / 缓冲 / 延迟执行。**
⛔ 不建议"直接执行"——那时新武器可能还没完整部署。

```gdscript
func request_fire() -> void:
    if state == WeaponState.SWITCHING or \
       (state == WeaponState.RELOADING and not can_fire_cancel_reload()):
        input_buffer.store(FIRE); return
    try_fire()

func finish_switch() -> void:
    state = WeaponState.IDLE
    if input_buffer.consume(FIRE): try_fire()
```

⚠ **快速切换 bug 的本质是"取消表现，却让状态副效应凭空消失"。**
典型链：换弹开始 → 切走 → 旧武器队列释放/隐藏 → reload notify 永不触发 →
切回时 `instantiate` 新实例或读到默认满弹。

✅ 正确模型：**切换不是销毁武器，而是 `disable`**；
弹药保存在武器实例或 loadout 中；切走时若正在换弹，明确调 `cancel(reason)`
决定保留多少；切回时从运行时状态恢复。

⚠ **"切换动画取消换弹"不应成为免费加速** ——
若玩家通过切枪获得完整弹匣且无时间成本，那已是**经济型漏洞**，不是操作深度。

## 7. ADS 是独立状态，扩散按乘区组合

```
AdsState = INACTIVE | ENTERING | STEADY | EXITING
```

⚠ 只有 `STEADY` 获得完整瞄准修正；过渡期可逐渐提高精度，
⛔ **不应瞬间消除全部扩散**（玩家会感觉前几毫秒开了挂）。

```gdscript
total_spread = base_spread
             * ads_profile.spread_mult      # 通常 0.2~0.5
             * move_profile.spread_mult
             * stance_profile.spread_mult
             + bloom                        # 连发累积是加法量
```

⚠ **乘法还是加法要二选一并写进数据规约**，
⛔ 不要在代码里散落 `if ads: spread *= 0.5; if crouch: spread -= 0.3`。
多个"减半"乘区自然可组合；纯加法在小基础值时效果微弱、大基础值时溢出。

⚠ **ADS 要获得精度，同时支付机动**：移动速度降低、灵敏度需换算、
视野变窄导致侧翼信息减少。
⚠ **FOV 插值要帧率安全**，用 `1 - exp(-k*dt)`，⛔ 不能 `lerp(cur, tgt, speed*dt)`。
⚠ FOV 变化会改变等效鼠标灵敏度（这是设置层问题，不是命中层）。

⚠ **ADS 与后坐力要分开**：模式后坐力可随 ADS 降低，视觉后坐力可更强或更易读，
⛔ 二者不得互相覆盖。若枪模从肩膀抬起导致 camera pivot 变化，
要保证最终瞄准点**不因 pivot 不同而产生跳变**。

## 8. 掩体：三套坐标（瞄准 / 角色 / 枪口）

⚠ **软掩体与硬掩体的区别是规则，不是碰撞形状。**
⛔ **不要让同一个"叶子碰撞体"同时承担弹道、AI 视线和玩家隐藏** ——
会出现"客户端看到一丛草，服务器根本没有这根草"。

⚠ **探头应控制可见身体比例、暴露时间和枪口位置**，
⛔ 不是把整个角色偏移。

⚠ **第三人称的核心矛盾**：camera shoulder socket、角色 spine/手部 bone、
枪口 muzzle 通常**不在同一竖线**。
从摄像机中心发射线 → 玩家"看到头露出来"却打不到人；
从枪口发射线 → 贴墙探头时看不见目标却命中。

**推荐方案：**
1. 瞄准射线始终从**统一命中源 socket** 发出
2. 第三人称时命中源受 lean 与 muzzle 约束，**不能穿墙**
3. 摄像机 shoulder socket **独立**控制视野
4. 命中源 socket 会被墙遮挡时 → 强制收枪 / 禁止开火 / 缩小暴露
5. **预测线从同一 socket 积分**，⛔ 不从摄像机中心积分
6. 掩体收益以"**暴露比例 / 受击部位**"衡量，⛔ 不是摄像机能否看见敌人

⚠ **"玩家看到只露头，服务器看到整个身体"**：
服务端维护权威 body/head hitbox、姿态和 lean；
⚠ **客户端摄像机只能用于输入投射，⛔ 不能把渲染结果发回服务端**。
⚠ 服务端对探头边界做胶囊/形状夹紧，避免极端 lean 让头模型穿墙。
⚠ 探头切换用固定时长状态机，⛔ 不能逐帧把摄像机自由拖到墙外。

## 9. 弹药：是节奏资源，备弹要支持多武器共享

⚠ 核心问题不是"数字多大"，而是**它限制什么**。
有限弹匣/备弹限制持续交战与一打多；无限备弹把压力转移给换弹时间与切换；
弹药类型增加决策但也增加背包与命中规则复杂度。
PvE 可偏资源收集，PvP 更偏战斗节奏与暴露窗口。

| 模型 | 优点 | 风险 |
|---|---|---|
| 按武器保存备弹 | 切换代价清晰、逻辑简单 | 背包可能碎片化 |
| **按弹药类型共享** | 更符合后勤资源模型 | 需统一规则与拾取归属 |
| 按完整弹匣保存 | 拟真、补给判断直观 | 余弹管理复杂，换弹会"合成弹匣" |

⚠ **`consume()` 永远先检查再写值**，
⛔ 不能在 RPC 中信任客户端传来的 `current_ammo`、`cost` 或 `max_reserve`。
⚠ 弹药类型应是稳定的 `AmmoType` 资源，⛔ 不是武器名字符串。
穿甲与高爆要定义：基础伤害 · 对护甲/材质倍率 · 是否爆炸 · 伤害半径 · 友伤规则。
⚠ **爆炸半径用独立 area/几何查询**，⛔ 不复用 hitscan 单点结果。

## 10. 多人射击：服务端验证输入与结果

⛔ **命中判定绝不能由客户端说"我打中了 X，扣 Y 血"。**

```gdscript
@rpc("any_peer", "call_remote", "unreliable")
func request_fire(input_time: int, seed: int, origin: Vector3, aim: Vector3) -> void:
    if not _is_valid_fire_request(multiplayer.get_remote_sender_id(), input_time):
        return
    var ctx := build_authoritative_context(origin, aim, seed)
    resolve_and_apply(ctx)
```

⚠ **射击请求可用不可靠传输**（旧射击包过期后没有执行价值）；
⚠ **命中确认、弹药变化、死亡与状态转换要用可靠有序传输**。
⚠ 不要每帧为每个 projectile 发位置 RPC —— 服务端持续模拟、低频同步、客户端预测外插。
⚠ 时间戳用固定模拟时钟，⛔ **不要混用 `Time.get_ticks_msec()` 与服务器 tick 时基**。

### 延迟补偿（rewind）

⚠ **正确含义是服务端在客户端输入时刻重建历史世界，⛔ 不是让客户端自行判定。**

```text
client input_time T
-> 服务端找最近的权威状态 t0/t1，插值出快照 S(T)
-> 只把命中相关实体回滚到 S(T)
-> 用同一确定性 resolver 判定
-> 在当前权威状态应用结果
-> 恢复当前状态
```

⚠ **窗口上限、最多回滚玩家数、是否回滚 hitbox animation、是否忽略非射击实体，
都应可配置。** ⛔ 没有边界的 rewind 会引入重计算、时钟伪造和时间跳跃漏洞。

⚠ **peeker's advantage 是客户端预测与延迟的固有产物，⛔ 不是"修好 rewind 就没了"。**
缓解：限制 rewind 窗口 · 提高服务端 tick · 双方一致的插值/外推 ·
把射击响应严格标成"本地预测" · ⛔ **观战视角不要混入 rewind 逻辑**（会造成误判）。

**权威清单：**

| 类别 | 内容 |
|---|---|
| **服务端权威** | 输入时间、弹药、冷却、武器状态、开火资格、命中源、射线/projectile、部位、伤害、护甲、穿透、击杀、备弹、换弹结果、位置与移动 |
| **客户端可预测** | 相机 viewmodel、轨迹、音效、非关键命中标记、hitstop/HUD |
| **服务端必须重算** | 客户端声称的 origin、direction、distance、penetrations、damage、hit result |
| **不进快照** | 纯视觉 tracer、弹壳、命中火花、UI 状态、摄像机抖动 |
| **可协商** | hitstop 时长、拖尾与屏幕反馈（⛔ 但反馈不得反向改变伤害） |

## 11. 待核对项（运行时验证）

⚠ 待核对：换弹逻辑门限（示例 0.80 s / 1.20 s）与切换部署门限 ·
验证：**示例值非行业标准**，须按动画关键帧、手感与平衡实测

⚠ 待核对：扩散乘区取值（ADS 0.2~0.5、移动/姿态倍率）·
验证：须在典型交战距离下测"命中圆直径是否超过目标头部/躯干"

⚠ 待核对：是否需要真实弹道下坠 ·
验证：取决于最大交战距离与弹速；短距离高弹速应直接归零

⚠ 待核对：rewind 窗口上限与回滚范围 ·
验证：无边界 rewind 会引入时钟伪造；须按 tick 与延迟分布实测

⚠ 待核对：备弹模型（按武器 / 按弹药类型 / 按弹匣）·
验证：三种是不同设计，须按玩法取舍

## 12. 相关文档

- 伤害公式与对抗层 → `combat.md`
- 投射物、穿透与预测线 → `projectile.md`
- 打击感与 hitstop → `vfx-feel.md`
- 网络同步进阶与 rewind → `netsync-advanced.md`、`multiplayer.md`
- 反作弊与服务器权威 → `security.md`
- 潜行与掩体 → `stealth-ai.md`
