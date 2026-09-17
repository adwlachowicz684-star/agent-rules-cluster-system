# Godot 4.7 / 4.8 版本专项

**目标版本：4.7.2（当前稳定）· 4.8（开发中，预计 Q4 2026）**

## 0. 版本现实（先定这个）

| 版本 | 状态 | 日期 |
|---|---|---|
| **4.7** | **stable** | 2026-06-18（代号 Lights, Camera, Action!） |
| **4.7.2** | **当前维护版** | 2026-08-18 |
| 4.8 dev1–dev6 | **开发中** | dev6 = 2026-09-15，特性冻结"本月晚些时候" |
| 4.8 stable | 未发布 | 官方策略表：**Q4 2026（估计）** |

⚠ **生产项目用 4.7.2，不要用 4.8 dev**。
4.8 现在还在 dev 快照阶段（dev6 是 2026-09-15），特性冻结都还没正式走完。
按 Godot 的发布节奏，4.7 会一直收到 bug 与安全修复，直到 4.8 stable 发布并出第一个补丁版。

⚠ **4.8 的"最想要特性" mip 级纹理流送**在 dev5 才落地，
即使 4.8 stable 发布，也要按实际版本核对 API 是否变动。

## 1. 4.7 新特性（对开发有直接影响的）

### 1.1 AreaLight3D —— 矩形面光源

以前做"发光的电视屏/广告牌/窗户"只能用自发光材质 + GI 假装。
现在有真正的矩形面光源，阴影更软、反射更真实。

```gdscript
var light := AreaLight3D.new()
light.size = Vector2(2.0, 1.0)      # 矩形尺寸
light.bake_mode = AreaLight3D.BAKE_MODE_DISABLED
add_child(light)
```

→ 3D 光照的选型要更新：见 `3d.md`。

### 1.2 HDR 输出

内部一直用 HDR 做光照，现在能真的输出到屏幕。

支持：Windows · macOS · iOS · visionOS · Linux（Wayland）
**不支持**：Android 仍在开发（官方明确）。

⚠ 开了 HDR 后颜色管线会变 —— 2D 的 `source_color` 语义、
后处理的取值范围都要重新验证。见 `shaders.md` 第 1 节。

### 1.3 Control offset_transform_* —— UI 动画的解法

以前在 Container 里给 Control 做旋转/缩放，容器一排序就被覆盖。
4.7 给了独立于布局系统的一组属性：

```gdscript
button.offset_transform_enabled = true
button.offset_transform_pivot_ratio = Vector2(0.5, 0.5)
var tween := create_tween()
tween.tween_property(button, "offset_transform_rotation", 0.0, 0.5).from(-PI / 2)
```

| 属性 | 默认 | 说明 |
|---|---|---|
| `offset_transform_enabled` | `false` | 总开关 |
| `offset_transform_position` / `_ratio` | 0 | 位移（绝对像素 / 相对比例） |
| `offset_transform_rotation` | 0.0 | 旋转（弧度） |
| `offset_transform_scale` | (1,1) | 缩放 |
| `offset_transform_pivot` / `_ratio` | 0 / **(0.5,0.5)** | 旋转缩放中心 |
| `offset_transform_visual_only` | **`true`** | 仅视觉，不影响点击区域 |

⚠ **`visual_only` 默认 true** 是刻意的：按钮动画后不会失去 hover。
要做"点击区域也跟着变"才设 false。

→ UI 动画写法见 `ui.md`。

### 1.4 DrawableTexture2D —— 画到纹理

以前要用 Viewport 或 RenderingDevice 硬搞，现在有简单入口。
适合：战争迷雾遮罩、绘制玩法、小地图标记、动态贴花。

### 1.5 Tween.tween_await —— 异步动画链

```gdscript
var tween := create_tween()
tween.tween_callback(launch)
tween.tween_await(collided).set_timeout(4.0)
tween.tween_callback(explode)
```

⚠ **信号必须无参数**。带参数的信号要用 `set_unbinds()`，
否则 tweener 不会正确结束。

⚠ 等的是**同一个 tween 里**某个回调发出的信号时，
必须保证信号在 await 开始**之后**才发。无法保证就并行触发：

```gdscript
tween.tween_await(sig)
tween.parallel().tween_callback(method_that_emits_sig)
```

→ 见 `animation.md`。

### 1.6 VirtualJoystick —— 内置虚拟摇杆

**这是 4.7 最省事的新增**。4.6 及更早要自己写，现在内置了。
见 `mobile.md` 第 3 节（`joystick_mode` 三模式、`action_*` 直连 Input Map）。

### 1.7 其他

- **Asset Store 取代 Asset Library**（评分、可缩放预览、后台线程加载）
- **Android GABE 稳定**：可直接在 Android/XR 设备上导出发布
- 控制器**陀螺仪与加速度计**读取（体感瞄准）
- 2D Scene Paint Mode（散布收集物/敌人/装饰，不用先建 tilemap）
- 3D 顶点吸附、ruler 向量、trackball 旋转、跟随移动物体
- inline shader 预览（编辑器里直接看 shader 效果）

## 2. 4.7 Breaking Changes（迁移必读）

### 2.1 Input 设备 ID —— 鼠标键盘不再用 0

```gdscript
# 4.6 及更早：鼠标键盘 device == 0
if event.device == 0:        # ← 4.7 起可能命中手柄
```

⚠ 因为**某些手柄的 device 也可能是 0**，4.7 把鼠标键盘改成专用常量。

```gdscript
# 4.7 正确写法
if event.device == InputEvent.DEVICE_ID_MOUSE:
elif event.device == InputEvent.DEVICE_ID_KEYBOARD:
```

### 2.2 LookAtModifier3D.relative 默认 true → false

| | 含义 |
|---|---|
| `true` | 基于**当前 pose** 叠加 |
| `false` | 基于 **rest pose** 计算（**4.7 新默认**） |

⚠ 4.6 项目升级后头部朝向会变。恢复旧行为要显式 `relative = true`。
⚠ 这个选项还会影响 `use_angle_limitation` 的**基准角度**。

（这条之前标"待核对"，现已确认为 4.7 官方 breaking change。）

### 2.3 新建项目 stretch 默认值改了

| 设置 | 旧默认 | 新默认 |
|---|---|---|
| `display/window/stretch/mode` | `disabled` | **`canvas_items`** |
| `display/window/stretch/aspect` | `keep` | **`expand`** |

⚠ **新建项目**才受影响（已有项目设置不变）。
⚠ 这意味着 4.7 新建项目的 UI 默认就会缩放 —— 分辨率适配的写法要跟着调整。
见 `ui.md`。

### 2.4 GDScript 两处

```gdscript
# ① 继承带类型返回值的方法，override 必须显式 return
func _get_value() -> int:
    return null          # 4.7 起不加会报错
```

```gdscript
# ② packed array 元素赋值不再触发整体 setter
arr[0] = 5               # 不再调用整个属性的 setter
```

⚠ 第 ② 条会让"靠数组 setter 做自动保存/脏标记"的写法**静默失效**。

### 2.5 Jolt Physics 四处（用 Jolt 才受影响）

- `WorldBoundaryShape3D.plane.d` 符号**反转**
- `SoftBody3D` 默认质量 0 → **1 kg**（以前是按点算，总质量巨大）
- `SoftBody3D.linear_stiffness` 换算方式变，需重调参数
- `Area3D` 现在会报与 `SoftBody3D` 的重叠（调碰撞层屏蔽）

### 2.6 其他

| 变更 | 影响 |
|---|---|
| `AudioEffectSpectrumAnalyzer` 移除 `tap_back_pos` | 音频可视化 |
| `OpenXRExtensionWrapper._on_register_metadata` 改签名 | XR 插件 |
| **shader 预处理器的条件解析受限** | 复杂 `#if` 宏可能编译失败 |
| 粒子角速度修正（技术性破坏兼容） | 粒子表现会变 |
| **粒子在 timescale=0 时移动的问题修复** | hitstop 实现要重测 |
| `RichTextLabel.add_image` 的 `width_in_percent` 默认 `false` → `0` | 图文混排 |
| `ResourceImporterDynamicFont.hinting` 1 → 3 | 字体渲染 |
| `sky_reflections/roughness_layers` 7 → 8 | 反射质量/性能 |
| Android 移除 Google Play OBB 支持 | 旧发布流程 |

⚠ **hitstop 那条特别要重测**：我文档里 `2d-rendering.md` 写过用
`Engine.time_scale = 0` + `SceneTreeTimer(ignore_time_scale=true)` 做顿帧。
4.7 修了"粒子在 timescale=0 时仍移动"的问题，粒子表现会变。

### 2.7 AnimationNodeBlendSpace 的 sync_mode

⚠ 4.6 里混合正常的 AnimationTree，4.7 可能不再正确过渡。
表现是"动画卡住不切" —— 要给每个 blend space 设 `sync_mode`。

（这条来自 GodotPrompter 的 4.7 迁移提示，与官方文档的
"Animation: Display and allow setting name/index of BlendSpace points" 相关，
**具体行为按你的项目实测核对**。）

## 3. 4.8 dev 值得关注的

### 3.1 Mip 级纹理流送（开放世界关键）

按相机相对位置**只加载需要的 mipmap 层级**，大幅降低 VRAM。
这是社区多年最想要的特性，对大型开放世界 3D 尤其关键。

```gdscript
# 项目设置开启后需重启编辑器；运行时可通过单例调整
TextureStreaming  # 单例
```

- 纹理要以新导入类型 **"Texture2D Streamed"** 导入
- 每个纹理可覆盖 min/max 分辨率
- 实现者为 Trevor Davenport（GH-113429）

⚠ **只在 Mobile 与 Forward+ 渲染器实现**，Compatibility 没有（GLES 3.0 读回限制）。
⚠ Mobile 渲染器缺 depth pre-pass，用 alpha scissor 或 `discard` 时
会强制开 early-z，**性能可能更差**。
⚠ 不用 sparse/部分驻留纹理，只是普通加载+换纹理。
⚠ 官方说 2D 用法"没怎么测"，**主要面向 3D**。

→ 与 `openworld.md` 的 chunk 流式加载是**互补不是替代**：
那个管场景节点，这个管纹理 VRAM。

### 3.2 其他（dev4/dev5）

- **Trail3D** 原生节点
- Visual Shader **分组**
- **multi-bounce 环境光遮蔽**
- **方向性 lightmap 高光**
- **alpha coverage 修复**：alpha scissor 的植被/栅栏远处不再糊
  （新增选项在降 mip 时保留 alpha 数据）
- Jolt Physics 5.6.0
- 2D 工具栏重做

## 4. 待核对（按目标版本实测）

| 项 | 状态 |
|---|---|
| `VirtualJoystick` 的 `flicked` 触发频率（每帧？还是仅甩动时？） | 未实测 |
| HDR 输出对 2D `source_color` 的具体影响 | 需真机/目标平台验证 |
| `DrawableTexture2D` 的性能与适用场景 | 未实测 |
| 4.8 texture streaming 的实际 VRAM 收益与设置项名称 | dev 阶段，API 可能变 |
| `Trail3D` 的参数与性能 | dev 阶段 |
| MSAA 与注视点渲染在特定 OpenXR 合成层上是否冲突 | 需目标设备实测 |
| `AreaLight3D` 的实时性能开销 | 需按场景规模实测 |

## 5. 相关文档

- 迁移总览 → `version-migration.md`
- 摇杆 → `mobile.md`
- UI 动画 → `ui.md`
- 3D 光照 → `3d.md`
- 开放世界 → `openworld.md`
- Shader → `shaders.md`
- 插件与版本锁 → `plugins.md`
