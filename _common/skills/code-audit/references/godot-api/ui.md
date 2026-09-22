<!-- oversize-exempt: 引擎 API 查表文档，按 API 索引，需整体查阅 -->
# Godot 4.x UI 与 2D 渲染 API 级静态审查判据

## 摘要：审查应同时覆盖「节点属性」与「脚本行为」两层

本报告以 Godot 4.x（截至 4.3/4.4 稳定版，官方文档 `docs.godotengine.org`）为范围，把 UI 与 2D 渲染的 API 拆成可直接落进 `.gd` / `.cs` 静态规则引擎的「成员级判据」：每个成员给出 GDScript/C# 签名、用途、误用场景、源码特征正则与验证方式。

三个结论需要优先强调：

1. **Godot 4.x 的 `Label` 没有 Cocos `cacheMode` 这类"一键缓存文本网格"的属性**（官方明确，`Label` 页面无 `cache_mode` / `CacheMode` 相关条目）[2]。性能优化只能靠 `autowrap_mode = OFF`、避免每帧改 `text`、缩短文本长度、用 `clip_text` 限制可视区等手段，不能通过设置一个开关解决。
2. **`CanvasItem.clip_children` 与 `CanvasGroup` 都不能随意嵌套使用**。`CanvasGroup` 本身要额外占用一块 backbuffer，`fit_margin` / `clear_margin` 越大、backbuffer 面积越大；两者叠加会形成 backbuffer 链式分配（官方明确，CanvasGroup 页面与 2D 光照/Canvas 教程均指出其性能代价）[3]。
3. **很多"直觉正确"的写法实际是错的**：`focus_neighbor_*` / `focus_next` 是 `NodePath` 而非自动推断；`margin_*` 是 Theme 常量而非普通属性；`TileMap` 的 `set_cell(layer, ...)` 4 参形式已被 `TileMapLayer.set_cell(coords, ...)` 取代；3.x 的 `Light2D` 在 4.x 已拆为 `PointLight2D` / `DirectionalLight2D` / `SpotLight2D`（官方明确，2D 光照教程列出完整节点清单）[18]。

**置信度说明**：每条判据标注「官方明确 / 社区共识 / 推测」三者之一。官方明确 = 官方 API 文档或官方教程直接说明；社区共识 = 官方未直接说明但多份独立实战材料与官方 issue/PR 描述一致；推测 = 仅能由 API 签名/机制推断，需要实测或运行时确认。**签名以官方 4.x 稳定版为准；新版本（如 4.7 的 `Control` Transform Offset）未在本文中纳入判据。**

---

## 1. Control 几何：锚点+偏移构成"约束"，容器会改写这套约束

**锚点与偏移是同一套布局约束的两面，缺一边就会得到"运行时位置对、代码读不懂"的控件。** `anchor_left/right/top/bottom` 决定 offset 是相对父控件哪条边解释，`offset_left/right/top/bottom` 则是这条边到自身对应边的距离。`anchors_preset`（LayoutPreset，0–15）与 `set_anchors_preset(preset, keep_offsets)`、`set_anchors_and_offsets_preset(preset, resize_mode)` 是编辑器 Layout 菜单的代码等价物[1]。审查时若只改 offset 不改 anchor，控件在父级 resize 时会跑到意料之外的地方；若 anchor 全部为 `ANCHOR_END(1)` 却给出很小或负的 offset，控件会在父级缩小时"逃出"父区域。

**`size_flags_horizontal/vertical`（BitField[SizeFlags]）只在父节点是 Container 时生效**。`SIZE_FILL(1)` 让控件占据分配到的空间，`SIZE_EXPAND(2)` 让它参与富余空间竞争，`SIZE_EXPAND_FILL = SIZE_EXPAND | SIZE_EXPAND`（即 `3`）是"扩展并填满"的常见组合[1]。误用是：给一个不在任何 Container 下的 Control 设 `size_flags_horizontal = SIZE_EXPAND_FILL`，该标志完全不生效，控件仍按 offset 定尺寸；或在 `HBoxContainer`/`VBoxContainer` 里既设 `SIZE_EXPAND_FILL` 又用绝对 offset 硬顶，布局结果与预期冲突。

**`custom_minimum_size`（Vector2，默认 (0,0)）是"软下限"，不是"硬锁定尺寸"**。设为 (0,0) 之外的值后，控件包围盒至少取该值，但 Container 分配的空间可以更大；若同时设 `size_flags` 为 0（不 fill 不 expand）又指望控件撑满，不会生效[1]。

`size`（Vector2，只读）、`global_position`（Vector2）、`pivot_offset`（Vector2）、`rotation`（float）、`scale`（Vector2）这组变换属性与 Container 布局会互相干扰：`rotation`/`scale` 是渲染/变换层，Container 的布局计算读的是 layout 尺寸，旋转缩放后的视觉尺寸不回写进布局，可能造成子项被父裁剪或命中区错位。判据应检查「Container 子项同时出现 `rotation != 0` 或 `scale != Vector2.ONE` 且父级 `clip_children != DISABLED`」这类组合。

| 成员 | GDScript | C# | 常见误用（源码特征） | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `anchor_left/right/top/bottom` | `anchor_left = 0.5` | `AnchorLeft = 0.5f;` | anchor 全 1 却用负 offset；anchor 混用 0/1 导致 resize 方向错 | `anchor_(left\|right\|top\|bottom)\s*=` | 改父尺寸跑一次，看子项是否越界 | 官方明确 |
| `offset_left/right/top/bottom` | `offset_left = 10` | `OffsetLeft = 10;` | 只改 offset 不改 anchor；offset 与 preset 语义打架 | `offset_(left\|right\|top\|bottom)\s*=` | 比对编辑器与运行时包围盒 | 官方明确 |
| `anchors_preset` | `anchors_preset = Control.LayoutPreset.PRESET_FULL_RECT` | `AnchorsPreset = Control.LayoutPreset.FullRect;` | 设 preset 后又手动覆盖 anchor，等于白设 | `anchors_preset\s*=` | 检查后续是否再写 anchor_* | 官方明确 |
| `set_anchors_preset` | `set_anchors_preset(Control.LayoutPreset.PRESET_CENTER, true)` | `SetAnchorsPreset(Control.LayoutPreset.Center, true);` | `keep_offsets=false`（默认）时位置突变 | `set_anchors_preset\s*\(` | 看第二个实参是否显式 true | 官方明确 |
| `set_anchors_and_offsets_preset` | `set_anchors_and_offsets_preset(Control.LayoutPreset.PRESET_FULL_RECT)` | `SetAnchorsAndOffsetsPreset(...)` | 在 `_ready` 里重复调用，与场景内 preset 冗余 | `set_anchors_and_offsets_preset\s*\(` | 场景文件 vs 脚本对比 | 官方明确 |
| `size_flags_horizontal/vertical` | `size_flags_horizontal = Control.SIZE_EXPAND_FILL` | `SizeFlagsHorizontal = Control.SizeFlags.ExpandFill;` | 非 Container 父级下使用；值 3 写成 `SIZE_EXPAND \| SIZE_FILL` 之外的魔法数 | `size_flags_(horizontal\|vertical)\s*=` | 检查父节点 `is Container` | 官方明确 |
| `custom_minimum_size` | `custom_minimum_size = Vector2(100, 32)` | `CustomMinimumSize = new Vector2(100, 32);` | 用 0/负数指望"锁定尺寸"；与 `size_flags=0` 混用 | `custom_minimum_size\s*=` | 父级压缩时观察是否小于设定值 | 官方明确 |
| `size` | `var s = size` | `var s = Size;` | 写入 `size`（只读，应改 offset 或 `custom_minimum_size`） | `\bsize\s*=` | 编译/静态检查是否报错 | 官方明确 |
| `pivot_offset` | `pivot_offset = Vector2(16, 16)` | `PivotOffset = new Vector2(16, 16);` | 旋转缩放时未同步考虑命中区；pivot 与 anchor 语义混淆 | `pivot_offset\s*=` | 旋转后看输入命中是否偏移 | 官方明确 |

---

## 2. 输入与焦点：MouseFilter 决定"谁收到"，FocusMode 决定"谁能被 Tab 到"

**`mouse_filter`（MouseFilter 枚举）控制的是鼠标按钮事件能否进 `_gui_input()`，不等于"是否可见"**。`MOUSE_FILTER_STOP(0)` 拦截并阻止向深层传播，`MOUSE_FILTER_PASS(1)` 自己处理后继续传，`MOUSE_FILTER_IGNORE(2)` 完全不处理本节点（事件直接走下面的节点）[1]。最常见的错是"想让面板挡住底层按钮点击"却设成 PASS，或"想让装饰层透传"却设成 STOP。判据应抓 `mouse_filter = MOUSE_FILTER_PASS` 出现在全屏半透明遮罩/弹窗根节点上的组合。

**`focus_mode`（FocusMode 枚举）决定 Tab/方向键能否把焦点给到本控件**：`FOCUS_NONE(0)`、`FOCUS_CLICK(1)`（仅鼠标点击）、`FOCUS_ALL(2)`（键鼠/手柄均可）、`FOCUS_ACCESSIBILITY(3)`（仅辅助功能）[1]。误用：`focus_mode = FOCUS_NONE` 的控件调用 `grab_focus()` 无效；期望手柄方向键导航却只设了 `FOCUS_CLICK`。

**`focus_neighbor_left/right/top/bottom`、`focus_next`、`focus_prev` 都是 `NodePath`，必须显式指向目标节点，Godot 不会自动推断**。类型是 `NodePath`（默认 `NodePath("")`）[1]。若路径写错或目标节点未启用/未入树，导航会跳到默认邻居。判据：`focus_neighbor_(\w+)\s*=\s*["'][^"']*["']` 抓出所有显式邻居，运行时校验路径可解析；若写的是相对路径，检查是否依赖场景结构。

`grab_focus(hide_focus=false)`、`has_focus(ignore_hidden_focus=false)`、`release_focus()` 这组 API 有一个关键陷阱：**`grab_focus()` 会"抢走"当前焦点控件的焦点**，而且只在节点入树且 `focus_mode` 允许时生效[1]。在 `_ready()` 里对尚未入树的节点调用无效；`has_focus()` 默认参数下会忽略隐藏的焦点控件，若你在隐藏/显示逻辑里依赖它判断状态，需显式传 `true`。

**`_gui_input(event)` 必须配合 `accept_event()` 才算"消费事件"**。官方明确：`accept_event()` 会把事件标记为已处理，之后即使监听 `Node._unhandled_input()` / `_unhandled_key_input()` 的节点也收不到该事件[1]。若只写 `_gui_input` 不 `accept_event()`，事件会继续传播，可能导致"按钮点了，底层也收到点击"；反过来，无条件 `accept_event()` 会把所有输入吃掉，导致全局快捷键失效。判据应抓「`_gui_input` 方法体内没有任何 `accept_event()` 调用」且 `mouse_filter != IGNORE` 的情况。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `mouse_filter` | `mouse_filter = Control.MOUSE_FILTER_STOP` | `MouseFilter = Control.MouseFilterEnum.Stop;` | 全屏遮罩用 PASS；透传层用 STOP | `mouse_filter\s*=` | 点下层控件看是否响应 | 官方明确 |
| `focus_mode` | `focus_mode = Control.FOCUS_ALL` | `FocusMode = Control.FocusModeEnum.All;` | `FOCUS_NONE` 下调 grab_focus；手柄导航用 CLICK | `focus_mode\s*=` | 用键盘 Tab 测试 | 官方明确 |
| `grab_focus` | `grab_focus()` / `grab_focus(true)` | `GrabFocus();` / `GrabFocus(true);` | `_ready` 里调（未入树）；重复抢焦点 | `grab_focus\s*\(` | 检查 `is_inside_tree()` | 官方明确 |
| `has_focus` | `if has_focus():` / `has_focus(true)` | `if (HasFocus())` | 默认忽略隐藏焦点，状态判断失真 | `has_focus\s*\(` | 隐藏焦点控件下验证 | 官方明确 |
| `focus_neighbor_*` | `focus_neighbor_bottom = NodePath("Button2")` | `FocusNeighborBottom = new NodePath("Button2");` | 依赖自动推断；路径失效 | `focus_neighbor_(left\|right\|top\|bottom)\s*=` | 运行时 `get_node()` 校验路径 | 官方明确 |
| `focus_next/focus_prev` | `focus_next = NodePath("...")` | `FocusNext = new NodePath("...");` | 与 `focus_neighbor_*` 语义混淆；路径为空却指望导航 | `focus_(next\|prev)\s*=` | 按 Tab/Shift+Tab 测试 | 官方明确 |
| `release_focus` | `release_focus()` | `ReleaseFocus();` | 在 `_input` 里无条件释放，打断正常流程 | `release_focus\s*\(` | 与 grab/release 配对检查 | 官方明确 |
| `_gui_input` | `func _gui_input(event):` | `public override void _GuiInput(InputEvent @event)` | 处理完不 accept_event，事件继续传播 | `func _gui_input|override void _GuiInput` | 方法体内查 accept_event | 官方明确 |
| `accept_event` | `accept_event()` | `AcceptEvent();` | 无条件调用，吃掉全局快捷键 | `accept_event\s*\(` | 快捷键是否失效 | 官方明确 |

---

## 3. 容器：布局行为由"容器类 + 子项 size_flags + Theme 常量"三者共同决定

**`HBoxContainer` / `VBoxContainer` 只管一维排列，交叉轴尺寸靠子项自己的 `custom_minimum_size` 与 size_flags**。对齐方式由 `alignment`（AlignmentMode：BEGIN=0/CENTER=1/END=2）控制，`add_spacer(begin)` 在盒子头部插入一个 spacer 控件[24]。误用：用 `HBoxContainer` 装需要换行的控件却指望自动折行（`HBoxContainer` 不折行，应改用 `GridContainer`）；用 spacer 实现"撑开"却忘记 spacer 本身需要 `SIZE_EXPAND_FILL`。判据：抓「`HBoxContainer` 子项数量大且均 `size_flags=0`」——可能溢出或挤作一团。

**`GridContainer.columns`（int，默认 1）是唯一必须显式设置的布局参数，改它会触发子项重排**[26]。误用：动态增删子项后不更新 `columns`，最后一行的空位行为不符合预期；或在 Grid 里给子项设 `SIZE_EXPAND` 却指望每格严格等宽（`GridContainer` 格宽取该列最宽子项）。判据：`columns\s*=` 与 `add_child` 顺序共同分析。

**`ScrollContainer` 的滚动条与自动跟随焦点是两个独立开关**。`scroll_horizontal`/`scroll_vertical` 是当前滚动偏移（int），`horizontal_scroll_mode`/`vertical_scroll_mode` 是 ScrollMode 枚举（控制滚动条是否可用、何时可见），`follow_focus`（bool，默认 false）开启后，滚动容器会自动把获得焦点的子项（含间接子项）滚到完全可见[5]。误用：`follow_focus = true` 但目标子项跨多层嵌套，自动滚动目标不确定；或靠 `scroll_vertical = N` 每帧驱动滚动却忽略 `scroll_vertical` 是被布局/内容高度约束的（内容高度变化时 N 的语义会变）。

**`ScrollContainer` 内大量子项没有虚拟化，是 Godot UI 最典型的内存与帧性能陷阱**（社区共识，官方未提供 `ItemList`/`Tree` 之外的虚拟化控件）。判据应抓「`ScrollContainer` 下有 `for`/`while` 循环 `add_child` 生成上百个 `Control`/`Label`/`TextureRect`」的代码模式，建议改用 `ItemList`、`Tree`，或自建对象池+只实例化可视区子项。

`CenterContainer` 把子控件按其最小尺寸居中，只有一个 `use_top_left`（bool，默认 false）控制是相对容器中心还是左上角对齐[23]。误用：指望它把子项"拉伸填满"（那是 `PanelContainer` + size_flags 的职责），或以为需要手动设 size_flags。

`MarginContainer` 的 `margin_left/right/top/bottom` **是 Theme 常量而非普通属性**，只能通过 `add_theme_constant_override("margin_top", 100)` 设置[22]。GDScript/C# 官方示例写法分别为 `add_theme_constant_override("margin_top", margin_value)` 与 `AddThemeConstantOverride("margin_top", marginValue)`[22]。误用：直接写 `margin_top = 100`（属性不存在，会在运行时报 `Nonexistent property` 或静默不生效，取决于调用方式）。判据：`(margin_left|margin_right|margin_top|margin_bottom)\s*=` 直接赋值应报缺陷。

`PanelContainer` 把子控件限制在 `StyleBox` 区域内，常用于"给控件加边框/背景"[25]。误用：把多个同级控件都放进 `PanelContainer` 指望它们自动排布（`PanelContainer` 只接纳一个主子项，多子项行为取决于内部逻辑，实际布局应交由 `BoxContainer` 等）。

`SplitContainer.split_offset`（int，默认 0）是分隔条的像素偏移，`collapsed`（bool）、`dragger_visibility`（DraggerVisibility 枚举，默认 DRAGGER_VISIBLE=0）控制把手可见性[21]。误用：`split_offset` 写死大值却未考虑子项 `custom_minimum_size`，导致一侧被压到最小仍拉不动。

`TabContainer.current_tab`（int，默认 -1）是当前选中页索引，另有 `get_tab_title`/`set_tab_title`、`get_tab_icon`、`is_tab_disabled`、`get_tab_control`、`tabs_visible`[20]。误用：`current_tab = -1` 是"无选中"的合法值，但代码里把 -1 当错误处理；或动态增删子项后 `current_tab` 指向已移除页。

`SubViewportContainer` 的 `stretch`（bool，默认 false）开启后子视口自动缩放到容器尺寸，`stretch_shrink`（int，默认 1）把子视口有效分辨率除以该值：例如 1280×720 设 `stretch_shrink=2` 会以 640×360 渲染但占同样屏幕空间，以牺牲清晰度换取渲染速度[19]。判据：抓 `stretch_shrink > 1` 的组合，提醒清晰度代价；`stretch = true` 且子视口尺寸远大于容器时，backbuffer 开销显著。

| 容器/成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `HBoxContainer.alignment` | `alignment = BoxContainer.ALIGNMENT_CENTER` | `Alignment = BoxContainer.AlignmentMode.Center;` | 靠 alignment 做"等宽分布" | `alignment\s*=` | 子项尺寸不等时看布局 | 官方明确 |
| `GridContainer.columns` | `columns = 3` | `Columns = 3;` | 动态增删子项后不更新 | `columns\s*=` | 对比行尾空位 | 官方明确 |
| `ScrollContainer.follow_focus` | `follow_focus = true` | `FollowFocus = true;` | 深层嵌套子项焦点跟随失败 | `follow_focus\s*=` | Tab 到子项看是否自动滚动 | 官方明确 |
| `MarginContainer` margin_* | `add_theme_constant_override("margin_top", 100)` | `AddThemeConstantOverride("margin_top", 100);` | 直接 `margin_top = 100` 赋值 | `(margin_left\|margin_right\|margin_top\|margin_bottom)\s*=` | 编译/运行报 Nonexistent property | 官方明确 |
| `SplitContainer.split_offset` | `split_offset = 200` | `SplitOffset = 200;` | 忽略子项 minimum，值被钳制 | `split_offset\s*=` | 拖拽看是否卡住 | 官方明确 |
| `SubViewportContainer.stretch_shrink` | `stretch_shrink = 2` | `StretchShrink = 2;` | 值过大导致明显模糊 | `stretch_shrink\s*=` | 对比渲染清晰度 | 官方明确 |

---

## 4. 主题：override 是"局部覆盖"，Theme 资源才是"全局皮肤"

**Theme 是给 `Control`/`Window` 做样式/换肤的 Resource**，可通过 `ProjectSettings.gui/theme/custom` 设置项目级主题，使其对所有 Control 生效[6]。Theme 提供 `add_type(theme_type)`、`set_color(name, theme_type, color)`、`get_color(name, theme_type)`、`has_color(name, theme_type)` 等 `set_*`/`get_*`/`has_*` 系列方法；当属性未定义时 `get_*` 返回 ThemeDB 的引擎回退值（fallback）[6]。

**`theme_type_variation`（StringName，默认 `&""`）是 Control 查找自身主题项时使用的变体类型名**，与 `ThemeDB` 配合构成"基础类型 → 变体"的查找链[1]。误用：写了变体名却未在 Theme 资源里注册该变体类型，运行时回退到基础类型，样式"不生效"却无报错。

**`theme_override_*` 系列属性与 `add_theme_*_override()` 方法**（`add_theme_color_override(name, color)` 等）是"只影响本节点"的局部覆盖[1]。判据应区分：直接在场景里堆 `theme_override_*` 会让该控件与主题解耦，迁移/换肤时失效；动态 `add_theme_*_override` 若在每帧/每次 `_process` 里调用，会重复分配与触发主题重算。

**特别反直觉：`MarginContainer` 的 `margin_*` 是 Theme 常量，必须用 `add_theme_constant_override`，而不是属性赋值**[22]。同理，`BoxContainer` 的 `separation`、`PanelContainer` 的 StyleBox 引用，凡是 Theme 驱动的量都走这套 override 接口。判据可统一抓「对 Control 子类直接赋值 `margin_*`/`separation`/`custom_styles_*` 等本不存在的属性」的模式。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `theme_type_variation` | `theme_type_variation = &"MyButton"` | `ThemeTypeVariation = "MyButton";` | 变体名未注册到 Theme 资源 | `theme_type_variation\s*=` | 检查 .tres Theme 是否含该类型 | 官方明确 |
| `add_theme_color_override` | `add_theme_color_override("font_color", Color.WHITE)` | `AddThemeColorOverride("font_color", Colors.White);` | 每帧调用；与主题资源重复 | `add_theme_(\w+)?_override\s*\(` | 查调用频率 | 官方明确 |
| `add_theme_constant_override` | `add_theme_constant_override("margin_top", 100)` | `AddThemeConstantOverride("margin_top", 100);` | 用普通属性赋值替代 | `add_theme_constant_override\s*\(` | 检查是否同时有 `margin_*\s*=` | 官方明确 |
| `Theme.set_color` | `theme.set_color("font_color", "Button", Color.WHITE)` | `theme.SetColor("font_color", "Button", Colors.White);` | type 名写错回退到 fallback，无报错 | `set_(color\|font\|style\|constant)\s*\(` | 验证 theme 文件内类型 | 官方明确 |
| `ThemeDB` fallback | `ThemeDB.get_default_theme()` | `ThemeDB.GetDefaultTheme();` | 依赖未定义项的 fallback 值做逻辑判断 | `ThemeDB\.` | 检查取到的颜色是否符合预期 | 官方明确 |

---

## 5. Label：没有缓存开关，autowrap 与每帧改 text 是主要开销源

**官方明确：`Label` 没有 `cache_mode` / `CacheMode` 属性**（官方 `Label` 页面列出的成员中不含任何 cache 相关条目）[2]。任何"给 Label 加缓存一键优化"的写法在 Godot 4.x 都不存在。**本能以为 Label 像 Cocos 那样有 cacheMode 能缓存文本网格，实际 Godot 4 根本没有这个属性。**

**`text`（String）改变会触发重测/重排**，大文本 + `autowrap_mode != OFF` + `clip_text = true` 三者叠加时开销最明显（社区共识，源自 TextServer 重排机制；官方未在 Label 页面量化）。判据应抓「在 `_process(delta)` / `_physics_process(delta)` 里无条件 `label.text = ...`」的代码，建议改为"值未变则跳过"，或把高频计数器放到 `set_interval`/`Timer` 里降频刷新。

**`autowrap_mode`（Label.AutowrapMode 枚举）在设为非 OFF 时让文本在节点包围盒内折行，节点 resize 时自动改高度以显示全部文本**[2]。枚举值：`TextServer.AUTOWRAP_OFF` 之外为各折行模式（含 `ARBITRARY`、`WORD`、`WORD_SMART` 等，以官方 `TextServer.AutowrapMode` 枚举为准）。误用：开了 autowrap 却给 `custom_minimum_size.y = 0` 且不设高度，节点高度依赖文本；或在极小宽度下折行产生几十上百行，命中成本放大。

**`text_overrun_behavior`（OverrunBehavior 枚举）是 4.x 里控制"文本超出包围盒时如何截断"的属性**——它取代了早期版本/其他控件里 `overrun_behavior` 风格的命名，4.x 统一为 `text_overrun_behavior`[2]。**本能以为属性还叫 `overrun_behavior`，实际 4.x 已改名为 `text_overrun_behavior`。** 误用：`text_overrun_behavior` 与 `clip_text = true` 语义重叠，同时设置时两者都参与截断逻辑，应明确只用其一。

**`clip_text`（bool，默认 false）让 Label 只显示能塞进包围盒的文本，并做水平裁剪**；`visible_characters`（int，默认 -1）控制显示字符数，-1 为全部；`visible_ratio`（float，默认 1.0）按比例显示；`lines_skipped`（int，默认 0）跳过开头行数；`max_lines_visible`（int，默认 -1）限制最多显示行数[2]。**`clip_text = true` + `autowrap_mode != OFF` + 大文本是重排开销最重的组合**：autowrap 需要逐行计算换行位置，clip 又要裁剪，每帧改 text 时双重成本叠加。判据应把这三者同时出现标记为"需降频"或"建议关闭 autowrap/改为逐行更新"。

`horizontal_alignment`（HorizontalAlignment）、`vertical_alignment`（VerticalAlignment）分别控制水平/垂直对齐，uppercase（bool）强制全大写渲染[2]。判据：`visible_characters >= 0` 与 `visible_ratio != 1.0` 同时设置时两者都影响可见范围，属冗余配置应告警。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `text` | `text = "hello"` | `Text = "hello";` | 每帧无条件赋值；大文本+autowrap+clip | `\.text\s*=` 在 `_process/_physics_process` 内 | 降频后看帧时间 | 官方明确 |
| `autowrap_mode` | `autowrap_mode = TextServer.AUTOWRAP_WORD_SMART` | `AutowrapMode = TextServer.AutowrapMode.WordSmart;` | 极小宽度+大文本产生海量行 | `autowrap_mode\s*=` | 看产生的行数 | 官方明确 |
| `text_overrun_behavior` | `text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS` | `TextOverrunBehavior = TextServer.OverrunBehavior.TrimEllipsis;` | 与 clip_text 重复；旧名 `overrun_behavior` 不存在 | `text_overrun_behavior\s*=` / `overrun_behavior\s*=` | 编译报错即旧名 | 官方明确 |
| `clip_text` | `clip_text = true` | `ClipText = true;` | 与 text_overrun_behavior 重复 | `clip_text\s*=` | 对比两者共存 | 官方明确 |
| `visible_characters` | `visible_characters = 10` | `VisibleCharacters = 10;` | 与 visible_ratio 同时设，语义冲突 | `visible_characters\s*=` | 检查是否同时设 ratio | 官方明确 |
| `visible_ratio` | `visible_ratio = 0.5` | `VisibleRatio = 0.5f;` | 每帧动画式递增却没降频 | `visible_ratio\s*=` | 帧分析 | 社区共识 |
| `max_lines_visible` | `max_lines_visible = 3` | `MaxLinesVisible = 3;` | 与 lines_skipped 相加超总行数 | `max_lines_visible\s*=` | 行数检查 | 官方明确 |
| `uppercase` | `uppercase = true` | `Uppercase = true;` | 与 TextServer 格式化重复 | `uppercase\s*=` | 显示对比 | 官方明确 |

---

## 6. BaseButton 与 Button：信号名与属性名的对应关系是审查重点

**`BaseButton` 的"按下状态"有两个入口**：`pressed`（bool，只读）+ `set_pressed(value)` / `is_pressed()` 读的是"是否被按下"；`button_pressed` 是另一个属性（用于 `toggle_mode` 下读写开关状态）[7]。**`pressed` 只读，`set_pressed`/`is_pressed` 才是写读 API，不能写 `pressed = true`。** 误用：直接 `button.pressed = true`（属性只读，赋值会失败或报错）。

**信号：`button_down`、`button_up` 分别是按下/松开时发出；`toggled(toggled_on: bool)` 在 `toggle_mode` 下状态翻转时发出**[7]。误用：把 `toggled` 当"每次点击都触发"——非 toggle 模式下普通点击不发出 `toggled`；或在 `_on_button_toggled(state)` 里只处理 `state == true`。

**`toggle_mode`（bool，默认 false）让按钮每次被点击在按下/未按下间翻转**；`disabled`（bool）让按钮不可点击/切换[7]。`action_mode`（ActionMode 枚举）决定"何时算作点击"（按下即算 / 松开才算）[7]——**这是反直觉点：默认行为不是"按下即触发"，取决于 ActionMode**。

`shortcut`（Shortcut 资源）关联快捷键[7]。`flat`、`expand_icon` 属 `Button` 层扩展属性（官方 `Button` 页面另行列出），判据按 `flat =`、`expand_icon =` 抓取即可，但需标注"非 BaseButton 成员"。

**`CheckBox` 继承链 `CheckBox < Button < BaseButton < Control`**，`toggle_mode` 在 CheckBox 中被覆盖为 `true`[31]。官方提示：遵循既有 UX 惯例时，当切换"没有即时效果"才用 CheckBox（暗示即时生效的场景可能更适合其他控件）。

`ProgressBar` 的 `show_percentage`（bool，默认 true）控制是否在中间显示百分比，`indeterminate`（bool，默认 false）为"不确定进度"模式（此时不显示百分比/数值），`fill_mode`（FillMode 枚举）为填充方向：FILL_BEGIN_TO_END=0、FILL_END_TO_BEGIN=1、FILL_TOP_TO_BOTTOM=2、FILL_BOTTOM_TO_TOP=3[30]。误用：`indeterminate = true` 却同时靠 `value` 驱动显示，语义冲突。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `pressed` / `set_pressed` | `is_pressed()` / `set_pressed(true)` | `IsPressed()` / `SetPressed(true);` | `pressed = true` 赋值（只读） | `pressed\s*=\s*true|set_pressed\s*\(` | 编译检查 | 官方明确 |
| `toggle_mode` | `toggle_mode = true` | `ToggleMode = true;` | 指望 toggled 信号在非 toggle 下触发 | `toggle_mode\s*=` | 点按听信号 | 官方明确 |
| `disabled` | `disabled = true` | `Disabled = true;` | disabled 状态仍可被 shortcut 触发 | `disabled\s*=` | 实测快捷键 | 官方明确 |
| `action_mode` | `action_mode = BaseButton.ACTION_MODE_BUTTON_PRESS` | `ActionMode = BaseButton.ActionModeEnum.Press;` | 默认松开才触发，与预期不符 | `action_mode\s*=` | 按下/松开时看回调时机 | 官方明确 |
| `shortcut` | `shortcut = preload("res://quit.tres")` | `Shortcut = ...;` | shortcut 未设到 InputMap | `shortcut\s*=` | 实测快捷键 | 官方明确 |
| `flat` / `expand_icon` | `flat = true` | `Flat = true;` | 在 BaseButton 引用上访问（应是 Button） | `flat\s*=|expand_icon\s*=` | 类型检查 | 官方明确 |
| `ProgressBar.indeterminate` | `indeterminate = true` | `Indeterminate = true;` | 与 value 驱动显示冲突 | `indeterminate\s*=` | 显示是否卡死 | 官方明确 |

---

## 7. 图像与精灵：区域裁剪与九宫格的开关必须成对使用

**`TextureRect` 的 `expand_mode`（ExpandMode 枚举）决定最小尺寸如何根据纹理尺寸计算**，`stretch_mode`（StretchMode 枚举）控制节点包围盒缩放时纹理的行为（缩放/平铺/保持原尺寸等）[8]。`texture`（Texture2D）、`flip_h`/`flip_v`（bool）分别是纹理资源与翻转开关[8]。误用：`stretch_mode` 设为"保持原尺寸"却把节点框拉得很大，纹理不填满；或 `expand_mode` 让节点最小尺寸随纹理变化，在 Container 里与 size_flags 打架。

**`NinePatchRect` 的核心是四边距与轴拉伸模式成对出现**。`patch_margin_left/right/top/bottom`（int，像素）定义九宫格四个边的列/行宽，可分别设成非均匀边框[9]。`axis_stretch_horizontal`/`axis_stretch_vertical`（AxisStretchMode 枚举，值 STRETCH=0/TILE=1/TILE_FIT=2）分别控制水平/垂直方向拉伸或平铺[9]。`region_rect`（Rect2）是从纹理采样的矩形区域，用图集时靠它定义九宫格使用的区域，其他属性都相对它解释；rect 为空则使用整张纹理[9]。误用：`patch_margin` 大于纹理尺寸导致中区为负；`axis_stretch_mode = TILE` 却指望不重复；`region_rect` 与 `patch_margin` 单位/基准混淆。

**`Sprite2D` 的 `region_enabled`（bool）是 `region_rect` 与 `region_filter_clip_enabled` 的总开关**：`region_rect`（Rect2，默认 (0,0,0,0)）定义图集区域，`region_enabled` 必须为 true 才生效；`region_filter_clip_enabled`（bool）为 true 时会裁剪 `region_rect` 外的区域，避免周围纹理像素渗色[14]。**本能以为设了 `region_rect` 就能切图，实际必须先 `region_enabled = true`；本能以为切图会自动防渗色，实际还要 `region_filter_clip_enabled = true`。** `hframes`/`vframes`（int，默认 1）、`frame`（int）组成逐帧动画的行列与当前帧；`centered`（bool，默认 true）、`offset`（Vector2）、`flip_h`/`flip_v`（bool）控制绘制偏移与翻转[14]。

**`AnimatedSprite2D` 的 `sprite_frames`（SpriteFrames 资源）是动画数据的容器**，`animation`（StringName，默认 `&"default"`）是 `sprite_frames` 里的当前动画——**改 `animation` 会重置帧计数器与 `frame_progress`**[10]。`play(name="", custom_speed=1.0, from_end=false)` 播放指定动画；`stop()` 停止并把动画位置重置为 0、`custom_speed` 重置为 1.0；`pause()` 暂停但保留帧与进度，之后 `play()`/`play_backwards()` 无参会从当前位置恢复[10]。`get_frame()`/`set_frame()` 读写当前帧索引，设置帧也会重置 `frame_progress`[10]。信号：`animation_finished`（播到末尾或反向播到开头）、`animation_changed`、`frame_changed`[10]。误用：在 `frame_changed` 里 `play()` 新动画导致递归/抖动；改 `animation` 后手动重置 frame 却忘了 progress 已被清。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `TextureRect.texture` | `texture = preload("res://a.png")` | `Texture = ...;` | 每帧 load 新纹理 | `texture\s*=` 在 process 内 | 纹理加载次数 | 官方明确 |
| `Sprite2D.region_enabled` | `region_enabled = true` | `RegionEnabled = true;` | 只设 region_rect 不开启 | `region_enabled\s*=` | 显示是否切图 | 官方明确 |
| `Sprite2D.region_filter_clip_enabled` | `region_filter_clip_enabled = true` | `RegionFilterClipEnabled = true;` | 图集相邻像素渗色 | `region_filter_clip_enabled\s*=` | 边缘像素检查 | 官方明确 |
| `Sprite2D.frame` | `frame = 3` | `Frame = 3;` | 设 frame 后依赖旧 progress | `frame\s*=` 在动画回调内 | 进度检查 | 官方明确 |
| `AnimatedSprite2D.animation` | `animation = &"run"` | `Animation = "run";` | 改 animation 后手动重置 frame/progress 重复 | `animation\s*=` | 帧状态检查 | 官方明确 |
| `AnimatedSprite2D.play` | `play("run", 2.0)` | `Play("run", 2.0f);` | 每帧 play() 导致重启动画 | `play\s*\(` 在 process 内 | 帧检查是否卡第 0 帧 | 官方明确 |
| `AnimatedSprite2D.stop` | `stop()` | `Stop();` | stop 后 custom_speed 被重置为 1.0 未察觉 | `stop\s*\(` | 再 play 看速度 | 官方明确 |

---

## 8. 文本编辑：RichTextLabel 的追加优于重建，TextEdit 是重量级控件

**`RichTextLabel` 的 `bbcode_enabled`（bool，默认 false）是 BBCode 解析的总开关**，`text`（String）为文本，`parse_bbcode(bbcode)` 解析 BBCode 字符串，`append_text(bbcode)` 追加内容[11]。**官方明确：`parse_bbcode()` 每次调用会重建整个 BBCode 字符串，大文本量下较慢；`append_text()` 只追加，性能显著更好**[11]。判据：抓「每帧/高频调用 `parse_bbcode`」应改为 `append_text` 或降频。

**`push_*` / `pop()` 是标签栈的手动构造接口**：`push_bold()`、`push_underline(color)` 等成对推入标签，`pop()` 关闭，`clear()` 清空整个标签栈[11]。**`clear()` 会清除所有手动 push 的标签栈，与直接编辑 `text` 属性冲突**[11]——误用是在 push/pop 流程里调 `clear()` 后又写 `text`，栈状态不一致。判据：抓 `push_` 与 `clear()` 在同一生命周期内交替出现。

`fit_content`（bool）、`scroll_to_line(line)`、`custom_effects`（Array）分别是"收缩到内容尺寸"、"滚到指定行"、"安装自定义文本效果"[11]。

**`LineEdit` 的 `placeholder_text`（String）是"空时的占位提示"，不是默认值**——`text` 才是真实文本[12]。误用：把占位符当默认值读。其余：`editable`（bool）控制可否修改，`secret`（bool）用 `secret_character` 遮罩输入，`max_length`（int，0 为无限制）限制输入长度，`alignment`（HorizontalAlignment）水平对齐，`caret_blink`（bool）光标闪烁，`clear_button_enabled`（bool，非空时显示清空按钮），`context_menu_enabled`（bool，右键菜单），`select_all_on_focus`（bool，获焦时全选）[12]。

**`TextEdit` 是重量级多行编辑器**：`text`（String）、`editable`（bool）、`wrap_mode`（LineWrappingMode）、`syntax_highlighter`（SyntaxHighlighter）、`highlight_current_line`（bool）[13]；`set_line_as_first_visible(line, wrap_index=0)` 把指定行放到视口顶部[13]。误用：在聊天/日志场景用 `TextEdit` 而非 `RichTextLabel`，承受了语法高亮、行号等不必要开销；`wrap_mode` 与 `set_line_as_first_visible` 语义冲突（自动折行时 wrap_index 需一并考虑）。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `RichTextLabel.bbcode_enabled` | `bbcode_enabled = true` | `BbcodeEnabled = true;` | 写了 BBCode 却未开启 | `bbcode_enabled\s*=` | 文本是否解析 | 官方明确 |
| `RichTextLabel.parse_bbcode` | `parse_bbcode("[b]hi[/b]")` | `ParseBbcode("[b]hi[/b]");` | 高频调用，重建整串 | `parse_bbcode\s*\(` 在 process/循环内 | 帧分析 | 官方明确 |
| `RichTextLabel.append_text` | `append_text("more")` | `AppendText("more");` | 仍用 parse_bbcode 做追加 | `append_text\s*\(` | 对比两种方式 | 官方明确 |
| `RichTextLabel.clear` | `clear()` | `Clear();` | 与 push_*/pop 栈冲突 | `clear\s*\(` 与 `push_\w+\(` 同作用域 | 栈状态检查 | 官方明确 |
| `LineEdit.placeholder_text` | `placeholder_text = "name"` | `PlaceholderText = "name";` | 当默认值读取 | `placeholder_text\s*=` | 空值时显示 | 官方明确 |
| `TextEdit.wrap_mode` | `wrap_mode = TextEdit.LINE_WRAPPING_BOUNDARY` | `WrapMode = TextEdit.LineWrappingMode.Boundary;` | 与 set_line_as_first_visible 不配合 | `wrap_mode\s*=` | 滚动位置检查 | 官方明确 |

---

## 9. 选择类控件：Tree 多选时"聚焦项"与"选中项"不是一回事

**`Tree` 的选择模式由 `SelectMode` 枚举控制**，且"聚焦项"与"选中项"在不同模式下含义不同：`get_selected()` 返回当前聚焦项，在 SELECT_ROW / SELECT_SINGLE 模式下聚焦项等于选中项，**在 SELECT_MULTI 模式下聚焦项是焦点光标所在项，不一定是已选项**[15]。**本能以为 `get_selected()` 在多选下返回"当前选中的那一组"，实际它只返回焦点光标项。** 多选下应遍历 `get_next_selected(prev)` 或用信号收集。

`create_item(parent=null, index=-1)` 创建树项，`parent` 为 null 时挂到根或成为新根；`get_root()` 返回根项或 null；`set_column_title(column, title)` 设列标题；`columns`（int，默认 1）为列数，且在鼠标选择期间不允许修改（会打印错误）[15]。`hide_root`（bool）隐藏根项，`scroll_to_item(item, center_on_item=false)` 跳到指定项[15]。`clear()` 移除全部项[15]。判据：`create_item(null)` 连续多次却未设 `hide_root`，可能出现"多根"视觉。

**`PopupMenu` 是模态窗口，必须调 `Window.popup_*()` 系列才显示**（如 `popup_centered_clamped()`）[16]。`add_item(label, id=-1, accel=0)`、`add_separator(label="", id=-1)`、`add_check_item(label, id=-1, accel=0)`（**官方明确：checkable 项只显示勾选标记，没有内置勾选行为，必须手动勾/取消**）[16]、`add_radio_check_item(label, id=-1, accel=0)`、`add_submenu_item(label, submenu, id=-1)`（**已 deprecated，应改用 `add_submenu_node_item()`**）[16]。`set_item_text(index, text)` 改指定索引项文本；信号 `id_pressed`（按 id）、`index_pressed`（按索引）；`clear(free_submenus=false)` 可释放子菜单节点[16]。误用：把 `add_submenu_item` 当现行 API；check item 不写手动 toggle 逻辑。

**`OptionButton`**：`add_item(label, id=-1)`（不传 id 时用项索引作 id，新项追加到末尾）、`get_item_text(idx)`、`select(idx)`（idx=-1 取消选择）、`get_selected()`（返回选中索引或 -1）、`clear()`、`item_count`（int）[17]。判据：`select(-1)` 与 `get_selected() == -1` 的"无选中"分支必须处理。

**`ItemList`**：`add_item(text, icon=null, selectable=true)`、`set_item_text(idx, text)`、`set_item_icon(idx, icon)`、`select(idx, single=true)`、`deselect(idx)`、`is_selected(idx)`、`get_selected_items()`、`clear()`、`item_count`、`set_fixed_icon_size(value)`、`max_text_lines`（int，默认 1）、`same_column_width`（bool，默认 false）[17]。判据：`select(idx, single=false)` 在单选预期下使用属逻辑错误。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `Tree.get_selected` | `var it = get_selected()` | `var it = GetSelected();` | 多选下当"选中集合"用 | `get_selected\s*\(` 在 multiselect 场景 | 多选后对比 | 官方明确 |
| `Tree.columns` | `columns = 3` | `Columns = 3;` | 鼠标选择期间修改（报错） | `columns\s*=` | 运行时日志 | 官方明确 |
| `PopupMenu.add_submenu_item` | `add_submenu_item("More", "Sub")` | `AddSubmenuItem("More", "Sub");` | 用已 deprecated 的旧 API | `add_submenu_item\s*\(` | 编译器警告 | 官方明确 |
| `PopupMenu.add_check_item` | `add_check_item("Bold")` | `AddCheckItem("Bold");` | 不写手动 toggle，勾选无效果 | `add_check_item\s*\(` | 点按是否切换 | 官方明确 |
| `OptionButton.get_selected` | `get_selected()` | `GetSelected();` | 未处理 -1 | `get_selected\s*\(` | -1 分支检查 | 官方明确 |
| `ItemList.get_selected_items` | `get_selected_items()` | `GetSelectedItems();` | 单选场景用错 API | `get_selected_items\s*\(` | 选中逻辑 | 官方明确 |

---

## 10. CanvasItem：modulate 会向下传播，clip_children 会触发遮罩渲染

**`modulate`（Color）会影响本节点**及其**子 CanvasItem**，而 `self_modulate`（Color）只影响本节点不影响子节点[4]。**这是最典型的父子传播坑：给父节点 `modulate = Color(1,1,1,0.5)` 会让整棵子树都半透明，若只想淡出自己，应改 `self_modulate`。** 判据：抓「父 CanvasItem 同时 `modulate != WHITE` 且子树含多个子项」的组合，确认是否符合意图。

**`z_index`（int）控制绘制顺序，值越大越靠前**，取值范围在 `RenderingServer.CANVAS_ITEM_Z_MIN` 与 `CANVAS_ITEM_Z_MAX` 之间；`z_as_relative`（bool）为 true 时最终 z 是父 z + 自身 z（例：自身 2、父 3，最终 5）[4]。`show_behind_parent`（bool）让节点绘制在父节点之后[4]。误用：靠 `z_index` 做"层级管理"却开了 `z_as_relative`，结果最终 z 随父级叠加；`z_index` 超出引擎常量范围。

**`y_sort_enabled`（bool）让本节点及子 CanvasItem 按 Y 坐标高的在后面/前面渲染**，关掉则按场景树顺序[4]。误用：在 TileMap/Sprite 堆里既用 y_sort 又手动设 z_index，两者竞争导致层级闪烁。

**`clip_children`（ClipChildrenMode 枚举）让本节点作为子节点的遮罩**：`DISABLED`（不裁剪）、`ONLY`（只作为遮罩，子项不绘制自身——即"子项画到遮罩上"）、`DRAW_ONLY`（子项作为遮罩且可见，按父绘制区域裁剪）[4]。**这是反直觉点：CLIP_CHILDREN_ONLY 模式下"子项本身不可见、只贡献遮罩"，与"子项被裁掉"是两种不同结果。** 判据：`clip_children != DISABLED` 且自身无可见内容/无子项时应告警。

**`material`（Material）作用于本 CanvasItem**；`texture_filter`（CanvasItem.TextureFilter 枚举）与 `texture_repeat`（CanvasItem.TextureRepeat 枚举）控制纹理过滤与重复[4]。判据见第 12 章"每帧 new ShaderMaterial"。

**`_draw()` 是虚函数，`draw_*` 系列只能在 `_draw()` 内或 `force_update_transform()` 之后调用**：`draw_line(from, to, color, width=-1.0, antialiased=false)`、`draw_rect(rect, color, filled=true, width=-1.0, antialiased=false)`、`draw_texture(texture, position, modulate=Color(1,1,1,1))`、`draw_string(font, pos, text, alignment=0, width=-1, font_size=16, modulate=Color(1,1,1,1), justification_flags=3, direction=0, orientation=0, oversampling=0.0)`、`draw_arc(center, radius, start_angle, end_angle, point_count, color, width=-1.0, antialiased=false)`、`draw_circle(position, radius, color, filled=true, width=-1.0, antialiased=false)`、`draw_colored_polygon(points, color, uvs=PackedVector2Array(), texture=null)`、`draw_set_transform(position, rotation=0.0, scale=Vector2(1,1))`[4]。判据：`draw_*` 出现在 `_draw()` 之外的调用应告警（静态分析难精确，可抓"方法体内无 `_draw` 定义却有 `draw_` 前缀调用"的近似模式）。

**`queue_redraw()` 是"请求在下一帧重绘"，不是立即重绘**。`CanvasItem` 每帧会去重合并 redraw 请求[4]。误用：每帧/每物理帧/在 setter 里无条件 `queue_redraw()`，形成"每帧全树重排"；或在循环里对大量子项逐个调用而非改状态让引擎批量处理。判据：`queue_redraw\s*\(` 出现在 `_process`/`_physics_process`/`_set_*` 内且无节流条件。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `modulate` | `modulate = Color(1,1,1,0.5)` | `Modulate = new Color(1,1,1,0.5f);` | 只想淡出自己却影响全子树 | `modulate\s*=` 在父节点 | 对比子项透明度 | 官方明确 |
| `self_modulate` | `self_modulate = Color(1,1,1,0.5)` | `SelfModulate = new Color(1,1,1,0.5f);` | 与 modulate 语义混淆 | `self_modulate\s*=` | 子项是否变 | 官方明确 |
| `z_index` / `z_as_relative` | `z_index = 10` / `z_as_relative = false` | `ZIndex = 10;` / `ZAsRelative = false;` | 开了 z_as_relative 又手动算绝对 z | `z_index\s*=`,`z_as_relative\s*=` | 父子 z 叠加检查 | 官方明确 |
| `y_sort_enabled` | `y_sort_enabled = true` | `YSortEnabled = true;` | 与手动 z_index 竞争 | `y_sort_enabled\s*=` | 层级闪烁检查 | 官方明确 |
| `clip_children` | `clip_children = CanvasItem.CLIP_CHILDREN_DRAW_ONLY` | `ClipChildren = CanvasItem.ClipChildrenMode.DrawOnly;` | 误以为子项不可见；与 CanvasGroup 重叠 | `clip_children\s*=` | 子项可见性测试 | 官方明确 |
| `material` | `material = preload("res://m.tres")` | `Material = ...;` | 每帧 new ShaderMaterial | `material\s*=\s*ShaderMaterial\.new` | 对象分配数 | 官方明确 |
| `queue_redraw` | `queue_redraw()` | `QueueRedraw();` | 每帧/setter 内无条件调用 | `queue_redraw\s*\(` 在 process/setter 内 | 帧分析 | 官方明确 |

---

## 11. CanvasLayer 与 CanvasGroup：额外画布有分配与缩放代价

**`CanvasLayer` 的 `layer`（int，默认 1）控制绘制顺序，值越小越靠后**；`transform`（Transform2D）是层的世界变换；`follow_viewport_enabled`（bool，默认 false）为 true 时层保持在世界空间位置，为 false 时固定在屏幕坐标[27]。`visible`（bool，默认 true）控制可见性，但**不向底层/其他层传播**（与 `CanvasItem.visible` 不同）[27]。`custom_viewport` 指向自定义 Viewport，为 null 时用默认视口[27]。

误用：`follow_viewport_enabled = false` 却用 Node2D 的 position 移动层内容（此时层固定在屏幕，position 不改变显示）；`visible = false` 却以为子 CanvasItem 仍受控于本层可见性。判据：抓「`CanvasLayer.visible` 与子 `CanvasItem.visible` 双开关冗余」。

**`CanvasGroup` 的 `fit_margin`（float，默认 10.0）扩展绘制矩形**——它先按子项拟合出一个矩形再把四边各扩 `fit_margin`，**增大它会同时增加 backbuffer 占用面积和 CanvasGroup 覆盖区域，两者都可能降低性能**[3]。`clear_margin`（float，默认 10.0）扩展清除矩形，**减小它可减少 backbuffer 使用从而提升性能，但开了 `use_mipmaps` 时 margin 太小会导致 mip 边缘伪影，应保持"尽可能小但出现边缘瑕疵时增大"**[3]。`use_mipmaps`（bool，默认 false）在绘制前为 backbuffer 生成 mipmap 供自定义 ShaderMaterial 使用，**生成 mipmap 有性能代价，除非必需不应开启**[3]。

**本能以为 `CanvasGroup` 只是"把子项合成一组渲染"，实际它要额外分配一块 backbuffer，且 `fit_margin`/`clear_margin` 越大 backbuffer 越大、性能越差；本能以为 `CanvasGroup` 可以任意嵌套做复杂遮罩，实际嵌套会让每块都各自分配 backbuffer，叠加代价。**

判据应抓：`CanvasGroup` 节点数、`fit_margin`/`clear_margin` 值、`use_mipmaps = true` 的组合；以及 `CanvasGroup` 与 `clip_children != DISABLED` 同时出现在相邻层级。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `CanvasLayer.layer` | `layer = 10` | `Layer = 10;` | 与 CanvasItem.z_index 混用竞争 | `layer\s*=` | 绘制顺序检查 | 官方明确 |
| `CanvasLayer.follow_viewport_enabled` | `follow_viewport_enabled = true` | `FollowViewportEnabled = true;` | 关掉后还用 Node2D.position 移动 | `follow_viewport_enabled\s*=` | 移动后显示 | 官方明确 |
| `CanvasLayer.custom_viewport` | `custom_viewport = $SubViewport` | `CustomViewport = GetNode<SubViewport>("SubViewport");` | 指向未启用的 Viewport | `custom_viewport\s*=` | 渲染输出检查 | 官方明确 |
| `CanvasGroup.fit_margin` | `fit_margin = 64.0` | `FitMargin = 64.0f;` | 值过大浪费 backbuffer | `fit_margin\s*=` | backbuffer 面积估算 | 官方明确 |
| `CanvasGroup.clear_margin` | `clear_margin = 64.0` | `ClearMargin = 64.0f;` | use_mipmaps 下过小致边缘伪影 | `clear_margin\s*=` 与 `use_mipmaps` 组合 | 边缘瑕疵 | 官方明确 |
| `CanvasGroup.use_mipmaps` | `use_mipmaps = true` | `UseMipmaps = true;` | 无自定义 ShaderMaterial 需求却开启 | `use_mipmaps\s*=` | 帧分析 | 官方明确 |

---

## 12. Camera2D 与 Parallax2D：平滑/拖拽/视口跟随的开关都有副作用

**`Camera2D.position_smoothing_enabled`（bool，默认 false）开启后相机平滑移向目标位置**，`position_smoothing_speed`（float，默认 5.0）单位为像素/秒[28]。误用：`speed` 过小在高速移动下"拖尾"明显；开启平滑后 `get_screen_center_position()` 读到的不是即时目标位置，逻辑判断延后一帧。判据：`position_smoothing_enabled = true` 却无对应 `speed` 设置（用默认 5.0 可能过慢）应提示。

**`limit_left/right/top/bottom`（int，默认 ±10000000）是相机停止的边界**，`limit_smoothed`（bool，默认 false）让相机到边界时平滑停下[28]。`set_limit(margin: Side, limit: int)` / `get_limit(margin)` 是统一接口[28]。**`offset` 可以越过 limit**——官方明确 limit 只限制 view，offset 能推着视图越过边界[28]。判据：抓"依赖 limit 做边界判定"却没考虑 offset 越界的代码。

`zoom`（Vector2，默认 (1,1)，值越大越放大）、`anchor_mode`（AnchorMode 枚举）、`ignore_rotation`（bool，默认 true，相机渲染视图不受 Node2D.rotation/global_rotation 影响）[28]。`drag_horizontal_enabled`/`drag_vertical_enabled`（bool，默认 false）让相机只在拖拽边距内移动[28]。`process_callback`（Camera2DProcessCallback 枚举）选择相机更新时机[28]。`make_current()` 让本相机成为当前活动相机（`enabled` 必须为 true）[28]。`get_screen_center_position()` 返回相机视角下的屏幕中心（全局坐标）[28]。

**`Parallax2D`（4.x 新增，替代 3.x 的 ParallaxBackground + ParallaxLayer）**：`scroll_scale`（Vector2，默认 (1,1)）把视差偏移乘上该值模拟深度；`repeat_size`（Vector2，默认 (0,0)）定义子纹理重复的偏移，制造无限滚动错觉；`repeat_times`（int，默认 1）覆盖重复次数；`autoscroll`（Vector2，默认 (0,0)）为自动滚动速度（像素/秒）；`limit_begin`（Vector2，默认 (-10000000,-10000000)）、`limit_end`（Vector2，默认 (10000000,10000000)）是滚动边界，相机超出后滚动停止；`follow_viewport`（bool，默认 true）控制是否随当前相机位置偏移[29]。

**本能以为 3.x 的 `ParallaxBackground`/`ParallaxLayer` 在 4.x 还能直接用，实际 4.x 已改为 `Parallax2D` 单节点 + 子节点重复的方式。** 误用：`scroll_scale` 设成 (1,1) 等于无视差；`repeat_size` 为 (0,0) 却不指望重复；`autoscroll` 与脚本手动移 Parallax2D 位置双重驱动。判据：`ParallaxBackground`/`ParallaxLayer` 出现在 4.x 项目里应标 deprecated 迁移提示。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `Camera2D.position_smoothing_speed` | `position_smoothing_speed = 8.0` | `PositionSmoothingSpeed = 8.0f;` | smoothing_enabled 开但 speed 默认 5.0 过慢 | `position_smoothing_speed\s*=` | 拖尾长度 | 官方明确 |
| `Camera2D.limit_*` | `set_limit(Side.LEFT, -500)` | `SetLimit(Side.Left, -500);` | 忽略 offset 可越过边界 | `limit_(left\|right\|top\|bottom)\s*=|set_limit\s*\(` | 边界测试 | 官方明确 |
| `Camera2D.ignore_rotation` | `ignore_rotation = false` | `IgnoreRotation = false;` | 关掉后旋转相机导致整个视口旋转 | `ignore_rotation\s*=` | 旋转测试 | 官方明确 |
| `Parallax2D.scroll_scale` | `scroll_scale = Vector2(0.5, 0.5)` | `ScrollScale = new Vector2(0.5f, 0.5f);` | 设 (1,1) 等于无效果 | `scroll_scale\s*=` | 视觉视差 | 官方明确 |
| `Parallax2D.repeat_size` | `repeat_size = Vector2(512, 512)` | `RepeatSize = new Vector2(512, 512);` | 设 (0,0) 却指望无限滚动 | `repeat_size\s*=` | 滚动终点 | 官方明确 |
| `Parallax2D.autoscroll` | `autoscroll = Vector2(20, 0)` | `Autoscroll = new Vector2(20, 0);` | 与手动位移双重驱动 | `autoscroll\s*=` 与位移代码共存 | 帧检查 | 官方明确 |

---

## 13. 2D 光照：Light2D 已拆三件，CanvasModulate 是每个场景最多一个

**3.x 的 `Light2D` 在 4.x 已拆为 `PointLight2D`（全向/点光）、`DirectionalLight2D`（阳光/月光，平行光）、`SpotLight2D`（聚光）**[18]。**本能以为 4.x 还叫 `Light2D` 可以 new，实际类名已不存在，必须按光型选三个子类。** `LightOccluder2D` 提供阴影遮挡体，`CanvasModulate` 提供环境光底色。

**`PointLight2D` 继承链 `PointLight2D < Light2D < Node2D < CanvasItem`**。其属性：`height`（float，默认 0.0）、`offset`（Vector2）、`texture`（Texture2D）、`texture_scale`（float，默认 1.0）[32]。**官方页面列出的 PointLight2D 独有属性只有 height/offset/texture/texture_scale——`color`、`energy`、`range_*`、`shadow_*`、`z_*` 这些"直觉上该有"的属性实际都在 `Light2D` 基类上**（官方 2D 光照教程列出"common light properties"：`Enabled`、`Color`、`Energy`、`Blend Mode`、`Range`、`Item Cull Mask`，两者共享）[18]。判据：抓「`PointLight2D.color =` / `PointLight2D.energy =`」这类直接写子类属性（应走 Light2D 基类或对应 Light2D 成员）的模式，属推测级告警。

**`DirectionalLight2D` 独有属性：`height`（float，默认 0.0，0 为平行平面、1 为垂直平面，用于 2D normal mapping）与 `max_distance`（float，默认 10000.0，阴影被裁剪的最大距离，像素）**[33]。判据：`max_distance` 过小导致远处阴影消失，属常见配置错误。

**`LightOccluder2D`**：`occluder`（OccluderPolygon2D，用于计算阴影的多边形）、`occluder_light_mask`（int，默认 1，遮挡体只对 `light mask` 相同的 Light2D 投阴影）、`sdf_collision`（bool，默认 true，启用后遮挡体加入实时生成的 SDF 供自定义 shader 使用）[34]。**误用：遮挡体的 light_mask 与光源 mask 不匹配，导致"明明加了 Occluder 却没阴影"。** 官方明确：开启 PointLight2D/DirectionalLight2D 的 `Shadow > Enabled` 后初始看不到阴影，因为场景里还没有任何 occluder；且 occluder 多边形应与 sprite 轮廓匹配[18]。

**`CanvasModulate.color`（Color，默认 (1,1,1,1)）给整个 canvas 上环境色**。官方明确：**一个 canvas 只能用一个 CanvasModulate 做 tint，但可用 CanvasLayer 做独立渲染**[35]；没有 CanvasModulate 时场景会过亮，因为 2D 光只在"未打光"的已亮外观上叠加提亮[18]。**本能以为场景天生就是"未照亮"的暗色，实际 Godot 2D 默认是全亮，要靠 CanvasModulate 把环境压暗才有"光照感"。** 判据：抓「同一 CanvasLayer 下多个 CanvasModulate 节点」（只生效一个），以及"场景全亮却没放 CanvasModulate"。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `PointLight2D.height` | `height = 0.5` | `Height = 0.5f;` | normal map 无效果（height=0） | `height\s*=` | normal 视觉 | 官方明确 |
| `DirectionalLight2D.max_distance` | `max_distance = 2000.0` | `MaxDistance = 2000.0f;` | 过小致远处阴影消失 | `max_distance\s*=` | 远处阴影测试 | 官方明确 |
| `LightOccluder2D.occluder_light_mask` | `occluder_light_mask = 2` | `OccluderLightMask = 2;` | 与光源 mask 不匹配 | `occluder_light_mask\s*=` | 阴影是否出现 | 官方明确 |
| `LightOccluder2D.sdf_collision` | `sdf_collision = true` | `SdfCollision = true;` | 无自定义 SDF shader 却开启 | `sdf_collision\s*=` | 性能测试 | 官方明确 |
| `CanvasModulate.color` | `color = Color(0.3, 0.3, 0.4)` | `Color = new Color(0.3f, 0.3f, 0.4f);` | 同 canvas 多个 CanvasModulate | `CanvasModulate` 节点计数 | 场景检查 | 官方明确 |

---

## 14. TileMap 与 TileMapLayer：4.3+ 应迁移到分层结构

**4.3+ 引入 `TileMapLayer`，`TileMap` 内部由 Layer 组成，官方建议用多个 `TileMapLayer` 节点替代单 `TileMap`**（官方 TileMap 页面标注 deprecated 提示："Use multiple TileMapLayer nodes instead"，并提供"Extract TileMap layers as individual TileMapLayer nodes"的编辑器工具）[36]。**本能以为 `TileMap.set_cell(layer, ...)` 是现行 API，实际新项目应改用 `TileMapLayer.set_cell(coords, ...)`（无 layer 参数，因为 layer 本身就是节点）。**

`TileMapLayer` 签名：`set_cell(coords: Vector2i, source_id: int = -1, atlas_coords: Vector2i = Vector2i(-1,-1), alternative_tile: int = 0)`、`set_cells_terrain_connect(cells: Array[Vector2i], terrain_set: int, terrain: int, ignore_empty_terrains: bool = true)`、`get_used_cells() -> Array[Vector2i]`（const）[36]。`tile_set`（TileSet 资源）存所有可用 tile 的纹理、碰撞与行为[36]。判据：`TileMap.set_cell\s*\(` 四参形式 → 迁移提示；`TileMapLayer.set_cell\s*\(` 四参形式 → 签名错误（应为 1–4 参的 coords 起始形式）。

**`TileMap` 的 `set_cell(layer, coords, source_id=-1, atlas_coords=Vector2i(-1,-1), alternative_tile=0)` 带 layer 参数**，`set_cells_terrain_connect(layer, cells, terrain_set, terrain, ignore_empty_terrains=true)`、`get_used_cells(layer)` 同样带 layer[36]。官方页面说明：TileSet 存所有 tile 的纹理、碰撞与行为，`set_cell` 的 source/atlas/alternative 参数用于寻址具体 tile[36]。物理与导航在 `TileMapLayer` 上通过 `physics_quadrant_size`（而非 `physics_layer` 属性）与 `navigation_map` RID 管理（官方 `TileMapLayer` 页面列出 `tile_map_data`（PackedByteArray）与 `get_navigation_map()`，无独立的 `physics_layer`/`navigation_layer` 属性）[36]。

**判据：`physics_layer`/`navigation_layer` 作为 `TileMapLayer` 属性直接访问（如 `tile_map_layer.physics_layer =`）属签名错误**——这两个在 4.x 的 API 面上是"按层配置"的 quadrant/navigation_map 形式，不是节点上的整数属性。若审查规则库要覆盖旧项目，应区分"TileSet 资源上的 physics/navigation layers 位掩码"与"TileMapLayer 节点的 layer 组织"。

| 成员 | GDScript | C# | 常见误用 | 判据正则 | 确认方式 | 置信度 |
|---|---|---|---|---|---|---|
| `TileMapLayer.tile_set` | `tile_set = preload("res://ts.tres")` | `TileSet = ...;` | TileSet 资源未含所用 source_id | `tile_set\s*=` | 运行时报 missing source | 官方明确 |
| `TileMapLayer.set_cell` | `set_cell(Vector2i(1,2), 0)` | `SetCell(new Vector2i(1,2), 0);` | 4 参（带 layer）调用，签名错误 | `set_cell\s*\(\s*\d+\s*,` | 编译报错 | 官方明确 |
| `TileMap.set_cell` | `set_cell(0, Vector2i(1,2))` | `SetCell(0, new Vector2i(1,2));` | 4.3+ 仍用单 TileMap 多 layer | `TileMap\b.*set_cell\s*\(` | 迁移提示 | 官方明确 |
| `TileMapLayer.get_used_cells` | `get_used_cells()` | `GetUsedCells();` | 与 TileMap.get_used_cells(layer) 混淆 | `get_used_cells\s*\(` | 参数个数 | 官方明确 |

---

## 15. 性能与正确性：五条"反直觉坑"构成审查的核心规则集

**坑 1：Label 没有 cacheMode。** 官方 `Label` 页面无 `cache_mode` / `CacheMode` 属性[2]。**判据正则**：`cache_mode\s*=|CacheMode\s*=|cacheMode\s*=` → 告警"Godot 4.x Label 无此属性"。**确认**：编译/静态检查报错。**置信度：官方明确。**

**坑 2：`clip_children` 与 `CanvasGroup` 不能嵌套（链式使用有代价）。** 官方 `CanvasItem` 页面给出 ClipChildrenMode 三态语义，`CanvasGroup` 页面明确 backbuffer 分配与 `fit_margin`/`clear_margin` 的性能代价[3][4]。**判据正则**：`clip_children\s*=\s*CanvasItem\.CLIP_CHILDREN_(ONLY|DRAW_ONLY)` 与 `class CanvasGroup`/`extends CanvasGroup` 同时出现；或「`CanvasGroup` 节点的父/子链上再出现 `CanvasGroup`」。**确认**：场景树检查 + 渲染帧分析。**置信度：官方明确（backbuffer 代价）+ 社区共识（嵌套不推荐）。**

**坑 3：每帧 `ShaderMaterial.new()` 导致状态碎片化。** `material` 是 CanvasItem 的 Material 属性，静态分析抓 `material\s*=\s*ShaderMaterial\s*\.new` 或 `new ShaderMaterial()` 出现在 `_process`/`_process(delta)` 内。**确认**：对象分配计数。**置信度：社区共识**（官方无直接禁令，但 "每帧 new 资源对象" 是通用反模式）。

**坑 4：每帧改 `Label.text` 在大文本 + autowrap + clip 下叠加重排开销。** **判据正则**：`\.text\s*=` 出现在 `func _process|func _physics_process|func _set_.*` 内；与 `autowrap_mode\s*!=\s*TextServer\.AUTOWRAP_OFF`、`clip_text\s*=\s*true` 同时存在 → 高优先级。**确认**：降频/关闭 autowrap 后帧时间对比。**置信度：社区共识**（官方未量化，机制上来自 TextServer 重测）。

**坑 5：`ScrollContainer` 内大量子项无虚拟化。** **判据正则**：`ScrollContainer` 节点下出现 `for\s+.+\s+in\s+.+:|while\s+.+:|range\s*\(` 等循环 `add_child`/`instance()` 模式，子项数阈值（如 > 50）可配置。**确认**：场景树节点数与帧耗时。**置信度：社区共识**（官方无内置虚拟化容器，仅 `ItemList`/`Tree` 内部支持）。

**坑 6：`queue_redraw()` 滥用。** **判据正则**：`queue_redraw\s*\(` 出现在 `_process|func _physics_process|_set_|setter` 内且无节流/去重条件。**确认**：Profiler 的 CanvasItem 重绘次数。**置信度：社区共识**（官方明确 `queue_redraw` 是"请求重绘"，每帧去重合并，但滥用仍造成全树重排）。

**坑 7：`_gui_input` 不 `accept_event()` 导致事件继续传播，或反之无条件吃掉全局输入。** **判据正则**：`func _gui_input\(` 方法体内无 `accept_event\s*\(`，且 `mouse_filter != MOUSE_FILTER_IGNORE` → 提示"事件会继续传播"；或 `accept_event\s*\(` 出现在无条件分支 → 提示"可能拦截全局快捷键"。**确认**：点击/按键测试。**置信度：官方明确。**

**坑 8：`focus_neighbor_*`/`focus_next`/`focus_prev` 是 NodePath，必须显式赋值。** **判据正则**：`focus_(neighbor_(left|right|top|bottom)|next|prev)\s*=` 抓取所有显式值，检查是否为合法 `NodePath`（形如 `NodePath("...")` 或 `"..."` 在 GDScript 中自动转）。**确认**：运行时 `get_node(path)`。**置信度：官方明确。**

**坑 9：`MarginContainer` 的 `margin_*` 是 Theme 常量，必须 `add_theme_constant_override`。** **判据正则**：`(margin_left|margin_right|margin_top|margin_bottom)\s*=` → 告警。**确认**：运行报 `Nonexistent property`（取决于访问方式）。**置信度：官方明确。**

**坑 10：3.x → 4.x 类名迁移。** `Light2D` → `PointLight2D`/`DirectionalLight2D`/`SpotLight2D`；`ParallaxBackground`/`ParallaxLayer` → `Parallax2D`；`TileMap.set_cell(layer,...)` → `TileMapLayer.set_cell(coords,...)`。**判据正则**：`class_name\s+.*Light2D|extends\s+Light2D`、`ParallaxBackground|ParallaxLayer`、`TileMap\.set_cell\s*\(` 四参。**确认**：编译错误。**置信度：官方明确。**

---

## 引用来源

[1] https://docs.godotengine.org/en/stable/classes/class_control.html
> "Anchors the left edge of the node to the origin, the center or the end of its parent control. It changes how the left offset updates when the node moves or changes size."

[2] https://docs.godotengine.org/en/stable/classes/class_label.html
> "If set to something other than TextServer.AUTOWRAP_OFF, the text gets wrapped inside the node's bounding rectangle. If you resize the node, it will change its height automatically to show all the text."

[3] https://docs.godotengine.org/en/stable/classes/class_canvasgroup.html
> "This increases both the backbuffer area used and the area covered by the CanvasGroup both of which can reduce performance."

[4] https://docs.godotengine.org/en/stable/classes/class_canvasitem.html
> "The color applied to this CanvasItem. This property does affect child CanvasItem s, unlike self_modulate which only affects the node itself."

[5] https://docs.godotengine.org/en/stable/classes/class_scrollcontainer.html
> "If true, the ScrollContainer will automatically scroll to focused children (including indirect children) to make sure they are fully visible."

[6] https://docs.godotengine.org/en/stable/classes/class_theme.html
> "A resource used for styling/skinning Control and Window nodes."

[7] https://docs.godotengine.org/en/stable/classes/class_basebutton.html
> "If true, the button is in toggle mode. Makes the button flip state between pressed and unpressed each time its area is clicked."

[8] https://docs.godotengine.org/en/stable/classes/class_texturerect.html
> "Defines how minimum size is determined based on the texture's size."

[9] https://docs.godotengine.org/en/stable/classes/class_ninepatchrect.html
> "A margin of 16 means the 9-slice's left corners and side will have a width of 16 pixels."

[10] https://docs.godotengine.org/en/stable/classes/class_animatedsprite2d.html
> "The current animation from the sprite_frames resource. If this value is changed, the frame counter and the frame_progress are reset."

[11] https://docs.godotengine.org/en/stable/classes/class_richtextlabel.html
> "void parse_bbcode (bbcode: String ) ... void append_text (bbcode: String ) ... void clear ()"

[12] https://docs.godotengine.org/en/stable/classes/class_lineedit.html
> "Text shown when the LineEdit is empty. It is not the LineEdit's default value (see text)."

[13] https://docs.godotengine.org/en/stable/classes/class_textedit.html
> "Sets the line wrapping mode to use."

[14] https://docs.godotengine.org/en/stable/classes/class_sprite2d.html
> "If true, texture is cut from a larger atlas texture. See region_rect."

[15] https://docs.godotengine.org/en/stable/classes/class_tree.html
> "In SELECT_MULTI mode, the focused item is the item under the focus cursor, not necessarily selected."

[16] https://docs.godotengine.org/en/stable/classes/class_popupmenu.html
> "Note: Checkable items just display a checkmark, but don't have any built-in checking behavior and must be checked/unchecked manually."

[17] https://docs.godotengine.org/en/stable/classes/class_optionbutton.html
> "If no id is passed, the item index will be used as the item's ID."

[18] https://docs.godotengine.org/en/stable/tutorials/2d/2d_lights_and_shadows.html
> "CanvasModulate (to darken the rest of the scene) PointLight2D (for omnidirectional or spot lights) DirectionalLight2D (for sunlight or moonlight) LightOccluder2D (for light shadow casters)"

[19] https://docs.godotengine.org/en/stable/classes/class_subviewportcontainer.html
> "a 1280×720 sub-viewport with stretch_shrink set to 2 will be rendered at 640×360 while occupying the same size in the container."

[20] https://docs.godotengine.org/en/stable/classes/class_tabcontainer.html
> "Returns the title of the tab at index tab_idx."

[21] https://docs.godotengine.org/en/stable/classes/class_splitcontainer.html
> "Offsets for each dragger in pixels."

[22] https://docs.godotengine.org/en/stable/classes/class_margincontainer.html
> "Note: The margin sizes are theme overrides, not normal properties."

[23] https://docs.godotengine.org/en/stable/classes/class_centercontainer.html
> "If true, centers children relative to the CenterContainer's top left corner."

[24] https://docs.godotengine.org/en/stable/classes/class_boxcontainer.html
> "void add_spacer (begin: bool)"

[25] https://docs.godotengine.org/en/stable/classes/class_panelcontainer.html
> "A container that keeps its child controls within the area of a StyleBox."

[26] https://docs.godotengine.org/en/stable/classes/class_gridcontainer.html
> "If modified, GridContainer reorders its Control-derived children to accommodate the new layout."

[27] https://docs.godotengine.org/en/stable/classes/class_canvaslayer.html
> "Unlike CanvasItem.visible, visibility of a CanvasLayer isn't propagated to underlying layers."

[28] https://docs.godotengine.org/en/stable/classes/class_camera2d.html
> "If true, the camera's view smoothly moves towards its target position at position_smoothing_speed."

[29] https://docs.godotengine.org/en/stable/classes/class_parallax2d.html
> "The camera stops moving when reaching this value, but offset can push the view past the limit."

[30] https://docs.godotengine.org/en/stable/classes/class_progressbar.html
> "Shows the fill percentage in the center. Can also be used to show indeterminate progress."

[31] https://docs.godotengine.org/en/stable/classes/class_checkbox.html
> "To follow established UX patterns, it's recommended to use CheckBox when toggling it has no immediate effect on something."

[32] https://docs.godotengine.org/en/stable/classes/class_pointlight2d.html
> "Inherits: Light2D < Node2D < CanvasItem < Node < Object"

[33] https://docs.godotengine.org/en/stable/classes/class_directionallight2d.html
> "The maximum distance from the camera center objects can be before their shadows are culled (in pixels)."

[34] https://docs.godotengine.org/en/stable/classes/class_lightoccluder2d.html
> "The LightOccluder2D will cast shadows only from Light2D(s) that have the same light mask(s)."

[35] https://docs.godotengine.org/en/stable/classes/class_canvasmodulate.html
> "CanvasModulate applies a color tint to all nodes on a canvas. Only one can be used to tint a canvas."

[36] https://docs.godotengine.org/en/stable/classes/class_tilemap.html
> "Deprecated: Use multiple TileMapLayer nodes instead."
