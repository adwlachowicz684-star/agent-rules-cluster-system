<!-- oversize-exempt: 引擎 API 查表文档，按 API 索引，需整体查阅 -->
# Godot 4.x 物理系统核心 API 审查清单

## 摘要

本清单聚焦 Godot 4.x 中角色、刚体、静态/可动画体、区域、碰撞层、射线和空间查询的核心 API。最高优先级的迁移结论是：`move_and_slide()` 在 4.x 为无参方法，必须写入节点自带 `velocity`，而不能把 `move_and_slide(velocity, up)` 等 3.x 写法照搬到 4.x；静态类型源码中还可能因局部变量遮蔽 `Velocity` 而导致角色不动 [1][2]。刚体 API 的持续性力与一次性冲量不可混用：每物理帧调用 `apply_impulse()` 会随物理 tick 变化，官方明确建议一次冲击才使用冲量 [5]。静态体与可动画体的关键区别不是“会不会移动”，而是移动后是否计算速度并推动路径上的其他物体；`StaticBody` 传送，`AnimatableBody` 同步至物理帧并估算速度 [6][7]。碰撞层与掩码是位掩码，第 N 层对应 `1 << (N-1)`；常见错误是把第 3 层写成 `3`、把“第 2 层”写成位值 `2` 却误以为是 2 号槽 [8]。直接空间查询统一使用 `Physics*QueryParameters*D` 的 `RefCounted` 对象；结果与 3.x 仍为字典式 `Dictionary`，但参数对象本身不是字典 [10][11]。物理逻辑应放在 `_physics_process(delta)`，默认固定 60 tick；`delta` 不是永远精确的 1/60，改变 tick 时也不能假定插值已经自动消除视觉卡顿 [12][13]。

## 适用范围、版本与判据规则

本文优先采用 docs.godotengine.org 的 4.0、4.2 和 4.x 类参考，结合官方 2D 角色教程、物理入门教程和射线投射教程交叉确认。除特别标注外，2D 与 3D 节点在 API 形状上基本对应，仅向量、节点名后缀和少量 3D 特有属性不同。本文不重复列 `_process` 内容，所有“必须物理帧”的结论只针对物理对象与查询。

正则判据用于静态扫描，不是语法完备分析。搜索时应按源码的原始语言选择对应模式：GDScript 优先检查小写成员调用与属性读取，C# 检查 PascalCase 的 Godot API。不要用单一判据自动判定为错误；例如 `apply_impulse` 出现在 `_physics_process` 里才更值得告警，`get_overlapping_bodies()` 在 `force_update` 之后读取应降为建议。正则可额外加入前后的 `physics_process`、`_ready`、`set_physics_process`、`enabled`、`monitoring`、赋值符或方法调用上下文，以减少误报。

置信度分三级：官方明确＝官方类参考或教程直接陈述；社区共识＝官方 API 表面支持、多个官方示例/社区常见做法共同支持；推测＝由 API 语义推导、尚未由文档逐字确认，审查时应要求补测或补源码证据。

## 1. CharacterBody2D/3D

### CharacterBody2D/3D.velocity
- **签名**：`var velocity: Vector2` / `Vector3`（GDScript 成员属性）；`Vector2 Velocity { get; set; }` / `Vector3 Velocity { get; set; }`（C#）
- **用途**：角色当前速度，单位为每物理秒；`move_and_slide()` 会读取并修改它，不再以返回值承载最终速度。
- **误用**：局部声明 `var velocity := Vector2.ZERO` 会遮蔽节点属性；代码对局部变量赋值后，`move_and_slide()` 仍读取零速度。也常见先乘 `delta` 再写入 `velocity`，导致重力/加速每帧被重复缩放；`move_and_slide()` 自己按物理时间步进。
- **判据**：GDScript：`move_and_slide\s*\(`；`velocity\s*\.`（访问分量）；`velocity\s*[\+\-\*]=`；C#：`MoveAndSlide\s*\(`；`Velocity\s*=|\.Velocity\.|Velocity\s*;`。
- **置信度**：官方明确 [1][2]。

### CharacterBody2D/3D.move_and_slide()
- **签名**：`void move_and_slide()`（GDScript）；`void MoveAndSlide()`（C#）；4.x 无位置、速度、上方向参数，无返回值。
- **用途**：按当前 `velocity` 执行运动，并在接触时执行滑动、地板/墙/天花板分类与 snap 等处理；属于“我移动，引擎算响应”。
- **误用**：`velocity = move_and_slide(velocity, Vector2.UP)`、`move_and_slide(velocity)` 是 3.x 残留；即使旧签名能通过字符串残留而误导，4.x 也不应传入 velocity。将 `move_and_slide()` 放在 `_process()` 会使速度与渲染帧耦合，掉帧或高刷设备上行为不稳定；放到 `_physics_process(delta)`。
- **判据**：`move_and_slide\s*\([^)]+`；`velocity\s*=\s*move_and_slide`；C#：`MoveAndSlide\s*\([^)]+`；命中后优先提示迁移。
- **置信度**：官方明确 [1][2]。

### CharacterBody2D/3D.is_on_floor()
- **签名**：`bool is_on_floor()` / `bool IsOnFloor()`。
- **用途**：上一次 `move_and_slide()` 后是否把某接触面判定为地板；用于跳跃许可、地面摩擦/动画状态。
- **误用**：只在调用 `move_and_slide()` 之后有效；不要读取后立刻修改 `velocity`、下一行就假定状态仍是同一物理步。更不要把 `is_on_floor()` 当“刚离开地面”的边沿信号，应自行记录上一物理帧状态。
- **判据**：`is_on_floor\s*\(`；`IsOnFloor\s*\(`。
- **置信度**：官方明确 [1][3]。

### CharacterBody2D/3D.is_on_wall()
- **签名**：`bool is_on_wall()` / `bool IsOnWall()`。
- **用途**：判断上一次滑动结果是否存在墙接触，配合 `get_wall_normal()` 做墙滑、墙跳。
- **误用**：`MOTION_MODE_GROUNDED` 下才按 floor/wall/ceiling 分类；`MOTION_MODE_FLOATING` 下所有碰撞被视为“墙”，此时 `is_on_wall()` 会失真。也不要单独靠它判定“贴墙”，应结合速度方向或法线，避免站在墙角/地面时的状态歧义。
- **判据**：`is_on_wall\s*\(`；`IsOnWall\s*\(`。
- **置信度**：官方明确 [1][3]。

### CharacterBody2D/3D.is_on_ceiling()
- **签名**：`bool is_on_ceiling()` / `bool IsOnCeiling()`。
- **用途**：判定上一次移动后是否顶到天花板。
- **误用**：不能替代通用头撞检测；若角色以非标准上方向运动（如顶视、重力可变），需先设 `up_direction`。仅存在碰撞也不保证是 ceiling，分类仍依赖 `up_direction`。
- **判据**：`is_on_ceiling\s*\(`；`IsOnCeiling\s*\(`。
- **置信度**：官方明确 [1][3]。

### CharacterBody2D/3D.get_slide_collision_count()
- **签名**：`int get_slide_collision_count()` / `int GetSlideCollisionCount()`。
- **用途**：返回最近一次 `move_and_slide()` 产生的滑动碰撞数，作为遍历索引边界。
- **误用**：旧 3.x 是 `get_slide_count()`；迁移时只改半句会找不到方法。该计数只在最近一次 slide 后有语义，不能在帧末多次复用为“当前所有接触”。
- **判据**：`get_slide_collision_count\s*\(`；`GetSlideCollisionCount\s*\(`；同时告警 `get_slide_count\s*\(`。
- **置信度**：官方明确 [3][9]。

### CharacterBody2D/3D.get_slide_collision(i)
- **签名**：`KinematicCollision2D get_slide_collision(int slide_idx)` / `KinematicCollision3D GetSlideCollision(int slideIdx)`。
- **用途**：按索引取得滑动碰撞信息：碰撞体、法线、接触点、剩余运动等。
- **误用**：索引越界会返回无效结果；应使用 `for i in get_slide_collision_count():` 而不是硬编码到固定次数。不要把“最后一个碰撞”当成“最重要的碰撞”，顺序取决于内部碰撞解算，业务应按 normal/tag/collider 再筛选。
- **判据**：`get_slide_collision\s*\(`；`GetSlideCollision\s*\(`。
- **置信度**：官方明确 [3][9]。

### CharacterBody2D/3D.up_direction
- **签名**：`Vector2 up_direction` / `Vector3 UpDirection`。默认 2D `(0,-1)`、3D `(0,1,0)`。
- **用途**：定义“上”方向，从而决定哪些面算地板/墙/天花板。
- **误用**：重力方向改变时只改重力没改 `up_direction`，会导致地面判定错乱。注意 2D 中默认“负 Y 为上”，与 3D 的“正 Y 为上”不同；不要无脑复用字符串常量。
- **判据**：`up_direction\s*=|set_up_direction|UpDirection\s*=`。
- **置信度**：官方明确 [1][3]。

### CharacterBody2D/3D.floor_max_angle
- **签名**：`float floor_max_angle` / `float FloorMaxAngle`；默认约 `0.785398` 弧度（45°）。
- **用途**：超过该角与 `up_direction` 偏差的面不再被认定为地板。
- **误用**：使用角度制直觉设置 `floor_max_angle = 50` 是严重错误，4.x 中是弧度；会接近 2864°。应写 `deg_to_rad(50)` / `Mathf.DegToRad(50f)`。
- **判据**：`floor_max_angle\s*=`（后接明显大于 `1.6` 的数字时优先告警）；`FloorMaxAngle\s*=`。
- **置信度**：官方明确 [1][3]。

### CharacterBody2D/3D.floor_snap_length
- **签名**：`float floor_snap_length` / `float FloorSnapLength`；2D 默认约 `4.0` 像素，3D 约 `0.1` 米，且跨小距离吸附到地板。
- **用途**：让角色在地面边缘、微台阶或重力累积时保持接地。
- **误用**：离开地面后未禁用 snap，会导致角色在跳跃/下落时被“吸回”平台；官方模式是在空中清零、落地后恢复。3D 中给 `0.1` 像素也是单位错配。
- **判据**：`floor_snap_length\s*=`；`FloorSnapLength\s*=`。
- **置信度**：官方明确 [3][9]。

### CharacterBody2D/3D.motion_mode
- **签名**：`MotionMode motion_mode` / `MotionMode MotionMode`；枚举 `MOTION_MODE_GROUNDED=0`、`MOTION_MODE_FLOATING=1`。
- **用途**：选择地面/墙/天花板分类的运动模型，还是把所有碰撞当墙的悬浮模型。
- **误用**：顶视角色选 GROUNDED 会意外触发“地板/墙”语义；平台角色选 FLOATING 会让 `is_on_floor()` 的分类失效。默认值为 GROUNDED，不能假定某旧场景或子类一定显式设置过。
- **判据**：`motion_mode\s*=|MOTION_MODE_|MotionMode\s*=|\.MotionMode`。
- **置信度**：官方明确 [1][3]。

### CharacterBody2D/3D.safe_margin
- **签名**：`float safe_margin` / `float SafeMargin`；3D 默认 `0.001`。
- **用途**：为连续碰撞解算保留的微小安全间距，用于减少卡边、穿透与解算抖动。
- **误用**：为“防止卡住”直接设为 0 会显著增加卡缝与抖动；盲目放大到角色尺寸量级又会让物体悬空或提前停住。仅在遇到稳定复现的卡边/隧道问题时调整，并在低帧率和高速度下回归测试。
- **判据**：`safe_margin\s*=`；`SafeMargin\s*=`。
- **置信度**：官方明确 [3][9]。

### CharacterBody2D/3D.platform_on_leave
- **签名**：`PlatformOnLeave platform_on_leave` / `PlatformOnLeave PlatformOnLeave`；常见值 `PLATFORM_ON_LEAVE_ADD_VELOCITY=0`、`PLATFORM_ON_LEAVE_KEEP_VELOCITY=1`、`PLATFORM_ON_LEAVE_RESET_VELOCITY=2`；4.2 类参考中还涉及 `platform_floor_layers`、`platform_wall_layers`。
- **用途**：决定角色离开移动平台时如何处理从平台继承的速度，是平台跳跃手感的关键开关。
- **误用**：默认“叠加平台速度”并不适合所有游戏；若角色在平台停下后跳跃仍带着旧平台速度，应审查该项。不要把它理解为“自动让角色永远站稳平台”，还需正确的平台层与 `up_direction`。
- **判据**：`platform_on_leave\s*=`；`PLATFORM_ON_LEAVE_`；`PlatformOnLeave\s*=`。
- **置信度**：官方明确，但具体枚举及默认值会随小版本演进，应在项目实际 Godot 版本类参考中复检 [3]。

## 2. RigidBody2D/3D

### RigidBody2D/3D.apply_force()
- **签名**：`void apply_force(Vector2 force, Vector2 position=Vector2.ZERO)` / `void ApplyForce(Vector2 force, Vector2 position=Vector2.Zero)`；3D 为 `Vector3` 版本。
- **用途**：在质心或指定偏移施加持续力；适合推进器、持续风力，应与每物理帧配合。
- **误用**：只在单次事件里调用一次，容易得到几乎不可见的效果；反过来在 `_process()` 中每渲染帧调用，物理行为会随帧率变化。想要“本物理帧累计受力”，应放在 `_physics_process()`；不要与冲量混名使用。
- **判据**：`apply_force\s*\(`；`ApplyForce\s*\(`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.apply_impulse()
- **签名**：`void apply_impulse(Vector2 impulse, Vector2 position=Vector2.ZERO)` / `void ApplyImpulse(Vector2 impulse, Vector2 position=Vector2.Zero)`；3D 为 `Vector3` 版本。
- **用途**：施加与持续时间无关的瞬间冲量，适合爆炸、单次踢击、跳跃施力。
- **误用**：每物理帧调用会把“冲量”当成持续力，使最终速度随 tick 变化；官方明确警示。不要在 `_physics_process()` 的条件分支里无条件调用，除非该条件本身只在进入/离开瞬间成立。
- **判据**：`apply_impulse\s*\(`；`ApplyImpulse\s*\(`；若其外层/同方法能静态判定为每物理帧重复调用，则提升告警等级。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.apply_central_force()
- **签名**：`void apply_central_force(Vector2 force)` / `void ApplyCentralForce(Vector2 force)`；3D 为 `Vector3`。
- **用途**：只通过质心施加持续力，不引入扭矩。
- **误用**：误以为“central”意味着会自动忽略质量或自动作用于世界坐标某点；它只是偏移默认位于质心。每帧叠加而未加衰减时，仍会使速度持续增加。
- **判据**：`apply_central_force\s*\(`；`ApplyCentralForce\s*\(`。
- **置信度**：官方明确 [4][5]。

### RigidBody2D/3D.apply_central_impulse()
- **签名**：`void apply_central_impulse(Vector2 impulse=Vector2.ZERO)` / `void ApplyCentralImpulse(Vector2 impulse=Vector2.Zero)`；3D 为 `Vector3`。
- **用途**：一次性中心冲量，不产生额外旋转；适合弹跳、无扭矩的击退初值。
- **误用**：2D 重载可省略参数，但写成“零冲量”并无意义；常见问题是把已含质量的“力大小”直接当冲量。冲量仍受物理质量和反作用力关系影响，不能把数值直接理解成每物理秒速度变化。
- **判据**：`apply_central_impulse\s*\(`；`ApplyCentralImpulse\s*\(`。
- **置信度**：官方明确 [4][5]。

### RigidBody2D/3D.apply_torque()
- **签名**：`void apply_torque(float torque)` / `void ApplyTorque(float torque)`；3D 存在向量形式的持续扭矩，2D 为标量。
- **用途**：施加持续旋转力。
- **误用**：每物理帧调用会产生持续角加速度；若只想让门/轮子达到目标角度，还需要阻尼或停止条件。2D 传 `Vector2`、3D 传 `float` 属于典型类型错配。
- **判据**：`apply_torque\s*\(`；`ApplyTorque\s*\(`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.apply_torque_impulse()
- **签名**：`void apply_torque_impulse(float torque)` / `void ApplyTorqueImpulse(float torque)`；3D 使用 `Vector3` 扭矩冲量。
- **用途**：一次性改变角速度。
- **误用**：每物理帧调用会导致角速度无限累积；2D/3D 的标量/向量类型不能互换。不要把它当成“设置角速度”，它执行的是累加。
- **判据**：`apply_torque_impulse\s*\(`；`ApplyTorqueImpulse\s*\(`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.linear_velocity / angular_velocity
- **签名**：`Vector2 linear_velocity` / `Vector3 LinearVelocity`；`float angular_velocity` / `Vector3 AngularVelocity`；角速度单位为弧度每秒。
- **用途**：读取或设置刚体线速度、角速度；可用于受控弹跳初值、限速。
- **误用**：直接每帧覆盖 `linear_velocity` 会绕过部分模拟语义，接近“手动运动体”；刚体更适合施加力/冲量，或使用 `lock_rotation`、`custom_integrator`。在 `_process()` 里覆盖速度，会使高刷与低帧率设备手感不一致。
- **判据**：`linear_velocity\s*=|set_linear_velocity|LinearVelocity\s*=`；`angular_velocity\s*=|AngularVelocity\s*=`。
- **置信度**：官方明确 [4][5]。

### RigidBody2D/3D.freeze
- **签名**：`bool freeze` / `bool Freeze`。
- **用途**：冻结/解冻刚体；冻结后不再受力与重力作用。
- **误用**：把“永久静态障碍”做成运行时来回 `freeze=false` 的 `RigidBody`；静态/可动画体才是更合适的表达。冻结不自动清除速度，解冻后旧速度可能继续生效；应同时按需求重置速度。
- **判据**：`freeze\s*=|set_freeze_enabled|Freeze\s*=|\.Freeze\s*;`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.freeze_mode
- **签名**：`FreezeMode freeze_mode` / `FreezeMode FreezeMode`；常见枚举 `FREEZE_MODE_STATIC=0`、`KINEMATIC=1`、`REPLICATED=2`。
- **用途**：决定冻结时是作为静态碰撞体、可手动运动体，还是复制体行为。
- **误用**：从冻结切回动态时，若模式是 KINEMATIC 而代码没有再切回动态，碰撞响应不会恢复为模拟体。不要把 `freeze_mode` 当动画平台同步开关；那属于 `AnimatableBody.sync_to_physics`。
- **判据**：`freeze_mode\s*=|FREEZE_MODE_|FreezeMode\s*=|\.FreezeMode\s*=`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.can_sleep / sleeping
- **签名**：`bool can_sleep` / `bool CanSleep`；`bool sleeping` / `bool Sleeping`。
- **用途**：允许物体在无运动进休眠，或读取/强制其睡眠状态。
- **误用**：用 `sleeping` 查询“是否静止”时，物体可能已被引擎休眠，查询未必反映最新接触；需要精确查询时应先 `force_...` 或依赖信号。设 `can_sleep=false` 可避免休眠导致的漏触发，但会增加 CPU 开销。
- **判据**：`can_sleep\s*=|is_able_to_sleep|CanSleep\s*=`；`sleeping\s*=|is_sleeping|Sleeping\s*=`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.mass
- **签名**：`float mass` / `float Mass`；默认 `1.0`。
- **用途**：参与力、冲量、重力与碰撞响应的惯性计算。
- **误用**：把 `mass=1` 当作“标准质量”，又在 `gravity_scale` 之外另行假设重力固定；重力实际为项目 3D/2D 设置乘 `gravity_scale`。不能从 `mass` 单独推断推得动不动，还要看接触与质量关系。
- **判据**：`mass\s*=`；`Mass\s*=`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.gravity_scale
- **签名**：`float gravity_scale` / `float GravityScale`；默认 `1.0`。
- **用途**：缩放本物体受到的项目重力；`0` 可取消重力，`2` 近似双倍重力。
- **误用**：用重力手感调平衡时只改 `gravity_scale` 却忘了所有场景共享项目重力；测试环境改项目默认值后可能破坏其他刚体。不要把负值当稳定悬浮，控制应另做。
- **判据**：`gravity_scale\s*=`；`GravityScale\s*=`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.contact_monitor
- **签名**：`bool contact_monitor` / `bool ContactMonitor`；默认 `false`。
- **用途**：开启后刚体才维护接触并触发 body/shape 接触信号。
- **误用**：只连接 `body_entered` 却没开启 `contact_monitor`，信号不会触发；还须保证 `max_contacts_reported` 足够大。性能敏感场景中不要对所有堆叠刚体无差别开启。
- **判据**：`contact_monitor\s*=`；`set_contact_monitor|ContactMonitor\s*=`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.max_contacts_reported
- **签名**：`int max_contacts_reported` / `int MaxContactsReported`；默认 `0`。
- **用途**：限制记录的接触数量，配合 `contact_monitor` 与接触查询使用。
- **误用**：保持默认 0 会“零接触”，即使 `contact_monitor=true` 也查不到完整结果；若环境同时接触地面、墙、多个刚体，缓冲区过小会丢失次要接触。官方提示只在确有需要时开启。
- **判据**：`max_contacts_reported\s*=`；`MaxContactsReported\s*=`。
- **置信度**：官方明确 [5]。

### RigidBody2D/3D.body_entered
- **签名**：`body_entered(Node node)` / `BodyEntered(Node body)`；对应 `body_exited`。
- **用途**：接触开始/结束时通知刚体；适合拾取、伤害触发、进入平台事件。
- **误用**：必须在开启 `contact_monitor` 且满足接触记录条件后才可靠；不要在初始化竞态里假定刚体生成时已有接触。该信号是刚体接触，不是 Area 的进入；检测区域触发应使用 `Area*.body_entered`。
- **判据**：`body_entered\.connect|on_body_entered|BodyEntered\s*\+=|body_exited\.connect`。
- **置信度**：官方明确 [5]。

## 3. StaticBody2D/3D 与 AnimatableBody2D/3D

### StaticBody2D/3D：静态或手动移动但不推动路径物体
- **签名**：`StaticBody2D` / `StaticBody3D`，无特殊运动 API；`constant_linear_velocity` / `constant_angular_velocity` 可表达传送带/转动表面的运动。
- **用途**：墙、地板、永久障碍物；也适合手动改变位置但不需要把速度传给其他物体的对象。
- **误用**：用代码逐帧移动 `StaticBody` 当电梯/平台，角色可能被“传送”的碰撞体推穿、卡住或不随平台运动。官方明确：手动移动时，它是传送到新位置，不会影响路径上的其他物体 [6]。
- **判据**：`extends StaticBody2D|extends StaticBody3D|class\s+\w+\s*:\s*StaticBody2D|class\s+\w+\s*:\s*StaticBody3D`；进一步结合 `position\s*=|global_transform\s*=|\.Position\s*=|\.GlobalTransform\s*=`。
- **置信度**：官方明确 [6]。

### AnimatableBody2D/3D：继承 StaticBody，可估算速度并推动其他物体
- **签名**：`AnimatableBody2D` / `AnimatableBody3D`，属性 `bool sync_to_physics = true`（GDScript）；`bool SyncToPhysics { get; set; }`（C#）。
- **用途**：移动平台、门、由动画/代码/RemoteTransform 驱动的碰撞体；移动时会估算线速度和角速度并影响路径上的刚体、角色。
- **误用**：把它当成“可被子弹撞飞”的物体，实际外部力和接触仍不能推动它。开启 `sync_to_physics` 后还用 `PhysicsBody*.move_and_collide()` 是官方明确不建议的组合 [7]。
- **判据**：`extends AnimatableBody2D|extends AnimatableBody3D|class\s+\w+\s*:\s*AnimatableBody2D|class\s+\w+\s*:\s*AnimatableBody3D`；`sync_to_physics\s*=|SyncToPhysics\s*=`。
- **置信度**：官方明确 [7]。

### 选型判断
- **永远不动**：首选 `StaticBody`；可读性最好，不应为了“未来可能动”提前用 Animatable。
- **固定时静态、偶尔动画**：若移动是短暂且参与物理推动，使用 `AnimatableBody`；永久静态对象仍用 `StaticBody`。
- **需要传送带效果但无真实运动体**：`StaticBody` 的 `constant_linear_velocity` / `constant_angular_velocity` 更贴切。
- **必须被子弹、爆炸和其他物体推动**：选择 `RigidBody`，不要因为“想让它平时不动”而滥用 freeze。
- **希望完全控制每步运动响应**：优先 `CharacterBody`（角色）或用 `move_and_collide()` 的自定义运动体，而不是用同步平台节点模拟角色。

## 4. Area2D/3D

### Area2D/3D.monitoring
- **签名**：`bool monitoring` / `bool Monitoring`；默认 `true`。
- **用途**：本 Area 是否主动检测进入/离开它的 body 与 area。
- **误用**：若本节点是“传感器”，却被误关 `monitoring`，`body_entered` 等不会触发。检测关系要求“观察者”的 mask 覆盖“被观察者”的 layer，不是单靠两者 layer 相同。
- **判据**：`monitoring\s*=|set_monitoring|Monitoring\s*=`。
- **置信度**：官方明确 [7][14]。

### Area2D/3D.monitorable
- **签名**：`bool monitorable` / `bool Monitorable`；默认 `true`。
- **用途**：本 Area 是否可被其他开启 monitoring 的 Area 检测到。
- **误用**：传感器自身的 `monitorable=false` 不会阻止它检测别人；两个 Area 相互发现通常需要观察方开启 monitoring、被观察方开启 monitorable。常见“Area 看不到 Area”就是因为被观察方关闭了 monitorable 或层/掩码不匹配 [14]。
- **判据**：`monitorable\s*=|set_monitorable|Monitorable\s*=`。
- **置信度**：官方明确 [14]。

### Area2D/3D.priority
- **签名**：`int priority` / `int Priority`；默认 `0`。
- **用途**：多个 Area 覆盖同一空间时影响重力、阻尼覆盖的处理顺序；数值高者先处理。
- **误用**：不要把它理解为检测信号的“层优先级”或遮挡顺序；它作用于 Area 覆盖/空间处理，不改变层掩码。没有覆盖行为时不要依赖它解决“为什么没检测到”。
- **判据**：`priority\s*=`；`Priority\s*=`。
- **置信度**：官方明确 [14]。

### Area2D/3D.body_entered / body_exited / area_entered
- **签名**：`body_entered(Node2D body)` / `BodyEntered(Node2D body)`；`body_exited(...)`；`area_entered(Area2D area)` / `AreaEntered(Area2D area)`；3D 对应 `Node3D` / `Area3D`。
- **用途**：进入/离开过渡时通知；适合触发区域、伤害区、交互范围。
- **误用**：对象生成时已经重叠不会补发“entered”，应在 `_ready()` 用 `get_overlapping_bodies()` 做初始扫描。连接 `area_entered` 却只开 `monitoring` 而对方 `monitorable=false`，不会触发。
- **判据**：`body_entered\.connect|body_exited\.connect|area_entered\.connect|BodyEntered\s*\+=|AreaEntered\s*\+=`。
- **置信度**：官方明确 [14]。

### Area2D/3D.get_overlapping_bodies()
- **签名**：`Node2D[] get_overlapping_bodies()` / `Node3D[] GetOverlappingBodies()`。
- **用途**：返回当前与本 Area 相交的 `PhysicsBody*`/网格地图集合，适合初始状态、按键轮询。
- **误用**：官方明确该列表在物理步期间统一修改，不是移动对象后立即更新；同一物理帧刚 teleport 完就读取可能得到旧结果。高频轮询也可能比信号更贵。
- **判据**：`get_overlapping_bodies\s*\(`；`GetOverlappingBodies\s*\(`。
- **置信度**：官方明确 [14]。

### Area2D/3D.overlaps_body()
- **签名**：`bool overlaps_body(Node body)` / `bool OverlapsBody(Node body)`。
- **用途**：检查指定 body 当前是否与本 Area 重叠。
- **误用**：参数应是实际 body 节点；不要传 layer 整数、碰撞 shape、RID 或 Area。结果同样受物理步更新延迟影响，不能假定移动后立即准确。
- **判据**：`overlaps_body\s*\(`；`OverlapsBody\s*\(`。
- **置信度**：官方明确 [14]。

## 5. 碰撞层与位掩码

### collision_layer / collision_mask
- **签名**：`int collision_layer` / `int CollisionLayer`；`int collision_mask` / `int CollisionMask`。`layer` 表示“我属于哪些层”，`mask` 表示“我扫描哪些层”；两者不要求对称。
- **用途**：构建墙、玩家、敌人、拾取物之间的单向或双向交互关系。
- **误用**：把第 3 层写成 `3` 实际是层 1 和层 2；第 4 层的值是 `8`。菜单/代码里第 N 个勾选框对应位 `1 << (N-1)`，即第 1/2/3/4 层分别为 `1/2/4/8` [8]。
- **判据**：`collision_layer\s*=|collision_mask\s*=|set_collision_layer_value|set_collision_mask_value|CollisionLayer\s*=|CollisionMask\s*=`；数值字面量 `3`、`5`、`6`、`7`、`9-15` 出现在层/掩码上下文时应复核，避免误把层号当位值。
- **置信度**：官方明确 [8]。

### 常见错误写法对照

| 想表达的语义 | 正确位掩码 | 常见错误 | 错误结果 |
|---|---:|---:|---|
| 只在第 1 层 | `1` | `0` 或关闭全部 | 不参与默认碰撞 |
| 只在第 2 层 | `2` | `2` 写成“第二个勾”却将其他值相加不当 | 逻辑看似正确但可读性差 |
| 只在第 3 层 | `4` | `3` | 实际同时落在层 1、层 2 |
| 只在第 4 层 | `8` | `4` | 实际落在层 3 |
| 层 1、3、4 | `13` | `1+3+4` 或 `0b0111` | 将层 2 错误纳入 |
| 检测层 1、2、3 | `7` | `1+2+3` | 实际等于 6，漏掉层 1 |

- **更安全的替代写法**：直接设置编辑器层名称，或用 `set_collision_layer_value(layer_number, true)`；`layer_number` 是从 1 开始的人类序号，不要传 `1<<n`。[8]
- **判据**：`set_collision_layer_value\s*\(|set_collision_mask_value\s*\(`；数值字面量紧跟的参数为 layer 序号，出现 `0` 或大于 32 的值应告警。
- **置信度**：官方明确 [8]。

## 6. RayCast2D/3D

### RayCast2D/3D.target_position
- **签名**：`Vector2 target_position` / `Vector3 TargetPosition`；相对于节点自身的 `position`/`global_transform.origin`。
- **用途**：定义射线终点，因此同时决定方向与长度；不是单位方向向量。
- **误用**：把 `Vector2.RIGHT` 当成“长度 1 像素”通常有效，但会生成极短射线；在 3D 中误传局部 forward 又忘记它相对节点位置时，方向会随父节点变化。长度为 0 时射线没有有效探测段。
- **判据**：`target_position\s*=`；`TargetPosition\s*=`。
- **置信度**：官方明确 [15]。

### RayCast2D/3D.enabled
- **签名**：`bool enabled` / `bool Enabled`；默认 `true`。
- **用途**：开启/关闭射线检测；关闭后仍可调用 `force_raycast_update()` 获得一次结果。
- **误用**：以为 `enabled=false` 后 `force_raycast_update()` 也无效；官方明确 `enabled` 不必为 true 该方法也能工作 [15]。反过来说，若只依赖自动更新而 `enabled=false`，下一物理帧不会自动刷新。
- **判据**：`enabled\s*=|set_enabled|Enabled\s*=`。
- **置信度**：官方明确 [15]。

### RayCast2D/3D.is_colliding()
- **签名**：`bool is_colliding()` / `bool IsColliding()`。
- **用途**：在最新一次更新后判断射线是否命中；是安全读取碰撞信息的闸门。
- **误用**：读取后没有闸门保护就调用 `get_collider()`/`get_collision_point()`，虽然节点 API 会返回 null/默认值，业务层可能仍把 `null` 当实体。它只代表节点最新缓存状态，不代表强制更新后的当帧状态。
- **判据**：`is_colliding\s*\(`；`IsColliding\s*\(`。
- **置信度**：官方明确 [15]。

### RayCast2D/3D.get_collider()
- **签名**：`Object get_collider()` / `Object GetCollider()`；未命中返回 `null`。
- **用途**：取得首个相交的碰撞对象；典型转换目标为 `CollisionObject2D/3D`。
- **误用**：未检查 null；或把返回值直接当 `PhysicsBody`/`Area`，忽略 Area 默认不被 `collide_with_areas` 报告的情况。C# 中还需显式转换，转换失败会异常。
- **判据**：`get_collider\s*\(`；`GetCollider\s*\(`。
- **置信度**：官方明确 [15]。

### RayCast2D/3D.get_collision_point()
- **签名**：`Vector2 get_collision_point()` / `Vector3 GetCollisionPoint()`。
- **用途**：返回世界空间中的碰撞点。
- **误用**：认为是相对节点的局部坐标，或以为它是射线起点。如果角色转身后要把碰撞点转回本地空间，应显式乘 `global_transform.affine_inverse()`，不要直接加减节点位置。
- **判据**：`get_collision_point\s*\(`；`GetCollisionPoint\s*\(`。
- **置信度**：官方明确 [15]。

### RayCast2D/3D.force_raycast_update()
- **签名**：`void force_raycast_update()` / `void ForceRaycastUpdate()`。
- **用途**：立即更新一次射线状态，不等待下一 `_physics_process()`；适合同一帧移动节点后重新查询。
- **误用**：在同一帧改变节点、目标点、层或例外后不调用，读取的是上一物理帧缓存；尤其是在角色转身、伸缩射线、瞬移平台后。开启 `enabled` 本身不会触发立即同步。
- **判据**：`force_raycast_update\s*\(`；`ForceRaycastUpdate\s*\(`；其后紧跟读取 `is_colliding/get_collider/get_collision_point` 属于推荐模式。
- **置信度**：官方明确 [15]。

## 7. PhysicsDirectSpaceState2D/3D 与查询参数对象

### PhysicsDirectSpaceState2D/3D.intersect_ray()
- **签名**：`Dictionary intersect_ray(PhysicsRayQueryParameters2D parameters)` / `Dictionary IntersectRay(PhysicsRayQueryParameters2D query)`；3D 对应 `PhysicsRayQueryParameters3D`。
- **用途**：执行一次直接空间射线查询；返回命中字典或空字典。
- **误用**：仍传 `(from, to, exclude, collision_mask, ...)` 等 3.x 多位置参数；4.x 只接收一个参数对象。结果未命中时是空字典，不能用 `if result.collider`；应使用 `if result:`/`if (result.Count > 0)`。
- **判据**：`intersect_ray\s*\([^)]*(,|PhysicsRayQueryParameters)`；`IntersectRay\s*\(`。4.x 建议形式：`PhysicsRayQueryParameters[23]D\.create\s*\(`。
- **置信度**：官方明确 [10][11]。

### PhysicsDirectSpaceState2D/3D.intersect_point()
- **签名**：`Array[Dictionary] intersect_point(PhysicsPointQueryParameters2D parameters, int max_results=32)` / 3D 同形；C# 为 `Godot.Collections.Array<Godot.Collections.Dictionary>`。
- **用途**：检测某点落在哪些实体 shape 内；适合点击、出生点、重叠点查询。
- **误用**：3.x 的位置参数风格迁移到 4.x 的对象风格失败；默认只返回最多 32 项，拥挤场景可能截断，需要显式增大 `max_results`。只设置查询点的 `position`，忘了 `collision_mask`/`collide_with_areas` 会漏结果。
- **判据**：`intersect_point\s*\(`；`IntersectPoint\s*\(`。
- **置信度**：官方明确 [10]。

### PhysicsDirectSpaceState2D/3D.intersect_shape()
- **签名**：`Array[Dictionary] intersect_shape(PhysicsShapeQueryParameters2D parameters, int max_results=32)` / 3D 同形。
- **用途**：用指定 shape、transform、motion 和 margin 查询相交；适合胶囊/球扫描、范围检查。
- **误用**：没有把 `Resource shape` 或 `shape_rid` 绑定到真实 shape，查询无结果；只在参数对象中设置 transform 而不确认 shape 生命周期。4.x 文档明确建议用 `shape` 引用而非裸 `shape_rid`，以免查询期间 shape 被释放 [11]。
- **判据**：`intersect_shape\s*\(`；`IntersectShape\s*\(`；同时检查 `PhysicsShapeQueryParameters[23]D` 的 `.shape\s*=|Shape\s*=|\.ShapeRid\s*=`。
- **置信度**：官方明确 [10][11]。

### PhysicsDirectSpaceState2D/3D.cast_motion()
- **签名**：`PackedFloat32Array cast_motion(PhysicsShapeQueryParameters2D parameters)` / `float[] CastMotion(PhysicsShapeQueryParameters2D parameters)`；3D 相同。
- **用途**：返回运动的安全比例与不安全比例（0–1），用于实现形状扫掠/避免穿透。
- **误用**：把返回值当成命中距离米数；实际是运动总量的比例，未命中返回 `[1.0,1.0]`。当前 shape 已经重叠的对象会被忽略，不能把它当“现在卡在谁里面”的检测；需用 `collide_shape()`。
- **判据**：`cast_motion\s*\(`；`CastMotion\s*\(`。
- **置信度**：官方明确 [10]。

### PhysicsDirectSpaceState2D/3D.get_rest_info()
- **签名**：`Dictionary get_rest_info(PhysicsShapeQueryParameters2D parameters)` / 3D 同形。
- **用途**：在多个相交结果中选最近一个，返回碰撞体、RID、shape、法线、接触点等字典；适合形状穿透后的“退出方向”。
- **误用**：未命中返回空字典，必须先判空。结果字典中的字段与 `intersect_ray()` 不完全相同，不能把两者字典混用。该调用返回最近接触，而不是所有接触；需要完整重叠集合应用 `intersect_shape()`。
- **判据**：`get_rest_info\s*\(`；`GetRestInfo\s*\(`。
- **置信度**：官方明确 [10]。

### PhysicsRayQueryParameters2D/3D：4.x 的参数对象
- **签名**：`static PhysicsRayQueryParameters2D create(Vector2 from, Vector2 to, int collision_mask=4294967295, RID[] exclude=[])` / 3D 为 `Vector3` 版本；也可 `new()` 后设置 `From/To/CollisionMask/Exclude/CollideWithAreas/CollideWithBodies`。
- **用途**：封装一次射线查询的参数；是 4.x 的核心迁移对象。
- **误用**：沿用 3.x `Dictionary` 多参数或手写 `{"from":..., "to":...}`，4.x 的 `intersect_ray()` 不接受这种形式。坐标须为世界坐标；复制旧查询对象并只改 `to` 可能遗漏 exclude、mask。
- **判据**：`PhysicsRayQueryParameters[23]D\.create\s*\(|PhysicsRayQueryParameters[23]D\s*\(`；C#：`PhysicsRayQueryParameters[23]D\.Create\s*\(|new PhysicsRayQueryParameters[23]D\s*\(`。
- **置信度**：官方明确 [10][11]。

### PhysicsShapeQueryParameters2D/3D
- **签名**：`new()` 或场景节点资源；关键属性包括 `shape`/`shape_rid`、`transform`、`motion`、`margin`、`collision_mask`、`exclude`、`collide_with_areas`、`collide_with_bodies`。
- **用途**：为 shape/point/motion 查询提供参数；适合无法用单一 RayCast 节点覆盖的批量或动态形状查询。
- **误用**：误以为像 3.x 那样传位置参数字典；4.x 是 `RefCounted` 对象。只用 `shape_rid` 而释放过早，可能得到失效 RID；官方推荐保留 shape 引用 [11]。
- **判据**：`PhysicsShapeQueryParameters[23]D\s*\(|\.Shape\s*=|ShapeRid\s*=|Transform\s*=|Motion\s*=`。
- **置信度**：官方明确 [10][11]。

### PhysicsPointQueryParameters2D/3D
- **签名**：`new()`；至少设置 `position`，并配置 `collision_mask`、`exclude`、`collide_with_areas`、`collide_with_bodies`。
- **用途**：为 `intersect_point()` 描述待查询点及过滤条件。
- **误用**：4.x 中不能只传 `(point, canvas_instance_id, ...)` 等 3.x 位置参数；新 API 中该类已不再是 `Dictionary`。只设置 point 而 layer 不匹配会返回空。
- **判据**：`PhysicsPointQueryParameters[23]D\s*\(|\.Position\s*=|position\s*=` 紧邻 point query 参数对象构造。
- **置信度**：官方明确 [10]；3.x 参数迁移细节以具体小版本类参考复核为佳。

### World.direct_space_state 的获取与生命周期
- **签名**：`get_world_2d().direct_space_state` / `get_world_3d().direct_space_state`；C# 为 `GetWorld2D().DirectSpaceState`。
- **用途**：取得当前世界的直接空间状态，用于上述查询。
- **误用**：在 `_physics_process()` 之外访问可能在空间锁定时报错；教程示例建议在物理回调内查询 [10]。缓存跨物理帧的 state 引用不应假定跨线程安全或跨世界有效。
- **判据**：`direct_space_state|DirectSpaceState|space_get_direct_state|SpaceGetDirectState`。
- **置信度**：官方明确 [10]。

## 8. _physics_process 与 _process

### _physics_process(delta) 的执行契约
- **签名**：`func _physics_process(delta: float) -> void` / `public override void _PhysicsProcess(double delta)`。
- **用途**：固定步长物理回调；物理模拟、`move_and_slide()`、力/冲量、刚体读取、射线/空间查询应集中于此。
- **误用**：将角色移动放进 `_process(delta)` 会让行为受帧率影响；反过来将昂贵动画/IO 放入 `_physics_process()` 会按 tick 增加 CPU 成本。把 `_process()` 的 `delta` 当 1/60 的固定值是错误假设。
- **判据**：`func _physics_process|_PhysicsProcess\s*\(`；并查找其在同一文件中与 `move_and_slide|apply_force|apply_impulse|intersect_ray|force_raycast_update` 的组合。
- **置信度**：官方明确 [12][13]。

### Engine.physics_ticks_per_second
- **签名**：`int Engine.physics_ticks_per_second` / `int Engine.PhysicsTicksPerSecond`；默认 `60`。
- **用途**：设置每秒固定物理迭代次数，同时控制 `_physics_process()` 频率。
- **误用**：默认 60 并非“永远是 60”；引擎可能因追帧在一个渲染帧执行多次物理回调，逻辑不能假定每渲染帧恰一次。提高 tick 会增加 CPU 占用并需同步考虑 `max_physics_steps_per_frame`；官方也提示 Godot 不做物理插值，过低的值会显卡 [13]。
- **判据**：`physics_ticks_per_second\s*=|ProjectSettings\.get_setting\("physics/common/physics_ticks_per_second"\)|PhysicsTicksPerSecond\s*=`。
- **置信度**：官方明确 [13]。

### delta 的使用边界
- **签名**：`float delta` / `double delta`，单位为秒。
- **用途**：把速度、力、阻尼等积分到当前固定时间步。
- **误用**：`delta` 不是恒定魔法值；不要把 `delta == 1.0/60` 当断言，也不要在 `move_and_slide()` 之前再给 `velocity` 乘一次 delta。对 `_physics_process()` 内持续力使用 delta 积分通常是正确模型，而 `_process()` 中的渲染插值数值不应直接用于物理状态。
- **判据**：`velocity\s*\*=\s*delta|velocity\s*\*=\s*\(float\)delta|move_and_slide\(velocity\s*\*\s*delta`；后两项应优先告警。
- **置信度**：官方明确 [2][12][13]。

## 反直觉坑

- **本能以为 `move_and_slide(velocity, up)` 在 4.x 还能用，但实际已无参化。** 4.x 从 `velocity` 属性读取并在滑动后回写，`move_and_slide()` 不接受速度或上方向参数 [1][2]。
- **本能以为 `velocity *= delta` 是正确防帧率写法，但在 4.x `move_and_slide()` 之前通常是错误的。** 引擎会在物理步内部使用 `velocity` 做时间积分；教程示例只把重力按 delta 累加到 `velocity.y`，随后直接调用 `move_and_slide()` [1][2]。
- **本能以为静态体“不移动”，实际 `StaticBody` 可以手动移动，只是移动方式是传送。** 因此它不适合需要推动角色/刚体的移动平台；这种需求应选 `AnimatableBody` [6][7]。
- **本能以为 `AnimatableBody` 是某种可被子弹击飞的物理体，实际它仍是 StaticBody 的子类。** 外力与接触不会把它推开，它只负责把动画/代码运动估算成速度去影响其他物体 [7]。
- **本能以为碰撞层第 3 层的值是 `3`，但实际是 `4`。** 第 1/2/3/4 层的位值依次为 1/2/4/8；位掩码是 `1 << (层号-1)` [8]。
- **本能以为 Area 的信号只需要一个对象开启监测，实际观察者和被观察者双方各需正确配置。** 观察者要 `monitoring=true` 且 mask 覆盖对方 layer；被观察 Area 要 `monitorable=true` [14]。
- **本能以为 `enabled=false` 时 `force_raycast_update()` 无效，官方明确它仍可执行。** 真正的坑在反面：改完节点/目标/掩码后若不调用，下一行读取的仍是旧缓存 [15]。
- **本能以为 3.x 的 `intersect_ray(from,to,...)` 可原样迁移，实际 4.x 只接收参数对象。** `PhysicsRayQueryParameters*D.create(from,to)` 后传入 state；结果仍是字典，未命中是空字典 [10][11]。
- **本能以为 Area/RigidBody 的接触列表会随 `position=` 立即刷新，实际官方说明这些列表通常在物理步期间统一更新。** 同帧轮询得到旧结果时，应优先使用信号或等待下一物理步 [5][14]。
- **本能以为把 `freeze=true` 的 RigidBody 当静态平台最省事，实际永久静态物应选 StaticBody/AnimatableBody。** `freeze=true` 后仍需处理模式、速度残留和动态恢复；对象语义也不符合“由物理模拟的刚体” [5][6][7]。

## 审查建议优先级

P0 应自动阻断：4.x 中 `move_and_slide(...)` 传参；`move_and_slide()` 出现在 `_process()`；局部变量遮蔽 `velocity`；`PhysicsDirectSpaceState.intersect_ray(...)` 的位置参数；`floor_max_angle` 被设置成角度制大值；层掩码出现 `3/5/6/7` 等可疑层号/位值混用。

P1 应告警并要求复核：每物理帧 `apply_impulse()`/`apply_torque_impulse()`；刚体 `body_entered` 但 `contact_monitor=false` 或 `max_contacts_reported=0`；移动 `StaticBody` 作为平台；同帧移动后读取 Area 重叠/刚体接触；改变 RayCast 后未调用 `force_raycast_update()`。

P2 建议人工检查：修改 `safe_margin`/`gravity_scale`/`freeze_mode`；依赖 `is_on_floor()` 做边沿检测；直接覆盖刚体速度；`intersect_shape()` 只靠默认 32 项；缓存 `direct_space_state` 跨帧使用。

## 引用来源

[1] https://docs.godotengine.org/en/4.2/tutorials/physics/using_character_body_2d.html
> “move_and_slide() will modify this value automatically when colliding.”

[2] https://docs.godotengine.org/zh-cn/4.x/tutorials/physics/kinematic_character_2d.html
> “move_and_slide already takes delta time into account.”

[3] https://docs.godotengine.org/zh_CN/latest/classes/class_characterbody3d.html
> “void move_and_slide()”

[4] https://docs.godotengine.org/zh_CN/4.x/classes/class_rigidbody2d.html
> “void apply_central_impulse(impulse: Vector2 = Vector2(0, 0))”

[5] https://docs.godotengine.org/en/4.2/classes/class_rigidbody3d.html
> “If true, the RigidBody3D will emit signals when it collides with another body.”

[6] https://devdocs.io/godot~4.7/classes/class_staticbody3d
> “When StaticBody3D is moved, it is teleported to its new position without affecting other physics bodies in its path.”

[7] https://docs.godotengine.org/en/4.0/classes/class_animatablebody2d.html
> “When the body is moved manually… the physics will automatically compute an estimate of their linear and angular velocity.”

[8] https://docs.godotengine.org/zh-tw/4.4/tutorials/physics/physics_introduction.html
> “如果某物件不在遮罩指定的層內，就會被忽略。”

[9] https://docs.godotengine.org/en/4.0/classes/class_characterbody3d.html
> “Vector3 get_slide_collision(slide_idx: int) int get_slide_collision_count() const”

[10] https://docs.godotengine.org/ko/latest/classes/class_physicsdirectspacestate3d.html
> “This class is not meant to be instantiated directly. Use World3D.direct_space_state…”

[11] https://docs.godotengine.org/en/4.2/classes/class_physicsrayqueryparameters3d.html
> “Provides parameters for PhysicsDirectSpaceState3D.intersect_ray.”

[12] https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html
> “The physics engine runs at a fixed rate (a default of 60 iterations per second).”

[13] https://docs.godotengine.org/zh_CN/4.x/classes/class_engine.html
> “int physics_ticks_per_second = 60 每秒执行的固定迭代次数。”

[14] https://docs.godotengine.org/en/4.0/classes/class_area2d.html
> “Requires monitoring to be set to true.”

[15] https://docs.godotengine.org/en/4.2/classes/class_raycast2d.html
> “Updates the collision information for the ray immediately, without waiting for the next _physics_process call.”
