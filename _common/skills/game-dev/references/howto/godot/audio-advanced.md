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

⚠ **Master 上要挂限制器（Limiter）作为最后一道保险。**
大量音效叠加会超过 0 dBFS 导致**削波爆音**。
ⓘ 这不是"让声音更好听"的润色，是防止硬件/耳朵受损的保护；
没有它时，爆音只在"恰好多个音效同帧"时出现，很难复现。

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

### 多声部：池之外的另一条路

ⓘ 池解决"同一音效连点"，**多声部**解决"同一播放器同时发多个声"。
需要动态叠加（如和弦、连续脚步尾音）时用 `AudioStreamPolyphonic`：

```gdscript
var _poly := AudioStreamPolyphonic.new()
_poly.polyphony = 16          # ⚠ 属性名是 polyphony，不是 max_polyphony
```

⚠ **属性名是 `polyphony`**（默认 **32**，范围 **1–128**），
⛔ 写 `max_polyphony` 会直接报"该属性不存在"。

⚠ **`play_stream()` 在"正在播放的流数 == `polyphony`"时返回 `INVALID_ID`** ——
⛔ 不是"裁掉最旧的声音"，而是**本次新的被丢弃**。
这个区别决定排查方向：不是音量被抢，是这次压根没播。

ⓘ 完整说明（含返回的整数 ID 何时失效）见 `input-audio.md` 第 5 节。

### 池 + 随机音高

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

⚠ **4.3 之后优先用 `AudioStreamSynchronized`** —— 多播放器方案
**无法保证层间完美同步**（各自独立播放，长时间后会累积漂移）。见第 7 节。

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


## 7. 自适应音乐（4.3+ 内置类型）

⚠ **"分层音乐"在 4.3 之后不需要手写多个播放器了。**
4.3 引入了三个专用 `AudioStream` 类型，引擎内建支持自适应音乐。
⛔ 本文第 4 节"多个 `AudioStreamPlayer` 各放一层"是 4.2 及更早的做法，
新项目应优先用内置类型——多播放器方案**无法保证层间完美同步**。

| 类型 | 用途 |
|---|---|
| `AudioStreamPlaylist` | 按序播放序列（intro → loop → outro），支持 bpm 对齐、shuffle、整表循环 |
| `AudioStreamSynchronized` | **完美同步**的多层混合（base / drums / intense），逐层调音量 |
| `AudioStreamInteractive` | 按触发切换片段（探索 → 战斗 → Boss），可配交叉淡入/淡出/立即切 |

**Playlist（关卡音乐，intro 后接 loop）**：
```gdscript
var pl := AudioStreamPlaylist.new()
pl.stream_count = 2
pl.set_list_stream(0, preload("res://audio/music/boss_intro.ogg"))
pl.set_list_stream(1, preload("res://audio/music/boss_loop.ogg"))
pl.bpm = 120.0        # ⚠ bpm 用于让切换落在节拍边界上
pl.shuffle = false
pl.loop = true
$MusicPlayer.stream = pl
$MusicPlayer.play()
```

**Synchronized（分层，层间完美同步）**：
```gdscript
var sync := AudioStreamSynchronized.new()
sync.stream_count = 3
sync.set_sync_stream(0, preload("res://audio/music/ambient_base.ogg"))
sync.set_sync_stream(1, preload("res://audio/music/ambient_drums.ogg"))
sync.set_sync_stream(2, preload("res://audio/music/ambient_intense.ogg"))
sync.set_sync_stream_volume(0, 0.0)      # 底层全音量
sync.set_sync_stream_volume(1, -80.0)    # ⚠ 静音是 -80 dB，不是 0
sync.set_sync_stream_volume(2, -80.0)
$MusicPlayer.stream = sync
$MusicPlayer.play()

# 战斗开始时淡入鼓层
var pb := $MusicPlayer.get_stream_playback() as AudioStreamPlaybackSynchronized
var t := create_tween()
t.tween_method(func(db): pb.set_stream_volume(1, db), -80.0, 0.0, 1.5)
```

**Interactive（状态切换）**：
⚠ 主要在 **Inspector 里配置**（片段列表与切换规则），代码只负责触发：
```gdscript
var pb := $MusicPlayer.get_stream_playback() as AudioStreamPlaybackInteractive
pb.switch_to_clip(2)      # 切到第 2 个片段（如 combat）
```

## 8. 预注册样本与延迟尖峰

⚠ **首次播放一个 `AudioStream` 时引擎要先注册它，这会造成 lag spike。**

官方 API：`AudioServer.register_stream_as_sample(stream)` 强制预注册，
`AudioServer.is_stream_registered_as_sample(stream)` 查询状态。

⚠ **官方明确建议**：

> Lag spikes may occur when calling this method, especially on single-threaded builds.
> It is suggested to call this method **while loading assets, where the lag spike
> could be masked**, instead of registering the sample right before it needs to be played.

✅ 在**加载阶段**（过场、加载画面）批量注册密集音效，⛔ 不要在开火前一刻注册。
否则第一次开枪会卡顿，而之后就不卡了——极难排查。

```gdscript
# 加载阶段批量预注册
for stream in _combat_sfx:
    if not AudioServer.is_stream_registered_as_sample(stream):
        AudioServer.register_stream_as_sample(stream)
```

## 9. 全局播放速度（与 time_scale 无关）

```gdscript
AudioServer.playback_speed_scale = 0.5   # 音频放慢到一半
```

⚠ **官方文档明确：`playback_speed_scale` 与 `Engine.time_scale` 相互独立。**
改 `time_scale` 做慢动作时，**音频不会跟着变慢**，要单独设这个。

ⓘ 这也正是"子弹时间"里音频不同步的根因——
只改了 `time_scale` 就以为音频会跟着走。

ⓘ 相关 API：`AudioServer.get_output_latency()`（实际输出延迟，随系统与驱动不同）、
`AudioServer.get_time_to_next_mix()`（距下次混音的时间）。

## 10. headless 与总线 API 细节

⚠ **`--headless` 会自动把音频驱动设为 Dummy。**
官方原话：`--headless also automatically sets the audio driver to Dummy`。
ⓘ 专用服务器上音频调用不会崩，但也不会有声音——
⛔ 不要依赖"服务器没报错"来判断音频链路正常。

其他容易踩的 API 细节：

| API | 注意 |
|---|---|
| `AudioServer.get_bus_index(name)` | ⚠ **不存在时返回 -1**，用它前必须判 `-1` |
| `AudioServer.set_bus_volume_linear()` | 等价于 `set_bus_volume_db(linear_to_db(v))`，比手动转更不容易错 |
| `AudioServer.add_bus(at_position)` | 新增总线默认 send 到 Master，要显式 `set_bus_send` 才改 |
| `AudioServer.lock()/unlock()` | 锁音频主循环，⛔ 忘记 `unlock()` 会让整个音频线程停住 |
| `set_bus_solo()` | 调试用；⛔ 别把它当"只播放某类"的业务开关留在上线代码里 |

⚠ 混响 / 压缩 / EQ 这类效果**放在总线上**，不是每个音源各挂一个。
总线是混音链（见第 0 节），效果在链上是**共享的一份**，
挂在音源上则是 N 份实例——CPU 与听感都不对。

## 11. 相关文档

- 输入与基础音频 → `input-audio.md`
- 动画 → `animation-advanced.md`
- 性能 → `performance.md`
