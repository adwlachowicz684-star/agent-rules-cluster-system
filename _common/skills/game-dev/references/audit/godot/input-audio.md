<!-- oversize-exempt: 反模式清单，审核用 -->
# input-audio — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/input-audio.md`

## 常见漏写

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | `new AudioStreamPlayer` 未 `queue_free` | 节点累积（P0） | GD52 |
| 2 | `_process` 里 `is_action_just_pressed` | 掉帧漏输入 | GD51 |
| 3 | 游戏逻辑放 `_input` | 点 UI 时同时触发游戏动作 | 人工 |
| 4 | 音量直接把线性值当 dB | 音量曲线不对 | 人工 |
| 5 | `get_vector()` 后又 `normalized()` | 多余（它已归一化），且零向量会 NaN | 人工 |
| 6 | 硬编码 `KEY_SPACE` | 玩家无法改键，手柄不通用 | 人工 |
| 7 | MP3 做循环 BGM | 循环点咔哒声 | 人工 |
| 8 | `panning_strength` 调很大 | 声音**完全跑到一侧耳朵**，戴耳机时听感突兀；默认通常是合理起点 |
| 9 | 2D 空间音效用全局坐标当局部坐标 | 位置错、声像错；要按父节点变换换算 |
