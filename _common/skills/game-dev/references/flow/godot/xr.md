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

⚠ `XROrigin3D.world_scale` 是**全局统一缩放**。
改它会影响所有 XR 节点，不是"只缩放某个物体"。

## 2. 控制器输入

```gdscript
@onready var ctrl: XRController3D = $XROrigin3D/RightHand

func _process(_d: float) -> void:
    var trigger := ctrl.get_float("trigger")         # 0..1
    var stick := ctrl.get_vector2("thumbstick")      # 摇杆
    if ctrl.is_button_pressed("grip_click"):
        pass
```

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

## 8. 相关文档

- 3D 基础 → `3d.md`
- 性能 → `performance.md`
- 插件与版本锁 → `plugins.md`
- 渲染与 LOD → `rendering-advanced.md`
