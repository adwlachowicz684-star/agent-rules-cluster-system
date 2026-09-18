# 相机与过场动画

## 0. 相机首先是"坐标变换职责划分"，不是几个参数

推荐分层（2D）：

```
CameraRig (Node2D)    负责跟随、死区、前瞻、屏震偏移
└── Camera2D          负责 limit、平滑、offset、zoom
```

⚠ **不要用 Camera2D 自己同时做跟随和边界** ——
跟随逻辑写进去后，`limit` 和平滑会互相干扰。

## 1. 跟随策略对比

| 方式 | 延迟 | 适合 | 风险 |
|---|---|---|---|
| 直接赋值 | 零 | 固定房间、UI 相机 | **把目标抖动直接传到屏幕** |
| 内置平滑 | 中低 | 平台、俯视、追尾 | 急停后仍有拖尾 |
| 帧率无关 lerp | 可控 | 不同轴向、状态化 | 与内置平滑叠加 |
| **死区 drag** | 视死区 | 街机动作、双人 | 死区过小=直接跟随 |
| **前瞻** | 可瞬时 | 高速横版 | 转向"甩头" |

### 内置 drag_margin 就是 Godot 的死区

```gdscript
camera.drag_horizontal_enabled = true
camera.drag_vertical_enabled = true
camera.drag_left_margin = 0.2    # 屏幕 20% 边距
camera.drag_right_margin = 0.2
```

- 0.2 适合动作游戏，0.5 适合较慢的俯视探索
- ⚠ **坐标系经过缩放与锚点计算**，不是固定屏幕像素矩形

⚠ **内置死区是"居中跟随"而非"固定区域"** ——
目标一到边距就追，手感较"黏"。
专业平台游戏的死区是"目标离开固定区域后再重新居中"。

### 帧率无关平滑（自定义时必用）

```gdscript
# 错：lerp(a, b, 0.1) —— 帧率越高越快
camera.position = lerp(camera.position, target_pos, 0.1)

# 对：帧率无关
camera.position = lerp(camera.position, target_pos, 1.0 - exp(-k * delta))
```

⚠ **`lerp(a, b, 0.1)` 的平滑速度与帧率相关** ——
120Hz 机器上相机明显更快。这是最常见的相机 bug。

## 2. 边界、缩放与多目标

⚠ **边界、缩放、多目标必须共同计算**，否则画面会穿出关卡。

**多目标**（双人/多人）：取所有目标的**包围盒**，
再用 `viewport_size / zoom` 算出需要的缩放。

```gdscript
func _fit(targets: Array) -> void:
    var box := Rect2(targets[0].global_position, Vector2.ZERO)
    for t in targets:
        box = box.expand(t.global_position)
    var center = box.get_center()
    var need_zoom = min(
        get_viewport_rect().size.x / (box.size.x + margin),
        get_viewport_rect().size.y / (box.size.y + margin))
    zoom = Vector2.ONE * clampf(need_zoom, MIN_ZOOM, MAX_ZOOM)
```

⚠ 缩放变化会改变可视区域，**limit 要跟着重算**。

## 3. 屏震：trauma 模型

⚠ **不要做"每帧随机偏移"** —— 那是抖动，不是震动，
看起来廉价且容易让画面糊掉。

正确做法：**trauma 值 + 平方衰减 + 噪声**

```gdscript
class_name TraumaShake
extends Node2D

@export var max_offset := 12.0
@export var max_roll := 0.05
@export var decay := 1.4

var trauma := 0.0
var _noise := FastNoiseLite.new()
var _t := 0.0

func add(amount: float) -> void:
    trauma = clampf(trauma + amount, 0.0, 1.0)

func _process(delta: float) -> void:
    if trauma <= 0.0:
        position = Vector2.ZERO; rotation = 0.0; return
    _t += delta
    trauma = maxf(trauma - decay * delta, 0.0)
    var s := trauma * trauma          # 平方衰减，小震更收敛
    position = Vector2(
        _noise.get_noise_2d(_t * 25.0, 0.0),
        _noise.get_noise_2d(0.0, _t * 25.0)) * max_offset * s
    rotation = _noise.get_noise_1d(_t * 20.0) * max_roll * s
```

⚠ 用 **trauma²** 而不是 trauma 线性 —— 小震动衰减更快，手感更干净。
⚠ 多个震源用 `add()` 累加并 clamp，不要各自乱设。

## 4. 3D 第三人称：标准三层结构

```
Player (CharacterBody3D)
└── Pivot (Node3D)          ← 只处理旋转（鼠标控制）
    └── SpringArm3D         ← 碰撞避让
        └── Camera3D        ← 只处理距离
```

⚠ **SpringArm 的碰撞层必须显式配置**，并且要**排除角色自己** ——
否则相机会被自己的碰撞体顶开。这是"相机穿墙/抽搐"最常见的原因。

## 5. 过场：按复杂度选型

| 场景 | 首选 | 不推荐 |
|---|---|---|
| 精确镜头+角色+音效同步 | **AnimationPlayer** | 手写大量定时器 |
| 动态目标、命中 punch、相机路径 | **Tween / 代码** | 为每个距离烘焙动画 |
| 多分支、条件、存档续播 | **脚本状态机** | 多个独立布尔标志 |
| 一次性 UI 渐变 | Tween | 新建动画资源 |

⚠ **选型标准是时间复杂度，不是节点流行度**。
"移动两秒—等对话—继续移动"用 Tween 比动画资源轻得多。

⚠ 4.7 的 `tween_await()` 可等信号（目标释放或超时也会结束），
很适合过场里等对话/等到达（见 `version-47-48.md`）。

⚠ **AnimationPlayer 的代价是状态恢复责任**：
跳到结尾或中途停止后，被动画改写的属性要自己恢复。

## 6. 过场三要素必须写成同一状态机

**控制权 · 可跳过 · 可恢复** —— 缺一个就会出 bug。

### 控制权：保存并恢复权限，不是设布尔

⚠ **直接 `player.can_move = false` 会漏掉镜头输入、菜单、攻击、载具**。

```gdscript
class_name InputAuthority
extends Node

var _stack: Array[Dictionary] = []

func push(snapshot: Dictionary) -> void:
    _stack.append(snapshot)

func pop() -> void:
    if _stack: _stack.pop_back()

func can_accept(capability: StringName) -> bool:
    return _stack.is_empty() or _stack[-1].get(capability, true)
```

⚠ **结束时从快照恢复，不要假设"一定恢复为 true"** ——
异常路径（玩家强退、场景切换）会导致永久锁死。

### 可跳过

⚠ **跳过不是"直接结束动画"，是要把状态推进到终态**：
- 相机要回到正确位置
- 被改写的属性要恢复
- 后续逻辑要触发

跳过处理不当 = 玩家跳过过场后角色卡在原地。

### 可恢复

⚠ 过场中途退出游戏，回来要能续播或至少回到一致状态。
配合存档系统（见 `security.md`）。

## 7. 黑边是 UI，不是相机缩放

```gdscript
# 用 CanvasLayer + 两个 ColorRect，默认高度 0，过场时展开
```

⚠ 用 `anchor_top/anchor_bottom` + `offset_*`，**不要把 position 写死** ——
分辨率变化时会自动响应。

## 8. 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | Camera2D 兼做跟随和边界 | 要分层：Rig 跟随，Camera2D 管 limit |
| 2 | `lerp(a,b,0.1)` 是标准平滑 | **帧率相关**，要用 `1-exp(-k*dt)` |
| 3 | 死区就是 drag_margin | 内置是居中跟随，专业死区要固定区域 |
| 4 | 屏震=每帧随机偏移 | 那是抖动，要用 trauma+平方衰减+噪声 |
| 5 | 缩放改了不用管 limit | 可视区域变了，limit 要重算 |
| 6 | SpringArm 自动避让角色 | 要**显式排除角色碰撞层** |
| 7 | 过场用 AnimationPlayer 最专业 | 简单过场用 Tween 更轻 |
| 8 | 禁用玩家 = `can_move=false` | 会漏镜头/菜单/攻击，要用权限栈 |
| 9 | 过场结束恢复为 true | 异常路径会永久锁死，要从**快照**恢复 |
| 10 | 跳过=结束动画 | 要把状态**推进到终态** |
| 11 | 黑边用相机缩放做 | 是 UI，用 CanvasLayer+ColorRect |
| 12 | 黑边位置写死 | 分辨率变化会错位，用 anchor+offset |
| 13 | 动画播完属性自动恢复 | AnimationPlayer 不负责恢复 |
| 14 | 过场中途退出无所谓 | 要能续播或回到一致状态 |

## 9. 相关文档

- 打击感（屏震/顿帧）→ `combat.md`
- 2D 渲染与特效 → `2d-rendering.md`
- 对话系统 → `game-systems.md`
- 输入 → `input-audio.md`
- 3D 相机 → `3d.md`
