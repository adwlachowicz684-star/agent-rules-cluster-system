# Godot 4.x 音频高级

基础播放见 `input-audio.md`。本文讲**总线架构、音效池、动态音乐、空间音频**。

## 0. 总线是混音链，不是分组标签

```
Master    ← 最终输出、全局静音/音量入口
├── Music ← BGM（可放侧链压缩、EQ）
├── SFX   ← 战斗、环境、脚步（可放混响）
├── UI    ← 按钮、提示（**独立**，见下）
└── Voice ← 语音/对话（可懂度优先）
```

```gdscript
func setup_buses() -> void:
    for name in ["Music", "SFX", "UI", "Voice"]:
        AudioServer.add_bus()
        AudioServer.set_bus_name(AudioServer.get_bus_count() - 1, name)
```

⚠ **UI 音效不要走 Master**。
它把"全部静音"和"界面反馈静音"耦合了——玩家调低 Master 想保留语音时，
按钮声也没了；暂停时想保留 UI 反馈也做不到。

## 1. 音量：dB 不是线性

```gdscript
# 错：直接拿 0–1 的 slider 值当音量
AudioServer.set_bus_volume_db(idx, slider.value)   # 完全不对

# 对：先转 dB
AudioServer.set_bus_volume_db(idx, linear_to_db(slider.value))
```

⚠ **`set_bus_volume_db` 接受的是分贝，不是 0–1**。
直接把 slider 的 `0.0–1.0` 传进去，音量曲线会完全不对
（0.5 听起来不是一半，而是几乎听不见）。

⚠ 音量 0 要用**极小值或静音**，不能用 `0 dB`（那是原始音量，不是无声）。

## 2. 播放器节点选型

| 节点 | 用途 |
|---|---|
| `AudioStreamPlayer` | 非空间音效（UI、BGM） |
| `AudioStreamPlayer2D` | 2D 空间音效（按屏幕位置衰减/声像） |
| `AudioStreamPlayer3D` | 3D 空间音效（衰减模型、多普勒） |

```gdscript
var p := AudioStreamPlayer3D.new()
p.stream = preload("res://sfx/footstep.ogg")
p.max_distance = 20.0
p.attenuation_model = AudioStreamPlayer3D.ATTENUATION_INVERSE_DISTANCE
add_child(p)
p.play()
```

⚠ 3D 音效节点**必须在场景树里**才有空间效果。
`AudioStreamPlayer3D.new()` 不 `add_child` 就是普通播放器。

## 3. 音效池

同时播几十个相同音效会爆音。用池 + 随机音高：

```gdscript
class_name SfxPool
extends Node

@export var pool_size := 8
@export var base_pitch := 1.0
@export var pitch_variance := 0.15

var _players: Array[AudioStreamPlayer] = []
var _next := 0

func _ready() -> void:
    for i in pool_size:
        var p := AudioStreamPlayer.new()
        p.bus = &"SFX"
        add_child(p)
        _players.append(p)

func play(stream: AudioStream) -> void:
    var p := _players[_next]
    _next = (_next + 1) % _players.size()
    p.stream = stream
    # 随机音高：避免重复感
    p.pitch_scale = base_pitch * randf_range(
        1.0 - pitch_variance, 1.0 + pitch_variance)
    p.play()
```

⚠ **同一个 `AudioStreamPlayer` 反复 `play()` 会打断自己**，
密集触发时听感是"卡住"。必须用池轮转。

⚠ 音高随机化幅度别太大（±15% 以内），否则听出变调。

## 4. 动态音乐

### 交叉淡入

```gdscript
func crossfade(to: AudioStream, time := 1.5) -> void:
    var t := create_tween()
    t.tween_method(_set_music_vol, 0.0, -80.0, time)   # 淡出
    t.tween_callback(func(): _swap_stream(to))
    t.tween_method(_set_music_vol, -80.0, 0.0, time)   # 淡入

func _set_music_vol(db: float) -> void:
    AudioServer.set_bus_volume_db(AudioServer.get_bus_index(&"Music"), db)
```

⚠ 淡出到 `0 dB` 不是静音。要淡到 **-80 dB**（或更低）。

### 分层音乐

多个 `AudioStreamPlayer` 各放一层（鼓/贝斯/旋律），
按游戏状态调各自的音量。比交叉淡入更平滑。

## 5. 暂停时的音频

```gdscript
func _on_pause() -> void:
    get_tree().paused = true
    # UI 音效仍需响应 → 把 UI 播放器设为 PROCESS_MODE_ALWAYS
```

⚠ `get_tree().paused = true` 会停掉默认 process_mode 的节点。
UI 反馈音想要继续，播放器要设 `process_mode = PROCESS_MODE_ALWAYS`。

⚠ 用 bus_mute 暂停音频，不等于暂停播放节点——
恢复后声音会从"中间"继续，不是重新同步。

## 6. 文件格式

| 格式 | 取舍 |
|---|---|
| **WAV** | 无压缩、无延迟、体积大。**短音效用它** |
| **OGG** | 有压缩、体积小、需解码。**BGM 与长音用它** |
| **MP3** | 许可与循环点不友好，一般不选 |

⚠ **循环 BGM 用 OGG 要注意循环点**。
MP3 因编码特性几乎无法无缝循环。

⚠ 短音效（枪声、脚步、UI）用 WAV——
OGG 的解码延迟会让密集触发的音效迟到。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/audio-advanced.md`


## 7. 相关文档

- 输入与基础音频 → `input-audio.md`
- 动画 → `animation-advanced.md`
- 性能 → `performance.md`
