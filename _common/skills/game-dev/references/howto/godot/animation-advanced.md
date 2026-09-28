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
    tree.active = true          # ⓘ 4.x 起默认已是 true（见 §8），这行不再是"没输出"的主因
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

⚠ 用 `travel` 到没有连接的节点，官方口径是**传送（teleport）**：
*"If the path does not connect from the current state, the animation will play after the state teleports."*
⛔ 所以表现**不是**"没反应"，而是**无过渡地跳变** —— 排查时会被引向"过渡时间没配"，
而实际是状态图根本没连。初始化用 `start`，之后用 `travel`。

### switch_mode = 过渡时机，不是淡入算法

| 模式 | 行为 | 适合 |
|---|---|---|
| **Immediate** | 立即切换，与下一状态开头混合 | 响应式移动（默认） |
| **Sync** | 立即切换，但新状态 seek 到旧状态位置 | 长度相近的循环 |
| **AtEnd** | 等当前播完再播下一个 | 不可打断的演出 |

⚠ **不要用 AtEnd 做受击/攻击** —— 玩家会觉得操作有延迟。
⚠ Sync 强加在长度差异大的动画（idle vs attack）上会导致**变形**。

ⓘ 与 AtEnd 配套的一个独立开关：**`break_loop_at_end`**。
循环动画用 AtEnd 时**永远不会"播完"**，转移条件即使为真也不触发；
要显式 `break_loop_at_end = true` 才能在本次循环结束时转出。
⛔ 表现为"条件明明满足了，状态就是不变"，
而转移条件与 switch_mode 两处检查都是对的。

### 转移条件的两个限制

```gdscript
# advance_condition：只能设布尔真
tree["parameters/conditions/can_run"] = true
```

⚠ **条件只能判断真，不能写 `!can_run` 或比较表达式**。
"速度 > 阈值"这类要用 **Advance Expression**（Expression Base Node 要指向有该属性的脚本节点）。

⚠ **同一状态多条候选转移时要显式设 `priority`**


ⓘ 转移还有一层开关：`advance_mode` 可取
**`DISABLED`**（该转移不参与 travel 与自动前进）、
**`ENABLED`**（可被 `travel()` 使用）、
**`AUTO`**（`advance_condition` / `advance_expression` 为真时**自动前进，不需 travel**）。
⛔ 只用 `travel` 而不用 AUTO —— 状态判定逻辑会全部堆进脚本，
表现为"状态机图与代码两处都要改"，改一处漏一处。
（越小越优先）。
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

> **反模式清单（不能怎么做，审核用）** → `audit/godot/animation-advanced.md`


## 7. 相关文档

- 基础动画与 Tween → `animation.md`
- 音频 → `audio-advanced.md`
- 3D 骨骼与模型 → `3d.md`
- 性能 → `performance.md`


## 8. 4.x 的三个覆盖默认值（"配置全对但不对"先看这里）

⛔ `AnimationTree` 继承 `AnimationMixer`，但**覆盖了它的三个默认值**。
这三条的共同点是：属性面板上显示的值**看起来完全正常**，
而混合结果不对，且不报错 —— 排查方向必然被引向动画资源本身。

| 属性 | `AnimationMixer` 默认 | `AnimationTree` 覆盖为 | 后果 |
|---|---|---|---|
| `callback_mode_discrete` | `1`（Recessive） | **`2`（ForceContinuous）** | Discrete 轨道被当成连续值插值 |
| `deterministic` | `false` | **`true`** | 总权重**不归一化**，从初始值累加 |
| `active` | `true` | 继承（不覆盖） | ⛔ 与 3.x 的 `false` 不同 |

### 启用路径：Start 节点或 start()，⛔ 不是只设 active

官方教程原文：*"Make sure to either call start() or connect a node to Start."*
`active` 由 `AnimationMixer` 继承，4.x 默认已是 **`true`**
（⛔ 3.x 是 `false`，这是迁移后最容易沿用的旧经验）。

⛔ 于是"配置全对但没输出"会被反复归因为"active 忘了设"，
加了一行本来就为真的代码，⛔ 真正的成因（没调 `start()` / 没连 Start 节点）被永久掩盖。

ⓘ 同源的一条：Advance Expression 的 `advance_expression_base_node` 默认 `"."`，
⛔ 必须在 **Inspector** 里指向实际持有该属性的脚本节点，否则表达式取不到值且不报错。

### ⛔ Discrete 轨道在 AnimationTree 里会被强制连续

官方原文：*"Always treat the Discrete track value as Continuous with Nearest.
**This is the default behavior for AnimationTree**."*

⛔ 轨道在 `AnimationPlayer` 里明明设成了 `UPDATE_DISCRETE`，
进了 AnimationTree 仍被插值。典型症状：**表情切换、开关、整数索引在混合时"滑动"**
—— 例如用 `texture_offset` 切表情，混合时脸会滑过去。

表现极具误导性：轨道属性面板上写着 Discrete，混合节点配置也对，
于是排查被引向"是不是该写代码强制赋值"。解法是改 `callback_mode_discrete`：

```gdscript
# ⓘ 承接本文：tree 为 AnimationTree
tree.callback_mode_discrete = AnimationMixer.ANIMATION_CALLBACK_MODE_DISCRETE_DOMINANT
```

### ⛔ deterministic 为 true 让 Add 类节点效果减半

官方原文：*"the total weight is not normalized and the result is accumulated with an
initial value (0 or a `RESET` animation if present)"*。
而官方 Note 明确点名的陷阱是：

> 在 AnimationTree 中与 `AnimationNodeAdd2` / `Add3` / `Sub2`，
> 或**权重大于 1.0** 混合，可能产生意外结果。
> 例：Add2 混合两个 amount 为 1.0 的节点，总权重 2.0 却**被归一化回 1.0**，
> 结果等于 `AnimationNodeBlend2` 取 0.5。

⛔ 这就是"叠加调了没反应 / 效果只有一半"的真正成因：
节点连对了、amount 也给了 1.0，**而结果是它的一半，且不报错**。

ⓘ 另一面：`deterministic = true` 时**总混合量为 0 的结果等于 RESET 动画**，
这是它能给出可复现初值的原因，不要一律关掉。

### ⛔ 动画节点是资源，实例间共享

官方 Using AnimationTree 原文：*"Keep in mind that the animation nodes are just
resources, so they are shared between all instances using them."*

⛔ 直接改节点里的值会影响**所有**使用该树的场景实例，
表现为"改一个敌人的动画参数，全场同类敌人一起变"。
这与材质共享是同一类坑（见 `cosmetic` 域）。

ⓘ 一个容易记反的对照：`AnimationNodeStateMachinePlayback` 的
`resource_local_to_scene` **默认是 `true`（官方显式覆盖 Resource 的 `false`）**。
即：**树共享，但 playback 每实例独立**。
所以"改树参数 → 全场变"，而"改 playback → 只影响自己"。

### root_motion_local 与混合前后的位移

`AnimationMixer.root_motion_local` 默认 **`false`**：
为 `true` 时 `get_root_motion_position()` 取的是**混合前的局部位移**。
⛔ 默认取的是混合**后**的值 —— 分层叠加根运动时，两者差异会直接表现成位移量不对。

## 9. IK 节点：已弃用 + 三个生效时机

⛔ 官方对 `SkeletonIK3D` 的标注是 **Deprecated**：
*"This class is deprecated, and might be removed in a future release."*
其 `interpolation` 属性同样 deprecated，官方指向 **`SkeletonModifier3D.influence`**。
头部朝向用 `LookAtModifier3D`（⛔ 4.7 起 `LookAtModifier3D.relative` 默认从 `true` 改为 `false`，
已配好的瞄准/IK 需要重核）。

| 时机 | 官方口径 |
|---|---|
| `start()` | *"will only take effect **starting on the next frame**"* |
| `start(true)` | 立即生效，但**下一帧重置** |
| `stop()` | 停止并调用 `clear_bones_global_pose_override()` |

⛔ 三条各自的坑：

1. **`start()` 下一帧才生效** —— 调完立刻读骨骼姿势读到的是**旧的**，
   表现为"第一帧 IK 没生效"，排查被引向"骨骼名写错了"。
2. **`stop()` 清的是全部骨骼的 override** ——
   ⛔ 不是只清这条链。别处（另一条 IK、程序化骨骼修正）设的 override 会**一起被清掉**，
   表现为"关掉脚部 IK，手部 IK 也失效了"。
3. **`influence <= 0.01` 等价清 override** —— 官方明确写了这个阈值，
   所以"把 influence 设 0 来临时关 IK"是可行的，但要按第 2 条的连带影响来验收。

⛔ `get_parent_skeleton()` 返回的是 **IK 进入场景树时**的父节点，
若那时父节点不是 `Skeleton3D` 则返回 `null`。
所以**运行时 reparent 之后 IK 不会重新绑定** ——
这与坐骑/附身类玩法直接冲突（见 `companion` 域的 reparent 时序）。

## 10. 流程：按什么顺序做

→ `flow/godot/animation-advanced/00-域流程总览.md`
