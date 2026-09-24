# 05 RTL 与结构化文本（i18n 域）

> **前置**：03（切语言已成事务）
> **本步交付**：**layout_direction 生效 + 手写坐标与结构化文本已处理**
> **对应**：做法 `howto/godot/i18n.md#10. RTL 的边界：只镜像 Control，不镜像坐标系`
> 　　　审核 `audit/godot/i18n.md`

## 0. 交付物定义

⚠ **本步最容易"看起来做完了"：设了 `layout_direction`，容器也确实翻了。**

⛔ 但官方明确两点**不会**自动处理：

| 官方原话 | 后果 |
|---|---|
| *"Coordinate system is not mirrored"* | 坐标系不镜像——手写坐标 / 拖拽 / 位移动画方向仍是反的 |
| *"Non-UI nodes (sprites, etc.) are not affected"* | Sprite2D、3D 节点等**不受影响** |

⚠ 所以"设了就完事"是错的：容器翻了，手写逻辑没翻。

做完这一步，应该能**当场演示**：

1. ⚠ 根级 Control 的 `layout_direction` 跟随应用 locale
2. ⛔ 手写坐标 / 拖拽 / 位移动画在 RTL 下方向正确
3. ⛔ 非 UI 节点（Sprite2D / 3D）里的文字已单独处理
4. ⚠ 路径 / URL 设了 `structured_text_bidi_override`
5. ⚠ 方向性图标（前进 / 后退）已翻转

**产出物**：

```text
RTL 适配清单（含手写坐标项）
结构化文本 BiDi 覆盖配置
图标翻转清单
```

## 1. 前置检查清单

- [ ] 已确认目标语言含阿语 / 希语等 RTL 语言
- [ ] 已列出所有手写坐标 / 拖拽的 UI 逻辑
- [ ] 已列出 Sprite2D / 3D 里出现的文字
- [ ] 已列出含方向语义的图标

## 2. 工序

### Step 1　⚠ 根级 Control 用 APPLICATION_LOCALE　`[05#S1]`

【读】`howto/godot/i18n.md#3. 布局方向（RTL）`

【做】根级 Control 设 `LAYOUT_DIRECTION_APPLICATION_LOCALE`，UI 用容器布局而非写死锚点像素。

【产出】根级布局方向配置

【判据】⚠ 切到阿语时，容器子项顺序**自动镜像**

【审】`audit/godot/i18n.md#8`

### Step 2　⛔ 手写坐标不会自动镜像，要自己翻　`[05#S2]`

【读】`howto/godot/i18n.md#10. RTL 的边界：只镜像 Control，不镜像坐标系`

【做】把所有手写坐标 / 拖拽 / 位移动画列出来，按当前 layout direction 取反或改符号。

【产出】手写坐标 RTL 适配清单

【判据】⛔ 阿语下拖拽与动画方向**与视觉一致**，不是反的

【审】`audit/godot/i18n.md#12`

### Step 3　⛔ 非 UI 节点的文字不受自动镜像影响　`[05#S3]`

【读】`howto/godot/i18n.md#10. RTL 的边界：只镜像 Control，不镜像坐标系`

【做】Sprite2D、3D 场景内的文字单独接入翻译与方向处理。

【产出】非 UI 文字清单及处理方式

【判据】⛔ 场景内文字**也**随语言变化

【审】`audit/godot/i18n.md#22`

### Step 4　⚠ 路径与 URL 要设 BiDi 覆盖　`[05#S4]`

【读】`howto/godot/i18n.md#11. 结构化文本要单独指定 BiDi 覆盖`

【做】对文件名、URI、邮箱、正则这类结构化文本设 `structured_text_bidi_override`（路径用 `"File"` 类型）。

【产出】结构化文本 BiDi 配置

【判据】⛔ 阿语下显示的路径**目录顺序正确**

【审】`audit/godot/i18n.md#13`

### Step 5　⚠ 方向性图标要翻转　`[05#S5]`

【读】`howto/godot/i18n.md#12. 资源按 locale 重映射`

【做】前进 / 后退等含左右指向语义的图标在 RTL 下水平翻转；无方向语义的图标保持不变。

【产出】图标翻转清单

【判据】⚠ 阿语下"返回"箭头指向**与阅读方向一致**

【审】`audit/godot/i18n.md#18`

## 3. 参考实现

见 `howto/godot/i18n.md#10. RTL 的边界：只镜像 Control，不镜像坐标系` 中的官方边界说明。

## 4. 验收清单

- [ ] ⚠ 根级 layout_direction 生效
- [ ] ⛔ 手写坐标已适配
- [ ] ⛔ 非 UI 文字已处理
- [ ] ⛔ 结构化文本已覆盖
- [ ] ⚠ 方向性图标已翻转

## 5. 常见返工

**① 以为设了 layout_direction 就完事。** 手写坐标仍是反的。

**② 漏了 Sprite / 3D 文字。** 场景内文字不随语言变。

**③ 路径 BiDi 没覆盖。** 目录顺序错乱。

**④ 图标没翻转。** 返回箭头指向反了。

## 6. 下一步 → `06-资源本地化与长文本适配.md`

## 7　整体审核（功能点级收尾）

【审】`audit/godot/i18n.md`　全部条目，逐条对照本步产出

[05#S1]: howto/godot/i18n.md#3. 布局方向（RTL）
[05#S2]: howto/godot/i18n.md#10. RTL 的边界：只镜像 Control，不镜像坐标系
[05#S3]: howto/godot/i18n.md#10. RTL 的边界：只镜像 Control，不镜像坐标系
[05#S4]: howto/godot/i18n.md#11. 结构化文本要单独指定 BiDi 覆盖
[05#S5]: howto/godot/i18n.md#12. 资源按 locale 重映射
