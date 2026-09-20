# 时间操控：慢动作、暂停、倒带、本地时间倍率（Godot 4.7.2）

"慢动作""子弹时间""时间操控""倒带" 此前 **全部 0 命中**。

## 0. ⚠ 时间不是单一旋钮，是至少五层

| 层 | 受 `Engine.time_scale` 影响？ |
|---|---|
| `_process` / `_physics_process` 的 `delta` | ✅ |
| `Timer` / `SceneTreeTimer` | ✅（要 `ignore_time_scale` 才不受） |
| `Tween` / `AnimationPlayer` | ⚠ 传统上没有忽略开关，**4.7 才新增 `Tween.set_ignore_time_scale()`** |
| **音频播放** | ❌ **官方明确不受影响** |
| 物理服务器 | ⚠ 不自动提高 `physics_ticks_per_second` |

⚠ **把 `time_scale` 当成"万能子弹时间"是最容易把动作游戏改坏的做法。**

官方表述：`Engine.time_scale` 影响 Timer、SceneTreeTimer 及所有使用 delta 的
模拟；建议保持 > `0.0`；**不自动调整 `physics_ticks_per_second`**。

音频要用 `AudioServer.playback_speed_scale` 或 Bus 的 PitchShift 单独处理。

## 1. 暂停不是"一切停止"

⚠ `get_tree().paused = true` **不是"世界停止并忽略输入"**：

- 默认停止 2D/3D 物理
- 按 `process_mode` 开关节点
- `_process` / `_physics_process` / `_input` / `_input_event` 会停
- ⚠ **但信号仍可触发**

### 四种 `process_mode`（官方确认）

| 值 | 含义 |
|---|---|
| `INHERIT = 0` | 继承父级 |
| `PAUSABLE = 1` | 未暂停时处理 |
| `WHEN_PAUSED = 2` | 暂停时处理 |
| `ALWAYS = 3` | 始终处理 |
| `DISABLED = 4` | 完全不处理 |

⚠ **UI 动画有两件事要分清楚，不要混为一谈**：

- `process_mode` 决定**节点是否处理**
- `Tween.set_ignore_time_scale()` 决定 **Tween 的时间基**

**两者正交。** 给 UI 节点设 `PROCESS_MODE_ALWAYS` 就以为动画安全是错的 ——
菜单/按钮/HUD 数字在子弹时间里还是会变"黏"。
正确做法是 UI 工厂函数统一返回已 `set_ignore_time_scale(true)` 的 Tween。

## 2. 暂停 vs 慢放要分开

- **暂停** = 冻结
- **time_scale** = 慢放

⚠ 混用会出奇怪行为。

## 3. 子弹时间

- ⚠ **恢复必须"必然发生"** —— 任何路径都不能漏掉恢复，
  否则游戏永久慢动作
- 平滑过渡（瞬间切很突兀，用 Tween 过渡缩放值）
- ⚠ **玩家自身要不要也慢**：经典做法是玩家保持原速、世界变慢，手感最好
- 输入缓冲要不要跟着缩放，要明确

## 4. ⚠ 倒带：快照回放，不是物理倒流

两种路线：**状态快照回放** vs **输入重放**。
单机时间回溯应选**前者**。

⚠ 倒带要**保存完整快照并冻结模拟，而不是让物理反向运行**。

- 环形缓冲区（固定容量，满了覆盖最旧）
- ⚠ **倒带期间物理要禁用**，否则会重新模拟
- ⚠ 存什么：位置/旋转/速度/动画进度/状态标志 —— **漏一个就不同步**
- ⚠ 内存：每秒 60 帧 × N 实体 × 每帧数据量
- ⚠ **倒带与网络**：一般只能倒自己，不能倒别人的世界
- ⚠ **倒带结束的交接**：回到当前时刻时状态怎么对齐

## 5. 本地时间倍率

让单个物体有自己的倍率（如被减速的敌人）。

⚠ **物理物体不能简单缩放 delta** —— 要缩放施加的力/速度。

⚠ 与全局 `time_scale` 是**叠加**关系。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/timescale.md`


## 6. 待核对项（运行时验证）

⚠ 待核对：`Tween.set_ignore_time_scale()` 是否仅 4.7+ · 验证：4.6 或更早版本必须删除该调用或改写

⚠ 待核对：环形缓冲容量与内存占用 · 验证：按目标实体数与倒带时长压测

## 7. 相关文档

- 顿帧 hitstop → `vfx-feel.md`
- 死亡期间的输入锁 → `survival.md`
- Tween/Timer 生命周期 → `systems.md` / `animation-advanced.md`
- 音频总线与音高 → `input-audio.md`
- 物理 tick 与积分 → `physics.md`
- 网络同步 → `netsync-advanced.md`
- 调试与 time_scale 陷阱 → `diagnostics.md`
