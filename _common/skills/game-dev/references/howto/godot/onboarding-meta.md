# 新手引导与元系统

上线必备，但很容易做一半就埋坑。本文讲**引导、成就、排行榜、统计、Mod**。

## 0. 引导的类型与边界

| 类型 | 适合 |
|---|---|
| 强制线性 | 核心操作必须教会 |
| 情境触发 | 首次遇到才教 |
| 可跳过 | 给熟练玩家 |
| 渐进式解锁 | 功能逐步开放 |

⚠ **什么时候不该做引导**：核心操作本身够直觉时。
强行引导反而让玩家反感——配合埋点看流失率决定（见 `analytics.md`）。

## 1. 引导步骤：数据驱动

```gdscript
# tutorial_step.gd
class_name TutorialStep
extends Resource

@export var step_id: StringName = &""
@export var text: String = ""
@export var target_path: NodePath
@export var highlight_target: bool = true
@export var wait_for: StringName = &"click"   # click / signal / timer
@export var wait_signal: StringName = &""
@export var timeout: float = 0.0               # 0 = 不超时
```

⚠ **每一步都要能定义"怎么算完成"**：
等玩家真的点了、等某个信号、或超时自动过。

## 2. 高亮遮罩：真正"挖洞"

⚠ **引导最难看的问题**：遮罩压住目标、点击穿透、洞口有半透明描边。

不依赖 shader 的做法：**九宫格挖洞**——四个暗色矩形围住目标。

```gdscript
# tutorial_overlay.gd
class_name TutorialOverlay
extends Control

@export var dim_color := Color(0, 0, 0, 0.72)
@export var hole_padding := Vector2(10, 10)

var _target: Control = null

func _ready() -> void:
    set_anchors_preset(Control.PRESET_FULL_RECT)
    mouse_filter = Control.MOUSE_FILTER_STOP   # ⚠ 吃掉所有点击
    visible = false

func _draw() -> void:
    if not _target or not visible:
        return
    var r := _target.get_global_rect().grow(hole_padding.x)
    var full := get_global_rect()
    # 上下左右四块，围出中间的洞
    draw_rect(Rect2(full.position, Vector2(full.size.x, r.position.y - full.position.y)), dim_color)
    draw_rect(Rect2(Vector2(full.position.x, r.end.y), Vector2(full.size.x, full.end.y - r.end.y)), dim_color)
    draw_rect(Rect2(Vector2(full.position.x, r.position.y), Vector2(r.position.x - full.position.x, r.size.y)), dim_color)
    draw_rect(Rect2(Vector2(r.end.x, r.position.y), Vector2(full.end.x - r.end.x, r.size.y)), dim_color)
```

⚠ 遮罩 `mouse_filter = MOUSE_FILTER_STOP` 吃掉所有点击，
只允许目标可点——这样就不会有"点错地方推进了引导"。

## 3. 引导存档与埋点

⚠ **中途退出要能续**：引导进度存进存档，新玩家/老玩家走不同分支。

⚠ **每一步都要埋点**（`tutorial_step{step_id, status}`）——
引导流失率是最值得看的数据之一，能直接告诉你哪一步设计得不好。

⚠ **最严重的问题是引导卡死**：玩家没按预期操作 → 引导永久卡住。
**每一步都要有超时兜底或"跳过引导"出口。**

## 4. 成就系统：定义 + 状态分离

```gdscript
# achievement_definition.gd
class_name AchievementDefinition
extends Resource

@export var id: StringName = &""
@export var title: String = ""
@export var description: String = ""
@export var hidden: bool = false
@export var target_progress: int = 1
@export var platform_id: StringName = &""      # Steam/Epic 对应 ID
```

| 类型 | 说明 |
|---|---|
| 一次性 | `target_progress = 1` |
| 进度型 | 累计（击杀 100 次） |
| 隐藏 | 解锁前不显示描述 |

⚠ **定义（Resource）与运行时状态（存档）分开存** ——
否则策划改了目标值，旧存档会覆盖新定义。

⚠ **解锁检测用事件驱动**，不要轮询。
⚠ **平台成就**（Steam/Epic）：Godot 核心**没有内置**，
需要插件（GodotSteam 等），维护状态与版本兼容要现查（见 `plugins.md`）。

ⓘ 本节是**摘要**。完整做法（进度模型、解锁事务、幂等、隐藏成就、平台对接、backfill）
见 `achievement.md`，流程见 `flow/godot/achievement/`。

## 5. 排行榜

- **本地排行榜**：存存档里，简单
- **在线排行榜**：需要后端

⚠ **客户端上报的分数不可信** ——
排行榜特有的防作弊考量见 `security.md`。

⚠ 周榜/好友榜需要后端支持，不是客户端能做的事。

## 6. 游戏内统计

⚠ **与数据分析埋点的区别**：
统计是**给玩家看的**（总游戏时长、总击杀数），
埋点是**给开发者看的**。两者不是一回事，别混用。

⚠ **不要每次都写盘** —— 高频变化的统计要节流，定期落盘。

## 7. Mod 支持

Godot 支持通过 **`ProjectSettings.load_resource_pack()`** 加载 pck。

```gdscript
ProjectSettings.load_resource_pack("user://mods/my_mod.pck")
```

⚠ **Mod 是任意代码** —— 加载第三方 pck 等于执行其脚本，
安全风险由你自己承担。

⚠ 加载顺序与覆盖规则要明确（后加载的覆盖先加载的）。

⚠ **值得做吗？** 务实判断：
除非你的核心卖点就是 UGC，否则 Mod 支持的投入产出比不高，
且会显著增加测试与安全负担。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/onboarding-meta.md`


## 8. 相关文档

- 埋点（开发者视角的数据）→ `analytics.md`
- 存档 → `security.md`
- 对话系统 → `game-systems.md`
- UI → `ui.md`
- 插件与版本锁 → `plugins.md`
- 成就平台对接 → `cicd-publish.md`
