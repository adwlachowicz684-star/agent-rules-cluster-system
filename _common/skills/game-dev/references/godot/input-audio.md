# Godot 4.x 输入与音频

## 1. 输入

### Input Map：先配动作，不要读物理按键

**项目设置 → Input Map**，加动作再绑键位：

```
move_left    → A / 左箭头 / 手柄左
move_right   → D / 右箭头 / 手柄右
jump         → Space / 手柄 A
attack       → 鼠标左键 / 手柄 X
pause        → Esc / 手柄 Start
```

代码里**只用动作名**，不碰 `KEY_SPACE`：

```gdscript
# 反例：硬编码按键
if Input.is_key_pressed(KEY_SPACE): ...

# 正例
if Input.is_action_just_pressed("jump"): ...
```

好处：玩家能自己改键，手柄/键盘自动通用。

### 四个回调的执行顺序与选哪个

```
InputEvent 产生
  ↓
_input(event)                  ← 最先，UI 之前。全局快捷键
  ↓
_gui_input(event)              ← Control 节点收到（鼠标在其上/有焦点）
  ↓
_unhandled_key_input(event)    ← 未被 UI 消费的按键
  ↓
_unhandled_input(event)        ← 未被消费的其它事件。游戏逻辑放这里 ←
```

| 回调 | 用在哪 | 别用在哪 |
|---|---|---|
| `_input` | 全局快捷键（Esc 暂停、截图） | 游戏逻辑 —— 会被 UI 抢先 |
| `_gui_input` | 自定义控件的点击/拖拽 | 游戏世界的东西 |
| `_unhandled_key_input` | 快捷键（且不想被 UI 屏蔽时用 `_input`） | 通常不用 |
| **`_unhandled_input`** | **游戏逻辑（攻击、交互、切武器）** | — |

⚠ 游戏逻辑放 `_unhandled_input` 而不是 `_input`：
`_input` 在 UI 之前触发，玩家点按钮时会同时触发游戏逻辑。

### 事件驱动 vs 轮询

```gdscript
# 事件驱动（推荐）：不丢输入，适合"按一下触发一次"
func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("attack"):
        attack()

# 轮询：适合"按住持续生效"
func _physics_process(delta: float) -> void:
    var dir := Input.get_axis("move_left", "move_right")
```

⚠ **不要在 `_process` 里用 `is_action_just_pressed()`** ——
它只在"按下的那一帧"为 true，在 `_process` 里轮询可能整帧错过（审查 GD51）。

如果确实要在固定步里判断，一次性采样成字段：

```gdscript
var _jump_pressed := false

func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("jump"):
        _jump_pressed = true

func _physics_process(delta: float) -> void:
    if _jump_pressed and is_on_floor():
        velocity.y = jump_velocity
    _jump_pressed = false
```

### 常用 API

```gdscript
Input.is_action_pressed("move_right")        # 按住
Input.is_action_just_pressed("jump")         # 刚按下（一帧）
Input.is_action_just_released("jump")        # 刚松开
Input.get_axis("move_left", "move_right")    # -1..1 单轴
Input.get_vector("left","right","up","down") # 二维方向（已归一化）
Input.get_action_strength("accelerate")      # 0..1，手柄扳机/摇杆幅度
```

⚠ `get_vector()` 已归一化，斜向不会比直线快。自己拼 `Vector2(x, y)` 要 `.normalized()`。

### 鼠标

```gdscript
func _ready() -> void:
    Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)   # FPS 锁定

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseMotion:
        rotate_y(-event.relative.x * 0.002)
    if event.is_action_pressed("ui_cancel"):
        Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)
```

模式：VISIBLE / HIDDEN / CAPTURED（锁定并隐藏）/ CONFINED（限制在窗口内）

### 输入缓冲（连招 / 手感）

与跳跃缓冲同理：记录按下的时间，在可执行的窗口内生效。

```gdscript
const BUFFER_TIME := 0.15
var _attack_buffer := 0.0

func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("attack"):
        _attack_buffer = BUFFER_TIME

func _physics_process(delta: float) -> void:
    _attack_buffer = maxf(_attack_buffer - delta, 0.0)
    if _attack_buffer > 0.0 and _can_attack:
        do_attack()
        _attack_buffer = 0.0
```

### 手柄震动

```gdscript
Input.start_joy_vibration(0, 0.5, 0.3, 0.2)   # 设备ID, 弱马达, 强马达, 秒
Input.stop_joy_vibration(0)
```

`Input.get_connected_joypads()` 拿已连接设备列表。

## 2. 音频

### AudioServer 总线

先在项目里建总线（底部面板 Audio）：

```
Master
├── Music
└── SFX
```

代码控制：

```gdscript
func set_bus_volume(bus_name: String, linear: float) -> void:
    var idx := AudioServer.get_bus_index(bus_name)
    if idx < 0:
        push_error("总线不存在: %s" % bus_name)
        return
    AudioServer.set_bus_volume_db(idx, linear_to_db(linear))
    # linear_to_db：0..1 线性 → 分贝。别直接把 0.5 当 dB 用
    AudioServer.set_bus_mute(idx, linear <= 0.0)
```

⚠ 音量用 `linear_to_db()` 转换。分贝是对数，滑块值和 dB 不是一回事。

### 播放器选型

| 节点 | 用途 |
|---|---|
| `AudioStreamPlayer` | BGM、UI 音效（无空间感） |
| `AudioStreamPlayer2D` | 2D 世界音效（有位置衰减、声像） |
| `AudioStreamPlayer3D` | 3D 世界音效（距离衰减、多普勒） |

### BGM 管理器（含交叉淡入）

```gdscript
# autoload/audio_manager.gd —— Autoload，名 AudioManager
extends Node

const FADE_TIME := 1.0

var _bgm_player: AudioStreamPlayer
var _bgm_tween: Tween
var _sfx_pool: Array[AudioStreamPlayer] = []

func _ready() -> void:
    _bgm_player = AudioStreamPlayer.new()
    _bgm_player.bus = "Music"
    add_child(_bgm_player)

func play_bgm(stream: AudioStream) -> void:
    if _bgm_player.stream == stream and _bgm_player.playing:
        return                          # 同一首，别重开
    if _bgm_tween and _bgm_tween.is_valid():
        _bgm_tween.kill()
    _bgm_tween = create_tween()
    # 淡出旧的 → 换流 → 淡入
    if _bgm_player.playing:
        _bgm_tween.tween_property(_bgm_player, "volume_db", -40.0, FADE_TIME / 2.0)
        _bgm_tween.tween_callback(func():
            _bgm_player.stream = stream
            _bgm_player.play())
    else:
        _bgm_player.stream = stream
        _bgm_player.play()
        _bgm_player.volume_db = -40.0
    _bgm_tween.tween_property(_bgm_player, "volume_db", 0.0, FADE_TIME / 2.0)

func stop_bgm() -> void:
    if _bgm_tween and _bgm_tween.is_valid():
        _bgm_tween.kill()
    _bgm_tween = create_tween()
    _bgm_tween.tween_property(_bgm_player, "volume_db", -40.0, FADE_TIME)
    _bgm_tween.tween_callback(_bgm_player.stop)
```

### 音效：用池，不要每次 new

```gdscript
func play_sfx(stream: AudioStream, volume_db: float = 0.0) -> void:
    var p := AudioStreamPlayer.new()
    p.stream = stream
    p.bus = "SFX"
    p.volume_db = volume_db
    add_child(p)
    p.play()
    # 关键：播完必须释放，否则每个音效都是节点，越攒越多
    p.finished.connect(p.queue_free)
```

⚠ 动态 `new AudioStreamPlayer` 后**必须 `queue_free()`**（审查 GD52，P0）。
`finished.connect(p.queue_free)` 是最简写法。

**高频音效**（脚步、枪声）用 `AudioStreamPolyphonic` 更好 —— 一个播放器处理多个声部：

```gdscript
func _ready() -> void:
    _sfx_poly.stream = AudioStreamPolyphonic.new()
    _sfx_poly.max_polyphony = 16      # 超出会裁掉最旧的
    _sfx_poly.play()

func play_sfx_poly(stream: AudioStream) -> void:
    var playback := _sfx_poly.get_stream_playback() as AudioStreamPlaybackPolyphonic
    playback.play_stream(stream)
```

⚠ `max_polyphony` 超限会**静默裁掉最旧的声音** —— 表现为"连点时丢音"。

### 2D 位置音效

```gdscript
@onready var _sfx: AudioStreamPlayer2D = $AudioStreamPlayer2D

func play_at(stream: AudioStream, world_pos: Vector2) -> void:
    _sfx.global_position = world_pos   # 与监听器（Camera2D）的距离决定衰减
    _sfx.stream = stream
    _sfx.play()
```

`AudioStreamPlayer2D` 属性：`max_distance`（衰减距离）、`attenuation`、`panning_strength`。

### 常用资源类型

| 类 | 用途 |
|---|---|
| `AudioStreamWAV` | 短音效（无压缩、可循环点精确） |
| `AudioStreamMP3` | BGM（有压缩，循环点不精确） |
| `AudioStreamOggVorbis` | BGM（推荐，压缩率好） |
| `AudioStreamRandomizer` | 随机音高/音量（脚步声不单调） |
| `AudioStreamPolyphonic` | 多声部复用一个播放器 |

⚠ BGM 循环用 **Ogg**，不要用 MP3 —— MP3 有 encoder delay，循环处会有咔哒声。

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| `new AudioStreamPlayer` 未 `queue_free` | 节点累积（P0） | GD52 |
| `_process` 里 `is_action_just_pressed` | 掉帧漏输入 | GD51 |
| 游戏逻辑放 `_input` | 点 UI 时同时触发游戏动作 | 人工 |
| 音量直接把线性值当 dB | 音量曲线不对 | 人工 |
| `get_vector()` 后又 `normalized()` | 多余（它已归一化），且零向量会 NaN | 人工 |
| 硬编码 `KEY_SPACE` | 玩家无法改键，手柄不通用 | 人工 |
| MP3 做循环 BGM | 循环点咔哒声 | 人工 |
