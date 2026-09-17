<!-- oversize-exempt: 引擎 API 查表文档，按 API 索引，需整体查阅 -->
# Godot 4.x 输入、音频、动画、Tween 与 Timer API 静态审查规则

## 摘要

这份文档以 Godot 4.4 稳定版官方类文档和教程为核心依据，把语言包审查目标收敛为 100 余条 API 级判据，而不是泛泛的“最佳实践”清单。输入域最关键的反直觉点是：`_input`、`Control._gui_input`、`_shortcut_input`、`_unhandled_key_input`、`_unhandled_input` 有固定传播顺序；GUI 已消费后 `_unhandled_input` 不会触发，且只有显式调用 `Viewport.set_input_as_handled()` 或 `Control.accept_event()` 才会阻断后续传播[1]。`Input.is_action_just_pressed()` 等“即时”状态轮询适合放在 `_input`/`_unhandled_input` 或固定步逻辑中；若放在可变步 `_process`，在高帧率、低帧率、逐帧跳过或重复输入处理中都可能漏掉或重复处理，但这属于语义风险，不能仅凭单条调用判死。[1]

音频域的核心风险是资源与节点生命周期：`AudioStreamPlayer.finished` 只在流正常播完时发出；动态 `new()` 后 `add_child()` 的播放器若未连接 `finished`、未设置 `one_shot` 式释放，也未手动 `queue_free()`，会残留于场景树[4]。`AudioStreamPlayer3D.max_polyphony` 超过限制时会静默裁掉最旧声音，而不是报错[5]。动画域的可静态检查高风险项是 `AnimationTree.set("parameters/...")`，错误路径在运行时可能只表现为不生效或异常，同时 `Animation` 方法轨会把目标方法名硬编码进资源，脚本重构无法自动同步[9][10]。Tween 域必须把 `Node.create_tween()`、`SceneTree.create_tween()` 与 `bind_node()` 视为不同生命周期语义；`SceneTree.create_tween()` 默认不绑定节点，节点释放后仍可能继续运行[12][13]。Timer 域应把不可重启动的 `SceneTreeTimer` 与可重启动的 `Timer` 节点分开：`await get_tree().create_timer(x).timeout` 没有 `start()`/`stop()`，且没有保存强引用时不保证后续还能控制它[14][16]。

## 1. 输入系统

### 输入审查应以“事件源、传播阶段、即时查询”三层建立规则

**输入错误通常不是 API 写错，而是把事件传播、UI 焦点和每帧轮询混在同一判断里。** 规则库应先识别代码使用的是事件回调、动作轮询还是原始键鼠查询，再检查其所在函数与对象生命周期。同一个 `Input.is_action_just_pressed()` 出现在 `_unhandled_input` 里可能完全正确，出现在逐帧跳过处理的 `_process` 中则存在丢失窗口；仅匹配方法名无法区分。

Godot 的输入流程先进入普通 `Node._input()`，再尝试喂给 GUI；GUI 消费前还会调用 `_shortcut_input()`，随后才是 `_unhandled_key_input()` 和 `_unhandled_input()`[1]。这意味着“全局游戏输入”不天然优先于 UI：如果前面的 Control 消费了事件，后续 `_unhandled_input()` 就不会再收到。相反，若代码只监听 `_input()`，也会截获本应由按钮、输入框或其他 Control 处理的事件。

### `Input.is_action_pressed()`

- **签名**：`float Input.is_action_pressed(action: StringName, exact_match: bool = false)` / `float Input.IsActionPressed(StringName action, bool exact_match = false)`
- **用途**：查询动作当前是否处于按下状态，适合连续移动、加速、瞄准。
- **误用**：在 `_process` 里用其边沿语义；`exact_match=false` 时把组合设备事件当作精确匹配；动作名拼写错误或尚未在 InputMap 中定义。
- **判据（源码特征）**：正则 `(?:^|[^.\w])Input\s*\.\s*is_action_pressed\s*\(`；参数应为 `StringName`/带引号的动作名；注意 GDScript 还允许 `is_action_pressed(action, exact_match)`。
- **确认**：在编辑器输入映射中核对动作名；调用前后打印状态并覆盖不同设备和组合键；`exact_match` 需根据“任意匹配”或“精确匹配”的审查意图复核。
- **置信度**：官方明确。

### `Input.is_action_just_pressed()`

- **签名**：`bool Input.is_action_just_pressed(action: StringName, echo: bool = false)` / `bool Input.IsActionJustPressed(StringName action, bool echo = false)`
- **用途**：检测动作在本轮输入处理中刚被按下；`echo=false` 时忽略长按回显。
- **误用**：在可变步 `_process(delta)` 中使用，若某帧跳过处理、帧率波动或事件已被上层消费，可能出现“按了键却未响应”的漏检；把 `echo=false` 的默认行为当成所有重复按键都会触发。
- **判据（源码特征）**：匹配 `Input\s*\.\s*is_action_just_pressed\s*\(`；若其直系调用上下文是 `_process\s*\([^)]*\)`，发出“边沿输入在可变步轮询”提示；这不是硬性错误。
- **确认**：把相同逻辑改为 `_unhandled_input(event)` 配合 `event.is_action_pressed(action)`，或在固定时间步逻辑中使用；用按键重复测试默认 `echo` 值。
- **置信度**：官方明确；静态上下文分类为工程判断。

### `Input.is_action_just_released()`

- **签名**：`bool Input.is_action_just_released(action: StringName)` / `bool Input.IsActionJustReleased(StringName action)`
- **用途**：检测动作本轮刚被释放。
- **误用**：与 `just_pressed` 共用时重复处理；在 `_process` 中的漏帧窗口同样存在；误以为它能恢复物理状态或自动释放资源。
- **判据（源码特征）**：`Input\s*\.\s*is_action_just_released\s*\(`。
- **确认**：构造“按下—多帧—释放”测试用例；在同一回调中检查是否存在重复的 pressed/released 状态机迁移。
- **置信度**：官方明确。

### `Input.get_action_strength()`

- **签名**：`float Input.get_action_strength(action: StringName, exact_match: bool = false)` / `float Input.GetActionStrength(StringName action, bool exact_match = false)`
- **用途**：取得标准化后的动作强度，常用于模拟量输入。
- **误用**：把返回值当布尔；认为其天然具有死区；在 Deadzone 不一致的输入映射上直接相加不同动作。
- **判据（源码特征）**：`Input\s*\.\s*get_action_strength\s*\(`。
- **确认**：摇杆居中/偏移、键盘双键同时按、不同死区配置下打印返回值；审查 InputMap 动作的 `deadzone`。
- **置信度**：官方明确。

### `Input.get_axis()`

- **签名**：`float Input.get_axis(negative_action: StringName, positive_action: StringName)` / `float Input.GetAxis(StringName negativeAction, StringName positiveAction)`
- **用途**：以 `正动作强度 - 负动作强度` 得到一维轴值。
- **误用**：两个动作名称顺序颠倒；输入映射中同时配置正/负造成超过预期的符号；与 `get_action_strength()` 自行相减实现时死区处理不一致。
- **判据（源码特征）**：`Input\s*\.\s*get_axis\s*\(`。
- **确认**：检查调用中的动作顺序、对应 InputMap 的死区和方向约定；做全行程测试。
- **置信度**：官方明确。

### `Input.get_vector()`

- **签名**：`Vector2 Input.get_vector(negative_x: StringName, positive_x: StringName, negative_y: StringName, positive_y: StringName, deadzone: float = -1.0)` / `Vector2 Input.GetVector(StringName negativeX, StringName positiveX, StringName negativeY, StringName positiveY, float deadzone = -1.0)`
- **用途**：返回长度裁剪至 1 的输入向量，适合二维移动。
- **误用**：把返回值直接当作“物理速度”，忽略最大速度缩放；`deadzone=-1.0` 时实际采用输入映射默认死区；与未规范化向量比较导致斜向速度不一致。
- **判据（源码特征）**：`Input\s*\.\s*get_vector\s*\(`。
- **确认**：检查四动作顺序、死区参数及下游是否再乘速度；斜向摇杆行程是否超过设计上限。
- **置信度**：官方明确。

### `Input.is_key_pressed()`

- **签名**：`bool Input.is_key_pressed(key: Key) const` / `bool Input.IsKeyPressed(Key key)`
- **用途**：按逻辑键码查询键盘物理按键，不依赖动作映射。
- **误用**：在不同键盘布局或远程桌面环境中把 `keycode` 当稳定物理位置；与 `is_action_pressed()` 混用导致按键与动作语义冲突；硬编码 ASCII 键名却未使用 `KEY_*` 常量。
- **判据（源码特征）**：`Input\s*\.\s*is_key_pressed\s*\(`。
- **确认**：跨布局、跨平台测试；检查键常量来自 `Key` 枚举；审查是否存在同名 `InputEventKey.keycode` 与全局方法混淆。
- **置信度**：官方明确。

### `Input.is_key_label_pressed()`

- **签名**：`bool Input.is_key_label_pressed(label: Key) const` / `bool Input.IsKeyLabelPressed(Key label)`
- **用途**：按当前键盘布局下的键标签查询按键，是 4.x 中处理“用户所见字符/位置”的接口。
- **误用**：把它与 `is_key_pressed()` 视为完全等价；在需要固定物理位置时错误使用键标签；把 `Key` 整数与字符、动作名混传。
- **判据（源码特征）**：`Input\s*\.\s*is_key_label_pressed\s*\(`。
- **确认**：切换键盘布局测试；对物理位置固定操作改用 `physical_keycode`/`is_key_pressed()`，对输入法相关或布局相关操作使用标签查询。
- **置信度**：官方明确；选择键码还是键标签属于设计判断。

### `Input.is_mouse_button_pressed()`

- **签名**：`bool Input.is_mouse_button_pressed(button: MouseButton) const` / `bool Input.IsMouseButtonPressed(MouseButton button)`
- **用途**：轮询指定鼠标按钮状态。
- **误用**：在捕获鼠标时使用原始位置而非相对增量；按钮常量类型错误；将滚动“方向”误当按钮按下持续状态。
- **判据（源码特征）**：`Input\s*\.\s*is_mouse_button_pressed\s*\(`。
- **确认**：匹配 `MouseButton` 枚举；检查鼠标捕获、GUI 悬停与拖拽冲突；审查是否存在重复的位置查询。
- **置信度**：官方明确。

### `Input.get_mouse_position()`

- **签名**：`Vector2 Input.get_mouse_position() const` / `Vector2 Input.GetMousePosition()`
- **用途**：获取当前鼠标位置。
- **误用**：把该值当作事件坐标；在鼠标捕获时把屏幕位置当世界坐标；把它与 `_input(event)` 混用造成“事件坐标”和“轮询坐标”两套来源。
- **判据（源码特征）**：`Input\s*\.\s*get_mouse_position\s*\(`。
- **确认**：在捕获/非捕获、窗口缩放、不同 CanvasLayer 下测试；确认下游使用 Camera2D 等 `screen_to_world` 转换。
- **置信度**：官方明确。

### `Input.get_last_mouse_velocity()`

- **签名**：`Vector2 Input.get_last_mouse_velocity() const` / `Vector2 Input.GetLastMouseVelocity()`
- **用途**：获取最近一次鼠标速度。
- **误用**：把它当每帧增量；误以为捕获模式下无需处理相对运动；在 `_process` 采样时间不稳定时直接使用而不归一化到 `delta`。
- **判据（源码特征）**：`Input\s*\.\s*get_last_mouse_velocity\s*\(`。
- **确认**：比较 `InputEventMouseMotion.velocity` 与该方法；审查时间缩放和帧率变化。
- **置信度**：官方明确。

### `Input.get_last_mouse_screen_velocity()`

- **签名**：`Vector2 Input.get_last_mouse_screen_velocity() const` / `Vector2 Input.GetLastMouseScreenVelocity()`
- **用途**：获取不受缩放影响的最近一次鼠标屏幕速度。
- **误用**：在已有内容缩放的相机空间使用屏幕速度，造成灵敏度随缩放变化；误以为它总是等于窗口像素速度。
- **判据（源码特征）**：`Input\s*\.\s*get_last_mouse_screen_velocity\s*\(`。
- **确认**：缩放窗口或视口后测试；检查是否应使用 `get_last_mouse_velocity()`。
- **置信度**：官方明确。

### `Input.set_mouse_mode()`

- **签名**：`void Input.set_mouse_mode(mode: MouseMode)` / `void Input.SetMouseMode(MouseMode mode)`
- **用途**：设置鼠标可见性、隐藏、捕获或限制模式。
- **误用**：在暂停菜单、弹窗或场景切换时未恢复 `MOUSE_MODE_VISIBLE`；频繁在 `_process` 中每帧设置；退出游戏或进入文本输入前未恢复。
- **判据（源码特征）**：`Input\s*\.\s*set_mouse_mode\s*\(`；可选更严模式 `set_mouse_mode\s*\(\s*(Input\s*\.\s*)?MOUSE_MODE_(VISIBLE|HIDDEN|CAPTURED|CONFINED|CONFINED_HIDDEN|VISIBLE)\s*\)`。
- **确认**：所有改变鼠标模式的分支执行配对恢复测试；审查暂停、失败、弹窗关闭和退出流程。
- **置信度**：官方明确。

### `Input.get_connected_joypads()`

- **签名**：`Array[int] Input.get_connected_joypads()` / `int[] Input.GetConnectedJoypads()`
- **用途**：列出当前连接的手柄设备 ID。
- **误用**：把固定设备索引缓存过久；多手柄时把 `device=0` 当成“玩家一”；轮询空数组仍创建大量输入查询。
- **判据（源码特征）**：`Input\s*\.\s*get_connected_joypads\s*\(`。
- **确认**：插拔手柄并运行；检查是否监听 `joy_connection_changed` 类信号；检查设备 ID 与玩家槽位映射。
- **置信度**：官方明确。

### `Input.is_joy_button_pressed()`

- **签名**：`bool Input.is_joy_button_pressed(device: int, button: JoyButton) const` / `bool Input.IsJoyButtonPressed(int device, JoyButton button)`
- **用途**：查询指定设备的手柄按钮状态。
- **误用**：`device` 硬编码；按钮枚举错用 `JoyAxis`；与动作系统重复绑定后产生双输入。
- **判据（源码特征）**：`Input\s*\.\s*is_joy_button_pressed\s*\(`。
- **确认**：多手柄、SDL/原生后端下测试；核对按钮枚举及设备生命周期。
- **置信度**：官方明确。

### `Input.get_joy_axis()`

- **签名**：`float Input.get_joy_axis(device: int, axis: JoyAxis) const` / `float Input.GetJoyAxis(int device, JoyAxis axis)`
- **用途**：读取指定手柄轴的标准化值。
- **误用**：轴索引写错；未处理死区、漂移或反向；对扳机与摇杆使用同一阈值。
- **判据（源码特征）**：`Input\s*\.\s*get_joy_axis\s*\(`。
- **确认**：打印全轴范围，做居中漂移和死区测试；检查项目输入设置中的轴映射。
- **置信度**：官方明确。

### `Input.start_joy_vibration()`

- **签名**：`void Input.start_joy_vibration(device: int, weak_magnitude: float, strong_magnitude: float, duration: float = 0)` / `void Input.StartJoyVibration(int device, float weakMagnitude, float strongMagnitude, float duration = 0)`
- **用途**：启动指定手柄的震动。
- **误用**：`duration=0` 被误解为“持续 0 秒”还是“不自动停止”取决于具体上下文；暂停、切后台、场景退出时未停止；强度越界或负值未裁剪。
- **判据（源码特征）**：`Input\s*\.\s*start_joy_vibration\s*\(`。
- **确认**：检查存在配对 `stop_joy_vibration()`；测试暂停、场景卸载与不同设备；审查震动强度边界。
- **置信度**：官方明确；持续时间语义需运行验证。

### `Input.action_press()` / `Input.action_release()`

- **签名**：`void Input.action_press(action: StringName, strength: float = 1.0)` / `void Input.action_release(action: StringName)` / `void Input.ActionPress(StringName action, float strength = 1.0)` / `void Input.ActionRelease(StringName action)`
- **用途**：以代码模拟动作按压或释放，常用于回放、测试、网络预测或辅助功能。
- **误用**：只调用 `action_press()` 不释放，造成持续输入；在测试外长期模拟导致真实输入被覆盖；强度不在预期 `[0,1]` 范围。
- **判据（源码特征）**：`Input\s*\.\s*action_press\s*\(`、`Input\s*\.\s*action_release\s*\(`。
- **确认**：对每处 `action_press` 检查同生命周期内的释放；单元测试覆盖异常退出；确认生产代码是否真的需要全局输入注入。
- **置信度**：官方明确。

### `Input.parse_input_event()`

- **签名**：`void Input.parse_input_event(event: InputEvent)` / `void Input.ParseInputEvent(InputEvent @event)`
- **用途**：把已有 `InputEvent` 重新喂入输入管线，从而触发 `Node._input()` 等回调。
- **误用**：用它与动作系统形成回环；频繁手工派发导致重复事件；在回调中无条件 `accept_event` 后又重新派发，破坏传播预期。
- **判据（源码特征）**：`Input\s*\.\s*parse_input_event\s*\(`。
- **确认**：追踪事件来源、回调接收者及 `set_input_as_handled()` 状态；检查是否可用 `Signal`/命令对象替代全局注入。
- **置信度**：官方明确。

### `InputEvent.is_action()`

- **签名**：`bool InputEvent.is_action(action: StringName, exact_match: bool = false) const` / `bool InputEvent.IsAction(StringName action, bool exact_match = false)`
- **用途**：判断事件是否匹配某动作。
- **误用**：动作名写错或不存在；忽略 `exact_match`；在 MouseMotion/ScreenDrag 中错误地使用按下语义。
- **判据（源码特征）**：`\.is_action\s*\(`；事件对象应为 `InputEvent`。
- **确认**：用真实输入事件打印 `as_text()`；覆盖组合键、修饰键与手柄映射。
- **置信度**：官方明确。

### `InputEvent.is_pressed()`

- **签名**：`bool InputEvent.is_pressed() const` / `bool InputEvent.IsPressed()`
- **用途**：判断事件代表“按下”还是“释放”。
- **误用**：对 `InputEventMouseMotion`、`InputEventScreenDrag` 使用无意义；只检查 `pressed` 属性却忽略 `event.device`、echo 或动作匹配。
- **判据（源码特征）**：`\.is_pressed\s*\(`、`\.pressed\b`。
- **确认**：在事件类型守卫后调用；检查 pressed/released 分支完整。
- **置信度**：官方明确。

### `InputEvent.is_echo()`

- **签名**：`bool InputEvent.is_echo() const` / `bool InputEvent.IsEcho()`
- **用途**：判断键盘事件是否为长按回显；`is_action_just_pressed(action, false)` 默认也会忽略 echo。
- **误用**：只在文本输入中过滤 echo，却在游戏热键中未过滤；反过来在文本重发场景中误把 echo 当新按键。
- **判据（源码特征）**：`\.is_echo\s*\(`、`\.echo\b`。
- **确认**：长按按键测试；审查文本输入与游戏动作是否共用同一回调。
- **置信度**：官方明确。

### `InputEvent.as_text()`

- **签名**：`String InputEvent.as_text() const` / `string InputEvent.AsText()`
- **用途**：把事件转为可读文本，适合调试或重绑定 UI。
- **误用**：在高频事件流中构造字符串造成 GC/分配压力；用输出文本做稳定比较而非比较 `device`/键码/事件类型。
- **判据（源码特征）**：`\.as_text\s*\(`。
- **确认**：审查是否处于 `_input` 每事件热路径；若用于持久化，确认键表示和布局的跨平台稳定性。
- **置信度**：官方明确。

### `InputEventKey.keycode` / `physical_keycode` / `key_label`

- **签名**：`Key keycode`、`Key physical_keycode`、`Key key_label`；getter/setter 形如 `get_keycode()`/`set_keycode(value)`。
- **用途**：分别表示逻辑键码、物理位置和布局键标签。
- **误用**：在跨布局场景固定使用 `keycode`；在固定键位场景使用 `key_label`；读取事件前未通过 `is_pressed()` 或事件类型守卫判断按下/释放。
- **判据（源码特征）**：`\.keycode\b`、`\.physical_keycode\b`、`\.key_label\b`。
- **确认**：切换键盘布局测试；对快捷键重绑定保存“键码、物理键码、修饰符”组合，而非仅靠字符串。
- **置信度**：官方明确。

### `InputEventKey.pressed` / `echo` / `location`

- **签名**：`bool pressed`、`bool echo`、`KeyLocation location`，均带 getter/setter。
- **用途**：区分按下状态、重复键事件和左右位置。
- **误用**：同时读取 `pressed` 与 `echo` 时逻辑相反；把 `location` 用于没有左右区分的按键；只对 `echo=true` 执行长按逻辑却没有去抖。
- **判据（源码特征）**：`\.pressed\b`、`\.echo\b`、`\.location\b`。
- **确认**：长按、组合键、左右 Shift/Alt/Ctrl 分别测试。
- **置信度**：官方明确。

### `InputEventKey.get_keycode_with_modifiers()` 等

- **签名**：`Key get_keycode_with_modifiers()`、`Key get_physical_keycode_with_modifiers()`、`Key get_key_label_with_modifiers()`
- **用途**：得到包含修饰键信息的组合键表示，适合快捷键显示或比较。
- **误用**：把带修饰符的组合键与裸 `keycode` 直接比较；只保存键码却丢失 Shift/Ctrl/Alt 语义。
- **判据（源码特征）**：`get_keycode_with_modifiers\s*\(`、`get_physical_keycode_with_modifiers\s*\(`、`get_key_label_with_modifiers\s*\(`。
- **确认**：检查快捷键配置的保存格式；用修饰符组合测试重绑定 UI。
- **置信度**：官方明确。

### `InputEventMouseButton.button_index`

- **签名**：`MouseButton button_index = 0` / `MouseButton ButtonIndex { get; set; }`
- **用途**：标识鼠标按键或滚轮方向。
- **误用**：以裸整数 `0` 判断“没有按键”或左右键；把滚轮方向当按下状态；将事件按下与 `Input` 全局状态混用。
- **判据（源码特征）**：`\.button_index\b`。
- **确认**：使用 `MouseButton` 枚举；分别测试左键、右键、中键和滚轮。
- **置信度**：官方明确。

### `InputEventMouseButton.factor`

- **签名**：`float factor = 1.0` / `float Factor { get; set; }`
- **用途**：表示高精度滚动量或事件增量；普通按键事件中通常不是审查重点。
- **误用**：把 `factor` 当点击次数、按下强度或绝对位置；滚轮处理逻辑忽略正负方向。
- **判据（源码特征）**：`\.factor\b`。
- **确认**：用不同滚轮设备和滚动速度测试；检查符号、缩放与去抖。
- **置信度**：官方明确。

### `InputEventMouseButton.pressed` / `double_click`

- **签名**：`bool pressed = false`、`bool double_click = false`。
- **用途**：区分按钮按下/释放和双击。
- **误用**：在 `pressed=true` 分支未判断双击造成单击逻辑触发；双击判定依赖操作系统间隔却未配置项目级双击时间。
- **判据（源码特征）**：`\.pressed\b`、`\.double_click\b`、`InputEventMouseButton\s*\.\s*DOUBLE_CLICK` 等配置。
- **确认**：快速连击与慢速双击测试；审查单击/双击状态机是否存在竞态。
- **置信度**：官方明确。

### `InputEventMouseMotion.relative`

- **签名**：`Vector2 relative = Vector2(0,0)` / `Vector2 Relative { get; set; }`
- **用途**：相对上一帧位置的增量。
- **误用**：直接加到世界坐标而不做相机变换；用相对量计算速度时未除以 `delta`；捕获光标后使用绝对位置。
- **判据（源码特征）**：`\.relative\b`。
- **确认**：旋转、缩放窗口、相机跟随后测试；与 `velocity`/`screen_relative` 使用意图核对。
- **置信度**：官方明确。

### `InputEventMouseMotion.velocity`

- **签名**：`Vector2 velocity = Vector2(0,0)` / `Vector2 Velocity { get; set; }`
- **用途**：以像素每秒表示的鼠标速度。
- **误用**：把像素每秒当每帧增量；在不同窗口缩放下直接使用；用速度阈值触发点击。
- **判据（源码特征）**：`\.velocity\b`。
- **确认**：测试窗口缩放、DPI、捕获和不同刷新率；审查时间单位转换。
- **置信度**：官方明确。

### `InputEventMouseMotion.screen_relative`

- **签名**：`Vector2 screen_relative = Vector2(0,0)` / `Vector2 ScreenRelative { get; set; }`
- **用途**：屏幕坐标下、不受引擎缩放影响的相对移动。
- **误用**：在相机缩放后把屏幕相对量直接用于世界旋转；与 `relative` 混用造成灵敏度随视口缩放漂移。
- **判据（源码特征）**：`\.screen_relative\b`。
- **确认**：缩放窗口/视口；确认是否需要除以相机 zoom 或应用屏幕到世界变换。
- **置信度**：官方明确。

### `InputEventScreenTouch` / `InputEventScreenDrag`

- **签名**：`InputEventScreenTouch` 与 `InputEventScreenDrag` 为独立事件类型；审查中主要看 `event is InputEventScreenTouch` 和 `event is InputEventScreenDrag`。
- **用途**：分别表示触屏按下/释放与拖拽。
- **误用**：把 MouseMotion 与 ScreenDrag 用同一坐标语义处理；忽略多点触控的 `index`；在 GUI 已消费触摸时仍期望 `_unhandled_input`。
- **判据（源码特征）**：`InputEventScreenTouch\b`、`InputEventScreenDrag\b`、`\.index\b`。
- **确认**：多指测试；检查 UI 遮挡、事件消费与坐标转换。
- **置信度**：官方明确类型语义；具体字段需按项目引擎版本打开类页核对，本文不臆造属性。

### `InputEventJoypadButton` / `InputEventJoypadMotion`

- **签名**：两类事件分别承载手柄按钮与轴信息；审查中优先检查 `event is InputEventJoypadButton` / `is InputEventJoypadMotion`。
- **用途**：读取具体设备按钮按下或轴移动。
- **误用**：与动作系统重复处理；忽略 `device`；轴事件缺少死区、漂移阈值。
- **判据（源码特征）**：`InputEventJoypadButton\b`、`InputEventJoypadMotion\b`、`\.device\b`。
- **确认**：插拔设备；检查设备 ID 与玩家槽位、死区配置。
- **置信度**：官方明确类型语义；精确字段按具体 4.x 补丁版核对。

### `InputEventAction`

- **签名**：`StringName action = &""`、`bool pressed = false`、`float strength = 1.0`，以及 `set_action()`、`is_pressed()`、`get_strength()`。
- **用途**：手工表示或模拟动作事件。
- **误用**：动作名写错；`strength` 超出设计范围；把 `InputEventAction` 当真实硬件事件来源。
- **判据（源码特征）**：`InputEventAction\b`、`InputEventAction\s*\(`、`\.strength\b`。
- **确认**：打印 `as_text()`；检查动作是否在 InputMap 中存在，以及回调是否依赖 `pressed`。
- **置信度**：官方明确。

### `_input(event)` / `Control._gui_input(event)`

- **签名**：`void _input(event: InputEvent)` / `void _gui_input(event: InputEvent)`（C# 对应 `_GuiInput`）。
- **用途**：`_input` 是全局早期输入入口；`_gui_input` 是 Control 接收 GUI 前的具体控件入口。
- **误用**：在 `_input` 中无条件消费导致 UI 失焦；在 `_gui_input` 中处理全局游戏命令；忘记 `accept_event()` 后 GUI 仍把事件传播给后续逻辑。
- **判据（源码特征）**：`func _input\s*\(`、`func _gui_input\s*\(`、`_GuiInput\s*\(`。
- **确认**：按按钮、文本框、全屏游戏输入交叉测试；检查消费状态与后续回调顺序。
- **置信度**：官方明确。

### `_shortcut_input(event)` / `_unhandled_key_input(event)`

- **签名**：`void _shortcut_input(event: InputEvent)`、`void _unhandled_key_input(event: InputEvent)`。
- **用途**：前者在 GUI 尝试消费前处理快捷键；后者仅在前面未消费键盘事件时处理未处理按键。
- **误用**：把 `_unhandled_key_input` 当“最先收到按键”；按钮聚焦时误以为全局快捷键必触发；消费后不调用 `Viewport.set_input_as_handled()`。
- **判据（源码特征）**：`func _shortcut_input\s*\(`、`func _unhandled_key_input\s*\(`、`_UnhandledKeyInput\s*\(`。
- **确认**：聚焦 Control、普通 Node 和弹窗分别测试；检查 `set_input_as_handled()`。
- **置信度**：官方明确。

### `_unhandled_input(event)`

- **签名**：`void _unhandled_input(event: InputEvent)` / `_UnhandledInput(InputEvent event)`。
- **用途**：在 GUI 和其他早阶段输入未消费时处理全局游戏输入。
- **误用**：UI 打开时仍执行游戏输入；把本该让 UI 处理的事件提前消费；与 `_input` 双重处理。
- **判据（源码特征）**：`func _unhandled_input\s*\(`、`_UnhandledInput\s*\(`。
- **确认**：覆盖 Control 消费/未消费、模态弹窗、暂停菜单三种路径。
- **置信度**：官方明确。

### `Viewport.set_input_as_handled()` / `Control.accept_event()`

- **签名**：`void Viewport.set_input_as_handled()` / `void Control.accept_event()`；C# 通常暴露 `GetViewport().SetInputAsHandled()` 与 `AcceptEvent()`。
- **用途**：标记事件已处理，阻止后续传播。
- **误用**：在 `_input` 里消费后却仍希望 GUI 响应；反之在 `_gui_input` 里忘记 `accept_event()`；同一事件在多个节点重复消费却无状态机。
- **判据（源码特征）**：`set_input_as_handled\s*\(`、`accept_event\s*\(`、`SetInputAsHandled\s*\(`、`AcceptEvent\s*\(`。
- **确认**：检查消费点和后续回调日志；构造“消费/不消费”两条路径。
- **置信度**：官方明确。

### `InputMap.add_action()`

- **签名**：`void InputMap.add_action(action: StringName, deadzone: float = 0.2)` / `void InputMap.AddAction(StringName action, float deadzone = 0.2f)`
- **用途**：在运行时添加空动作，再绑定事件。
- **误用**：动作名重复导致隐性冲突；运行时动态创建却不随游戏状态重置；死区小于硬件漂移阈值。
- **判据（源码特征）**：`InputMap\s*\.\s*add_action\s*\(`。
- **确认**：先检查 `has_action()`；打印动作事件清单；测试重新进入场景时是否重复注册。
- **置信度**：官方明确。

### `InputMap.has_action()`

- **签名**：`bool InputMap.has_action(action: StringName) const` / `bool InputMap.HasAction(StringName action)`
- **用途**：检查动作是否存在。
- **误用**：只在编辑期检查，未覆盖首次运行时 `load_from_project_settings()` 时机；与本地化动作名硬编码比较。
- **判据（源码特征）**：`InputMap\s*\.\s*has_action\s*\(`。
- **确认**：在 `_ready()`、资源热重载后查询；核对动作名拼写和 `StringName`。
- **置信度**：官方明确。

### `InputMap.action_add_event()` / `action_erase_event()`

- **签名**：`void InputMap.action_add_event(action: StringName, event: InputEvent)` / `void InputMap.action_erase_event(action: StringName, event: InputEvent)`。
- **用途**：向动作绑定或解绑具体输入事件。
- **误用**：动作不存在时调用；使用等价但不 `==` 的 `InputEvent` 实例导致解绑失败；动态绑定后未保存原始映射，无法恢复默认。
- **判据（源码特征）**：`InputMap\s*\.\s*action_add_event\s*\(`、`InputMap\s*\.\s*action_erase_event\s*\(`。
- **确认**：列出 `action_get_events()`；检查绑定/解绑成对；测试重绑定 UI 的取消与恢复。
- **置信度**：官方明确。

### `InputMap.action_get_events()`

- **签名**：`Array[InputEvent] InputMap.action_get_events(action: StringName)` / `Godot.Collections.Array<InputEvent> InputMap.ActionGetEvents(StringName action)`。
- **用途**：取得某动作当前绑定的输入事件。
- **误用**：未先 `has_action()`；调用后立即修改数组并错误假定会回写 InputMap；在高频逻辑中反复分配数组。
- **判据（源码特征）**：`InputMap\s*\.\s*action_get_events\s*\(`。
- **确认**：打印每个事件 `as_text()`；核对数组只读快照语义。
- **置信度**：官方明确。

### `InputMap.load_from_project_settings()`

- **签名**：`void InputMap.load_from_project_settings()` / `void InputMap.LoadFromProjectSettings()`。
- **用途**：清空运行时动作并重新从 `ProjectSettings` 的输入映射加载。
- **误用**：误以为只增量更新；玩家自定义键位未持久化就被覆盖；在输入事件处理中途调用，导致映射状态不一致。
- **判据（源码特征）**：`InputMap\s*\.\s*load_from_project_settings\s*\(`。
- **确认**：保存/加载键位流程中设置断点；调用后验证玩家自定义仍有效。
- **置信度**：官方明确。

## 2. 音频

### 音频规则的重点不是“是否播放”，而是 bus、并发、资源流和节点回收

**动态 `AudioStreamPlayer` 是最容易留下泄漏的规则目标。** `play()` 触发播放后，节点仍是场景树成员；若代码没有连接 `finished`、没有重复播放保护、没有 `queue_free()`，它可能在逻辑上已经“用完”，却继续占用节点和播放状态。反之，正在播放时立即 `queue_free()` 又会切断尾部音频，因此释放策略必须落在合适的生命周期节点。

`AudioStreamPlayer.finished` 在流正常播放结束时发出[4]。对于被中断、停止、循环或对象提前释放的播放器，不能假定 `finished` 一定到来。规则应要求“动态播放器 = 保存强引用 + 释放策略 + 失败回退”，而不是盲目 `queue_free()`。

### `AudioServer.add_bus()` / `remove_bus()`

- **签名**：`void AudioServer.add_bus(at_position: int = -1)` / `void AudioServer.remove_bus(index: int)`。
- **用途**：动态增加或移除音频总线。
- **误用**：使用运行时 index 作为稳定 ID；移除正在使用的 bus；在编辑器资源与运行期混改 `bus_layout` 后回写。
- **判据（源码特征）**：`AudioServer\s*\.\s*add_bus\s*\(`、`AudioServer\s*\.\s*remove_bus\s*\(`。
- **确认**：在混音器 UI 检查总线索引；测试热重载、场景切换与并发播放。
- **置信度**：官方明确。

### `AudioServer.get_bus_count()` / `get_bus_index()`

- **签名**：`int AudioServer.get_bus_count() const` / `int AudioServer.get_bus_index(bus: StringName) const`。
- **用途**：遍历总线数量、按名称取得总线索引。
- **误用**：总线名写错导致索引检查通过、实际访问越界；依赖 `count` 在动态增删期间不变；把名称比较大小写敏感问题忽略。
- **判据（源码特征）**：`AudioServer\s*\.\s*get_bus_count\s*\(`、`AudioServer\s*\.\s*get_bus_index\s*\(`。
- **确认**：先校验 `get_bus_index()` 有效，再调用 `set_bus_volume_db()` 等索引方法；边界测试。
- **置信度**：官方明确。

### `AudioServer.set_bus_volume_db()` / `set_bus_mute()`

- **签名**：`void AudioServer.set_bus_volume_db(bus_idx: int, volume_db: float)` / `void AudioServer.set_bus_mute(bus_idx: int, enable: bool)`。
- **用途**：设置总线音量或静音。
- **误用**：用线性 0–1 值直接当 dB；总线索引不存在；多个系统争抢同一总线音量而无优先级/恢复机制。
- **判据（源码特征）**：`AudioServer\s*\.\s*set_bus_volume_db\s*\(`、`AudioServer\s*\.\s*set_bus_mute\s*\(`。
- **确认**：UI 显示线性值与内部 dB 双向转换；测试最小/最大、静音恢复。
- **置信度**：官方明确。

### `AudioServer.get_bus_effect()` / `add_bus_effect()`

- **签名**：`AudioEffect AudioServer.get_bus_effect(bus_idx: int, effect_idx: int)` / `void AudioServer.add_bus_effect(bus_idx: int, effect: AudioEffect, at_position: int = -1)`。
- **用途**：查询或添加总线效果。
- **误用**：效果索引越界；在音频线程锁定期间长时间执行；重复添加同一效果而未管理引用。
- **判据（源码特征）**：`AudioServer\s*\.\s*get_bus_effect\s*\(`、`AudioServer\s*\.\s*add_bus_effect\s*\(`。
- **确认**：检查锁定边界、效果槽位与效果启用状态。
- **置信度**：官方明确。

### `AudioServer.bus_layout`

- **签名**：`AudioBusLayout bus_layout` 属性。
- **用途**：读取或设置整个总线布局资源。
- **误用**：运行时加载/保存布局覆盖玩家配置；多个场景共享资源导致交叉修改；把 `bus_layout` 与单个 bus 属性混用。
- **判据（源码特征）**：`AudioServer\s*\.\s*bus_layout\b`、`AudioServer\s*\.\s*set_bus_layout\s*\(`。
- **确认**：加载前后比较 bus 名称、效果和连接；测试持久化恢复。
- **置信度**：官方明确。

### `AudioServer.lock()` / `unlock()`

- **签名**：`void AudioServer.lock()` / `void AudioServer.unlock()`。
- **用途**：锁定音频服务器，保护批量总线操作。
- **误用**：锁定后未解锁、异常路径未恢复；在锁定区间执行耗时逻辑；多次锁定嵌套语义误判。
- **判据（源码特征）**：`AudioServer\s*\.\s*lock\s*\(`、`AudioServer\s*\.\s*unlock\s*\(`。
- **确认**：检查每处 `lock()` 都存在匹配的 `unlock()`；用异常/提前返回路径静态分析。
- **置信度**：官方明确。

### `AudioServer.capture_get_device()` / `playback_get_device()`

- **签名**：属性访问形式为 `AudioServer.capture_get_device`/`playback_get_device`；具体在 4.x 中通过 `input_device`/`output_device` 管理。
- **用途**：获取当前音频采集/播放设备名。
- **误用**：设备字符串跨平台或跨语言环境比较；采集不可用却假定设备存在；设备名包含本地化字符。
- **判据（源码特征）**：`AudioServer\s*\.\s*(?:capture_get_device|playback_get_device|input_device|output_device)\b`。
- **确认**：在启用/未启用采集时读取设备名；检查 `audio/driver/enable_input`；核对具体 4.x 补丁版属性。
- **置信度**：官方明确，但属性名应随具体补丁版复核。

### `AudioServer.get_speaker_mode()`

- **签名**：`SpeakerMode AudioServer.get_speaker_mode() const` / `SpeakerMode AudioServer.GetSpeakerMode()`。
- **用途**：查询当前扬声器配置。
- **误用**：只按立体声混音，却在环绕布局下做空间假设；根据 speaker mode 改变 gameplay，导致音频设备改变时表现不同。
- **判据（源码特征）**：`AudioServer\s*\.\s*get_speaker_mode\s*\(`。
- **确认**：测试立体声、5.1、7.1 等可用配置；确认其只用于音频调试/诊断。
- **置信度**：官方明确。

### `AudioStreamPlayer.play()` / `stop()`

- **签名**：`void play(from_position: float = 0.0)` / `void stop()`。
- **用途**：从指定位置播放或停止流。
- **误用**：`stream` 为 `null` 仍调用 `play()`；多次点击触发重复播放且无重叠策略；`stop()` 后再假定 `finished` 会到来；立即 `queue_free()` 截断声音。
- **判据（源码特征）**：`\.play\s*\(`、`\.stop\s*\(`；并结合 `stream\s*=`、动态 `AudioStreamPlayer.new()` 上下文。
- **确认**：空 stream、重复点击、停止与释放分别测试；检查 `playing` 与 `finished` 的联动。
- **置信度**：官方明确。

### `AudioStreamPlayer.stream` / `playing`

- **签名**：`AudioStream stream` 与 `bool playing`；C# 为属性访问。
- **用途**：设置资源、读取是否正在播放。
- **误用**：把 `playing` 当“已完成”；预加载错误类型资源；跨线程读取 `playing`。
- **判据（源码特征）**：`\.stream\s*=`、`\.playing\b`。
- **确认**：检查资源扩展名与运行时类型；审查播放状态查询上下文。
- **置信度**：官方明确。

### `AudioStreamPlayer.seek()` / `get_playback_position()`

- **签名**：`void seek(to_position: float)` / `float get_playback_position() const`。
- **用途**：跳转播放位置、读取当前位置。
- **误用**：对不可寻址流调用 `seek()`；边播放边高频轮询位置；`get_playback_position()` 超过已知长度时未处理循环。
- **判据（源码特征）**：`\.seek\s*\(`、`get_playback_position\s*\(`。
- **确认**：测试 MP3/Ogg/WAV 等格式寻址能力；检查循环偏移。
- **置信度**：官方明确。

### `AudioStreamPlayer.volume_db` / `pitch_scale`

- **签名**：`float volume_db`、`float pitch_scale`；C# 为属性。
- **用途**：调整节点输出音量和播放速率。
- **误用**：把线性 0–1 赋给 `volume_db`；负 `pitch_scale` 或极小值导致倒放/停顿；多处系统叠加缩放造成爆音。
- **判据（源码特征）**：`\.volume_db\s*=`、`\.pitch_scale\s*=`。
- **确认**：边界值、静音、极低/极高音高测试；UI 线性值与内部值转换核对。
- **置信度**：官方明确。

### `AudioStreamPlayer.bus`

- **签名**：`StringName bus`；C# 为 `StringName Bus { get; set; }`。
- **用途**：指定输出总线名称。
- **误用**：拼写错误的总线名；编辑期改名后运行时仍引用旧名；使用 index 与名称两套体系。
- **判据（源码特征）**：`\.bus\s*=\s*&?"[^"]+"`；与 `ProjectSettings`/场景中的 bus 名称比对。
- **确认**：运行期打印有效总线索引；总线缺失时检查默认回退。
- **置信度**：官方明确。

### `AudioStreamPlayer.autoplay` / `stream_paused`

- **签名**：`bool autoplay`、`bool stream_paused`。
- **用途**：进入场景树自动播放，或在保持状态的同时暂停流。
- **误用**：`autoplay=true` 却未设置 `stream`；把 `stream_paused` 与节点 `process_mode` 混为一谈；暂停时仍执行播放位置逻辑。
- **判据（源码特征）**：`autoplay\s*=\s*true`、`\.stream_paused\s*=`。
- **确认**：场景进入、暂停恢复、后台切换测试。
- **置信度**：官方明确。

### `AudioStreamPlayer.finished`

- **签名**：`signal finished()`；C# 事件 `Finished`。
- **用途**：流正常播放完成时通知。
- **误用**：忘记连接信号；动态生成对象后信号接收者提前释放；把 `finished` 当唯一的清理保证。
- **判据（源码特征）**：`finished\s*\(`、`Finished`、`connect\s*\(\s*"finished"`、`Connect\(.*Finished`。
- **确认**：停止、中断、循环、释放、正常播完五条路径测试。
- **置信度**：官方明确。

### `AudioStreamPlayer.get_stream_playback()`

- **签名**：`AudioStreamPlayback AudioStreamPlayer.get_stream_playback()` / `AudioStreamPlayback GetStreamPlayback()`。
- **用途**：访问当前播放实例以执行类型特定控制。
- **误用**：在 `stream` 未设置、类型不符时强制转型；保存跨 `play()` 的 playback 引用，旧实例失效；对普通流调用 Polyphonic 专属方法。
- **判据（源码特征）**：`get_stream_playback\s*\(`、`GetStreamPlayback\s*\(`。
- **确认**：检查 `stream` 类型后再转型；每次播放重新查询实例的边界需实测。
- **置信度**：官方明确。

### `AudioStreamPlayer2D` / `AudioStreamPlayer3D`

- **签名**：继承 `AudioStreamPlayer`；常用属性分别处理 2D 衰减/平移与 3D 空间化。
- **用途**：按距离、位置、Area 和发射角播放声音。
- **误用**：用 3D 节点做 UI 音效；`max_distance=0` 却仍期待裁剪远处声音；相机/监听器设置错误导致空间化失真。
- **判据（源码特征）**：`AudioStreamPlayer2D\b`、`AudioStreamPlayer3D\b`、`max_distance\s*=`、`attenuation_model\s*=`、`panning_strength\s*=`、`area_mask\s*=`、`emission_angle\s*=`、`unit_size\s*=`。
- **确认**：远距离、近场、遮挡/Area、听者旋转测试；核对 2D/3D 场景角色。
- **置信度**：官方明确。

### `AudioStreamPlayer3D.max_polyphony`

- **签名**：`int max_polyphony = 1`；getter/setter `get_max_polyphony()`/`set_max_polyphony(value)`。
- **用途**：限制同一节点并发声音数。
- **误用**：把默认值 1 当作“允许无限”；达到上限后误以为新声音会排队，实际最旧声音会被裁掉；通过多个节点绕开限制又造成爆音。
- **判据（源码特征）**：`max_polyphony\s*=`。
- **确认**：高频触发音效测试；审查并发上限、声音优先级与总线限制。
- **置信度**：官方明确。

### `AudioStreamPlayer3D.max_distance` / `unit_size`

- **签名**：`float max_distance`、`float unit_size`。
- **用途**：定义声音完全听不见的边界与衰减缩放。
- **误用**：`max_distance<=0` 时仍期待裁剪/性能优化；`unit_size` 与项目世界单位不一致；忽略 `attenuation_model`。
- **判据（源码特征）**：`max_distance\s*=`、`unit_size\s*=`。
- **确认**：检查 `max_distance>0`；在大世界/小世界单位下验证听感与混音负载。
- **置信度**：官方明确。

### `AudioStreamPlayer3D.attenuation_model`

- **签名**：`AttenuationModel attenuation_model = 0`；可用 `set_attenuation_model(value)` 设置。
- **用途**：选择线性、平方、对数或无距离衰减。
- **误用**：选择 `ATTENUATION_DISABLED` 却期待随距离静音；把“无衰减”理解成非空间化；模型与 `max_distance` 语义冲突。
- **判据（源码特征）**：`attenuation_model\s*=\s*(AudioStreamPlayer3D\s*\.\s*)?ATTENUATION_(INVERSE_DISTANCE|INVERSE_SQUARE|LOGARITHMIC|DISABLED)`。
- **确认**：检查枚举值与设计意图；在关键距离点测量相对音量。
- **置信度**：官方明确。

### `AudioStreamPlayer3D.panning_strength` / `area_mask`

- **签名**：`float panning_strength`、`int area_mask = 0`。
- **用途**：缩放平移强度、选择影响混响/bus 的 Area 层。
- **误用**：默认 `area_mask=0` 与 Physics Layer 含义混淆；过度平移造成中心声像失衡；Area 未监听却期待 bus 切换。
- **判据（源码特征）**：`panning_strength\s*=`、`area_mask\s*=`。
- **确认**：Area enter/exit 与 mask 位运算测试；多 Area 重叠时验证优先级。
- **置信度**：官方明确。

### `AudioStreamPlayer3D.emission_angle`

- **签名**：`float emission_angle_degrees = 45.0`；setter `set_emission_angle(value)`。
- **用途**：定义声音未经衰减到达听者的方向角度。
- **误用**：以弧度传值；角度过窄导致玩家背面完全无声；与听者方向和节点旋转计算混淆。
- **判据（源码特征）**：`emission_angle\s*=`、`emission_angle_degrees\s*=`。
- **确认**：检查赋值单位；围绕音源旋转听者验证方向性。
- **置信度**：官方明确。

### `AudioStreamPlayback` / `AudioStreamPlaybackPolyphonic`

- **签名**：`AudioStreamPlayback` 是普通播放状态基类；Polyphonic 通过 `AudioStreamPlayer.get_stream_playback()` 取得。
- **用途**：对正在播放的流执行类型相关控制，尤其是 Polyphonic 并发播放。
- **误用**：未把 `stream` 设为 `AudioStreamPolyphonic` 就尝试取 Polyphonic playback；转型前不检查类型；把 playback 当稳定资源保存。
- **判据（源码特征）**：`as AudioStreamPlaybackPolyphonic`、`AudioStreamPlaybackPolyphonic\)`、`play_stream\s*\(`。
- **确认**：打印运行时类型；先设置 Polyphonic stream，再取 playback，再调用播放方法。
- **置信度**：官方明确。

### `AudioStreamPolyphonic.polyphony`

- **签名**：`int polyphony = 32`；C# 属性 `Polyphony`。
- **用途**：限制 Polyphonic 资源内的最大并发流。
- **误用**：超过限制时仍期待排队；在大量武器/UI 音效下把默认值当无限；并发限制与节点 `max_polyphony` 概念混淆。
- **判据（源码特征）**：`AudioStreamPolyphonic\s*\(\s*\)`、`polyphony\s*=`。
- **确认**：压测并发流；检查 CPU/音频尖峰，并区分节点级与资源级上限。
- **置信度**：官方明确。

### `AudioStreamRandomizer`

- **签名**：`add_stream(index, stream, weight=1.0)`；`random_pitch`、`random_volume_offset_db`；模式包括 `PLAYBACK_RANDOM_NO_REPEATS`、`PLAYBACK_RANDOM`、`PLAYBACK_SEQUENTIAL`。
- **用途**：从音频池随机或顺序播放，并施加随机音高/音量变化。
- **误用**：权重为 0 或负数；只加一个流却期望随机化；随机抖动过大造成明显失真或节奏不稳。
- **判据（源码特征）**：`AudioStreamRandomizer\s*\(`、`add_stream\s*\(`、`random_pitch\s*=`、`random_volume_offset_db\s*=`。
- **确认**：统计多次播放分布；边界检查随机音高/音量范围。
- **置信度**：官方明确。

### `AudioStreamSynchronized`

- **签名**：`int stream_count`；`set_sync_stream(stream_index, audio_stream)`；`set_sync_stream_volume(stream_index, volume_db)`。
- **用途**：同步播放多个子流，最后一个结束或循环子流继续时决定整体结束。
- **误用**：子流长度差异导致预期中的同时结束失效；循环子流造成整体不结束；索引越界。
- **判据（源码特征）**：`AudioStreamSynchronized\s*\(`、`set_sync_stream\s*\(`、`set_sync_stream_volume\s*\(`。
- **确认**：验证子流长度、循环与整体淡出；检查各子流音量叠加后是否削波。
- **置信度**：官方明确。

### `AudioStreamPlaylist`

- **签名**：`int stream_count`、`float fade_time = 0.3`、`bool loop = true`、`bool shuffle = false`；`set_list_stream(index, audio_stream)`。
- **用途**：把多个子流按顺序/乱序播放，并在切换时淡入淡出。
- **误用**：把 `fade_time=0` 当无缝切换；`shuffle=true` 却依赖固定顺序；列表末尾行为与 `loop` 设置冲突。
- **判据（源码特征）**：`AudioStreamPlaylist\s*\(`、`fade_time\s*=`、`loop\s*=`、`shuffle\s*=`、`set_list_stream\s*\(`。
- **确认**：切换边界、循环首尾和乱序种子测试。
- **置信度**：官方明确。

### `AudioStreamWAV` / `AudioStreamMP3` / `AudioStreamOggVorbis`

- **签名**：作为 `AudioStream` 资源加载或导入；审查中以 `load()` 返回类型、文件扩展名和导入配置为主。
- **用途**：分别承载 PCM WAV、MP3、Ogg Vorbis 解码流。
- **误用**：运行时加载很大未压缩 WAV 做短音效；把压缩格式当可精确随机寻址；平台不支持对应解码器。
- **判据（源码特征）**：`\.ogg`、`\.mp3`、`\.wav`、`AudioStreamOggVorbis\b`、`AudioStreamMP3\b`、`AudioStreamWAV\b`。
- **确认**：检查导入设置、内存预算、循环点和寻址能力；按目标平台验证。
- **置信度**：官方明确类型存在；平台支持需运行验证。

## 3. 动画

### 动画审查应区分“播放状态机”和“动画资源内部调用”

**AnimationPlayer 负责播放控制，AnimationTree 负责组合与过渡；两者混用会造成状态语义不一致。** 当 `AnimationTree` 链接 `AnimationPlayer` 后，官方说明 AnimationPlayer 的若干播放/过渡行为不再按预期工作，应通过 AnimationTree 及其节点控制播放[9]。静态规则可以标记“同时直接控制 AnimationPlayer 与 AnimationTree”，但不能据此自动判定错误，仍需核对是否在同一状态路径。

Animation 资源中的方法轨会保存方法名和参数；这些名称不在 GDScript 的符号引用图内，重命名脚本方法不会自动更新[10]。这是规则库可真正拦截的“硬删除后静默失效”类问题：导出 `.tres`/`.res`/`.tscn` 中的 method track 名称，再与脚本中的方法签名和可见性交叉检查。

### `AnimationPlayer.play()`

- **签名**：`void play(name: StringName = &"", custom_blend: float = -1, custom_speed: float = 1.0, from_end: bool = false)`。
- **用途**：按名称播放动画，可指定混合、速度和是否从末尾开始。
- **误用**：动画名写错、当前库前缀缺失；`custom_blend=-1` 误当“零混合”；`from_end=true` 与反向播放语义混淆。
- **判据（源码特征）**：`\.play\s*\(` 位于 AnimationPlayer 上下文；字符串/名称参数应匹配动画清单。
- **确认**：导出资源中的动画路径/名称与调用字符串比较；测试混合和速度。
- **置信度**：官方明确。

### `AnimationPlayer.play_backwards()`

- **签名**：`void play_backwards(name: StringName = &"", custom_blend: float = -1)`。
- **用途**：反向播放指定动画。
- **误用**：动画不支持反向时间、关键帧不是对称内容；与 `speed_scale<0` 混用造成双向状态混乱。
- **判据（源码特征）**：`\.play_backwards\s*\(`。
- **确认**：正向/反向边界与事件轨触发测试。
- **置信度**：官方明确。

### `AnimationPlayer.stop()`

- **签名**：`void stop(keep_state: bool = false)`。
- **用途**：停止动画；`keep_state=false` 时重置到首帧。
- **误用**：把 `keep_state=true` 当暂停；停止后误以为位置保持但下一播放仍会从头；与 `pause()` 混用。
- **判据（源码特征）**：`\.stop\s*\(`。
- **确认**：测试 `keep_state` 两种值；检查停止后节点属性是否回到设计状态。
- **置信度**：官方明确。

### `AnimationPlayer.pause()` / `AnimationPlayer.queue()`

- **签名**：`void pause()`；`void queue(name: StringName)`。
- **用途**：暂停当前动画或将动画排入队列。
- **误用**：队列名不存在；在手动 `seek()` 后未清空队列；暂停时调用 `play()` 的状态重置意图不清晰。
- **判据（源码特征）**：`\.pause\s*\(`、`\.queue\s*\(`。
- **确认**：播放—暂停—恢复、队列顺序、清空队列测试。
- **置信度**：官方明确。

### `AnimationPlayer.clear_queue()`

- **签名**：`void clear_queue()`。
- **用途**：清空已排队动画。
- **误用**：状态切换时只调用 `play()` 而未清空旧队列；频繁入队却无退出条件。
- **判据（源码特征）**：`clear_queue\s*\(`。
- **确认**：状态迁移测试；检查队列残留导致非预期动画。
- **置信度**：官方明确。

### `AnimationPlayer.current_animation_position` / `length`

- **签名**：属性 `float current_animation_position`、`float current_animation_length`。
- **用途**：读取当前播放位置或动画长度。
- **误用**：把位置当“已完成比例”忽略长度；循环动画中长度比较逻辑错误；在 manual 处理模式下假定自动推进。
- **判据（源码特征）**：`current_animation_position\b`、`current_animation_length\b`。
- **确认**：边界、循环、不同速度和手动推进测试。
- **置信度**：官方明确。

### `AnimationPlayer.assigned_animation` / `current_animation`

- **签名**：`StringName assigned_animation`、`StringName current_animation`。
- **用途**：分别表示被分配和正在交叉淡入的动画。
- **误用**：把 `assigned_animation` 当“当前已稳定播放”的名字；淡入未完成时据此切换状态。
- **判据（源码特征）**：`assigned_animation\b`、`current_animation\b`。
- **确认**：淡入期间打印两者；检查状态机是否使用正确的稳定态判断。
- **置信度**：官方明确。

### `AnimationPlayer.autoplay`

- **签名**：`StringName autoplay`；C# 为同名属性。
- **用途**：节点进入树时自动播放指定动画。
- **误用**：资源中自动播放名不存在；多个 AnimationPlayer 同时 autoplay 造成竞争；加载后自动播放与代码首次播放重复。
- **判据（源码特征）**：`autoplay\s*=\s*&?"[^"]+"`。
- **确认**：检查资源自动播放字段与动画清单；冷启动测试。
- **置信度**：官方明确。

### `AnimationPlayer.speed_scale`

- **签名**：`float speed_scale = 1.0`。
- **用途**：缩放当前动画速度。
- **误用**：0、负无穷或极小值造成静止/反向；跨多个系统叠加速度；在状态机回放中直接修改而非通过参数。
- **判据（源码特征）**：`speed_scale\s*=`。
- **确认**：速度边界、方向变化、事件轨时间缩放测试。
- **置信度**：官方明确。

### `AnimationPlayer.playback_default_mode`

- **签名**：枚举属性 `playback_default_mode`。
- **用途**：定义动画的默认播放/循环模式。
- **误用**：默认模式与资源 `loop_mode`、状态机过渡意图冲突；运行时修改后没有恢复。
- **判据（源码特征）**：`playback_default_mode\s*=`。
- **确认**：检查枚举值与资源设置一致；测试首次播放和重新播放。
- **置信度**：官方明确。

### `AnimationPlayer.playback_process_mode`

- **签名**：`AnimationProcessCallback playback_process_mode`；C# 通过 `ProcessCallback` 访问。
- **用途**：决定按 idle、physics 还是 manual 推进动画。
- **误用**：在 physics 角色动画中使用 idle 造成回放抖动；`ANIMATION_PROCESS_MANUAL` 却从未 `advance()`；暂停时仍手动推进。
- **判据（源码特征）**：`playback_process_mode\s*=`、`set_process_callback\s*\(`。
- **确认**：低速/高帧率/物理插值测试；检查 `advance(delta)` 调用点。
- **置信度**：官方明确。

### `AnimationPlayer.seek()` / `advance()`

- **签名**：`void seek(seconds: float, update: bool = false, update_only: bool = false)`；`advance()` 为 manual 推进方法。
- **用途**：跳转播放位置或手动前进。
- **误用**：`update=false` 时误以为已应用当前帧状态；manual 模式下忘记 `advance()`；在 playback callback 中反向 seek。
- **判据（源码特征）**：`\.seek\s*\(`、`advance\s*\(`。
- **确认**：测试手动/自动推进模式；检查位置更新与动画事件。
- **置信度**：官方明确。

### `AnimationPlayer.root_node`

- **签名**：`NodePath root_node`。
- **用途**：指定动画轨道解析属性的根节点路径。
- **误用**：场景重构后根路径失效；绝对/相对路径混淆；远程路径指向已释放节点。
- **判据（源码特征）**：`root_node\s*=\s*("|@?NodePath\()`。
- **确认**：解析所有轨道 `track_path`；场景迁移与节点改名测试。
- **置信度**：官方明确。

### `AnimationPlayer.method_call_mode`

- **签名**：`AnimationMethodCallMode method_call_mode`；属性访问器 `get_method_call_mode()`/`set_method_call_mode(mode)`。
- **用途**：控制方法轨在回放中何时调用。
- **误用**：延迟调用导致事件与可见状态不同步；在状态机快进/seek 后重复调用；把模式当安全防护。
- **判据（源码特征）**：`method_call_mode\s*=`、`set_method_call_mode\s*\(`。
- **确认**：审查 method track 调用时机；测试反向播放、循环和 seek。
- **置信度**：官方明确。

### `AnimationPlayer.animation_finished` / `animation_started`

- **签名**：`animation_finished(anim_name: StringName)`、`animation_started(anim_name: StringName)`。
- **用途**：通知动画开始或完成。
- **误用**：只连接 `animation_finished` 却未处理中断；信号参数名与动画库名不匹配；混合期间对“当前动画”理解错误。
- **判据（源码特征）**：`animation_finished\s*\(`、`animation_started\s*\(`、`"animation_finished"`、`"animation_started"`。
- **确认**：检查连接目标和参数使用；覆盖播放、停止、切换与循环。
- **置信度**：官方明确。

### `AnimationPlayer.animation_changed` / `animation_list_changed`

- **签名**：`animation_changed(old_name: StringName, new_name: StringName)`、`animation_list_changed()`。
- **用途**：通知动画资源重命名或列表变化。
- **误用**：缓存旧动画名不更新；编辑器重命名未触发运行时重构；以字符串拼接的动画名失效。
- **判据（源码特征）**：`animation_changed\s*\(`、`animation_list_changed\s*\(`。
- **确认**：动态增删/重命名动画；检查缓存刷新。
- **置信度**：官方明确。

### `AnimationPlayer.get_animation()` / `add_animation()`

- **签名**：`Animation get_animation(name: StringName) const`；`void add_animation(name: StringName, animation: Animation)`。
- **用途**：读取或添加当前库中的动画资源。
- **误用**：动画名不存在却读取；动态添加时名称冲突；从错误 AnimationLibrary 查询。
- **判据（源码特征）**：`get_animation\s*\(`、`add_animation\s*\(`。
- **确认**：先 `has_animation()`；测试库前缀与重复名称。
- **置信度**：官方明确。

### `AnimationPlayer.remove_animation()` / `rename_animation()` / `has_animation()`

- **签名**：`void remove_animation(name: StringName)`、`void rename_animation(name: StringName, newname: StringName)`、`bool has_animation(name: StringName) const`。
- **用途**：动态删除、重命名或检查动画。
- **误用**：删除正在播放的动画；重命名后旧缓存和字符串引用失效；不存在时调用。
- **判据（源码特征）**：`remove_animation\s*\(`、`rename_animation\s*\(`、`has_animation\s*\(`。
- **确认**：播放状态与名称引用测试；重命名后全项目字符串扫描。
- **置信度**：官方明确。

### `AnimationPlayer.get_animation_list()`

- **签名**：`Array[StringName] get_animation_list() const`。
- **用途**：枚举当前动画名称，适合校验调用字符串。
- **误用**：未处理多 AnimationLibrary 前缀；把返回快照当实时可修改集合；与资源内部方法轨名混为一谈。
- **判据（源码特征）**：`get_animation_list\s*\(`。
- **确认**：打印所有返回名称；与 `play()`/`queue()` 字符串交叉核对。
- **置信度**：官方明确。

### `AnimationLibrary.add_animation()`

- **签名**：`Error add_animation(name: StringName, animation: Animation)`。
- **用途**：向库添加动画并绑定键名。
- **误用**：同名覆盖、空资源、键名与文件命名规范不一致；错误返回值未处理。
- **判据（源码特征）**：`add_animation\s*\(`。
- **确认**：检查返回 `Error`；验证名称和资源非空。
- **置信度**：官方明确。

### `AnimationLibrary.remove_animation()` / `rename_animation()` / `has_animation()`

- **签名**：`void remove_animation(name: StringName)`、`void rename_animation(name: StringName, newname: StringName)`、`bool has_animation(name: StringName) const`。
- **用途**：管理库中的动画键。
- **误用**：删除或重命名后外部字符串未同步；键名为空或重复；跨库复制时键冲突。
- **判据（源码特征）**：`remove_animation\s*\(`、`rename_animation\s*\(`、`has_animation\s*\(`。
- **确认**：调用前存在性检查；调用后刷新缓存和引用。
- **置信度**：官方明确。

### `AnimationLibrary.get_animation_list()`

- **签名**：`Array[StringName] get_animation_list() const`。
- **用途**：返回库中的动画键清单。
- **误用**：把键清单当完整资源路径；对快照进行修改；名称中包含库前缀或不含前缀的假设不一致。
- **判据（源码特征）**：`get_animation_list\s*\(`。
- **确认**：遍历返回键并解析轨道；审查资源重构。
- **置信度**：官方明确。

### `AnimationTree.active`

- **签名**：`bool active`。
- **用途**：启用或停用 AnimationTree 求值。
- **误用**：`active=false` 却仍查询参数；树激活但 `AnimationPlayer.current_animation` 被代码直接控制；延迟激活造成首帧无动画。
- **判据（源码特征）**：`animation_tree\.active\s*=`、`\.active\s*=\s*true`。
- **确认**：检查树与 player 的启用顺序；首帧状态测试。
- **置信度**：官方明确。

### `AnimationTree.tree_root`

- **签名**：`NodePath tree_root`；实际根节点是 `AnimationRootNode` 子类。
- **用途**：定义状态机、混合树或其他根动画节点。
- **误用**：节点类型与代码预期不匹配；根节点未正确绑定到 AnimationPlayer；场景重构后路径失效。
- **判据（源码特征）**：`tree_root\s*=`、`AnimationNodeStateMachine\b`、`AnimationNodeBlendTree\b`。
- **确认**：核对 `tree_root` 类型、子节点连接与 AnimationPlayer 关联。
- **置信度**：官方明确。

### `AnimationTree.parameters/...` 路径访问

- **签名**：`animation_tree.set("parameters/eye_blend/blend_amount", 1.0)`；也可索引或 C# `Set("parameters/eye_blend/blend_amount", 1.0)`。
- **用途**：通过字符串路径读写动画节点参数、playback 和过渡请求。
- **误用**：路径拼写错误、节点名/参数名重构后失效、斜杠层级错；路径无效时可能静默不生效或抛出异常，不能假定一定有编译期检查。
- **判据（源码特征）**：`"parameters/[^"]+"`、`\["parameters/[^"]+"\]`、`set\s*\(\s*"parameters/`、`\.Set\s*\(\s*"parameters/`。
- **确认**：静态导出场景树中的 AnimationTree 节点名、参数名；生成允许路径白名单；运行期对每个路径至少覆盖一次读/写。
- **置信度**：官方明确存在路径语法；具体无效路径的运行时行为是版本相关工程风险，不应泛化为“一定静默”。

### `AnimationNodeStateMachinePlayback.travel()`

- **签名**：`void travel(to_node: StringName, reset_on_teleport: bool = true)`。
- **用途**：通过状态机的最短路径迁移到目标状态。
- **误用**：目标状态名错；`reset_on_teleport=true` 时把“瞬移”理解成保持当前时间；迁移中断后没有状态回退。
- **判据（源码特征）**：`travel\s*\(`、`\.travel\s*\(`。
- **确认**：导出状态机节点名生成白名单；测试所有合法目标及非法名称。
- **置信度**：官方明确。

### `AnimationNodeStateMachinePlayback.start()` / `next()` / `stop()`

- **签名**：`void start(node: StringName, reset: bool = true)`、`void next()`、`void stop()`。
- **用途**：启动状态、沿当前过渡走下一状态、停止状态机播放。
- **误用**：当前节点没有有效下一路径却调用 `next()`；`stop()` 后没有恢复或复位逻辑；与 `travel()` 重复迁移。
- **判据（源码特征）**：`\.start\s*\(`、`\.next\s*\(`、`\.stop\s*\(` 位于 state machine playback 上下文。
- **确认**：检查状态机是否有下一过渡；覆盖启动、迁移、停止与恢复。
- **置信度**：官方明确。

### `AnimationNodeStateMachinePlayback.is_playing()` / `get_current_node()` / `get_travel_path()`

- **签名**：`bool is_playing() const`、`StringName get_current_node() const`、`Array[StringName] get_travel_path() const`。
- **用途**：查询播放状态、当前稳定节点和当前迁移路径。
- **误用**：在迁移过程中把 `get_current_node()` 当最终目标；把 `is_playing()` 当状态完成；保存路径快照后长期引用。
- **判据（源码特征）**：`is_playing\s*\(`、`get_current_node\s*\(`、`get_travel_path\s*\(`。
- **确认**：在混合/迁移期间打印状态；设计明确“稳定态”与“过渡态”判据。
- **置信度**：官方明确。

### `AnimationNodeBlendTree` / `AnimationNodeBlendSpace1D/2D`

- **签名**：通过 `AnimationTree` 节点图配置；代码常用参数路径访问 blend_amount、blend_position 等。
- **用途**：组合多个动画输入，或在 1D/2D 参数空间内混合。
- **误用**：混合点/轴数量配置错误；`max_space`/范围与代码写入值不一致；更新位置却未设置正确输入数量。
- **判据（源码特征）**：`BlendTree\b`、`BlendSpace1D\b`、`BlendSpace2D\b`、`blend_amount\b`、`blend_position\b`。
- **确认**：遍历全部点；参数写入边界与自动三角形/网格生成测试。
- **置信度**：官方明确节点存在；精确参数路径应导出节点图后生成。

### `AnimationNodeOneShot` / `AnimationNodeAdd2/3`

- **签名**：以 AnimationTree 图节点及参数路径访问为主；具体 API 应结合 4.x 补丁版类页。
- **用途**：OneShot 触发一次性动画，Add2/Add3 做多轨叠加。
- **误用**：OneShot 请求名错；连续触发未判断是否可中断；Add 输出权重与预期不符导致叠加失真。
- **判据（源码特征）**：`OneShot\b`、`Add2\b`、`Add3\b`、`is_one_shot_requested\b`、`one_shot/`。
- **确认**：导出节点图参数；连续触发、中断和混合权重测试。
- **置信度**：官方明确节点存在；具体字段按补丁版复核。

### `AnimationNodeTimeScale` / `AnimationNodeTransition`

- **签名**：通过节点图和参数路径访问；可控制时间缩放与过渡开关。
- **用途**：缩放子动画时间或请求在状态间过渡。
- **误用**：负/零时间缩放造成反向或停止；Transition 自动前进条件与代码请求冲突；连续设置同一请求参数。
- **判据（源码特征）**：`TimeScale\b`、`Transition\b`、`time_scale\b`、`transition_request\b`。
- **确认**：遍历过渡图；时间缩放边界与自动过渡条件测试。
- **置信度**：官方明确节点存在；精确参数按补丁版复核。

### `Animation.length` / `loop_mode`

- **签名**：`float length = 1.0`、`LoopMode loop_mode = 0`。
- **用途**：定义动画总时长和循环方式。
- **误用**：时长为 0 或负数；`loop_mode` 与播放器/状态机默认模式冲突；按固定秒数等待结束却忽略循环。
- **判据（源码特征）**：`\.length\s*=`、`loop_mode\s*=`、`LOOP_(NONE|LINEAR|PINGPONG)`。
- **确认**：读取资源并校验大于 0；核对播放器与状态机配置。
- **置信度**：官方明确。

### `Animation.track_set_path()` / 各种 track 类型

- **签名**：`void track_set_path(track_idx: int, path: NodePath)` 以及 value/method/bezier/audio/animation track 的访问方法。
- **用途**：设置轨道绑定的节点与属性路径。
- **误用**：路径指向已改名/移动节点；属性名不存在；轨道索引越界；method track 名与脚本方法不一致。
- **判据（源码特征）**：`track_set_path\s*\(`、`track_set_type\s*\(`、`method_track_get_name\s*\(`。
- **确认**：解析所有 `track_path`；把 method track 名称加入符号交叉检查。
- **置信度**：官方明确。

### `Animation.method_track_get_name()` / `method_track_get_params()`

- **签名**：`StringName method_track_get_name(track_idx: int, key_idx: int) const`、`Array method_track_get_params(track_idx: int, key_idx: int) const`。
- **用途**：读取方法轨在关键帧上保存的方法名与参数。
- **误用**：重构脚本后方法名失效；参数类型与当前方法签名不兼容；仅检查方法存在而忽略可见性/参数变化。
- **判据（源码特征）**：`method_track_get_name\s*\(`、`method_track_get_params\s*\(`；从 `.tres`/`.res` 提取 `method`/`args`。
- **确认**：把资源导出方法与项目 GDScript/C# 符号表交叉比对；对缺失或签名变化发出阻断。
- **置信度**：官方明确；能否静态解析参数兼容性取决于规则库解析深度。

### `Animation.audio_track_*` / `animation_track_set_key_animation()`

- **签名**：音频轨 getter/setter 与 `void animation_track_set_key_animation(track_idx: int, key_idx: int, animation: StringName)`。
- **用途**：配置动画中的音频关键帧或动画轨引用的子动画。
- **误用**：音频资源缺失、时间越界；子动画名错；循环与嵌套动画造成重复播放。
- **判据（源码特征）**：`audio_track_`、`animation_track_set_key_animation\s*\(`。
- **确认**：导出资源依赖与关键帧时间；检查子动画清单。
- **置信度**：官方明确。

## 4. Tween

### Tween 规则的核心是“对象绑定、并行模式、停止语义”

**`create_tween()` 不是对象构造，而是 SceneTree 管理的 Tween 工厂。** 静态分析应把 `Tween.new()` 标记为疑似误用，除非项目通过 GDExtension 或特殊资源管理证明其合理；同时 `Node.create_tween()` 与 `SceneTree.create_tween()` 的默认生命周期不同[12][13]。

`bind_node()` 决定节点释放时 Tween 是否自动销毁，也参与 `TWEEN_PAUSE_BOUND` 暂停行为[12]。因此“自由 SceneTree Tween 是否在节点释放后继续”不能只看 `create_tween()`，还要看后续 `bind_node()`、`set_pause_mode()` 和保存的引用。

### `Node.create_tween()` / `SceneTree.create_tween()`

- **签名**：`Tween Node.create_tween()`、`Tween SceneTree.create_tween()`。
- **用途**：创建并自动在下一处理帧/物理帧启动的 Tween。
- **误用**：`Tween.new()` 创建；`SceneTree.create_tween()` 不绑定节点，误以为绑定当前节点；保存 Tween 引用但从不使用，造成生命周期误判。
- **判据（源码特征）**：`create_tween\s*\(`、`Tween\s*\.\s*new\s*\(`、`bind_node\s*\(`。
- **确认**：节点释放、暂停、切场景测试；检查 `bind_node()` 是否存在。
- **置信度**：官方明确。

### `Tween.tween_property()`

- **签名**：`PropertyTweener tween_property(object: Object, property: NodePath, final_val: Variant, duration: float)`。
- **用途**：从属性当前值补间到最终值。
- **误用**：对象为 `null` 或中途释放；`property` 路径拼错；把 `final_val` 当相对增量；属性 setter 有副作用却连续补间。
- **判据（源码特征）**：`tween_property\s*\(`。属性字符串可进一步正则 `NodePath\("[^"]+"\)`。
- **确认**：检查目标存活与属性路径；确认对象进入树/退出树时的行为。
- **置信度**：官方明确。

### `Tween.tween_interval()`

- **签名**：`IntervalTweener tween_interval(time: float)`。
- **用途**：在链中插入等待时间。
- **误用**：`time<=0` 或极大；误以为 interval 会自动成为后续 step 的独立时间尺度；在 loop 内无限累积。
- **判据（源码特征）**：`tween_interval\s*\(`。
- **确认**：测试循环、暂停与时间缩放。
- **置信度**：官方明确。

### `Tween.tween_callback()`

- **签名**：`CallbackTweener tween_callback(callback: Callable)`。
- **用途**：在链的特定位置执行回调。
- **误用**：捕获已释放对象；回调抛错中断链；依赖回调执行顺序却未理解并行模式。
- **判据（源码特征）**：`tween_callback\s*\(`。
- **确认**：对象释放测试；验证回调与前后 step 的执行顺序。
- **置信度**：官方明确。

### `Tween.tween_method()`

- **签名**：`MethodTweener tween_method(method: Callable, from: Variant, to: Variant, duration: float)`。
- **用途**：在 duration 内按插值调用指定方法。
- **误用**：`from==to` 仍产生逐帧调用；方法签名不接受插值参数；目标释放后继续调用造成异常。
- **判据（源码特征）**：`tween_method\s*\(`。
- **确认**：目标存活检查；检查调用次数、边界值与释放场景。
- **置信度**：官方明确。

### `Tween.tween_subtween()`

- **签名**：`SubtweenTweener tween_subtween(subtween: Tween)`。
- **用途**：把另一个 Tween 作为当前 Tween 的子步骤。
- **误用**：嵌套 Tween 各自绑定不同节点；父子 Tween 暂停/恢复语义冲突；循环父子导致无限嵌套。
- **判据（源码特征）**：`tween_subtween\s*\(`。
- **确认**：分别暂停、释放、kill 父子 Tween；测试生命周期传递。
- **置信度**：官方明确。

### `Tween.set_trans()` / `set_ease()`

- **签名**：`Tween set_trans(trans: TransitionType)`、`Tween set_ease(ease: EaseType)`。
- **用途**：设置最近追加 tween step 的缓动曲线和进出方式。
- **误用**：调用顺序错误导致只影响前一步；重复设置覆盖设计值；使用不存在的枚举组合。
- **判据（源码特征）**：`set_trans\s*\(`、`set_ease\s*\(`、`TRANS_(LINEAR|SINE|QUINT|QUART|QUAD|EXPO|ELASTIC|CUBIC|CIRC|BOUNCE|BACK|SPRING)`、`EASE_(IN|OUT|IN_OUT|OUT_IN)`。
- **确认**：审查 `set_trans()`/`set_ease()` 与对应 `tween_*()` 的相邻调用；肉眼/测试核对曲线。
- **置信度**：官方明确。

### `Tween.set_delay()` / `set_loops()`

- **签名**：`Tween set_delay(delay: float)`、`Tween set_loops(loops: int = 0)`。
- **用途**：设置首个 Tween 启动前的延迟和循环次数。
- **误用**：`loops=0` 被误解为不播放；`loops<0` 表示无限循环却没有退出条件；`set_delay()` 在链式调用中的影响范围错判。
- **判据（源码特征）**：`set_delay\s*\(`、`set_loops\s*\(`。
- **确认**：测试 0/1/正数/负数循环；检查循环退出和完成信号。
- **置信度**：官方明确。

### `Tween.set_parallel()` / `parallel()` / `chain()`

- **签名**：`Tween set_parallel(parallel: bool = true)`、`Tween parallel()`、`Tween chain()`。
- **用途**：切换后续追加的 tween 是并行还是串行。
- **误用**：误以为 `chain()` 让前一步等待某独立条件；`parallel()` 只影响后续追加器；模式跨函数边界时不易追踪。
- **判据（源码特征）**：`set_parallel\s*\(`、`parallel\s*\(`、`chain\s*\(`。
- **确认**：按 step 编号打印开始/结束时间；审查整个链式调用块的模式切换。
- **置信度**：官方明确。

### `Tween.bind_node()`

- **签名**：`Tween bind_node(node: Node)`。
- **用途**：绑定节点，使其释放时 Tween 自动销毁，并参与 `TWEEN_PAUSE_BOUND` 暂停。
- **误用**：绑定短期对象，Tween 提前结束；绑定错误父节点；忘记绑定造成节点释放后继续运行。
- **判据（源码特征）**：`bind_node\s*\(`。
- **确认**：节点释放/暂停测试；核对绑定对象生命周期与 Tween 意图。
- **置信度**：官方明确。

### `Tween.set_process_mode()` / `set_pause_mode()`

- **签名**：`Tween set_process_mode(mode: TweenProcessMode)`、`Tween set_pause_mode(mode: TweenPauseMode)`。
- **用途**：决定 Tween 按 process/physics 推进，以及 SceneTree 暂停时的行为。
- **误用**：physics 逻辑使用 process tween 造成抖动；暂停模式下仍期待推进；与绑定节点暂停语义叠加。
- **判据（源码特征）**：`set_process_mode\s*\(`、`set_pause_mode\s*\(`。
- **确认**：暂停、低速、物理帧率变化测试。
- **置信度**：官方明确。

### `Tween.set_speed_scale()` / `set_ignore_time_scale()`

- **签名**：`Tween set_speed_scale(speed: float)`、`Tween set_ignore_time_scale(ignore: bool = true)`。
- **用途**：缩放时间、忽略工程时间缩放。
- **误用**：0 或负速度；`ignore_time_scale` 与暂停逻辑冲突；动态修改未恢复。
- **判据（源码特征）**：`set_speed_scale\s*\(`、`set_ignore_time_scale\s*\(`。
- **确认**：时间缩放与暂停组合测试。
- **置信度**：官方明确。

### `Tween.custom_step()`

- **签名**：`bool custom_step(delta: float)`。
- **用途**：手动推进 Tween，通常用于 manual process 模式。
- **误用**：在正常自动推进流程中重复推进；delta 不稳定造成动画跳帧；返回失败未处理。
- **判据（源码特征）**：`custom_step\s*\(`。
- **确认**：只在 manual 处理意图下使用；测试负/零/大 delta。
- **置信度**：官方明确。

### `Tween.stop()` / `play()` / `pause()`

- **签名**：`void stop()`、`void play()`、`void pause()`。
- **用途**：停止并复位、恢复运行、暂停。
- **误用**：`stop()` 与 `kill()` 混用；暂停后多次 `play()`；在已完成 Tween 上恢复却期待从完成点继续。
- **判据（源码特征）**：`\.stop\s*\(`、`\.play\s*\(`、`\.pause\s*\(` 位于 Tween 上下文。
- **确认**：检查状态转换；验证 `finished`/`is_valid()`。
- **置信度**：官方明确。

### `Tween.kill()`

- **签名**：`void kill()`。
- **用途**：中止 Tween 操作并使其失效。
- **误用**：kill 后继续调用 chain/step 方法；与 `stop()` 混用；没有回调清理造成悬挂引用。
- **判据（源码特征）**：`\.kill\s*\(`。
- **确认**：kill 后检查 `is_valid()`；测试回调与子 tween。
- **置信度**：官方明确。

### `Tween.is_running()` / `is_valid()`

- **签名**：`bool is_running()`、`bool is_valid()`。
- **用途**：判断 Tween 是否运行、对象是否仍有效。
- **误用**：只检查 `is_running()` 却忽略 kill；长期保存引用却未验证有效；无效后继续追加 step。
- **判据（源码特征）**：`is_running\s*\(`、`is_valid\s*\(`。
- **确认**：释放、kill、stop、完成四条路径测试。
- **置信度**：官方明确。

### `Tween.get_total_elapsed_time()` / `get_loops_left()`

- **签名**：`float get_total_elapsed_time() const`、`int get_loops_left() const`。
- **用途**：查询总耗时和剩余循环数。
- **误用**：把总耗时当当前 step 时间；剩余循环数为负时误判无限循环；暂停期间直接比较时间。
- **判据（源码特征）**：`get_total_elapsed_time\s*\(`、`get_loops_left\s*\(`。
- **确认**：循环、暂停、速度缩放测试。
- **置信度**：官方明确。

### `Tween.finished` / `step_finished` / `loop_finished`

- **签名**：`finished()`、`step_finished(idx: int)`、`loop_finished(loop_count: int)`。
- **用途**：在链完成、单个 step 完成或每个循环完成时通知。
- **误用**：kill 后信号语义未确认；只连接 `finished` 却需要逐循环逻辑；参数索引与 step 顺序假设不一致。
- **判据（源码特征）**：`"finished"`、`"step_finished"`、`"loop_finished"`、`Finished`、`StepFinished`、`LoopFinished`。
- **确认**：kill、stop、完成、无限循环分别测试。
- **置信度**：官方明确。

### `Tween.TransitionType` 与 `EaseType`

- **签名**：`TRANS_LINEAR=0` 至 `TRANS_SPRING=11`；`EASE_IN=0`、`EASE_OUT=1`、`EASE_IN_OUT=2`、`EASE_OUT_IN=3`。
- **用途**：定义补间曲线与缓动方向。
- **误用**：枚举越界；自定义曲线与过渡类型语义重复；把 `SPRING` 当确定时长。
- **判据（源码特征）**：完整枚举字符串白名单。
- **确认**：渲染补间轨迹或数值曲线；核对时长、过冲与视觉回弹。
- **置信度**：官方明确。

## 5. Timer

### Timer 与 SceneTreeTimer 必须按“可重启”和“一次引用”分流

**`Timer` 节点适合需要反复启动、停止或暴露到编辑器/场景树的倒计时；`SceneTreeTimer` 适合短暂、一次性的协程等待。** 两者都有剩余时间和 `timeout`，但生命周期控制不同：`Timer` 可 `start()`/`stop()`，`SceneTreeTimer` 没有这些控制方法，时间结束后会被解除引用[14][16]。

`await get_tree().create_timer(x).timeout` 的审查重点是“等待是否可取消”。如果代码保存返回值并在后续执行取消/暂停逻辑，静态上会明显失配；若完全没有保存强引用，也不能保证后续通过变量继续控制。

### `Timer.wait_time`

- **签名**：`float wait_time`；`void set_wait_time(value: float)`。
- **用途**：设置倒计时秒数。
- **误用**：0 或负数；毫秒与秒单位混用；运行时动态修改但未重新 `start()`。
- **判据（源码特征）**：`wait_time\s*=`、`set_wait_time\s*\(`。
- **确认**：检查单位；`set_wait_time()` 后测试是否显式 `start()`。
- **置信度**：官方明确。

### `Timer.one_shot`

- **签名**：`bool one_shot`。
- **用途**：决定计时结束后是否自动重启。
- **误用**：默认 `false` 时误以为只触发一次；重复 `start()` 重置；循环等待却未处理持续触发。
- **判据（源码特征）**：`one_shot\s*=\s*(true|false)`。
- **确认**：`one_shot` 两种值下检查是否自动重启；异常退出清理。
- **置信度**：官方明确。

### `Timer.autostart`

- **签名**：`bool autostart`。
- **用途**：节点进入场景树后自动开始计时。
- **误用**：autostart 与代码 `start()` 重复；场景预加载时已经启动；首次等待时间不符合预期。
- **判据（源码特征）**：`autostart\s*=\s*true`。
- **确认**：冷启动、重复进入场景、暂停恢复测试。
- **置信度**：官方明确。

### `Timer.start()` / `stop()`

- **签名**：`void start(time_sec: float = -1)`、`void stop()`。
- **用途**：开始/重置计时或停止计时。
- **误用**：`start()` 参数与 `wait_time` 概念混淆；`stop()` 后依赖 `timeout`；多次 `start()` 导致重复触发。
- **判据（源码特征）**：`\.start\s*\(`、`\.stop\s*\(` 位于 Timer 上下文。
- **确认**：启动、重启、停止、暂停组合测试。
- **置信度**：官方明确。

### `Timer.is_stopped()` / `time_left`

- **签名**：`bool is_stopped() const`、`float time_left`。
- **用途**：检查是否停止、读取剩余时间。
- **误用**：把 `time_left=0` 当完成；停止时也显示 0；多次调用 `time_left` 的实时值未归一。
- **判据（源码特征）**：`is_stopped\s*\(`、`time_left\b`。
- **确认**：停止、运行、完成后分别读取；检查 UI 显示单位。
- **置信度**：官方明确。

### `Timer.paused`

- **签名**：`bool paused`。
- **用途**：暂停计时器处理。
- **误用**：暂停时仍调用 `start()` 却期望立即推进；暂停/恢复状态不保存；多个系统争抢 `paused`。
- **判据（源码特征）**：`paused\s*=\s*(true|false)`。
- **确认**：暂停期间修改时间；恢复后是否继续剩余时间测试。
- **置信度**：官方明确。

### `Timer.process_callback`

- **签名**：`TimerProcessCallback process_callback = 1`。
- **用途**：选择 idle 或 physics 回调模式。
- **误用**：physics 时间关键计时用 idle；`Timer` 与物理逻辑推进模式不一致；暂停/时间缩放组合错误。
- **判据（源码特征）**：`process_callback\s*=`、`TIMER_PROCESS_(IDLE|PHYSICS)`。
- **确认**：低帧率、物理步变化、时间缩放测试。
- **置信度**：官方明确。

### `Timer.timeout`

- **签名**：`signal timeout()`；C# 事件 `Timeout`。
- **用途**：倒计时归零时发出。
- **误用**：信号连接对象提前释放；`one_shot` 与重复触发假设冲突；同时用 `await` 和显式连接造成双重处理。
- **判据（源码特征）**：`timeout\s*\(`、`Timeout`、`connect\s*\(\s*"timeout"`。
- **确认**：停止、重启、对象释放测试；检查重复连接。
- **置信度**：官方明确。

### `SceneTree.create_timer()`

- **签名**：`SceneTreeTimer create_timer(time_sec: float, process_always: bool = true, process_in_physics: bool = false, ignore_time_scale: bool = false)`。
- **用途**：创建一次性的 SceneTreeTimer。
- **误用**：单位写成毫秒；`ignore_time_scale` 语义与暂停冲突；没有保存引用却后续尝试控制。
- **判据（源码特征）**：`create_timer\s*\(`。
- **确认**：检查返回值是否被使用、是否需要暂停控制；超时后引用释放测试。
- **置信度**：官方明确。

### `SceneTreeTimer.time_left` / `timeout`

- **签名**：`float time_left`、`signal timeout()`。
- **用途**：读取剩余时间、等待单次完成。
- **误用**：保存 timer 只为在超时后检查；`time_left` 与暂停/时间缩放交互；重复 `await` 同一 timer 的 `timeout`。
- **判据（源码特征）**：`time_left\b`、`timeout\s*\(` 位于 SceneTreeTimer 上下文。
- **确认**：检查是否可取消；超时后引用是否被解除。
- **置信度**：官方明确。

### `await get_tree().create_timer(x).timeout`

- **签名**：`await get_tree().create_timer(x).timeout`（GDScript）；C# 没有可直接等价的结构化 `await`。
- **用途**：在协程中等待一次性超时。
- **误用**：不可取消、不可暂停，却用于长生命周期菜单逻辑；超时期间脚本/节点释放；未处理调用者提前退出。
- **判据（源码特征）**：`await\s+get_tree\s*\(?\s*\)?\s*\.\s*create_timer\s*\([^)]*\)\s*\.\s*timeout`。
- **确认**：等待期间释放调用者；超时后协程恢复；无法取消时的替代设计测试。
- **置信度**：官方明确；C# 等价写法需按项目语言规则单独建模。

## 6. 可转换为静态规则的反直觉坑

### 输入路径：直觉签名不等于事件实际到达

| 坑 | 本能以为 | 实际规则 | 检查方式 |
|---|---|---|---|
| GUI 优先 | `_unhandled_input` 处理“全局输入”，应始终收到 | 前面的 `_input`/Control/`_shortcut_input`/`_unhandled_key_input` 可能已消费 | 追踪输入顺序与消费点 |
| 事件自动拦截 | 回调中处理完就自动停止传播 | 必须调用 `Viewport.set_input_as_handled()` 或 `Control.accept_event()` | 匹配消费方法 |
| `just_pressed` 稳定 | 每帧查询都能响应一次按键 | 可变步处理可能错过；事件回调更可靠 | 检查调用所在回调/循环 |
| 动作名是普通字符串 | 错字会编译失败 | 动作名是运行时 `StringName`，需与 InputMap 核对 | 白名单/资源导出 |
| `is_action_just_pressed` 忽略重复 | echo 按键不会触发 | 默认 `echo=false` 才忽略重复按键 | 检查第二个参数 |
| 物理/逻辑键码等价 | 键码就是键盘位置 | `keycode` 是逻辑键，`physical_keycode` 是物理位置，`key_label` 受布局影响 | 按键盘布局测试 |
| 鼠标位置即相对量 | `get_mouse_position()` 可用于瞄准 | 它是绝对位置；捕获瞄准通常应使用 motion relative | 检查赋值目标 |
| 模拟输入只影响动作 | `action_press()` 只是内部标记 | 它会改变全局动作状态 | 检查释放与测试隔离 |

### 音频路径：播放结束和资源释放不是同一事件

| 坑 | 本能以为 | 实际规则 | 检查方式 |
|---|---|---|---|
| `finished` 总会来 | 播放器最终会发 `finished` | 中断、停止、释放或循环路径可能不发 | 覆盖全部结束路径 |
| 用完自动消失 | 动态播放器播完会被回收 | `queue_free()` 是显式责任；立即释放又可能截断声音 | 检查生命周期策略 |
| `max_polyphony` 会排队 | 新声音超过限制会被延迟 | 默认上限为 1，超过会裁掉最旧声音 | 高频触发压测 |
| bus 名是安全字符串 | 不存在的 bus 会报错 | 应通过 `get_bus_index()` 验证 | 运行期校验与白名单 |
| `stream_paused` 等同停止 | 暂停只是静音 | 暂停仍保持播放状态 | 检查状态机 |
| Polyphonic playback 稳定 | 保存 playback 后可长期调用 | 必须先设置 Polyphonic stream 且实例有效性受播放状态影响 | 类型与获取顺序测试 |

### 动画路径：字符串路径与资源内部方法名都没有编译器担保

| 坑 | 本能以为 | 实际规则 | 检查方式 |
|---|---|---|---|
| AnimationTree 报错 | 参数路径错会编译/运行报错 | 路径以字符串访问，错误可能表现为不生效或异常 | 导出节点图并白名单化 |
| `travel()` 是瞬移 | `reset_on_teleport=true` 表示瞬移到目标 | 它会通过最短路径迁移；`teleport` 语义依赖具体状态机 | 阅读状态机过渡 |
| 当前节点等于目标 | `get_current_node()` 返回正在前往的节点 | 迁移中可能返回当前稳定节点 | 用 `get_travel_path()` |
| 方法轨会随脚本重构 | 重命名方法会自动更新动画 | 方法名硬编码在资源中 | 资源与符号交叉检查 |
| AnimationTree 与 Player 都可控 | 两套 API 可随意混用 | 链接后 Player 的若干行为不再按预期工作 | 审查状态控制入口 |
| loop 状态唯一决定 | Player 设置即可 | 还受资源 `loop_mode`、tree 模式影响 | 三层配置一致性检查 |

### Tween/Timer 路径：自动管理有前提条件

| 坑 | 本能以为 | 实际规则 | 检查方式 |
|---|---|---|---|
| Tween 随节点释放 | `SceneTree.create_tween()` 默认绑定调用者 | 默认不绑定节点，节点释放后仍可能运行 | 检查 `bind_node()` |
| `Node.create_tween()` 一定安全 | 节点释放就销毁 Tween | 还需检查 pause mode、弱引用与后续绑定 | 释放/暂停测试 |
| `new Tween()` 可用 | Tween 与其他节点一样 `new()` | 应使用 `create_tween()`；Tween 由 SceneTree 管理 | 阻断 `Tween.new()` |
| `kill()` 等同 `stop()` | 都是让 Tween 停下 | `kill()` 中止并使 Tween 失效；`stop()` 停止并复位 | 检查后续状态访问 |
| `chain()` 等待某条件 | 调用 `chain()` 会等待上一步 | 它切换后续追加器的并行/串行模式 | 审查整个链式块 |
| SceneTreeTimer 可停止 | `await create_timer().timeout` 之后可取消 | 没有 `start()`/`stop()`，且超时后引用会被解除 | 检查是否保存返回值及取消需求 |
| Timer 一定重启 | 倒计时结束自然重复 | 默认 `one_shot=false` 才自动重启 | 检查 `one_shot` |

## 7. 规则实现与验证清单

### 可静态执行的检查应分三级，而不是把风险提示一律判错

**第一级是可确定误用**：例如 `Tween.new()`、空输入参数、明显错误的枚举、调用 `remove_animation()` 前未检查存在性、动态播放器没有生命周期策略。这些规则可以在 PR 阶段阻断。

**第二级是可量化漂移**：例如 `Input.is_action_just_pressed()` 位于 `_process(delta)`、动作名或 bus 名无法匹配白名单、`AnimationTree` 参数路径未命中导出图、Tween `SceneTree.create_tween()` 后未 `bind_node()`。这类规则应给出“置信度/上下文”，因为是否错误取决于项目约定。

**第三级只能运行验证**：例如多设备键布局、鼠标捕获、GUI 遮挡、声音裁剪、动画过渡、暂停和时间缩放。静态规则应输出测试场景与属性覆盖，而不是伪装成编译错误。

建议规则引擎统一输出以下字段：

| 字段 | 内容 |
|---|---|
| `rule_id` | `GD4-INPUT-001` 等稳定 ID |
| `api` | 官方 4.x 类名与方法名 |
| `language` | `gdscript`、`csharp` 或 `both` |
| `severity` | `error`、`warning`、`info` |
| `evidence` | 官方 URL 与版本 |
| `regex` | 源码匹配式；不要要求单一正则覆盖 GDScript 和 C# |
| `context` | 所需 AST/CFG/资源图条件 |
| `autofix` | 仅限安全、可逆的改名或模式补全 |
| `test` | 可复现的测试动作与预期结果 |

对于 GDScript 和 C#，应分别维护签名与正则。C# 的 PascalCase 方法、属性 setter、`StringName` 字面量、`await` 缺失均不是简单文本等价。把两种语言硬塞进一条正则会显著提高误报率。

## 8. 结论与版本限制

### 这份文档可以直接转化为规则，但必须绑定具体 Godot 4.x 补丁版本

文档内容以 2026-09-17 可访问的 Godot 4.4 稳定版官方类文档和教程为基准。Godot 4.x 的补丁版本会改变少量方法、枚举、资源字段和运行时错误行为；因此语言包审查系统应将规则版本与引擎版本绑定。新增 API 不应默认向后兼容到 Godot 4.0，已废弃 API 也不应直接判错。

最值得立即实现的规则有五组：

1. 输入动作名、bus 名、动画名和 `AnimationTree` 参数路径全部白名单化。
2. 所有 `Input.is_action_just_*` 调用建立“回调/固定步”上下文，并追踪消费方法。
3. 所有动态 `AudioStreamPlayer` 必须有引用保存、释放策略与 `finished` 处理；`max_polyphony` 显式设置。
4. 所有 `Animation` method track 名称与项目符号表交叉检查，所有 `parameters/` 路径与导出的 AnimationTree 图交叉检查。
5. 所有 Tween 创建表达式追踪 `bind_node()`、`set_pause_mode()` 和 `kill()`/`stop()`；所有 `create_timer()` 检查是否保存引用以及是否真的需要取消能力。

官方文档本身不能完全证明所有运行时行为，尤其是无效 AnimationTree 路径在不同 4.x 补丁版中的异常语义、Tween playback 实例跨 `play()` 的稳定性、音频 playback 类型的兼容性，以及多设备键布局行为。因此上述结论属于“官方 API 语义 + 工程静态化规则”，具体项目的禁止级规则仍须用自动化场景测试最终验证。

## 引用来源

[1] https://docs.godotengine.org/en/stable/tutorials/inputs/inputevent.html
> "If any function consumes the event, it can call Viewport.set_input_as_handled(), and the event will not spread any more."

[2] https://docs.godotengine.org/en/stable/classes/class_input.html
> "Vector2 get_vector(negative_x: StringName, positive_x: StringName, negative_y: StringName, positive_y: StringName, deadzone: float = -1.0)"

[3] https://docs.godotengine.org/en/stable/classes/class_inputmap.html
> "void add_action(action: StringName, deadzone: float = 0.2) Adds an empty action to the InputMap with a configurable deadzone."

[4] https://docs.godotengine.org/en/stable/classes/class_audiostreamplayer.html
> "signal finished() Emitted when the audio stops playing, either naturally or because of a stop() call."

[5] https://docs.godotengine.org/en/stable/classes/class_audiostreamplayer3d.html
> "The maximum number of sounds this node can play at the same time. Playing additional sounds after this value is reached will cut off the oldest sounds."

[6] https://docs.godotengine.org/en/stable/classes/class_audiostreampolyphonic.html
> "Obtaining the playback instance is only valid after the stream property is set as an AudioStreamPolyphonic in those players."

[7] https://docs.godotengine.org/en/stable/classes/class_audiostreamsynchronized.html
> "The streams begin at exactly the same time when play is pressed, and will end when the last of them ends."

[8] https://docs.godotengine.org/en/stable/classes/class_audiostreamplaylist.html
> "float fade_time = 0.3 - Fade time used when a stream ends, when going to the next one."

[9] https://docs.godotengine.org/en/stable/classes/class_animationtree.html
> "When linked with an AnimationPlayer, several properties and methods of the corresponding AnimationPlayer will not function as expected."

[10] https://docs.godotengine.org/en/stable/classes/class_animation.html
> "StringName method_track_get_name(track_idx: int, key_idx: int) const Returns the method name of a method track."

[11] https://docs.godotengine.org/en/stable/classes/class_animationlibrary.html
> "Error add_animation(name: StringName, animation: Animation) Adds the animation to the library, accessible by the key name."

[12] https://docs.godotengine.org/en/stable/classes/class_tween.html
> "Used to chain two Tweeners after set_parallel() is called with true."

[13] https://docs.godotengine.org/en/stable/classes/class_scenetree.html
> "A Tween created using this method is not bound to any Node. If you want the Tween to be automatically killed when the Node is freed, use Node.create_tween() or Tween.bind_node()."

[14] https://docs.godotengine.org/en/stable/classes/class_scenetreetimer.html
> "The timer will be dereferenced after its time elapses. To preserve the timer, you can keep a reference to it."

[15] https://docs.godotengine.org/en/stable/classes/class_timer.html
> "If true, the timer will stop after reaching the end. Otherwise, as by default, the timer will automatically restart."

[16] https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/gdscript_basics.html
> "The await keyword can be used to create coroutines which wait until a signal is emitted before continuing execution."

[17] https://docs.godotengine.org/en/stable/classes/class_inputevent.html
> "bool is_action(action: StringName, exact_match: bool = false) const Returns true if this input event matches a pre-defined action of any type."

[18] https://docs.godotengine.org/en/stable/classes/class_inputeventkey.html
> "keycode = 0 ... physical_keycode = 0 ... key_label = 0"

[19] https://docs.godotengine.org/en/stable/classes/class_inputeventmousemotion.html
> "Vector2 velocity = Vector2(0, 0) The mouse velocity in pixels per second."

[20] https://docs.godotengine.org/en/stable/classes/class_inputeventaction.html
> "StringName action ... bool pressed ... float strength"