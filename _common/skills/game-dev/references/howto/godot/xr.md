# Godot 4.x XR（VR/AR）

VR 有两条普通 3D 没有的硬约束：**不能接管相机**，**帧率必须稳**。
这两条违反任意一条，玩家会直接晕。

## 0. 生态与版本链

| 组件 | 说明 |
|---|---|
| `XRServer` / `XROrigin3D` / `XRCamera3D` / `XRController3D` | **引擎内核内置**（4.0 起） |
| OpenXR | 首选 `XRInterface` 实现 |
| **godot-xr-tools**（MIT） | 社区标配：抓取点、传送、暗角、触觉、UI 指针 |
| OpenXR Vendors 插件 | 厂商扩展（Meta 透视、手部追踪、Pico/HTC） |

⚠ **版本链必须对齐**：xr-tools 4.5.x 要求 4.4+，Vendors 4.x 要求 4.4+、5.x 要求 4.6+。
以各自仓库为准（见 `plugins.md` 的锁 commit 原则）。

## 1. 最小场景结构

```
XROrigin3D                    ← 移动的是这个，不是相机
├── XRCamera3D                ← 每帧被头显覆盖
├── XRController3D (Left)
├── XRController3D (Right)
└── (玩家碰撞体)
```

⚠ **`XRCamera3D` 每帧位置由头显覆盖**。
想移动玩家 → 移动 `XROrigin3D`。直接改相机 = 眩晕 + 位置被覆盖。

⚠ `XROrigin3D.world_scale` 是**全局统一缩放**（实际是 `XRServer.world_scale`，由 origin 管理）。
改它会影响所有 XR 节点，不是"只缩放某个物体"。

⚠ **重新校准走 `XRServer.center_on_hmd(mode, keep_height)`，两个参数都要显式给。**
官方 `RotationMode` 三档：

| 常量 | 含义 |
|---|---|
| `RESET_FULL_ROTATION = 0` | 完全重置朝向（⛔ **默认值**） |
| `RESET_BUT_KEEP_TILT = 1` | 重置朝向但保留倾斜 |
| `DONT_RESET_ROTATION = 2` | 只居中位置，不动朝向 |

⛔ 不写第二/第三参数就是 `RESET_FULL_ROTATION`，会在玩家刚转身之后把朝向掰回正前方。
⚠ 不支持空间追踪的平台上原点就是头显位置，⛔ 玩家朝向基本不可控。

## 2. 控制器输入

```gdscript
@onready var ctrl: XRController3D = $XROrigin3D/RightHand

func _process(_d: float) -> void:
    var trigger := ctrl.get_float("trigger")         # 0..1
    var stick := ctrl.get_vector2("thumbstick")      # 摇杆
    if ctrl.is_button_pressed("grip_click"):
        pass
```

### ⚠ `has_tracking_data` 为真不等于真的被追踪

⚠ **`XRController3D.has_tracking_data` 为真时，位姿**仍可能**是推断出来的**
（控制器丢失后由平台用最后已知状态或手臂模型推算）。

⛔ 症状：手柄放在桌上/拿出了追踪范围，`has_tracking_data` **照样为 true**，
游戏以为手还在，抓取、瞄准、手势全部基于一个**假位姿**在跑。

✅ 判据要**两个一起看**：

```gdscript
var pose := ctrl.get_pose()
if pose == null or not pose.has_tracking_data:
    _on_lost()                      # 明确丢失
elif pose.tracking_confidence != XRPose.XR_TRACKING_CONFIDENCE_HIGH:
    _on_unreliable()                # ⚠ 有"数据"但不可信
```

⛔ **置信度在 `XRPose` 上，不在 `XRController3D` 上** ——
官方 `XRNode3D` 的公开属性只有 `pose` / `show_when_tracked` / `tracker` /
`physics_interpolation_mode`，方法只有 `get_has_tracking_data()` /
`get_is_active()` / `get_pose()` / `trigger_haptic_pulse()`，**没有 `tracking_confidence`**。
详见 §8。

⛔ **推论**：任何"手的位置驱动玩法"的逻辑，
都要有"位姿不可信"的降级路径（暂停交互 / 保持上一有效姿态 / 提示玩家），
⛔ 不能假设位姿永远有效。

⚠ **`XRController3D` 没有速度 API** —— 只有 `get_float` / `get_vector2` / `is_button_pressed`。
释放物体时需要的速度必须自己算，而且要**多样本平均**：

```gdscript
class_name VelocityTracker3D
extends Node3D

@export var samples := 12
var _pos: Array[Vector3] = []
var _t: Array[float] = []

func _process(_d: float) -> void:
    _pos.append(global_position)
    _t.append(Time.get_ticks_usec() / 1e6)
    if _pos.size() > samples:
        _pos.pop_front(); _t.pop_front()

func velocity() -> Vector3:
    if _pos.size() < 2:
        return Vector3.ZERO
    var dt := _t[-1] - _t[0]
    if dt <= 0.0:
        return Vector3.ZERO
    # 首尾差分，不是相邻帧差分（单帧差分在 120Hz 上出尖峰）
    return (_pos[-1] - _pos[0]) / dt
```

⚠ **用单帧差分算速度会在高刷新率头显（120Hz）上出尖峰**，
扔出去的物体速度乱跳。必须多样本平均。

### 触觉反馈

```gdscript
ctrl.trigger_haptic_pulse("haptic", 0.0, 0.5, 0.05, 0.0)
```

## 3. 抓取

三种方案：

| 方案 | 适合 |
|---|---|
| **物理关节**（推荐） | 物体仍是刚体，会与场景碰撞 |
| reparent | 简单，但物体失去物理碰撞 |
| 每帧跟随 | 简单，但穿透墙壁 |

⚠ **最容易做错的是释放时的速度传递**：
没有速度物体会"掉在手里"，手感非常假。

```gdscript
func _release() -> void:
    if _grab_joint:
        _grab_joint.queue_free()
        _grab_joint = null
    if _held:
        # 关键：把 tracker 的速度交给刚体
        _held.linear_velocity = _tracker.velocity()
        _held.angular_velocity = _tracker.angular_velocity()
        _held.set_deferred("can_sleep", true)
        _held = null
```

⚠ **睡着的刚体抓不起来**（官方老教程专门用 Sleep_Area 禁休眠）。
抓取时要 `sleeping = false` + 临时禁 `can_sleep`。

⚠ 抓取要记录**抓取偏移**，否则物体会瞬移到手腕中心。

⚠ 关节方案里**角向应松绑**，允许物体绕关节自转，手感更自然。

## 4. 传送

必须做四重有效性判定，否则会传到墙里或虚空：

```
1. 射线/抛物线是否命中
2. 命中点是否可站立（法线朝上）
3. 落点是否有足够空间（头顶高度）
4. 是否在允许区域内
```

⚠ **必须做淡入淡出（vignette）**。瞬间位移是晕动症的头号成因。

## 5. 晕动症（VR 特有，最重要）

| 成因 | 规避 |
|---|---|
| 接管相机移动 | 移动 `XROrigin3D`，**绝不**改相机 |
| 视觉与前庭不匹配 | 提供固定参考系（座舱/vignette） |
| 平滑转向 | 优先 **snap turn**（瞬时角度） |
| 帧率不稳 | 90Hz 必须稳，掉帧直接晕 |
| 加速度/失重 | 避免，或缩短 |

⚠ **VR 的帧率要求比普通 3D 严格得多**。
普通 3D 掉到 40fps 只是卡，VR 掉到 40fps 会让人呕吐。

⚠ **"所有 draw call ×2"是错的**。后处理与 MSAA 翻倍，几何提交大多共享。
但双眼渲染的净开销仍然显著。

## 6. 性能

| 优化 | 说明 |
|---|---|
| **MSAA** | VR 里画质提升明显，代价也大 |
| **注视点渲染**（foveated） | 周边降分辨率，收益大 |
| 减少 draw call | 比普通 3D 更重要 |
| 移动端（Quest） | 更严：发热降频、带宽受限 |

⚠ MSAA 与注视点渲染在某些 OpenXR 合成层上**可能冲突**，
按目标设备实测（标待核对）。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/xr.md`


## 7. 发布前检查清单

- [ ] 相机移动走 `XROrigin3D`，没有直接改 `XRCamera3D`
- [ ] 释放物体有速度传递
- [ ] 传送有四重判定 + 淡入淡出
- [ ] 提供 snap turn 选项
- [ ] 目标设备实测稳定 90Hz（不是编辑器里）
- [ ] 手部追踪的真机精度验证过
- [ ] 版本链对齐（Godot / xr-tools / Vendors）

## 8. ⛔ 官方口径：相机权威、插值与追踪置信度

三条都属于"属性面板看着有、实际不可信或不存在"这一类。

### ⛔ 相机大多数属性被 XRInterface 重写，唯一可信的是近/远裁剪面

官方原话（`XRCamera3D`）：*"if `Viewport.use_xr` is true, most of the camera
properties are ignored, as the HMD information overrides them. The only
properties that can be trusted are the near and far planes."*

⛔ 在 `XRCamera3D` 上调 FOV、`cull_mask`、`keep_aspect` 全部无效。
⛔ 尤其 `cull_mask`：想在 VR 里隐藏某一层，改相机 cull_mask **不会生效**，
而属性面板上它确实是勾好的 —— 排查必然被引向层名或渲染层设置。

### ⛔ XRCamera3D 强制关闭物理插值（硬编码 OFF）

官方源码在构造函数里直接 `set_physics_interpolation_mode(PHYSICS_INTERPOLATION_MODE_OFF)`，
注释写的是 *"XRCamera3D gets its transform updated every render frame and
shouldn't be interpolated."*，属性面板显示为 `physics_interpolation_mode = 2 (overrides Node)`。

⛔ 它是**强制**的，不继承项目设置 —— 面板上改不动。
⛔ 推论：把 HUD 或手持物挂在 `XRCamera3D` 下面，在项目开了物理插值时会与
场景其余部分**不同步**（其余插值、它不插值），表现为相对抖动。

### ⛔ 相机位置滞后几毫秒，不是权威物理抓手

官方原话：*"the render thread has access to the most up-to-date tracking data
of the HMD and the location of the XRCamera3D can lag a few milliseconds behind
what is used for rendering as a result."*

### ⛔ tracking_confidence 在 XRPose 上，不在 XRController3D 上

置信度是 **`XRPose`** 的属性，枚举 `TrackingConfidence` 三个值：

| 值 | 官方含义 |
|---|---|
| `XR_TRACKING_CONFIDENCE_NONE = 0` | 无追踪信息 |
| `XR_TRACKING_CONFIDENCE_LOW = 1` | 可能不准或是估算（官方举例：inside-out 追踪下控制器被部分遮挡） |
| `XR_TRACKING_CONFIDENCE_HIGH = 2` | 准确且最新 |

配套两条官方口径：

- ⛔ `XRPose.has_tracking_data` 为 false 时，官方原话是
  *"our state is whatever that last valid state was"* —— **不是清零**，
  所以"手柄放在桌上"照样返回一个看着合理的旧位姿。
- ⛔ `XRPositionalTracker.invalidate_pose()` 官方原话 *"we don't clear the
  last reported state"*，同理；官方给的对应机制是 `pose_lost_tracking` 信号
  与 `show_when_tracked` 属性（⛔ 默认 `false`，即丢失时**不隐藏**）。

⛔ 上一版写法里的 `elif not ctrl.has_tracking_data or ...` 是**死分支**
（`if` 已处理同一条件），且 `ctrl.tracking_confidence` 这个属性根本不存在。

### ⛔ XRPose.transform 不含 world_scale，要取用 get_adjusted_transform()

官方：`XRPose.transform` 是运行时上报的原始变换，而 `get_adjusted_transform()`
才是 *"the transform with world scale and our reference frame applied"*，
且它就是用来定位 `XRNode3D` 的那个。

⛔ 自己读 `pose.transform` 算世界坐标，在 `world_scale != 1` 时会得到错误尺度。

## 9. 流程：按什么顺序做

→ `flow/godot/xr/00-域流程总览.md`

## 10. 相关文档

- 3D 基础 → `3d.md`
- 性能 → `performance.md`
- 插件与版本锁 → `plugins.md`
- 渲染与 LOD → `rendering-advanced.md`
