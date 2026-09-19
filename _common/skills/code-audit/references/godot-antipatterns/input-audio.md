<!-- oversize-exempt: 反模式清单，审核用 -->
# input-audio — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于审核完成效果、约束边界。
> 「怎么做」看开发侧：`game-dev/references/godot/input-audio.md`

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
