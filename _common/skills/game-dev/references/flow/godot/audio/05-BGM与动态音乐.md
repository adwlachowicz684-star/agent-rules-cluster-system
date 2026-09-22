# 05 BGM 与动态音乐（音频域）

> **前置**：01 总线已建（Music 独立），02 播放已通
> **本步交付**：音乐切换平滑、状态变化有响应、循环点无缝
> **对应**：做法 `howto/godot/audio-advanced.md` `input-audio.md` · 审核 `audit/godot/audio-advanced.md`

## 0. 交付物定义

⚠ **4.3 之后，动态音乐不需要手写多个播放器了。**
引擎内建了三个专用 `AudioStream` 类型，
⛔ 手写"多个播放器各放一层"**无法保证层间完美同步**。

做完这一步，应该能**当场演示**：

1. 切换 BGM 是**淡入淡出**，不是硬切
2. ⚠ 淡出到 **-80 dB**，不是 0 dB
3. ⚠ 循环 BGM 是 **OGG**（不是 MP3），循环处无咔哒
4. 状态切换（探索→战斗）音乐有响应
5. 分层/自适应优先用 `AudioStreamSynchronized` / `Interactive`

**产出物**（下游按名字对接）：

```text
play_bgm(stream) / stop_bgm()  含 tween 淡入淡出
或 AudioStreamPlaylist / Synchronized / Interactive 资源
```

## 1. 前置检查清单

- [ ] Music 总线已独立
- [ ] ⚠ 已确认 BGM 文件格式（OGG）
- [ ] 已确认要不要动态音乐（很多项目一首 BGM 就够）
- [ ] ⚠ 已确认淡出目标是 -80 dB

## 2. 工序

### Step 1　交叉淡入：淡到 -80 不是 0　`[audio/05#S1]`

【读】`howto/godot/audio-advanced.md#4. 动态音乐`

【做】
```gdscript
func crossfade(to: AudioStream, time := 1.5) -> void:
    var t := create_tween()
    t.tween_method(_set_music_vol, 0.0, -80.0, time)   # ⚠ 淡到 -80
    t.tween_callback(func(): _swap_stream(to))
    t.tween_method(_set_music_vol, -80.0, 0.0, time)
```

⚠ **淡出到 `0 dB` 不是静音**。要淡到 **-80 dB**（或更低）。
⛔ 淡到 0 的结果是"切换瞬间音量变成最大然后爆响"。

⚠ 换曲前要 **kill 掉上一个 tween**，
否则两个 tween 同时改同一个音量，行为不可预测。

【产出】切歌平滑，无爆响

【判据】⚠ 切歌过程中**无突然变大声**

【审】`audit/godot/audio-advanced.md#6`（淡出到 0 → 要淡到 -80）

### Step 2　同一首别重开　`[audio/05#S2]`

【读】`howto/godot/input-audio.md#2. 音频` 的「BGM 管理器（含交叉淡入）」

【做】
```gdscript
if _bgm_player.stream == stream and _bgm_player.playing:
    return                          # 同一首，别重开
```

⚠ 场景切换时经常重复调 `play_bgm(同一首)`。
⛔ 不判断的话会从头开始——表现为"过个门 BGM 重头播"。

【产出】重复调用同一首不会重开

【判据】⚠ 连续调 3 次 `play_bgm(同一首)`，**音乐不中断**

【审】`audit/godot/audio-advanced.md#4`

### Step 3　⛔ MP3 不能做无缝循环　`[audio/05#S3]`

【读】`howto/godot/audio-advanced.md#6. 文件格式`

【做】⚠ **MP3 因编码特性几乎无法无缝循环**
（有 encoder delay，循环处会有咔哒声）。

ⓘ BGM 循环用 **OGG**。循环点仍要注意——
OGG 的循环点是导入时设定的，⛔ 不是自动对齐到节拍。

⚠ 若循环处有咔哒，先查是不是用了 MP3，再查循环点。

【产出】循环 BGM 是 OGG，循环点已确认

【判据】⚠ 听满 3 个循环，**接口处无咔哒**

【审】`audit/godot/audio-advanced.md#10`（MP3 能做无缝循环 BGM → 不能）

### Step 4　⚠ 4.3+ 用内置类型做动态音乐　`[audio/05#S4]`

【读】`howto/godot/audio-advanced.md#7. 自适应音乐（4.3+ 内置类型）`

【做】三选一（⛔ 不要手写多播放器）：

| 类型 | 用途 |
|---|---|
| `AudioStreamPlaylist` | 按序播放序列（intro → loop → outro），支持 bpm 对齐、shuffle、整表循环 |
| `AudioStreamSynchronized` | **完美同步**的多层混合，逐层调音量 |
| `AudioStreamInteractive` | 按触发切换片段（探索 → 战斗 → Boss），可配交叉淡入/淡出/立即切 |

```gdscript
# 分层：层间完美同步
var sync := AudioStreamSynchronized.new()
sync.stream_count = 3
sync.set_sync_stream(0, preload("res://audio/music/ambient_base.ogg"))
sync.set_sync_stream_volume(1, -80.0)    # ⚠ 静音是 -80 dB
$MusicPlayer.stream = sync
$MusicPlayer.play()

# 战斗开始淡入鼓层
var pb := $MusicPlayer.get_stream_playback() as AudioStreamPlaybackSynchronized
create_tween().tween_method(func(db): pb.set_stream_volume(1, db), -80.0, 0.0, 1.5)
```

⚠ `AudioStreamInteractive` 主要在 **Inspector 里配置**片段与切换规则，
代码只负责 `pb.switch_to_clip(idx)` 触发。

【产出】动态音乐用内置类型，无手写多播放器层

【判据】⚠ 分层音乐跑 5 分钟，**层间无漂移**（⛔ 不是逐渐错开）

【审】`audit/godot/audio-advanced.md#18`

### Step 5　Playlist 的 bpm 对齐　`[audio/05#S5]`

【读】`howto/godot/audio-advanced.md#7. 自适应音乐（4.3+ 内置类型）`

【做】⚠ `AudioStreamPlaylist.bpm` 用于让**切换落在节拍边界上**。

⛔ 不设 bpm 的话，intro 结束接 loop 的时机是"播完就接"，
可能切在小节中间——听感是"卡了一下"。

【产出】需要节拍对齐的 playlist 都设了 bpm

【判据】⚠ intro 接 loop 的瞬间，**听不出接缝**

【审】`audit/godot/audio-advanced.md#19`

### Step 6　音乐与游戏状态同步　`[audio/05#S6]`

【读】`howto/godot/audio-advanced.md#5. 暂停时的音频`

【做】⚠ 状态切换时要考虑：
- 暂停时音乐要不要停（通常停，或用低通滤波"闷"住）
- 场景切换时音乐要不要延续（通常延续，见 S2）
- ⛔ 用 `bus_mute` 代替暂停 → 恢复后从中间接，见 03 S4

⚠ 还有一个常见坑：**音乐播放器的 `process_mode`**。
暂停时若音乐播放器是默认模式，会被 `get_tree().paused` 停掉——
这通常是想要的，但要**明确**，⛔ 不是碰巧。

【产出】音乐在各状态下的行为已明确

【判据】⚠ 暂停/恢复/切场景，音乐表现**符合设计**（⛔ 不是碰巧对）

【审】`audit/godot/audio-advanced.md#8`

## 3. 参考实现

```gdscript
# 无动态音乐需求时，这个就够了
extends Node

const FADE_TIME := 1.0
const MUTE_DB := -80.0

var _bgm: AudioStreamPlayer
var _tween: Tween

func play_bgm(stream: AudioStream) -> void:
    if _bgm.stream == stream and _bgm.playing:
        return                                  # ⚠ 同一首别重开
    if _tween and _tween.is_valid():
        _tween.kill()                           # ⚠ 杀掉上一个，避免打架
    _tween = create_tween()
    if _bgm.playing:
        _tween.tween_property(_bgm, "volume_db", MUTE_DB, FADE_TIME / 2.0)
        _tween.tween_callback(func():
            _bgm.stream = stream
            _bgm.play())
    else:
        _bgm.stream = stream
        _bgm.play()
        _bgm.volume_db = MUTE_DB
    _tween.tween_property(_bgm, "volume_db", 0.0, FADE_TIME / 2.0)
```

⚠ 注意 `MUTE_DB = -80.0` 是**常量**——
把 -80 散写在各处，一定会有一处写成 0。

## 4. 验收清单

- [ ] 切歌是淡入淡出，无突然变大声
- [ ] 重复调同一首不重开
- [ ] 循环 3 次无咔哒（OGG）
- [ ] 动态音乐用内置类型，层间 5 分钟无漂移
- [ ] 需要节拍对齐的设了 bpm
- [ ] 暂停/切场景的音乐行为符合设计

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 切歌瞬间爆响 | 淡到 0 dB | S1 |
| 过个门 BGM 重头播 | 没判同一首 | S2 |
| 循环处咔哒 | 用了 MP3 | S3 |
| 分层跑久了错开 | 手写多播放器 | S4 |
| intro 接 loop 卡一下 | 没设 bpm | S5 |
| 暂停恢复音乐错位 | 用 bus_mute 暂停 | S6 |

## 6. 下一步

→ **06 空间音频**
→ **07 音频验收**

## 7　整体审核（功能点级收尾）

ⓘ 各 Step 的【审】是**步骤级即时检查**；本节是**功能点级复查**，两级都要走。

- [ ] 逐条过 `audit/godot/audio-advanced.md`，每条说出"我们是怎么避免的"
  - ⛔ 不能"应该没这个问题"
- [ ] 步骤级【审】列过的条目**再过一遍**
- [ ] ⚠ 实测参数已回填，⛔ 不留示例值
- [ ] 若属大功能 → ⚠ **还要集成验收**：各部件合格 ≠ 拼起来能用
