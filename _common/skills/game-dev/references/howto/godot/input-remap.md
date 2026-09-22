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


## 6. ⚠ InputMap 官方 API 与三个坑

官方方法清单（4.x）：
`action_add_event` / `action_erase_event` / `action_erase_events` /
`action_get_events` / `action_has_event` / `action_get_deadzone` /
`action_set_deadzone` / `add_action(action, deadzone=0.5)` /
`erase_action` / `event_is_action` / `get_actions` / `has_action` /
`load_from_project_settings`

### 坑① ⚠ `action_get_events()` 在编辑器里拿到的是编辑器的键位

ⓘ 官方原话：**"If you want to access your project's input binds from the
editor, read the `input/*` settings from `ProjectSettings`."**

⚠ 在 `@tool` 脚本或 `EditorPlugin` 里调 `action_get_events()`，
返回的是**编辑器自身 action** 的事件，不是你项目的。

⛔ 症状：编辑器里预览键位显示"正确"，导出后完全不对。
⛔ 更糟的是它**不报错** —— 拿到的确实是一份合法的键位表，只是不是你的。

✅ 编辑器内要读项目键位，走 `ProjectSettings` 的 `input/*`。

### 坑② ⚠ `load_from_project_settings()` 会先清空

ⓘ 官方原话：*"**Clears** all InputEventAction in the InputMap and load it
anew from ProjectSettings."*

⚠ **调用它等于丢弃玩家的全部自定义键位。**

⛔ 典型事故：设置界面初始化时"顺手"调一次以保证干净 →
玩家改的键位全没了，而且**没有任何提示**。

✅ 判据：**只在启动时调用一次**，⛔ 不在任何 UI 打开路径上调用。

### 坑③ ⚠ `add_action` 默认 deadzone = 0.5

ⓘ 官方签名：`add_action(action: StringName, deadzone: float = 0.5)`

⚠ 手柄摇杆动作的死区**默认 0.5**，这个值偏大：
玩家会觉得"推了一半才响应"。

ⓘ 更关键的是：**它是 action 级，不是全局**。
每个动作可以有自己的死区，⛔ 不要以为改一处就够。

### `event_is_action` 的 `exact_match` 会放宽匹配

⚠ `exact_match = false`（默认）时：
- 忽略 `InputEventKey` / `InputEventMouseButton` 的**附加修饰键**
- 忽略 `InputEventJoypadMotion` 的**方向**

⛔ 后果：`Shift+W` 会被判定为命中 `W` 动作。
✅ 需要严格区分（如"冲刺必须 Shift+W"）时**必须传 `true`**。

⚠ 另有一条：该方法在事件**未按下**时会忽略键盘修饰键（为了正确检测释放）——
这是官方有意为之，⛔ 不要当成 bug 去"修"。

## 7. 序列化：可落地的存/读流程

⚠ **`InputEvent` 不能直接存 JSON**（第 2 节已说），这里给完整流程。

### 存

```gdscript
func _ev2dict(e: InputEvent) -> Dictionary:
    if e is InputEventKey:
        return {
            "t": "key",
            "device": e.device,
            # ⚠ 三选一，⛔ 不要三个都存（见第 1 节）
            "physical": e.physical_keycode,
            "location": e.location,
            "pressed": e.pressed,
        }
    if e is InputEventJoypadButton:
        return {"t": "pad_btn", "device": e.device, "btn": e.button_index}
    if e is InputEventJoypadMotion:
        return {"t": "pad_axis", "device": e.device,
                "axis": e.axis, "dir": sign(e.axis_value)}
    return {}
```

⚠ **`dir` 只存方向不存 `axis_value`** ——
存了原始值会把"当前推了多少"也存进去，加载后死区判断全乱。

### 读

```gdscript
InputMap.action_erase_events(action)      # ⚠ 先清，⛔ 不清会叠加
for d in saved:
    InputMap.action_add_event(action, _dict2ev(d))
```

⚠ **必须先 `action_erase_events` 再逐个 add** ——
否则每次加载都叠加一份，表现为"一个动作被绑了 N 个相同的键"。

ⓘ 社区常见做法也是先清再加（论坛方案一致）。

### ⚠ 版本号不是可选项

ⓘ 官方明确 3.x → 4.x 字段已换（`scancode` → `keycode`/`physical_keycode`/…）。

⚠ **版本变化时旧键位必须能被识别为旧版并迁移或丢弃**，
⛔ 不能"按新版解析" —— 那会静默产生错误映射。

✅ 判据：存 `version`，加载时不匹配 → **回默认键位 + 提示**，
⛔ 不是"尽力解析"。

## 8. 手柄重绑定：SteamInput 会让设备数翻倍

ⓘ 官方 API：`Input.should_ignore_device(vendor_id, product_id)`，
文档注明："⚠ **SteamInput 会为手柄创建虚拟设备用于重映射**，
为避免同一设备被处理两次，**原始设备会被加入 ignore 列表**。"

⚠ 直接影响重绑定 UI：

| 现象 | 原因 |
|---|---|
| 同一个手柄出现**两个**设备 | SteamInput 虚拟设备 + 原始设备 |
| 玩家改了键没生效 | 改的是**虚拟设备**，游戏读的是另一个 |
| 不同机器上设备索引不同 | 索引不稳定 |

✅ 两条应对：
1. **用 `should_ignore_device` 过滤**掉被忽略的设备
2. ⛔ **不要把 `device` 索引写进存档** —— 重新插拔后顺序会变，
   应存"玩家选中的那个设备"的**当前索引**，并在连接变化时重解析

⚠ **`joy_connection_changed` 必须监听**：
玩家在改键界面拔掉手柄，不处理会崩或卡在独占捕获态。

## 9. 振动：官方文档里四条容易被忽略的

| 官方说明 | 后果 |
|---|---|
| ⚠ **"Not every hardware is compatible with long effect durations"**，官方建议超过几秒就**重启效果** | 长振动在部分手柄上会提前停或不停 |
| ⚠ **macOS 仅 11 及以上支持振动** | 老系统完全无声无息 |
| ⚠ Android 需要导出预设里开 **VIBRATE 权限**，否则无效 | 不报错，就是不动 |
| ⚠ Web 端 `amplitude` **不能改**；Safari / Firefox(Android) **不支持** | 移动端网页基本不可用 |

ⓘ 另有 `Input.vibrate_handheld(duration_ms, amplitude)` 走的是**移动端硬件振动**，
与手柄振动**不是同一套**。

### ⚠ 振动是"硬件状态"，必须自己管生命周期

第 5 节说了不会自动停。这里给**必停的四个时机**：

```text
1. 暂停 / 打开菜单
2. 切后台（NOTIFICATION_APPLICATION_PAUSED）
3. 释放场景 / 切场景
4. 重映射流程结束（无论成功还是取消）
```

⚠ **第 4 条最容易漏** —— 玩家进入改键界面时如果在振动，
取消后振动会一直持续到玩家退出游戏。

⛔ **崩溃时也不会停**（第 5 节已说），
所以"长振动"本身就要避免：用短振动循环代替一次长振动，
即使崩溃，残留时间也只有最后一次的时长。

✅ 判据：**全项目搜索 `start_joy_vibration`，每个都要能指认出对应的 stop 时机**。

## 10. 相关文档

- 输入回调与音频 → `input-audio.md`
- 移动端触控 → `mobile.md`
- 4.7 内置摇杆 → `version-47-48.md`
- 存档 → `io-network.md`
- UI → `ui.md`
- 无障碍 → `accessibility.md`
