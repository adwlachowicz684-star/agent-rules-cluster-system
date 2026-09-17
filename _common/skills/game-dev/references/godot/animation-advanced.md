# Godot 4.x 动画高级（AnimationTree 深入）

基础动画播放见 `animation.md`。本文讲**状态机、混合空间、根运动、IK、分层**——
角色动画工业化之后才会遇到的部分。

## 0. 先分清三件事

| 节点 | 解决什么 |
|---|---|
| **StateMachine** | "现在是什么状态"（离散、可打断） |
| **BlendSpace1D/2D** | "在两个状态之间取多少"（连续量） |
| **BlendTree** | "怎样组合成最终姿势"（分层、遮罩、叠加） |

⚠ 它们**不是二选一**。典型结构是：外层状态机管 Grounded/Air，
Grounded 内部用 BlendSpace2D 混合四向移动。

## 1. 状态机

### 最小场景结构

```
CharacterBody3D
├── Skeleton3D
├── AnimationPlayer        ← 动画资源在这里
└── AnimationTree          ← 混合在这里（anim_player 指向上面那个）
```

```gdscript
extends CharacterBody3D

@onready var tree: AnimationTree = $AnimationTree
@onready var playback: AnimationNodeStateMachinePlayback = tree["parameters/playback"]

const MAX_SPEED := 5.0

func _ready() -> void:
    tree.active = true          # ← 忘了这行：配置全对但没输出
    playback.start("idle")

func _physics_process(delta: float) -> void:
    var move := Input.get_vector("left", "right", "forward", "back")
    var ratio := clampf(velocity.length() / MAX_SPEED, 0.0, 1.0)

    tree["parameters/Grounded/blend_position"] = move
    tree["parameters/speed"] = ratio

    if Input.is_action_just_pressed("jump") and is_on_floor():
        playback.travel("jump")
    elif not is_on_floor():
        playback.travel("fall")
    elif ratio < 0.01:
        playback.travel("idle")
    else:
        playback.travel("run")
```

⚠ **`AnimationTree.active = true` 忘了设**是最常见的"配置全对但没反应"。

### `travel()` vs `start()`

| | 行为 |
|---|---|
| `travel("x")` | 沿状态图**走最短路径**到 x，中途经过的状态也会播 |
| `start("x")` | **直接**设为当前节点，不走路径 |

⚠ 用 `travel` 到没有连接的节点会**静默不动**。初始化用 `start`，之后用 `travel`。

### switch_mode = 过渡时机，不是淡入算法

| 模式 | 行为 | 适合 |
|---|---|---|
| **Immediate** | 立即切换，与下一状态开头混合 | 响应式移动（默认） |
| **Sync** | 立即切换，但新状态 seek 到旧状态位置 | 长度相近的循环 |
| **AtEnd** | 等当前播完再播下一个 | 不可打断的演出 |

⚠ **不要用 AtEnd 做受击/攻击** —— 玩家会觉得操作有延迟。
⚠ Sync 强加在长度差异大的动画（idle vs attack）上会导致**变形**。

### 转移条件的两个限制

```gdscript
# advance_condition：只能设布尔真
tree["parameters/conditions/can_run"] = true
```

⚠ **条件只能判断真，不能写 `!can_run` 或比较表达式**。
"速度 > 阈值"这类要用 **Advance Expression**（Expression Base Node 要指向有该属性的脚本节点）。

⚠ **同一状态多条候选转移时要显式设 `priority`**（越小越优先）。
不设的话选谁是不确定的，会变成难以追踪的随机行为。

### 读当前状态

```gdscript
playback.get_current_node()          # 状态名
playback.is_playing()
```

⚠ 状态机会在**淡化开始后立刻**把当前状态视为下一状态，
所以 `get_current_node()` 在过渡期间返回的是目标状态，不是你以为的那个。

## 2. 混合空间

| | 轴 | 典型用法 |
|---|---|---|
| **BlendSpace1D** | 一个标量 | 速度、倾斜度、潜行程度 |
| **BlendSpace2D** | 二维向量 | 局部坐标下的移动方向 `(x, z)` |

```gdscript
tree["parameters/Grounded/blend_position"] = Vector2(move.x, move.y)
```

⚠ **`sync` 适合 walk/run 这类长度相近的循环**（避免相位错开），
但 idle/jump/attack 长度差异大，强制同步会让动作变形。

## 3. 根运动（Root Motion）

用途：让**动画本身**决定角色位移，而不是代码算。适合精确的动作游戏。

```gdscript
# AnimationTree 上勾选 root_motion_track
var rm: Transform3D = tree.get_root_motion_transform()
var motion := rm.origin
```

⚠ **根运动读取的是"视觉抵消后"的增量**。
启用后角色的视觉位置不再等于 `Node.transform` ——
如果你同时用代码移动，会得到**双倍位移**。

⚠ 根运动的位移要自己 `move_and_slide()` 应用，
且通常要**转到角色朝向**（`transform.basis * motion`）。

⚠ 根运动与网络同步、物理插值配合时最容易出问题：
本地客户端和服务端的根运动增量可能不同步。

## 4. IK（反向动力学）

| 工具 | 用途 |
|---|---|
| `SkeletonIK3D` | 通用的两骨 IK（手臂、腿） |
| 脚部贴地 | 射线检测 + IK 或位移补偿 |
| 头部朝向 | `LookAt` 修改器（版本支持需按实际核对） |

```gdscript
@onready var ik: SkeletonIK3D = $Skeleton3D/SkeletonIK3D

func _ready() -> void:
    ik.start()

func _physics_process(delta: float) -> void:
    ik.target_transform = $Target.global_transform
```

⚠ IK 是**每帧求解**，大量角色同时用会明显吃 CPU。
远处 LOD 角色应关掉 IK。

⚠ IK 与根运动同时使用时，位移和骨骼修正会互相打架，
需要明确谁负责最终位置。

## 5. 分层与遮罩

典型需求："下半身跑，上半身开火"。

用 **BlendTree** 里的 Blend2/Blend3 + **轨道过滤**（指定哪些骨骼参与）：

```
BlendTree root
└── Blend2 (blend_amount)
    ├── A: 下半身 locomotion
    └── B: 上半身 aim/fire
```

⚠ 轨道过滤控制"哪些轨道参与混合"—— 这是分层的关键，
不做过滤会得到全身混合（上半身动作被下半身稀释）。

## 6. 程序化 vs 预烘焙

| | 用 Tween / 代码 | 用 AnimationPlayer |
|---|---|---|
| UI 动画 | ✅ | 也行 |
| 参数连续变化（血量条） | ✅ 更方便 | 过度设计 |
| 角色骨骼动画 | ❌ | ✅ |
| 需要美术在编辑器里调 | ❌ | ✅ |
| 大量同类对象 | ✅（共享一份逻辑） | 每个都要资源 |

⚠ `AnimationPlayer` 与 `AnimationTree` 在 4.x **共享 `AnimationMixer` 基类**。
大量角色时优先考虑动画资源的复用，不要每个实例一份。

## 7. 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 配置了状态机就能播 | `active = true` 忘了设，全无输出 |
| 2 | `travel` 能到任何状态 | 走状态图路径，**没连接就静默不动** |
| 3 | `start` 和 `travel` 一样 | `start` 直接设，不走路径 |
| 4 | switch_mode 是淡入算法 | 是**过渡时机** |
| 5 | AtEnd 适合受击 | 玩家感觉操作延迟 |
| 6 | 条件能写表达式 | 只能布尔真，复杂条件用 Advance Expression |
| 7 | 转移顺序决定优先级 | 要显式设 `priority` |
| 8 | 过渡期 get_current_node 是当前状态 | 淡化开始后就变成目标状态 |
| 9 | 根运动后还能用代码移动 | 会**双倍位移** |
| 10 | IK 很便宜 | 每帧求解，远处角色要关 |
| 11 | 分层不用过滤 | 全身混合，上半身被稀释 |
| 12 | Sync 总是更好 | 长度差异大时导致变形 |
| 13 | 状态机 vs 混合空间二选一 | 嵌套使用才是常态 |

## 8. 相关文档

- 基础动画与 Tween → `animation.md`
- 音频 → `audio-advanced.md`
- 3D 骨骼与模型 → `3d.md`
- 性能 → `performance.md`
