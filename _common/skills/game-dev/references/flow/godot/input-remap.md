# 输入重绑定与触觉反馈（Godot 4.7.2）

"输入重绑定""按键重映射""remap" 此前 **0 命中**。商业项目标配。

## 0. API 年代：别把 3.x 字段混进来

| 3.x（旧） | 4.x（用这个） |
|---|---|
| `scancode` | `keycode` / `physical_keycode` / `key_label` / `unicode` / `location` |
| `get_action_list()` | **`action_get_events()`** |

⚠ 混用的后果：轻则编辑器报错，重则在**静默类型转换下保存了错误的字段**。

⚠ **InputMap 是进程内内存副本** —— `load_from_project_settings()` 才从项目设置加载，
运行时改的是内存副本，不写回项目设置。

## 1. 键位字段：物理位置 vs 逻辑标签

⚠ **官方明确建议：键位映射只设置 `keycode`、`physical_keycode`、`unicode` 三者之一。**
键盘事件通常同时设置多个属性，但映射只能用一个语义字段。

| 字段 | 含义 |
|---|---|
| `physical_keycode` | **物理位置**（101/102 键美式键盘布局） |
| `keycode` | 当前布局中键上的拉丁标签 |
| `key_label` | 本地化标签 |
| `unicode` | 字符输入 |
| `location` | 区分左右 Shift/Alt |

⚠ **键位应以物理位置为主键，`keycode` 只用于当前布局显示。**
若保存时把三个键字段一起写出，加载后会产生"按布局变化"或"位置与显示不一致"的映射。

## 2. 序列化：InputEvent 不能直接存 JSON

⚠ **`InputEvent` 不能直接存 JSON** —— 要转纯字典再重建。

必须存的字段：类型、`device`、键模式字段（三选一）、`location`。
手柄轴还要存 `axis` / `axis_value` 方向与死区。

⚠ **要带版本号** —— 否则格式一变旧键位就废了。

## 3. 重绑定 UI 流程

正确链路：

```
进入独占捕获态 → 只接受符合要求的按下事件 → 检测同设备冲突
→ 在待提交缓存中完成交换/替换/撤销 → 保存为带版本的纯字典
→ 下次启动只覆盖玩家自定义项
```

⚠ **捕获应在 `_gui_input()` 里独占消费** —— 不能用 `_input` 直接抓，
否则 ESC 会同时触发菜单。

⚠ **ESC 取消必须成为明确的业务规则**，不能依赖"ESC 会顺手退出"。
若允许 ESC 作为可绑定按键，必须提供"清除绑定"选项，否则玩家无法把 ESC 从动作里移除。

⚠ **同设备冲突检测** —— 一个键被绑到多个动作要提示，跨设备（键盘 vs 手柄）不算冲突。

## 4. 手柄重绑定

⚠ **手柄轴捕获必须设死区** —— 轻微触碰会误触发捕获。
⚠ **按钮与轴不得混为一谈** —— 是两类事件，捕获逻辑不同。

⚠ **多手柄时要知道是哪个手柄在改键** —— `Input.joy_connection_changed` 管理连接。

## 5. 振动是有生命周期的硬件状态

```gdscript
Input.start_joy_vibration(device, weak_magnitude, strong_magnitude, duration = 0)
Input.stop_joy_vibration(device)
```

两个强度范围都是 0–1。`duration = 0` 表示**尝试无限振动**，需显式停止。
`stop_joy_vibration()` 只接收 `device`。

⚠ **`start_joy_vibration()` 不会因退出场景自动停止** ——
必须在**暂停、切后台、释放场景、重新映射流程结束**时调用 `stop_joy_vibration()`。
⚠ 游戏崩溃时振动也不会自己停。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/input-remap.md`


## 6. 相关文档

- 输入回调与音频 → `input-audio.md`
- 移动端触控 → `mobile.md`
- 4.7 内置摇杆 → `version-47-48.md`
- 存档 → `io-network.md`
- UI → `ui.md`
- 无障碍 → `accessibility.md`
