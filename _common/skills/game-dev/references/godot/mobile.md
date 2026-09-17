# Godot 4.x 移动端触控与虚拟摇杆

面向手机/平板的输入与适配。大型项目建议**一开始就按移动端设计**，
后期再补会改到骨头。

## 0. 先决定输入架构

```
游戏要上移动端吗？
├─ 是 → 所有输入走 InputMap 动作，平台差异只在"输入源"层收敛
└─ 否 → 可以只做键鼠/手柄
```

**核心原则**：玩家代码只读动作（`move` / `fire` / `jump`），
不关心这个动作来自键盘、手柄、虚拟摇杆还是屏幕按键。
在角色代码里写 `if OS.get_name() == "Android"` 分支 = 后面必乱。

## 1. 触控事件

### 三个事件类

| 类 | 触发 | 关键属性 |
|---|---|---|
| `InputEventScreenTouch` | 按下 / 抬起 | `index` · `position` · `pressed` · `double_tap` |
| `InputEventScreenDrag` | 按住移动 | `index` · `position` · `relative` · `velocity` |
| `InputEventMagnifyGesture` | 系统识别的捏合 | `factor` |
| `InputEventPanGesture` | 系统识别的平移 | `delta` |

⚠ **Godot 4 没有 `InputEventScreenSwipe`** —— 从 3.x 教程/插件复制会直接报错。
点击、双击、长按、单指滑动都要自己算。

⚠ `index` 是"当前存活的触摸点编号"，**不是稳定的手指 ID**。
第一根手指抬起后，其余手指的 index 可能变。跨事件追踪要自己维护映射。

### `emulate_mouse_from_touch` 的坑

项目设置 `input_devices/pointing/emulate_mouse_from_touch` 开启后：

```
一次触摸 → 同时产生 InputEventScreenTouch 和 InputEventMouseButton
```

⚠ 这不是"把触摸转换成鼠标"，而是**再生成一份事件**。
两套都处理 = 动作触发两次（表现为"点一下开两枪"）。

**建议**：移动端项目关掉它，统一用 `InputEventScreenTouch/Drag` 处理游戏输入；
只在需要复用桌面端 UI 逻辑时才开，并在代码里去重。

```gdscript
func _unhandled_input(event: InputEvent) -> void:
    # 开了模拟时，鼠标事件带 device=-1 且可能是模拟出来的
    if event is InputEventMouseButton and event.device == -1:
        if _is_emulated(event):
            return          # 跳过模拟事件，只处理真实的
    ...
```

更简单的做法：**关掉模拟开关**，UI 用 Control（它本身就能响应触摸），
游戏世界用 ScreenTouch/Drag。

### 多点触控

```gdscript
var _touches := {}          # index → position

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            _touches[event.index] = event.position
        else:
            _touches.erase(event.index)
    elif event is InputEventScreenDrag:
        if _touches.has(event.index):
            _touches[event.index] = event.position
```

⚠ 用 `event.index` 做 key，但记住它会变 ——
需要"追踪同一根手指"的场景（如双指缩放），要额外记录起始位置。

## 2. 手势识别器

系统只给 Magnify / Pan，其余自己算。

```gdscript
# gesture_detector.gd
extends Node

signal tap(pos: Vector2)
signal double_tap(pos: Vector2)
signal long_press(pos: Vector2)
signal swipe(dir: Vector2, velocity: float)
signal pinch(scale_factor: float)

const TAP_MAX_DIST := 20.0
const TAP_MAX_TIME := 0.25
const DOUBLE_TAP_TIME := 0.3
const LONG_PRESS_TIME := 0.5
const SWIPE_MIN_DIST := 60.0

var _start_pos := Vector2.ZERO
var _start_time := 0.0
var _pressing := false
var _last_tap_time := -1.0
var _last_tap_pos := Vector2.ZERO
var _long_fired := false
var _pinch_dist := 0.0

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed:
            _on_down(event)
        else:
            _on_up(event)
    elif event is InputEventScreenDrag:
        _on_move(event)

func _on_down(e: InputEventScreenTouch) -> void:
    _start_pos = e.position
    _start_time = Time.get_ticks_msec() / 1000.0
    _pressing = true
    _long_fired = false
    _pinch_active_check()

func _on_move(e: InputEventScreenDrag) -> void:
    if _pressing and not _long_fired:
        if e.position.distance_to(_start_pos) > TAP_MAX_DIST:
            _pressing = false       # 移动超阈值，不算点击
    _update_pinch()

func _on_up(e: InputEventScreenTouch) -> void:
    if not _pressing:
        return
    _pressing = false
    var dist := e.position.distance_to(_start_pos)
    var dur := Time.get_ticks_msec() / 1000.0 - _start_time
    if dist > TAP_MAX_DIST or dur > LONG_PRESS_TIME:
        _check_swipe(e.position, dur)
        return
    # 算点击
    var now := Time.get_ticks_msec() / 1000.0
    if now - _last_tap_time < DOUBLE_TAP_TIME \
       and e.position.distance_to(_last_tap_pos) < TAP_MAX_DIST * 2:
        double_tap.emit(e.position)
        _last_tap_time = -1.0
    else:
        tap.emit(e.position)
        _last_tap_time = now
        _last_tap_pos = e.position

func _check_swipe(end: Vector2, dur: float) -> void:
    var d := end - _start_pos
    if d.length() < SWIPE_MIN_DIST:
        return
    swipe.emit(d.normalized(), d.length() / maxf(dur, 0.001))

## 双指缩放：记录两指间距
var _pointers := {}

func _pinch_active_check() -> void:
    _pointers.clear()

func _update_pinch() -> void:
    if _touches_of_interest() < 2:
        return
    var pts := []
    for idx in _pointers:
        pts.append(_pointers[idx])
    if pts.size() < 2:
        return
    var d := pts[0].distance_to(pts[1])
    if _pinch_dist > 0.0:
        pinch.emit(d / _pinch_dist)
    _pinch_dist = d

func _touches_of_interest() -> int:
    return _pointers.size()
```

**更简单可靠的双指缩放**：直接用系统 `InputEventMagnifyGesture`：

```gdscript
func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMagnifyGesture:
        _zoom *= event.factor
        _zoom = clampf(_zoom, 0.5, 3.0)
```

⚠ 系统手势与自己算的二选一，**别同时开**，否则缩放会叠加两次。

## 3. 虚拟摇杆

⚠ **Godot 4 没有内置虚拟摇杆节点**，`TouchScreenButton` 只能做按键
（它绑定单个 action，没有方向输出、没有死区）。摇杆要自己做。

### 浮动摇杆（推荐）

按下时底座出现在手指落点，拖动输出方向 —— 手感比固定位置好，也不挡视野。

```gdscript
# virtual_joystick.gd
class_name VirtualJoystick
extends Control

signal vector_changed(dir: Vector2)
signal released

@export var base_node: Control
@export var tip_node: Control
@export var clamp_radius: float = 72.0
@export var dead_zone: float = 0.18

var _pointer := -1
var _center := Vector2.ZERO
var _current := Vector2.ZERO

func _ready() -> void:
    mouse_filter = Control.MOUSE_FILTER_STOP
    if base_node:
        base_node.hide()

func _gui_input(event: InputEvent) -> void:
    if event is InputEventScreenTouch:
        if event.pressed and _pointer == -1 \
           and get_global_rect().has_point(event.position):
            _pointer = event.index
            _center = event.position
            if base_node:
                base_node.global_position = _center - base_node.size * 0.5
                base_node.show()
            _update(event.position)
            accept_event()                 # 别让事件穿透到下层
        elif not event.pressed and event.index == _pointer:
            _release()
    elif event is InputEventScreenDrag and event.index == _pointer:
        _update(event.position)

func _update(p: Vector2) -> void:
    var raw := p - _center
    # 摇杆头限制在圆内
    if tip_node:
        tip_node.position = raw.limit_length(clamp_radius)

    # 归一化 + 死区重映射（死区外从 0 开始，不会有跳变）
    var n := raw / clamp_radius
    if n.length() < dead_zone:
        n = Vector2.ZERO
    else:
        n = n.normalized() * clampf(
            (n.length() - dead_zone) / (1.0 - dead_zone), 0.0, 1.0)
    _current = n
    vector_changed.emit(n)

func _release() -> void:
    _pointer = -1
    _current = Vector2.ZERO
    if base_node:
        base_node.hide()
    vector_changed.emit(Vector2.ZERO)
    released.emit()

func get_axis() -> Vector2:
    return _current
```

**场景结构**：

```
UI (CanvasLayer)
├── LeftHalf (Control)          ← 锚点全屏，只覆盖左半边
│   └── VirtualJoystick         ← 挂上面脚本
│       ├── Base (TextureRect)  ← 底座
│       └── Tip  (TextureRect)  ← 摇杆头
└── RightHalf (Control)
    └── SkillButtons
```

**接到角色移动**：

```gdscript
@onready var _joystick: VirtualJoystick = $UI/LeftHalf/VirtualJoystick
@export var speed: float = 200.0

func _ready() -> void:
    _joystick.vector_changed.connect(_on_move)

func _exit_tree() -> void:
    if _joystick.vector_changed.is_connected(_on_move):
        _joystick.vector_changed.disconnect(_on_move)

func _on_move(dir: Vector2) -> void:
    _move_input = dir          # 只保存方向，乘速度在物理帧做

func _physics_process(_delta: float) -> void:
    # 键盘与摇杆取其一：键盘有输入时优先（方便调试）
    var kb := Input.get_vector("move_left", "move_right", "move_up", "move_down")
    var dir := kb if kb != Vector2.ZERO else _move_input
    velocity = dir * speed
    move_and_slide()
```

⚠ 摇杆的 `clamp_radius` / `dead_zone` 用**比例**而不是绝对像素 ——
不同 DPI 手机上固定像素手感完全不同。

⚠ 摇杆 Control 的 `mouse_filter` 必须 `STOP`，否则触摸会穿透到下面的游戏世界。

### 固定按键用 TouchScreenButton

跳跃、射击这类离散动作，用 `TouchScreenButton` 比自制省事：

| 属性 | 说明 |
|---|---|
| `action` | 绑定到 InputMap 动作，按下/释放自动触发 |
| `texture_normal` / `texture_pressed` | 两种状态的贴图 |
| `shape` | 判定形状（`CircleShape2D` / `RectangleShape2D`） |
| `bitmask` | 用贴图透明区域做判定（异形按钮） |
| `passby_press` | 手指滑入也算按下（**滑动瞄准时别开**，会误触） |
| `visibility_mode` | `VISIBILITY_ALWAYS` / `VISIBILITY_TOUCHSCREEN_ONLY` |

⚠ `TouchScreenButton` 继承 `Node2D`，**不能用锚点** —— 刘海屏适配要自己算位置。

## 4. 输入管理器（推荐架构）

把"触摸"翻译成"动作"，玩家代码不碰事件。

```gdscript
# mobile_input.gd —— Autoload
extends Node

signal move_axis(dir: Vector2)
signal fire_pressed
signal fire_released
signal zoom_changed(factor: float)

var _move := Vector2.ZERO
var _primary := -1
var _secondary := -1

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMagnifyGesture:
        zoom_changed.emit(event.factor)
    elif event is InputEventScreenTouch:
        _handle(event)
    elif event is InputEventScreenDrag and event.index == _primary:
        _update_move(event.position)

func _handle(e: InputEventScreenTouch) -> void:
    var vp := get_viewport().get_visible_rect()
    if e.pressed:
        if _primary == -1 and e.position.x < vp.size.x * 0.5:
            _primary = e.index
            _center = e.position
        elif _secondary == -1:
            _secondary = e.index
            fire_pressed.emit()
    else:
        if e.index == _secondary:
            _secondary = -1
            fire_released.emit()
        elif e.index == _primary:
            _primary = -1
            _move = Vector2.ZERO
            move_axis.emit(Vector2.ZERO)

var _center := Vector2.ZERO

func _update_move(pos: Vector2) -> void:
    var raw := pos - _center
    _move = raw.limit_length(80.0) / 80.0
    move_axis.emit(_move)
```

⚠ 这个管理器要和摇杆**二选一**。摇杆自己输出方向时，管理器就别再做左半屏判定。

## 5. 屏幕适配

### 安全区（刘海屏）

```gdscript
func _ready() -> void:
    _apply_safe_area()
    get_viewport().size_changed.connect(_apply_safe_area)

func _exit_tree() -> void:
    if get_viewport().size_changed.is_connected(_apply_safe_area):
        get_viewport().size_changed.disconnect(_apply_safe_area)

func _apply_safe_area() -> void:
    var area := DisplayServer.get_display_safe_area()
    var scale := get_viewport().get_screen_transform().affine_inverse()
    var p := scale * Vector2(area.position)
    var s := scale * Vector2(area.size)
    # 顶部/底部留出安全边距
    _ui_root.offset_top = p.y
    _ui_root.offset_bottom = -(_screen_h - p.y - s.y)
```

⚠ `get_display_safe_area()` 返回的是**屏幕坐标**，不是项目 Content 坐标，
有拉伸设置（`canvas_items` / `viewport`）时必须转换。

⚠ 它只在 Android / iOS 真实实现，其它平台回退成 `screen_get_usable_rect()`。
`get_display_cutouts()` **仅 Android 实现**，别在 iOS 上依赖。

### 方向与分辨率

| 项目设置 | 值 |
|---|---|
| `display/window/handheld/orientation` | `Landscape` / `Portrait` / `SensorLandscape` 等 |
| `display/window/stretch/mode` | 2D 非像素风用 `canvas_items`；像素风用 `viewport` |
| `display/window/stretch/aspect` | `expand`（不裁切） |
| `display/window/energy_saving/keep_screen_on` | 防息屏 |
| `display/window/ios/hide_home_indicator` | 隐藏 Home 指示条 |

⚠ 选竖屏**不会自动交换** `viewport_width` / `viewport_height` —— 要自己改基础宽高。

⚠ 别把 `screen_get_dpi()` 当 UI 坐标乘数。它只适合决定最小字号、触摸热区大小、画质档位。

### 软键盘

```gdscript
DisplayServer.virtual_keyboard_show("", input_rect,
    DisplayServer.KEYBOARD_TYPE_NUMBER)
var h := DisplayServer.virtual_keyboard_get_height()
DisplayServer.virtual_keyboard_hide()
```

⚠ 没有统一的"键盘高度变化"信号。自定义输入框要在弹出后轮询 `get_height()` 调整布局。
`LineEdit` / `TextEdit` 会自动处理，自己做输入框才需要管。

## 6. 返回键（Android）

⚠ 返回键**不是** InputMap 动作，是窗口通知。不处理会直接退出游戏。

```gdscript
func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_GO_BACK_REQUEST:
        if _can_go_back():
            get_viewport().set_input_as_handled()   # 消费掉，别退出
            _go_back()

func _can_go_back() -> bool:
    return _popup.visible or _current_screen != "main"

func _go_back() -> void:
    if _popup.visible:
        _popup.hide()
    else:
        _goto_main()
```

⚠ 忘了 `set_input_as_handled()` 的话，即使处理了也会退出。

## 7. 权限

**三件事各自独立**：导出预设里声明 → 运行时请求 → 等回调。

```gdscript
func _ready() -> void:
    if OS.get_name() == "Android":
        var granted := OS.get_granted_permissions()
        if not granted.has("android.permission.RECORD_AUDIO"):
            OS.request_permissions()
            OS.permissions_granted.connect(_on_perm)

func _on_perm(perms: PackedStringArray) -> void:
    print_debug("已授权: %s" % perms)
```

⚠ **不要假设 `_ready` 后权限已授予** —— 请求是异步的。
启动时就要用的功能要么延后，要么先判权限再启用。

## 8. 移动端性能

| 项 | 建议 |
|---|---|
| 渲染后端 | 中低端 Android 用 `gl_compatibility`；有独显需求用 `mobile` |
| 过度绘制 | 半透明叠加层数控制在 3 层以内 |
| 阴影 | 移动端尽量只用 1 个方向光投影 |
| 粒子 | 数量减半，`fixed_fps` 限制更新率 |
| DrawCall | 共享材质、用图集 |
| 帧率 | `Engine.max_fps` 配合 vsync；主要是省电不是提帧 |

⚠ `Engine.max_fps` **不能突破刷新率上限**（vsync 开启时 vsync 优先）。
它主要用于省电和稳定延迟。

⚠ 桌面端 60fps 不代表移动端能跑。**至少在一台低端 Android 上跑 20 分钟**，
看发热、掉帧、内存。

## 常见漏写

| 漏写 | 后果 |
|---|---|
| 开了 `emulate_mouse_from_touch` 又处理两套事件 | 动作触发两次 |
| 用 `InputEventScreenSwipe` | 4.x 不存在，直接报错 |
| 摇杆用绝对像素半径 | 不同 DPI 手感差异巨大 |
| 摇杆 Control 的 `mouse_filter` 不是 STOP | 触摸穿透到游戏世界 |
| 返回键未 `set_input_as_handled()` | 处理了还是退出 |
| 权限请求后立刻使用 | 异步未返回，功能失败 |
| 安全区未从屏幕坐标转换 | 有拉伸时边距全错 |
| `get_display_cutouts()` 用在 iOS | 仅 Android 实现 |
| 玩家代码里分平台写输入 | 后续维护灾难 |
| 未在低端机实测 | 上线后大量掉帧投诉 |
