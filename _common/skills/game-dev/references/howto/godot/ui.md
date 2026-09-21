# Godot 4.x UI 开发

菜单、HUD、背包、对话框。给完整实现。

## 1. 锚点：先理解约束模型

Godot 的 UI 定位不是"坐标"，而是**约束**：`anchor`（相对父容器的比例）
+ `offset`（像素偏移）+ `size`。容器会改写子项的这套约束。

```
Control 的四个边各有 anchor + offset：
  anchor_left = 0.5, offset_left = -50  →  左边在父容器 50% 处再往左 50px
```

**快捷方式**：Inspector 顶部的锚点预设按钮，或代码里：

```gdscript
# 居中
control.set_anchors_preset(Control.PRESET_CENTER)
# 铺满父容器
control.set_anchors_preset(Control.PRESET_FULL_RECT)
# 右下角
control.set_anchors_preset(Control.PRESET_BOTTOM_RIGHT)
```

⚠ **在容器（HBox/VBox/Grid）里的子项，锚点设置会被容器覆盖**。
容器内的排列用 `size_flags` 和 `custom_minimum_size` 控制，不是锚点。

## 2. HUD（血条 + 分数）

```gdscript
# hud.gd
extends CanvasLayer

@onready var _health_bar: ProgressBar = $MarginContainer/VBox/HealthBar
@onready var _score_label: Label = $MarginContainer/VBox/ScoreLabel
@onready var _hp_text: Label = $MarginContainer/VBox/HealthBar/HpText

var _displayed_score: int = 0

func _ready() -> void:
    Events.score_changed.connect(_on_score_changed)
    Events.player_health_changed.connect(_on_health_changed)

func _exit_tree() -> void:
    Events.score_changed.disconnect(_on_score_changed)
    Events.player_health_changed.disconnect(_on_health_changed)

func _on_score_changed(new_score: int) -> void:
    _displayed_score = new_score
    _score_label.text = "分数: %d" % new_score

func _on_health_changed(hp: int, max_hp: int) -> void:
    _health_bar.max_value = max_hp
    _health_bar.value = hp
    # ProgressBar 自带的 percent_visible 关掉，用自己的 Label 更可控
    _hp_text.text = "%d / %d" % [hp, max_hp]
```

**场景结构**：

```
HUD (CanvasLayer)
└── MarginContainer          ← 用它的 theme_override_constants/margin 留边
    └── VBoxContainer        ← 垂直排列
        ├── HealthBar (ProgressBar)
        │   └── HpText (Label)   ← 覆盖在血条上，anchors = FULL_RECT
        └── ScoreLabel (Label)
```

⚠ HUD 用 **CanvasLayer**，不要用 CanvasItem 直接挂在游戏场景里 ——
否则相机移动时 HUD 跟着跑。

### 分数滚动（数字动画）

```gdscript
var _target_score: int = 0
var _shown_score: int = 0

func _process(delta: float) -> void:
    if _shown_score != _target_score:
        _shown_score = move_toward(_shown_score, _target_score,
                                   maxi(1, int(abs(_target_score - _shown_score) * delta * 8)))
        _score_label.text = "分数: %d" % _shown_score
```

⚠ 不要每帧无条件给 `Label.text` 赋值 —— Godot 的 Label **没有**类似
Cocos `cacheMode` 的缓存开关，每次赋值都触发重排。只在值变化时赋值。

## 3. 主菜单

```gdscript
# main_menu.gd
extends Control

@onready var _start_btn: Button = $VBox/StartButton
@onready var _options_btn: Button = $VBox/OptionsButton
@onready var _quit_btn: Button = $VBox/QuitButton
@onready var _options_panel: Panel = $OptionsPanel

func _ready() -> void:
    _start_btn.pressed.connect(_on_start)
    _options_btn.pressed.connect(_on_options)
    _quit_btn.pressed.connect(_on_quit)
    _options_panel.visible = false
    # 键盘/手柄导航：给第一个按钮焦点
    _start_btn.grab_focus()

func _on_start() -> void:
    # 用 SceneManager 带过场切换
    SceneManager.goto_scene("res://scenes/level1.tscn")

func _on_options() -> void:
    _options_panel.visible = not _options_panel.visible
    if _options_panel.visible:
        _options_panel.get_node("VBox/BackButton").grab_focus()
    else:
        _options_btn.grab_focus()

func _on_quit() -> void:
    get_tree().quit()
```

**键盘/手柄导航**：设 `focus_neighbor_*` 或让容器自动推断。
按钮的 `focus_mode` 默认是 `FOCUS_ALL`，能用 Tab 到。

⚠ **导出到主机/移动端要处理"没有鼠标"的情况** —— 菜单必须有默认焦点
（`grab_focus()`），否则手柄玩家没法操作。

## 4. 背包 / 物品格

```gdscript
# inventory_ui.gd
extends Control

const SLOT_SCENE := preload("res://ui/item_slot.tscn")

@export var columns: int = 5
@export var slot_size: Vector2 = Vector2(64, 64)

@onready var _grid: GridContainer = $Panel/GridContainer

func _ready() -> void:
    _grid.columns = columns
    Events.inventory_changed.connect(_rebuild)

func _exit_tree() -> void:
    Events.inventory_changed.disconnect(_rebuild)

func _rebuild(items: Array[String]) -> void:
    # 先清干净：不 free 的话格子会越堆越多
    for child in _grid.get_children():
        child.queue_free()

    for item_id in items:
        var slot := SLOT_SCENE.instantiate()
        _grid.add_child(slot)
        slot.custom_minimum_size = slot_size
        slot.setup(item_id)
```

⚠ 重建列表时**必须 `queue_free()` 旧节点**，只 `remove_child()` 不会释放
（审查 GD01）。

⚠ 大量格子上限（>200）时 `queue_free` + `instantiate` 会卡。
这种情况改成固定数量的格子 + 复用（不改数量，只改内容）。

## 5. 对话框（打字机效果）

```gdscript
extends Control

@onready var _text: RichTextLabel = $Panel/RichTextLabel
@onready var _name_label: Label = $Panel/NameLabel

var _full_text: String = ""
var _char_index: int = 0
var _typing: bool = false

func show_dialog(speaker: String, content: String) -> void:
    _name_label.text = speaker
    _full_text = content
    _text.text = ""
    _char_index = 0
    _typing = true
    visible = true
    _type_next_char()

func _type_next_char() -> void:
    if _char_index >= _full_text.length():
        _typing = false
        return
    _text.append_text(_full_text[_char_index])
    _char_index += 1
    await get_tree().create_timer(0.03).timeout
    # await 期间节点可能已被释放（比如玩家跳过了对话）
    if not is_instance_valid(self):
        return
    _type_next_char()

func _unhandled_input(event: InputEvent) -> void:
    if not visible:
        return
    if event.is_action_pressed("ui_accept"):
        if _typing:
            # 跳过打字机，直接显示全部
            _text.text = _full_text
            _char_index = _full_text.length()
            _typing = false
        else:
            visible = false
        get_viewport().set_input_as_handled()
```

⚠ `await` 之后要判 `is_instance_valid(self)` —— 协程挂起期间节点可能
已被 `queue_free`（审查 GD75）。

⚠ 用 `RichTextLabel.append_text()` 而不是 `text +=` —— 后者每帧重建整个文本，
长文本会明显卡。

## 6. 分辨率自适应

⚠ **4.7 起新建项目的 stretch 默认值变了**：

| 设置 | 4.6 及更早 | 4.7 新项目 |
|---|---|---|
| `display/window/stretch/mode` | `disabled` | **`canvas_items`** |
| `display/window/stretch/aspect` | `keep` | **`expand`** |

已有项目设置不受影响，但**新建项目默认就会缩放 UI** ——
照 4.6 的写法做适配会出现"为什么我的 UI 被拉伸了"。

### 4.7+：容器里的 UI 动画用 offset_transform

⚠ 在 `Container` 下给 Control 做旋转/缩放，容器一排序就把改动覆盖掉。
4.7 给了独立于布局系统的 `offset_transform_*`（详见 `version-47-48.md`）：

```gdscript
button.offset_transform_enabled = true
button.offset_transform_pivot_ratio = Vector2(0.5, 0.5)
var tween := create_tween()
tween.tween_property(button, "offset_transform_rotation", 0.0, 0.5).from(-PI / 2)
```

⚠ `offset_transform_visual_only` 默认 **true**（仅视觉，不影响点击区域）——
这是刻意的，按钮动画后不会失去 hover。

**项目设置**：

```
display/window/stretch/mode      = canvas_items
display/window/stretch/aspect    = expand
display/window/size/window_width  = 1280
display/window/size/window_height = 720
```

- `canvas_items`：按逻辑分辨率渲染再缩放，UI 布局稳定（**2D 像素游戏用这个**）
- `expand`：窗口比例不同时扩展可视区域（不裁切、不变形）

⚠ 用 `expand` 时，UI 元素必须靠**锚点**定位，不能写死像素坐标 ——
否则宽屏下 HUD 会跑到屏幕外。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/ui.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-01`　状态机优于 if 嵌套
【读】 `common/howto/principles.md#GC-02`　频繁生成/销毁要池化
【读】 `common/howto/principles.md#GC-04`　事件解耦 vs 直接引用
【读】 `common/howto/principles.md#GC-05`　缓存必须有失效路径
【读】 `common/howto/principles.md#GC-06`　性能：先定位再优化
