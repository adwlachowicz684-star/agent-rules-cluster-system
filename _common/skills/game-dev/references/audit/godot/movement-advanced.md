<!-- oversize-exempt: 反模式清单，审核用 -->
# movement-advanced — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/movement-advanced.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 特殊移动堆 if 就行 | 要**状态机** |
| 2 | 缓冲只给跳跃 | 要**覆盖所有状态** |
| 3 | 抓边一条射线够 | 要**两条**（上方+前方） |
| 4 | 抓到直接赋坐标 | 会**穿薄墙**，用 move_and_collide |
| 5 | 蹬墙跳随便给力 | **垂直分量要够** |
| 6 | 抓边阈值随便定 | 要按**胶囊高度实测** |
| 7 | 摆荡用纯物理 | 很难玩，要**给助力** |
| 8 | 水下只改重力 | 还有**阻尼、视野、音频** |
| 9 | 出水入水只切移动 | 相机/音频/模式**一起切** |
| 10 | 改 up_direction 必失效 | **不成立**，真正原因是那 5 个 |
| 11 | up_direction 能设 ZERO | **不能** |
| 12 | Floating 模式有地板 | **所有碰撞都算墙** |
| 13 | is_on_floor 是持久状态 | 只反映**本帧** |
| 14 | 改重力只改向量 | up/相机/移动平面**全要变** |
| 15 | 传感器各状态里投射 | 要**集中更新** |
| 16 | 移动平台用 StaticBody3D，角色站着能跟着走 | 官方：只有 **AnimatableBody3D** 被移动时会**估算线速度与角速度**并影响路径上的物体；StaticBody3D 不做估算，站在上面的角色**原地不动、平台从脚下抽走** |
| 17 | 用 `move_and_collide()` 驱动 AnimatableBody3D 平台 | 官方 Warning：**不要**与 `PhysicsBody3D.move_and_collide()` 同时使用（与 `sync_to_physics` 冲突） |
| 18 | 平台靠 AnimationPlayer 动就够 | 官方：`sync_to_physics` 为 true 时移动**与物理帧同步**，这正是 AnimationPlayer 驱动移动平台要靠的那一条；且 AnimationMixer 的 `callback_mode_process` 要设为 **PHYSICS** |
| 19 | 配了 `platform_floor_layers` 就所有平台都能承载 | 官方：**`platform_wall_layers` 默认 0，所有墙体一律忽略**。贴在角色侧面的垂直移动平台**不会被跟随** —— ⛔ 与 `platform_floor_layers` 默认 4294967295（全开）**恰好相反** |
| 20 | 离开下行平台还想要完整跳跃高度 | 官方：`PLATFORM_ON_LEAVE_ADD_UPWARD_VELOCITY` 才是"忽略向下运动"，**平台向下移动时仍能保持完整跳跃高度**；默认的 `ADD_VELOCITY` 会把下行速度一起带走，跳跃变矮 |
| 21 | 在 `move_and_slide()` 之前读 `get_platform_velocity()` | 官方：仅**在调用 move_and_slide() 之后**有效（角速度同理）。⛔ 读早了拿到上一帧的旧值，**不报错**，表现为"承载时快时慢" |
| 22 | `get_platform_velocity()` 手动加到 velocity 上更可控 | 官方：`move_and_slide()` **自己**读取平台速度并计入本步运动；⛔ 手动再加一次会**双倍**，表现为"平台一启动人就飞出去" |
| 23 | 拿 `get_floor_normal()` 当表面法线 | 官方 Warning：碰撞法线**并不总是**与表面法线相同。用它对齐攀爬姿态会在部分几何上偏 |
| 24 | 拿 `velocity` 当实际位移速度做手感/特效 | 官方：爬坡时即使 velocity 是水平的，实际也会斜向移动 —— **实际值要读 `get_real_velocity()`**，`velocity` 只是"请求速度" |
| 25 | 开了 `floor_constant_speed` 就匀速了 | 官方原话：为 true 时仍需 **`floor_snap_length` 才能在下坡上保持恒速贴合**。⛔ 只开前者，下坡会脱离地面再"抖"回去 |
| 26 | `floor_snap_length` 设 0 省事 | 官方：设为**非 0** 才保持附着斜坡；0 = **完全禁用吸附**，下坡会一路弹跳（`is_on_floor()` 时真时假） |
| 27 | 吸附一直生效 | 官方：**沿 up_direction 移动（含上升速度）时不应用吸附** —— 这正是跳跃能脱离地面的原因。想无视速度强制吸附要用 `apply_floor_snap()` |
| 28 | `is_on_floor()` 为 true 时再调 `apply_floor_snap()` 补一下 | 官方：该函数**在 is_on_floor 返回 true 时什么都不做** |
| 29 | 走不上斜坡就一味调大 `floor_max_angle` | 官方默认 **45°**（0.785398 弧度），超过即判为墙。⛔ 但真正的锅常在 `safe_margin`（默认 0.001），且官方注明：GROUNDED 模式下 **safe_margin 只在 `floor_block_on_wall` 为 true 时才影响移动** |
| 30 | CharacterBody3D 可以随便缩放 | 官方 Warning：**非均匀缩放**下该节点可能不按预期工作。必须保持缩放均匀，改**碰撞形状**的尺寸 |
| 31 | `max_slides` 调大更稳 | 官方默认 **6**，它决定一次 `move_and_slide()` 内允许改变方向的次数；调大只是让更多次滑动被计算，性能代价随值上升，且掩盖的是几何问题 |
| 32 | 二段跳次数靠"落地事件"重置 | 官方：`is_on_floor()` 只反映**本帧**最近一次 `move_and_slide()` 的结果。⛔ 用事件/信号重置会在斜坡、吸附失效、平台边缘等处**漏重置或多重置**，直接用**每帧读取**的状态判断 |
