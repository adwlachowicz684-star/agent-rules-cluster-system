# XR 深入：手部追踪与物理交互（Godot 4.7.2）

`xr.md` 讲基础场景搭建，本文讲**手部追踪与抓取**——XR 交互里最容易做错的部分。

## 0. OpenXR 不是设备 SDK

```
XROrigin3D      现实追踪空间的原点 ← 角色虚拟移动时移这个
├── XRCamera3D      头显
├── XRController3D  左手
└── XRController3D  右手
```

⚠ **角色移动时移 `XROrigin3D`，不是改相机变换。**

⚠ **`XRCamera3D` 的位置会滞后** ——
启用 `use_xr` 后大多数相机属性被活动接口覆盖，**只有近/远裁剪面可靠**；
渲染线程能拿到更新的追踪数据，节点变换可能比实际渲染位姿落后几毫秒。
所以它适合做渲染入口，**不适合做权威物理抓手**。

⚠ **OpenXR 是协议，SteamVR / Meta Quest / WMR 是运行时**。
Godot 不认品牌——运行时可能拥有、拒绝或**模拟**某项功能。

⚠ **XR 必须用 Mobile 或 Forward+** —— Compatibility 是否有完整支持需实测。

**XRTools 这类社区方案**：用前必做三件事——
① 空项目导入跑 demo ② **锁定提交哈希** ③ 保留回滚。
⚠ **不要一边用插件的抓取节点，一边自己 reparent `RigidBody3D`** ——
两套所有权会互相覆盖。建议只借鉴其动作映射/手型/传送指示器，
**核心抓取保留在自己的物理层**。

## 1. 手部追踪 vs 控制器

| | 控制器 | 手部追踪 |
|---|---|---|
| 数据来源 | 实体按钮 + 位姿 | 摄像头/传感器，输出手掌 + **26 个关节** |
| 稳定性 | 高、延迟低 | 有遮挡、光照、丢失状态 |
| 适合 | 精确抓取、射击、连续移动 | 自然捏合、指向、菜单 |

⚠ **SteamVR（含 Steam Link）通常只有"基于控制器的手部追踪"** ——
不是光学追踪。其他运行时若支持才是真光学追踪，否则**根本没有手部追踪**。

⚠ **两者应共享游戏语义**，不要做两套交互逻辑。

### 关节 API

```gdscript
var oxr := XRServer.find_interface("OpenXR") as OpenXRInterface
oxr.get_hand_joint_position(hand, joint)
oxr.get_hand_joint_rotation(hand, joint)
oxr.get_hand_joint_linear_velocity(hand, joint)
oxr.get_hand_joint_angular_velocity(hand, joint)
oxr.get_hand_joint_radius(hand, joint)
oxr.get_hand_joint_flags(hand, joint)
```

⚠ **关节 API 已提供逐关节速度**，不用自己差分。
但**控制器/手锚本身仍要自己缓存世界变换差分** ——
关节速度与抓取点速度不一定相同。

### pinch 判定的降级方案

没有运行时手势输入时，用拇指尖与食指尖的世界距离：

| 阈值 | 含义 |
|---|---|
| 约 2.0–3.0 cm | pinch ready |
| 约 1.2 cm 且持续 2–3 帧 | 触发 pinch |
| 更高阈值释放 | **迟滞** |

⚠ **手指长度因人而异** ——
最好把绝对距离**除以中指掌骨—中指尖的跨度**归一化，或做运行时校准。

⚠ **用速度防抖**：指尖相对速度过大时抑制点击，
否则快速挥手会被识别成捏合。

## 2. 抓取：管理所有权、约束和动量

⚠ **抓取不是把物体设为子节点** —— 对动态刚体 reparent 会破坏物理。

| 方案 | 适用 | 手感 |
|---|---|---|
| 直接 reparent | ❌ 动态刚体 | 破坏物理 |
| `Generic6DOFJoint3D` / `PinJoint3D` | 精确、有真实约束感 | 重，可能抖 |
| **速度追踪** | 通用 | 轻快，穿模风险 |

⚠ **释放时没速度 = 扔出去像掉下来** ——
`XRController3D` **没有速度 API**，必须自己缓存世界变换差分，
释放前**显式写入线速度与角速度**。

```gdscript
# 释放时把速度写回去
func _release(body: RigidBody3D) -> void:
    var dt := get_physics_process_delta_time()
    if dt > 0.0:
        body.linear_velocity = (hand.global_position - _prev_hand_pos) / dt
        body.angular_velocity = _estimate_angular(_prev_hand_basis, hand.global_basis, dt)
```

⚠ **做抓取时要写 `RigidBody3D` 的速度，不要拿相机拖动物体。**

## 3. 移动与舒适度

⚠ **晕动症的成因是前庭冲突** —— 不是"有些人容易晕"。

| 方案 | 说明 |
|---|---|
| **传送** | 持续平移应优先选它 |
| **snap turn** | 保留，比平滑旋转舒适得多 |
| 平滑移动 | 最易致晕，要给隧道视野 |
| 臂摆 / 房间规模 | 最舒适但受空间限制 |

**隧道视野（tunneling vignette）**在移动时收缩视野，能显著缓解。

⚠ 舒适度设置要暴露给玩家：移动方式、转向方式、隧道视野强度。

## 4. 空间 UI

⚠ 要同时解决**深度、命中、可读性**三件事：
- UI 要能被指针射线点中（射线与 UI 的碰撞层）
- 世界空间 UI 的分辨率决定可读性——**太远会糊**
- 文本输入要虚拟键盘

## 5. 性能

| 刷新率 | 帧预算 |
|---|---|
| 72 Hz | 13.89 ms |
| 90 Hz | 11.11 ms |
| 120 Hz | 8.33 ms |

⚠ **XR 掉帧的代价远大于普通游戏** —— 会直接导致晕动症。

⚠ **降负载顺序**：动态分辨率 → LOD/遮挡/远处阴影 → 才减对象与材质。
降内部分辨率立刻恢复 → fillrate 为主；GPU 时间几乎不变 → 查命令提交。

⚠ 官方建议 OpenXR **关闭常规 V-Sync**，让头显负责呈现；
支持平台可启用 `VrsModeEnum.XR` 或 foveation。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/xr-deep.md`


## 6. 待核对项（运行时验证）

⚠ 待核对：`ArcCast3D` 节点在 4.7.2 是否存在 · 验证：编辑器节点搜索框输入 ArcCast3D

⚠ 待核对：项目设置里是否有名为 single pass multiview 的开关 · 验证：项目设置搜索 multiview，并查目标硬件导出模板

⚠ 待核对：手关节枚举在 4.7.2 的实际字面量 · 验证：编辑器中运行 get_hand_joint_position 打印枚举值

⚠ 待核对：XR 虚拟键盘的可用方案 · 验证：在目标头显上测试现有方案是否有焦点与输入

⚠ 待核对：Compatibility 渲染器能否运行 XR · 验证：切到 Compatibility 在目标设备导出测试

## 7. 相关文档

- XR 基础场景 → `xr.md`
- 性能与热节流 → `perf-profiling.md`
- 物理 → `physics.md`
- 3D → `3d.md`
- 渲染器能力 → `render-pipeline.md`
- 输入 → `input-audio.md`
