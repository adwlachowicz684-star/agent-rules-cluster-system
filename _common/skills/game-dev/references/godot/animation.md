# Godot 4.x 动画与缓动

AnimationPlayer（美术做的动画）、AnimationTree（状态机混合）、Tween（代码驱动的补间）。
三者用途不同，选错了会绕远路。

## 选型

```
要做的事                          用什么
─────────────────────────────────────────────
播放一段固定动画（走路/攻击/开门）  AnimationPlayer
多个动画间按条件切换+混合          AnimationTree（状态机）
代码里让属性平滑过渡（UI淡入/抖动） Tween
每帧自己算（跟随、弹簧）           _process + lerp，不用 Tween
```

⚠ **Tween 不是"每帧改属性"的工具** —— 它是"在 N 秒内从 A 变到 B"。
需要持续跟随目标（相机跟随、血条平滑）用 `lerp`，Tween 会不断重建。

## 1. AnimationPlayer

### 在编辑器里做动画

1. 选中节点 → 底部面板 Animation → 新建动画
2. 点属性旁的钥匙图标插入关键帧
3. 调整 `length`、`loop_mode`

### 代码控制

```gdscript
@onready var _anim: AnimationPlayer = $AnimationPlayer

func _ready() -> void:
    _anim.animation_finished.connect(_on_anim_finished)

func _exit_tree() -> void:
    if _anim.animation_finished.is_connected(_on_anim_finished):
        _anim.animation_finished.disconnect(_on_anim_finished)

func play_attack() -> void:
    _anim.play("attack")

func _on_anim_finished(name: StringName) -> void:
    if name == "attack":
        _can_attack = true
```

**常用方法**：

| 方法 | 用途 |
|---|---|
| `play(name, custom_blend, custom_speed, from_end)` | 播放，`from_end=true` 倒放 |
| `play_backwards(name)` | 倒放 |
| `stop(keep_state)` | 停止，`keep_state=true` 保留当前姿态 |
| `queue(name)` | 播完当前后排队播 |
| `current_animation_position` | 当前进度（秒） |
| `seek(seconds, update)` | 跳到指定时间 |
| `speed_scale` | 全局倍速 |

### 动画名常量化（避免拼写静默失效）

```gdscript
const ANIM_IDLE := "idle"
const ANIM_RUN := "run"
const ANIM_ATTACK := "attack"

func _ready() -> void:
    # 启动时校验一遍，拼错立刻暴露，而不是"不报错也不播"
    for a in [ANIM_IDLE, ANIM_RUN, ANIM_ATTACK]:
        if not _anim.has_animation(a):
            push_error("缺少动画: %s" % a)
```

⚠ 动画名是字符串，**拼错不报错也不播放**（审查 GD54）。
集中成常量 + 启动时校验，比运行时调试快得多。

### 方法轨：在动画里调用代码

动画时间轴上可以插入"调用某个方法"的关键帧。适合"第 0.3 秒生成子弹"这类精确时机。

⚠ 方法轨里写的是**方法名字符串** —— 重命名方法后**动画不会跟着改**，
同样静默失效。改方法名要同步改动画资源。

## 2. AnimationTree（状态机）

角色有多个状态且要平滑过渡时用它，比在代码里 `if` 切换 `play()` 清晰得多。

### 搭建

```
Player
├── AnimationPlayer       ← 存放所有动画
└── AnimationTree         ← tree_root = AnimationNodeStateMachine
```

AnimationTree 的属性：

| 属性 | 设成 |
|---|---|
| `tree_root` | 新建 `AnimationNodeStateMachine` |
| `anim_player` | 指向上面的 AnimationPlayer 节点 |
| `active` | `true` |

在状态机面板里：添加节点对应每个动画，连线设置过渡条件。

### 代码控制

```gdscript
@onready var _tree: AnimationTree = $AnimationTree
@onready var _playback: AnimationNodeStateMachinePlayback = \
    _tree.get("parameters/playback")

func _ready() -> void:
    _tree.active = true

func _physics_process(delta: float) -> void:
    # 用参数驱动状态机，而不是直接 play()
    _tree.set("parameters/conditions/is_moving", velocity.length() > 1.0)
    _tree.set("parameters/conditions/is_grounded", is_on_floor())

func attack() -> void:
    _playback.travel("attack")       # 走过渡路径到 attack
```

**常用参数路径**（`"parameters/..."` 字符串）：

```gdscript
_tree.set("parameters/conditions/<条件名>", true)   # 状态机条件
_tree.set("parameters/<节点名>/blend_amount", 0.5)  # 混合权重
_tree.set("parameters/<节点名>/time_scale", 1.5)    # 单个动画倍速
```

⚠ **路径拼错静默失效**（审查 GD53）。建议集中常量：

```gdscript
const P_COND_MOVING := "parameters/conditions/is_moving"
const P_COND_GROUNDED := "parameters/conditions/is_grounded"
```

### travel vs start

| 方法 | 行为 |
|---|---|
| `travel("attack")` | 沿过渡路径走，会考虑中间状态 |
| `start("attack")` | 立刻跳过去，不管路径 |

一般用 `travel`。

## 3. Tween

### 基础

```gdscript
func fade_out(node: CanvasItem) -> void:
    var tw := create_tween()          # 4.x：Node.create_tween()
    tw.tween_property(node, "modulate:a", 0.0, 0.3)
```

**必须保存引用**（否则重复触发时旧 Tween 还在写属性）：

```gdscript
var _tween: Tween

func pulse() -> void:
    if _tween and _tween.is_valid():
        _tween.kill()                 # 重启前先杀掉旧的
    _tween = create_tween()
    _tween.tween_property(self, "scale", Vector2(1.2, 1.2), 0.1)
    _tween.tween_property(self, "scale", Vector2.ONE, 0.1)
```

⚠ `create_tween()` 返回值不保存 = **P0 泄漏**（审查 GD02）。

### 链式 API 全览

```gdscript
var tw := create_tween()

# 顺序执行（默认）
tw.tween_property(sprite, "position", Vector2(100, 0), 1.0)

# 并行：parallel() 后面的与前一个同时开始
tw.parallel().tween_property(sprite, "modulate:a", 0.0, 1.0)

# 或整体并行
tw.set_parallel(true)

# 间隔
tw.tween_interval(0.5)

# 回调
tw.tween_callback(func(): print("done"))

# 调自定义方法（from → to 插值）
tw.tween_method(_set_health_display, 100.0, 0.0, 2.0)

# 循环（0 = 无限）
tw.set_loops(3)
tw.set_loops(0)                      # 无限循环

# 缓动
tw.set_trans(Tween.TRANS_BACK)
tw.set_ease(Tween.EASE_OUT)

# 延迟
tw.set_delay(0.2)

# 绑定到节点（节点释放时自动销毁）
tw.bind_node(self)

# 暂停行为
tw.set_pause_mode(Tween.TWEEN_PAUSE_PROCESS)   # 树暂停时仍继续
```

**Trans 类型**：LINEAR / SINE / QUINT / QUART / QUAD / EXPO / ELASTIC / CUBIC / CIRC / BOUNCE / BACK / SPRING
**Ease 类型**：IN / OUT / IN_OUT / OUT_IN

### kill vs stop

| 方法 | 行为 |
|---|---|
| `kill()` | 终止，**属性停在当前值**，Tween 对象失效 |
| `stop()` | 停止但可以 `play()` 恢复 |

要"取消动画并重置"是 `kill()` + 手动复位属性。

### 绑定与生命周期

```gdscript
# Node.create_tween() —— 绑定到该节点，节点释放时自动销毁（推荐）
var tw := create_tween()

# SceneTree.create_tween() —— 不绑定任何节点，必须自己管理
var tw2 := get_tree().create_tween()
tw2.bind_node(self)                  # 手动绑定，否则节点没了 Tween 还活着
```

⚠ `get_tree().create_tween()` **不自动绑定节点**（审查 GD02 的成因）。

### 实战：UI 弹窗动画

```gdscript
func show_popup(panel: Control) -> void:
    panel.visible = true
    panel.scale = Vector2(0.8, 0.8)
    panel.modulate.a = 0.0

    if _tween and _tween.is_valid():
        _tween.kill()
    _tween = create_tween()
    _tween.set_parallel(true)
    _tween.tween_property(panel, "scale", Vector2.ONE, 0.25)\
          .set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
    _tween.tween_property(panel, "modulate:a", 1.0, 0.2)
    _tween.bind_node(panel)

func hide_popup(panel: Control) -> void:
    if _tween and _tween.is_valid():
        _tween.kill()
    _tween = create_tween()
    _tween.tween_property(panel, "modulate:a", 0.0, 0.15)
    _tween.tween_callback(func(): panel.visible = false)
    _tween.bind_node(panel)
```

### 实战：伤害数字飘字

```gdscript
func spawn_damage_number(pos: Vector2, amount: int) -> void:
    var label := Label.new()
    label.text = str(amount)
    label.position = pos
    label.modulate = Color.YELLOW
    add_child(label)

    var tw := create_tween()
    tw.set_parallel(true)
    tw.tween_property(label, "position:y", pos.y - 40.0, 0.8)\
      .set_trans(Tween.TRANS_QUAD).set_ease(Tween.EASE_OUT)
    tw.tween_property(label, "modulate:a", 0.0, 0.8)
    tw.chain().tween_callback(label.queue_free)   # 播完自毁
    tw.bind_node(label)
```

⚠ `tween_callback(label.queue_free)` —— 直接传方法引用，不要写 `func(): label.queue_free()`。

## 4. 每帧插值（不走 Tween）

持续跟随用 `lerp`，不要反复建 Tween：

```gdscript
@onready var _camera: Camera2D = $Camera2D

func _process(delta: float) -> void:
    # 指数平滑，与帧率无关的写法
    var t := 1.0 - exp(-5.0 * delta)
    _camera.position = _camera.position.lerp(_player.position, t)
```

⚠ 直接写 `lerp(a, b, 0.1)` 是**帧率相关**的 —— 高帧率下跟得紧、低帧率下跟得松。
用 `1.0 - exp(-speed * delta)` 才与帧率无关。

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| `create_tween()` 未保存引用 | 无法 kill，重复触发叠加 | GD02 |
| 重启动画前未 `kill()` | 两个 Tween 抢同一个属性，抖动 | GD02 |
| `get_tree().create_tween()` 未 `bind_node` | 节点释放了 Tween 还在 | GD02 |
| 动画名/参数路径用字面量 | 拼错静默失效 | GD54 / GD53 |
| 该用 `lerp` 的地方用 Tween | 每帧重建，GC 压力 | 人工 |
| `lerp(a,b,0.1)` 固定系数 | 帧率相关，不同机器表现不同 | 人工 |
| 方法轨里的方法改名 | 动画调用失效，不报错 | 人工 |
