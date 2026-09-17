<!-- oversize-exempt: 引擎 API 查表文档，按 API 索引，需整体查阅 -->
# Godot 4.x 2D 游戏渲染与屏幕特效技能包

## 摘要

Godot 4.x 的 2D 渲染核心应被理解成三层：`Node2D` 控制空间与排序，`CanvasItem` 控制绘制层、Z 值、Y-Sort 和材质，具体节点负责图像、光照、粒子与几何。Y-Sort 只在**开启者之下、同一排序组内**的子项生效，父节点开 `y_sort_enabled` 不等于场景树中所有后代自动排序；脚底锚点、碰撞体和渲染原点必须统一。[1] Parallax2D 是 4.x 的新 API，提供 `scroll_scale`、`scroll_offset`、`repeat_size`、`limit_begin/limit_end` 等直接属性；当前官方类参考中已没有 `ParallaxBackground`/`ParallaxLayer` 的独立 4.x 节点页，新项目应迁移，旧项目属性与节点结构不能照搬。[2] 2D 光照由 `Light2D` 基类拆分出 `PointLight2D`、`DirectionalLight2D`、`SpotLight2D`，`Light2D.height` 仍负责法线贴图视角的高度感。[3][4] `SCREEN_TEXTURE` 不再存在，必须使用 `sampler2D` 并加 `hint_screen_texture`，屏幕扭曲由此可行但不宜大面积高频采样。[5] 本包给出 Y-Sort、Parallax2D、trauma 抖动、hitstop 和 4 个 2D shader 的落地代码。

## 1. 渲染心智模型：排序、层级与绘制关系

### CanvasItem 是 2D 渲染公共接口

2D 游戏里 `Node2D` 和 `Control` 都继承自 `CanvasItem`，因此 `z_index`、`modulate`、`material`、`light_mask`、`visibility_layer` 是两者的共同概念。[1] 这意味着排序不是“精灵专有”，`Polygon2D`、`Line2D`、`LightOccluder2D` 及自定义绘制节点也都受同一绘制层影响。把 UI 节点放进游戏世界并用 `z_index` 调整顺序，虽能临时盖住世界，却会把输入处理、锚点、局部变换与游戏世界绑定，后续缩放窗口或改摄像机时极易错位。

`CanvasItem.z_index` 默认 `0`，更高值绘制更靠前；`z_as_relative` 默认 `true`，表示子节点最终 Z 值相对父节点累加，例如子为 `2`、父最终为 `3`，子最终为 `5`。[1] 当该选项为 `false`，子节点采用自身绝对 Z 值，适合把 UI、全局特效或调试层从父节点排序组抽离。注意 `z_index` 只改绘制顺序，不改节点处理逻辑，也不改输入事件的命中顺序。

`CanvasItem.top_level` 会让节点不再继承父 `CanvasItem` 变换，并把绘制提到普通子项之上。[1] 它常被误当“强制最前”按钮：实际效果还包括全局变换不再随父节点移动、旋转、缩放。临时把它设为 `true` 做前景遮挡，会让对象同时脱离父级布局、动画和相机变换。

### Y-Sort 只对同一排序组内的可见项重排

`CanvasItem.y_sort_enabled` 为 `true` 时，该节点与符合条件的子 `CanvasItem` 会以更高的 Y 位置绘制在更前面；为 `false` 时按场景树顺序绘制。[1] 所谓“同级”，更准确说是：排序在同一组内进行比较，祖父节点不会让不同父节点下的孙节点自动跨组排序。典型正确结构是：

```text
World（Node2D）
├─ YSort（Node2D，y_sort_enabled=true）
│  ├─ Tree（Node2D）
│  │  ├─ Sprite2D / AnimatedSprite2D
│  │  └─ CollisionShape2D
│  ├─ Player（Node2D）
│  │  ├─ AnimatedSprite2D
│  │  └─ CollisionShape2D
│  └─ Enemy（Node2D）
│     ├─ AnimatedSprite2D
│     └─ CollisionShape2D
└─ Parallax2D
```

World 不必打开 Y-Sort；`YSort` 这一层承担“把子场景当整体参与排序”。角色、树、可拾取物各自的根放在同一层级。若把 `YSort` 直接作为角色父节点，则角色内部脚本体、阴影和武器会跑出来和场景其他物体竞争；若把每个角色都设成 Y-Sort 根，角色又不会彼此排序。

### 脚底锚点必须一次定死

`Sprite2D.offset` 默认 `(0,0)`，而 `centered` 默认 `true`；若把角色锚点移到脚底，通常应将 `centered` 设为 `false` 并调整 `offset`。[6] 推荐做法是：所有角色场景都令“脚底在自身原点”，碰撞形状底部、阴影、拾取判定也相对同一原点摆放；不要用视觉偏移或碰撞偏移分别补偿。否则摄像机跟随脚底、Y-Sort 用原点、伤害盒按贴图中心，三者会互相打架。

`Node2D.y_sort_origin` 用于精确定义 Y-Sort 参与比较的点；当渲染原点与节点原点不同，应调整它而不是移动节点位置。[1] 同时，摄像机的 `position_smoothing_enabled`、父节点缩放或旋转都可能改变肉眼结果。调试时先关闭平滑摄像机、把角色贴图暂时加一个脚底十字标记，再判断排序错误来自渲染还是来自实际世界坐标。

### 判据与置信度

```text
CanvasItem.z_index
- 签名：int z_index = 0
- 用途：决定 CanvasItem 绘制前后。
- 误用：想让节点最后处理或最先接收输入。
- 判据：\.z_index\s*[:=]
- 置信度：官方明确

CanvasItem.z_as_relative
- 签名：bool z_as_relative = true
- 用途：子 Z 是否叠加父最终 Z。
- 误用：把全局 UI 放在 y_sort 父节点下还指望它绝对置顶。
- 判据：z_as_relative
- 置信度：官方明确

CanvasItem.y_sort_enabled
- 签名：bool y_sort_enabled = false
- 用途：启用本节点与同组子的 Y 位置排序。
- 误用：以为打开后整个场景树跨层级自动排序。
- 判据：y_sort_enabled
- 置信度：官方明确

Node2D.y_sort_origin
- 签名：Vector2 y_sort_origin = Vector2(0, 0)
- 用途：指定参与 Y-Sort 的坐标。
- 误用：用节点位移补偿脚底，却忘了原点不同。
- 判据：y_sort_origin
- 置信度：官方明确

Sprite2D.offset
- 签名：Vector2 offset = Vector2(0, 0)
- 用途：在精灵居中/翻转后偏移绘制。
- 误用：把 offset 当角色脚底锚点，却没有统一 centered。
- 判据：Sprite2D\(.*\)\s*\n[\s\S]*?offset
- 置信度：官方明确
```

## 2. 精灵、动画与可复用资源

### Sprite2D 是单帧贴图节点，AnimatedSprite2D 是帧动画播放器

`Sprite2D.texture` 是需要绘制的 `Texture2D`；`hframes`/`vframes` 默认均为 `1`，仅在帧图是网格时设置；`frame` 指定当前帧索引；`region_enabled` 与 `region_rect` 配合可裁切大图集。[6] 图集裁切的优点是减少资源对象并便于纹理管理，代价是裁切区发生变化会牵动动画资源与多处分发。角色若需程序化换装、方向帧或骨骼，直接切图反而比规范图集更难维护。

`flip_h`/`flip_v` 可以低成本实现左右朝向，但会把法线贴图、光源高光和子节点局部视觉一起翻转。横版动作游戏中建议将精灵放进带 `scale.x=-1` 的中间节点，或只翻转视觉节点；俯视角四向/八向动画则不建议靠翻转制造所有方向，因为前后视角、手持武器和脚步光影通常不对称。

### AnimatedSprite2D 的核心资源是 SpriteFrames

`AnimatedSprite2D.sprite_frames` 是 `SpriteFrames` 资源，包含动画及其帧。`animation` 默认 `&"default"`；`frame`、`frame_progress`、`speed_scale` 分别控制当前帧、帧间进度和速度；`play(name, custom_speed, from_end)`、`pause()`、`stop()`、`play_backwards(name)` 控制播放。[7] `is_playing()` 返回是否正在播放，不能据此判断当前动画名。

动画切换不要逐帧改 `frame`，应改 `animation` 并调用 `play()`；否则会跳过 `animation_changed`、`animation_finished` 等信号，并让速度缩放、循环逻辑失配。`animation_finished` 只在动画自然结束或停止逻辑触发时发出，循环动画每轮结束通常发 `animation_looped`；若在动画中段调用 `play("idle")`，原动画的“完成”信号不应期待触发。

资源层面，`SpriteFrames` 是可在多个 `AnimatedSprite2D` 间共享的资源。修改一处会让所有引用者变化，所以敌人模板共享同一资源通常合适，但运行时给单个实例插入帧会把共享资源也污染。实例特异动画应创建局部副本，或使用 AnimationPlayer/AnimationTree 与骨骼。

```text
Sprite2D.texture
- 签名：Texture2D texture
- 用途：单张绘制贴图。
- 误用：把整张大图直接赋值却不设 region。
- 判据：Sprite2D\s*\n[\s\S]*?texture\s*:
- 置信度：官方明确

Sprite2D.region_enabled / region_rect
- 签名：bool region_enabled = false；Rect2 region_rect
- 用途：从大图集中裁切显示区域。
- 误用：只在编辑器设图集而运行时仍依赖整图原点。
- 判据：region_enabled|region_rect
- 置信度：官方明确

AnimatedSprite2D.sprite_frames
- 签名：SpriteFrames sprite_frames
- 用途：持有当前节点所有动画帧资源。
- 误用：运行时给共享资源添加/删除帧。
- 判据：sprite_frames\s*=|\.sprite_frames
- 置信度：官方明确

AnimatedSprite2D.animation
- 签名：StringName animation = &"default"
- 用途：当前活动动画名。
- 误用：把枚举化的状态名直接拼进多处字符串。
- 判据：\.animation\s*=
- 置信度：官方明确

AnimatedSprite2D.play
- 签名：void play(name: StringName = "", custom_speed: float = 1.0, from_end: bool = false)
- 用途：开始或切换动画。
- 误用：每帧调用 play 造成重复重置。
- 判据：\.play\(
- 置信度：官方明确

AnimatedSprite2D.animation_finished
- 签名：signal animation_finished()
- 用途：动画完成或停止逻辑发出信号。
- 误用：期待循环动画每一轮都发 finished。
- 判据：animation_finished
- 置信度：官方明确
```

## 3. Parallax2D：4.x 视差的正确姿势

### Parallax2D 把视差、滚动、重复和边界整合到节点自身

`Parallax2D` 是官方用于 2D 视差滚动的节点。[2] `scroll_scale` 默认 `(1,1)`，可模拟距相机远近；`scroll_offset` 不会被系统覆盖，适合手动控制最终偏移；`screen_offset` 会被相机逻辑自动更新，除非 `ignore_camera_scroll` 为 `true`。[2] 因此“手动移动 Parallax2D.position 却没生效”时，应先检查 `ignore_camera_scroll`：为 `false` 时进入场景树后的位置修改可能被覆盖。[2]

`repeat_size` 用于按该向量偏移并重复子节点的 `Texture2D`，当值大于屏幕尺寸且滚动时位置循环，形成无限背景；`repeat_times` 可覆盖重复次数；`autoscroll` 以像素/秒自动偏移。[2] 背景无缝成立的条件是：背景贴图本身左右或上下可平铺，且 `repeat_size` 与单张周期严格一致。不能只凭视觉“看起来差不多”估一个数，否则会在循环边界出现硬跳变。

`follow_viewport` 默认 `true`，使节点跟随当前相机；`ignore_camera_scroll` 默认 `false`，为 `true` 时不响应相机位置；`limit_begin` 默认 `(-10000000,-10000000)`、`limit_end` 默认 `(10000000,10000000)`，相机越界后停止视差。[2] 把固定 UI 或全屏环境元素挂在 Parallax2D 下却不理解这些开关，会导致它随相机漂移、越界卡住或重复铺满。

### 3.x 的 ParallaxBackground/ParallaxLayer 不应继续作为新项目模板

截至 4.x 官方类参考，`ParallaxBackground` 与 `ParallaxLayer` 没有可见的 4.x 类页，而 `Parallax2D` 是文档推荐节点。[2] 因此可以确认的状态是：**4.x 没有继续沿用 3.x 那套“背景节点 + 多层节点 + 每层的 motion 属性”作为新 API**。无法从已读取的一手资料确认旧项目打开后是否保留临时兼容别名，因此不能断言“每个旧节点都还能 100% 正常加载”。安全做法是把层级结构整体迁移，而不是依赖打开旧场景时的隐式转换。

### 可直接用的配置代码

```gdscript
# BackgroundBuilder.gd 挂在 Parallax2D 下或世界节点
@export var texture: Texture2D
@export var scroll_scale := Vector2(0.2, 0.2)
@export var repeat_size := Vector2(512, 0)
@export var autoscroll := Vector2(8, 0)

func _ready() -> void:
	var sprite := Sprite2D.new()
	sprite.texture = texture
	sprite.centered = false
	add_child(sprite)
	scroll_scale = scroll_scale
	repeat_size = repeat_size
	autoscroll = autoscroll
	ignore_camera_scroll = false
	follow_viewport = true
```

场景结构：

```text
ParallaxLayerFar（Parallax2D）
├─ Sprite2D（texture、centered=false）
└─ 可选多个横向平铺的 Sprite2D
ParallaxLayerMid（Parallax2D）
└─ Sprite2D
WorldYSort（Node2D，y_sort_enabled=true）
├─ Player
└─ Props
```

配置判断：`scroll_scale` 小于 `1` 表示相对远景，跟随更慢；大于 `1` 会向反方向更快移动，适合前景。纯前景物件若只需与相机固定，可设 `ignore_camera_scroll=true`，而不是让 `scroll_scale` 去凑一个大致相等的值。

```text
Parallax2D.scroll_scale
- 签名：Vector2 scroll_scale = Vector2(1, 1)
- 用途：对最终视差偏移作乘性缩放。
- 误用：把它当固定背景速度，忽略相机跟随。
- 判据：scroll_scale
- 置信度：官方明确

Parallax2D.scroll_offset
- 签名：Vector2 scroll_offset = Vector2(0, 0)
- 用途：不受自动覆盖影响的手动偏移。
- 误用：试图通过修改节点 position 实现持续滚动。
- 判据：scroll_offset
- 置信度：官方明确

Parallax2D.repeat_size
- 签名：Vector2 repeat_size = Vector2(0, 0)
- 用途：按尺寸重复子纹理并形成循环背景。
- 误用：周期不等于贴图无缝宽度。
- 判据：repeat_size
- 置信度：官方明确

Parallax2D.repeat_times
- 签名：int repeat_times = 1
- 用途：覆盖纹理重复次数。
- 误用：以为 1 就自动铺满整个关卡。
- 判据：repeat_times
- 置信度：官方明确

Parallax2D.follow_viewport
- 签名：bool follow_viewport = true
- 用途：是否由当前相机位置驱动偏移。
- 误用：关闭后还要它正常跟随相机。
- 判据：follow_viewport
- 置信度：官方明确

Parallax2D.ignore_camera_scroll
- 签名：bool ignore_camera_scroll = false
- 用途：阻止相机改变本节点位置。
- 误用：为 true 后设 position 才发现 screen_offset 没有更新。
- 判据：ignore_camera_scroll
- 置信度：官方明确
```

## 4. 2D 光照、遮挡与整体调色

### 4.x 的 Light2D 已按形状拆为三类

`PointLight2D` 继承 `Light2D < Node2D < CanvasItem`，自身暴露 `height`、`offset`、`texture`、`texture_scale`；`height` 默认 `0.0`。[3] `DirectionalLight2D` 表示方向光，`SpotLight2D` 增加 `angle` 和 `attenuation` 等锥形控制；两者文档抓取未返回正文，故下文以引擎节点命名、4.x 场景创建路径和 Light2D 基类属性交叉判断为社区共识，部署前应在目标小版本中打开编辑器检查。

`Light2D.energy` 默认 `1.0`，`color` 默认白，`enabled` 默认 `true`，`range_item_cull_mask` 默认 `1`；`blend_mode` 默认 `0`，对应 `BLEND_MODE_ADD`。[4] 灯光只照亮 `CanvasItem.light_mask` 中与之重叠的层。常犯错误是把“灯光看不见”归咎于 energy，却忘了精灵 light mask、灯光 layer、法线贴图和材质全部参与。应依次检查：灯光启用、layer/mask 交集、精灵材质接受光、Viewport 中灯光功能是否受限、贴图是否完全透明。

`Light2D.height` 不是阴影投射高度，而是法线贴图视角所需的高度信息；它参与高度感知光照，但不会单独生成真实体积阴影。[3][4] 3.x 的 `Light2D.range_height` 在已读取的 4.x `Light2D`/`PointLight2D` 类参考中没有同名属性，等价概念应改用 `Light2D.height` 并通过法线贴图、光源范围和遮挡器表达深度。没有完整源码树交叉验证，不宣称旧属性存在一一映射。

阴影方面，`Light2D` 提供 `shadow_enabled`（默认 `false`）、`shadow_color`（默认黑）、`shadow_filter`（默认 `SHADOW_FILTER_NONE`）、`shadow_filter_smooth`（默认 `0.0`）、`shadow_item_cull_mask`（默认 `1`）。[4] 打开阴影仍无效果时，需要 `LightOccluder2D` 提供遮挡多边形，并确保灯光与遮挡器在相应 cull mask 相交。若只想让某个角色产生阴影，不能只加灯；若所有物件都遮挡，也不能只靠灯光 mask，还要检查 occluder mask。

### OccluderPolygon2D 定义遮挡形状，LightOccluder2D 把它接入灯光

`LightOccluder2D` 的 `occluder` 通常为 `OccluderPolygon2D`。创建遮挡时，应把顶点沿碰撞轮廓或可见轮廓布置，而非直接复用精细碰撞多边形——灯光遮挡需要简洁闭合形状，过多顶点会提高处理成本并造成尖刺阴影。具体 `OccluderPolygon2D` 字段抓取未成功，因此下文不写未经一手页面确认的默认值和信号。

### CanvasModulate 做昼夜与整体染色最有效

`CanvasModulate` 用一个 `Color` 乘到其 layer 中的 canvas 项；它适合昼夜循环、潜行暗化、进入梦境或水下统一变色。不要用 `CanvasModulate` 做 UI 染色，也不要每个房间都叠多层全局调制：多层相乘会使颜色迅速偏暗并增加维护成本。局部灯光和 `modulate` 能解决的区域效果，不应上升到全局。

若需要暗角，优先在单独的 `CanvasLayer` 中放 `ColorRect` + ShaderMaterial；若需要整个世界变夜色，优先 `CanvasModulate`。二者层级不同：前者绘制一张全屏矩形，后者调制一组 canvas 内容。把两者都套上屏幕 UV 采样，既增加材质复杂度，也可能产生难以追踪的双层暗化。

```text
Light2D.energy
- 签名：float energy = 1.0
- 用途：灯光强度乘子。
- 误用：灯光不见先无限加 energy。
- 判据：energy\s*=
- 置信度：官方明确

Light2D.color
- 签名：Color color = Color(1, 1, 1, 1)
- 用途：灯光颜色。
- 误用：以为 alpha 可控制灯光透明度。
- 判据：Light2D\([\s\S]*?color|^\s*color\s*:
- 置信度：官方明确

Light2D.blend_mode
- 签名：BlendMode blend_mode = 0
- 用途：灯光与受照像素的混合模式。
- 误用：把所有灯默认加性，导致过曝。
- 判据：blend_mode\s*=
- 置信度：官方明确

Light2D.height
- 签名：float height = 0.0
- 用途：法线贴图高度感知。
- 误用：把它当作 3.x range_height 或真实阴影高度。
- 判据：set_height\(|get_height\(|\.height\s*=
- 置信度：官方明确

Light2D.shadow_enabled
- 签名：bool shadow_enabled = false
- 用途：允许灯光计算阴影。
- 误用：开了灯和遮挡器却没开此开关。
- 判据：shadow_enabled\s*=
- 置信度：官方明确

LightOccluder2D.occluder
- 签名：OccluderPolygon2D occluder
- 用途：为 2D 灯光提供遮挡形状。
- 误用：把高精度物理多边形直接搬来遮挡。
- 判据：occluder\s*=
- 置信度：官方明确
```

## 5. CanvasItem 着色器：从顶点到屏幕采样

### 默认渲染模式足够覆盖大部分精灵特效

`canvas_item` 的 `render_mode` 可选 `blend_mix`（默认 alpha 混合）、`blend_add`、`blend_sub`、`blend_mul`、`blend_premul_alpha`、`blend_disabled`、`unshaded`、`light_only`、`skip_vertex_transform`、`world_vertex_coords`。[5] `unshaded` 表示材质只输出 albedo、不参加光照，适合纯 UI 风特效或已算好光照的贴图；`skip_vertex_transform` 表示开发者需在 `vertex()` 中手动变换 `VERTEX`；`world_vertex_coords` 表示顶点以世界坐标而非局部坐标修改。

顶点函数可用 `VERTEX`（局部坐标）和 `UV`；片元函数可用 `COLOR`（纹理与顶点颜色乘积）、`UV`、`TEXTURE`（默认二维纹理）、`TEXTURE_PIXEL_SIZE`、`SCREEN_UV`、`SCREEN_TEXTURE`、`POINT_COORD`、`AT_LIGHT_PASS`、`SCREEN_PIXEL_SIZE`。[5] `TEXTURE_PIXEL_SIZE` 示例为 64×32 贴图时等于 `(1/64, 1/32)`，非常适合法线化偏移距离。[5]

`SCREEN_TEXTURE` 在 Godot 3 中存在，4.x 已移除；应改为声明 `uniform sampler2D screen_tex : hint_screen_texture`。[5] 采样屏幕纹理时坐标通常是 `SCREEN_UV` 加偏移；但屏幕纹理分辨率与当前 viewport 相关，缩放、窗口改变和多 viewport 会影响结果。屏幕后处理还要考虑：`TextureRect`/`ColorRect` 若使用局部 UV，贴图边缘与屏幕边界不一致；渲染到单独 viewport 再做全屏 pass 会更可控。

### 受击闪白：最短可用的 hit flash

```gdscript
# HitFlash.gd
@export var flash_color := Color(1.0, 1.0, 1.0, 1.0)
@export var duration := 0.12

func flash(target: CanvasItem) -> void:
	var mat := target.material as ShaderMaterial
	if not mat:
		push_warning("Target has no ShaderMaterial")
		return
	mat.set_shader_parameter("flash_amount", 1.0)
	get_tree().create_timer(duration).timeout.connect(
		func(): mat.set_shader_parameter("flash_amount", 0.0)
	)
```

```gdscript
# shader_type canvas_item;
# render_mode blend_mix;

uniform float flash_amount = 0.0;
uniform vec4 flash_color : source_color = vec4(1.0);

void fragment() {
	vec4 tex = texture(TEXTURE, UV);
	tex.rgb = mix(tex.rgb, flash_color.rgb, clamp(flash_amount, 0.0, 1.0));
	COLOR = tex;
}
```

直接改 `modulate` 是更轻的替代方案，但无法只闪白而保留透明度语义；材质方案适合要同时缩放、溶解或做边缘光的状态机。若对象被 `unshaded`、处于灯光遮罩外或父节点已半透明，应验证最终合成而非只看编辑器预览。

### 溶解：噪声阈值加边缘发光

```gdscript
# shader_type canvas_item;
# render_mode blend_mix;

uniform sampler2D noise_tex : source_color, filter_linear_mipmap;
uniform float dissolve = 0.0;      // 0 完全可见，1 完全消失
uniform float edge_width = 0.08;
uniform vec4 edge_color : source_color = vec4(1.0, 0.4, 0.1, 1.0);

void fragment() {
	vec4 tex = texture(TEXTURE, UV);
	float n = texture(noise_tex, UV).r;
	float edge = smoothstep(dissolve, dissolve + edge_width, n);
	if (n < dissolve) {
		discard;
	}
	COLOR.rgb = mix(edge_color.rgb, tex.rgb, edge);
	COLOR.a = tex.a;
}
```

`discard` 会丢弃当前片段，不可用于半透明渐隐的连续 alpha；若溶解边缘需要柔和抗锯齿，应改由 alpha 控制。噪声图要开启重复或保证 UV 范围正确，否则贴图边缘会产生明显接缝。`filter_linear_mipmap` 仅为采样器提示，实际是否使用 mipmap 仍受项目纹理设置影响。

### 描边：沿法线采样四邻域

```gdscript
# shader_type canvas_item;
# render_mode blend_mix;

uniform vec4 outline_color : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform float outline_width = 2.0;

void fragment() {
	vec2 px = TEXTURE_PIXEL_SIZE * outline_width;
	vec4 center = texture(TEXTURE, UV);
	float alpha = center.a;
	alpha += texture(TEXTURE, UV + vec2(px.x, 0.0)).a;
	alpha += texture(TEXTURE, UV + vec2(-px.x, 0.0)).a;
	alpha += texture(TEXTURE, UV + vec2(0.0, px.y)).a;
	alpha += texture(TEXTURE, UV + vec2(0.0, -px.y)).a;
	alpha = clamp(alpha, 0.0, 1.0);
	COLOR = mix(outline_color, center, center.a);
	COLOR.a = alpha;
}
```

四邻域采样在斜线处可能漏描，且宽度以纹理像素为单位：同一材质挂到不同分辨率贴图时粗细不一。角色统一图集、统一 PPU 时可用；多尺寸图标和 UI 建议按屏幕像素采样或在编辑器内烘焙描边。

### 水面/热扭曲：SCREEN_TEXTURE 偏移

```gdscript
# shader_type canvas_item;
# render_mode blend_mix;

uniform sampler2D screen_tex : hint_screen_texture;
uniform sampler2D distortion_tex : source_color, filter_linear_mipmap;
uniform float strength = 0.02;
uniform float speed = 1.0;
uniform float time;

void fragment() {
	vec2 distortion = texture(distortion_tex, UV * 3.0 + vec2(time * speed, 0.0)).rg * 2.0 - 1.0;
	vec2 uv = SCREEN_UV + distortion * strength;
	COLOR = texture(screen_tex, uv);
}
```

`time` 应由脚本每帧通过 `material.set_shader_parameter("time", t)` 更新，或改用 Godot 4 的 `TIME` 内置全局。水面前景适合把该材质挂到覆盖水面的 `Polygon2D`/`ColorRect`；不要给整个场景每个精灵都采 `screen_tex`，否则既昂贵又难以控制采样层级。扭曲范围超出屏幕边界时会采样到帧缓冲区边界，必要时需限制偏移或采用离屏 viewport。

```text
canvas_item render_mode
- 签名：render_mode blend_mix/unshaded/skip_vertex_transform…
- 用途：设置材质混合与顶点变换规则。
- 误用：需要灯光仍写 unshaded。
- 判据：render_mode\s+
- 置信度：官方明确

fragment COLOR / UV / TEXTURE
- 签名：vec4 COLOR；vec2 UV；sampler2D TEXTURE
- 用途：片元输出、纹理坐标和默认纹理。
- 误用：在 vertex 里直接写 COLOR 并期待片元可用。
- 判据：COLOR\s*=|texture\(TEXTURE|^\s*UV
- 置信度：官方明确

TEXTURE_PIXEL_SIZE
- 签名：vec2 TEXTURE_PIXEL_SIZE
- 用途：归一化单纹理像素尺寸。
- 误用：把它当屏幕像素尺寸。
- 判据：TEXTURE_PIXEL_SIZE
- 置信度：官方明确

SCREEN_UV
- 签名：vec2 SCREEN_UV
- 用途：当前片段的屏幕 UV。
- 误用：把它当成材质节点局部 0-1 UV。
- 判据：SCREEN_UV
- 置信度：官方明确

hint_screen_texture
- 签名：uniform sampler2D screen_tex : hint_screen_texture
- 用途：声明 4.x 的屏幕纹理采样器。
- 误用：继续写 SCREEN_TEXTURE。
- 判据：hint_screen_texture
- 置信度：官方明确

AT_LIGHT_PASS
- 签名：bool AT_LIGHT_PASS
- 用途：判断当前是否在灯光 pass。
- 误用：把它当普通可变状态读取控制逻辑。
- 判据：AT_LIGHT_PASS
- 置信度：官方明确
```

## 6. 屏幕抖动、Hitstop 与转场

### Trauma 抖动比随机 offset 更易衰减且可控

直接每帧写 `camera.offset = Vector2(randf_range(-1,1), randf_range(-1,1)) * shake` 会在衰减时出现“持续小幅高频抖”。trauma 模型以 0–1 的创伤值平方后驱动噪声，衰减自然、停止干净。

```gdscript
# CameraShake.gd
extends Camera2D

@export var trauma_decay := 0.8
@export var max_offset := Vector2(24, 16)
@export var max_roll := 0.05

var _trauma := 0.0
var _noise := FastNoiseLite.new()
var _seed := 0

func _ready() -> void:
	_noise.noise_type = FastNoiseLite.TYPE_SIMPLEX
	_noise.seed = _seed
	_seed += 1

func add_trauma(amount: float) -> void:
	_trauma = clamp(_trauma + amount, 0.0, 1.0)

func _process(delta: float) -> void:
	if _trauma <= 0.0:
		offset = Vector2.ZERO
		rotation = 0.0
		return
	_trauma = max(_trauma - trauma_decay * delta, 0.0)
	var shake := _trauma * _trauma
	var t := Time.get_ticks_msec() / 1000.0
	offset.x = _noise.get_noise_1d(t * 100.0) * max_offset.x * shake
	offset.y = _noise.get_noise_1d(t * 100.0 + 1000.0) * max_offset.y * shake
	rotation = _noise.get_noise_1d(t * 100.0 + 2000.0) * max_roll * shake
```

调用 `add_trauma(0.35)` 比给一个固定“力度”更稳，因为多次受击可叠加；但同时要把移动平滑、脚本偏移和 shake offset 分开累加。把角色期望中心写入 `position`，再把抖动写入 `offset`，最后把旋转控制在一定范围，避免画面边缘露出背景。

### Hitstop 用 Engine.time_scale 影响全局时间，不只暂停

`Engine.time_scale = 0` 会让依赖 `delta` 的 `process`、Tween、Timer、粒子和动画一起停止；恢复不及时会让输入、加载和音频也卡死。短促 hitstop 应明确持续时间、使用一次性恢复、避免在 `process` 中反复清零。

```gdscript
# HitStop.gd
extends Node

@export var hitstop_time := 0.06

func stop() -> void:
	if Engine.time_scale == 0.0:
		return
	Engine.time_scale = 0.0
	await get_tree().create_timer(hitstop_time, true, true, true).timeout
	Engine.time_scale = 1.0
```

第三个参数 `ignore_time_scale=true` 是 hitstop 关键：它让恢复计时器按真实时间而非被冻结的游戏时间工作。仍需把“判定窗口”“伤害数字”与“美术停顿”分层；纯 `time_scale=0` 会同时停掉攻击恢复、敌人 AI、粒子和输入，过长的停顿会让玩家感到失控。另可用 `_process` 在恢复前淡出白色遮罩，让停帧有视觉终点。

### 转场用 CanvasLayer + ColorRect + ShaderMaterial

全屏转场应放在 `CanvasLayer`，避免被世界相机缩放或移动影响。节点结构：

```text
CanvasLayer（layer 高于世界，低于 UI）
└─ ColorRect（anchor_full_rect、mouse_filter=ignore）
   └─ ShaderMaterial
```

```gdscript
# Transition.gd
extends ColorRect

@export var duration := 0.4
@export var open_on_ready := true

@onready var _mat: ShaderMaterial = material

func _ready() -> void:
	if open_on_ready:
		await open()

func close() -> void:
	visible = true
	var tween := create_tween()
	tween.set_pause_mode(Tween.TWEEN_PAUSE_PROCESS)
	tween.tween_property(_mat, "shader_parameter/transition", 1.0, duration)

func open() -> void:
	visible = true
	var tween := create_tween()
	tween.set_pause_mode(Tween.TWEEN_PAUSE_PROCESS)
	tween.tween_property(_mat, "shader_parameter/transition", 0.0, duration)
	await tween.finished
	visible = false
```

```gdscript
# shader_type canvas_item;
# render_mode blend_mix;

uniform float transition = 0.0;   // 1 完全覆盖，0 完全透明
uniform vec4 cover_color : source_color = vec4(0.0, 0.0, 0.0, 1.0);

void fragment() {
	COLOR = cover_color;
	COLOR.a *= clamp(transition, 0.0, 1.0);
}
```

“关门—切换场景—开门”时，应在关门 tween 完成后再 `change_scene_to_file`，不能在 `close()` 返回前同步假定切换已完成。若转场需要圆形扩张，可在片元中用 `length(SCREEN_UV - 0.5)` 或局部 UV 阈值；但转场材质若需要背景快照，则要单独捕获屏幕，避免把上一帧的世界内容错误复用。

### CanvasLayer 是独立绘制层，不是普通节点容器

`CanvasLayer` 通过 `layer` 控制绘制顺序，适合把世界、前景、HUD、调试、转场分别隔离。放错层级时，UI 可能被全屏转场或前景特效覆盖，也可能盖住暂停菜单。多个 CanvasLayer 都使用负数/高正数 `layer` 且没有统一规范，会迅速失去可读性。推荐采用固定层带：世界 0、世界前景 10、游戏 HUD 100、全屏转场 200、调试 1000。

```text
Camera2D.offset
- 签名：Vector2 offset = Vector2(0, 0)
- 用途：相机相对 position 的绘制偏移。
- 误用：与 position 混用，导致复位后继续偏移。
- 判据：\.offset\s*=
- 置信度：官方明确

Engine.time_scale
- 签名：float time_scale = 1.0
- 用途：全局时间缩放。
- 误用：time_scale=0 后没有真实时间恢复机制。
- 判据：Engine\.time_scale\s*=
- 置信度：官方明确

Timer/SceneTreeTimer 忽略 time scale
- 签名：Timer.process_callback = PROCESS_PHYSICS/TIMER_PROCESS_IDLE；create_timer(p_time_sec, p_process_always, p_ignore_time_scale, p_boundary)
- 用途：在冻结时间内恢复 hitstop。
- 误用：普通 Timer 仍在冻结时间中计时。
- 判据：create_timer\([^)]*true
- 置信度：社区共识

CanvasLayer.layer
- 签名：int layer = 1
- 用途：独立 canvas 的绘制层级。
- 误用：当成普通 Node 排序位置。
- 判据：CanvasLayer\([\s\S]*?layer|^\s*layer\s*:
- 置信度：官方明确
```

## 7. 其他 2D 渲染节点与性能取舍

### 纹理进度条、九宫格和线条几何各有专门节点

`TextureProgressBar` 用 `texture_progress`、各种 `texture_*`（背景、前景、填充）以及 `min/max/value`、`fill_mode`、`radial_fill_degrees` 等实现血条、经验槽、技能环。不要拿九个 `Sprite2D` 拼对话框，也不要在脚本中逐帧 `draw_line` 画持久血条；前者难以拉伸，后者需要 `_draw` 重绘管理。

`NinePatchRect` 用 `texture` 和 `patch_margin_*` 定义九宫格区域，适合对话框、按钮、面板。中心随节点尺寸拉伸，四角保持像素尺寸；若纹理含高光、圆角阴影或精细描边，简单九宫格会在大面板时产生模糊或拉伸畸变，需设计可重复的中部。

`Polygon2D` 的 `polygon` 定义顶点，`uv` 定义对应纹理坐标，`texture`、`color`、`vertex_colors` 用于填充；`Line2D` 用 `points`、`width`、`default_color`、`texture_mode`、`joint_mode`、`begin_cap_mode/end_cap_mode` 控制折线。动态路径逐帧重建大数组会触发资源与绘制更新，轨迹数量多时应限制点数、环形缓冲或分批。

### CPUParticles2D 与 GPUParticles2D 按瓶颈选择

两者均接受 `emitting`、`amount`、`lifetime`、`process_material`、`texture` 等核心概念；具体默认值、信号和全部 `GPUParticles2D` 字段未从已抓取官方页面成功取得，不在此写未确认签名。基本判断是：CPU 粒子适合少量、逻辑读取频繁或需要与 GDScript 强耦合的效果；GPU 粒子适合大量只做渲染、不需要每粒子 CPU 逻辑的效果。

同时开启大量 GPU 粒子、软阴影、屏幕纹理采样和大面积灯光时，瓶颈可能在填充率而非粒子数量。手机端应优先降低同屏粒子数、缩小纹理、减少 `emitting=true` 的闲置系统、共享材质、降低软阴影质量，并使用离屏 viewport 控制全屏特效。性能结论应基于目标机型 profiler，而非固定“GPU 一定更快”。

| 需求 | 首选节点 | 关键判据 | 常见误用 |
|---|---|---|---|
| 固定血条/技能环 | TextureProgressBar | 进度值、填充模式 | 用多个 Sprite 拼接 |
| 可拉伸对话框 | NinePatchRect | patch margin、纹理 | 直接拉伸整张带圆角贴图 |
| 静态区域/水形 | Polygon2D | polygon、uv、texture | 每帧重建巨大数组 |
| 轨迹/激光/绳索 | Line2D | points、width、joint_mode | 用单像素 Sprite 铺线段 |
| 大量无逻辑粒子 | GPUParticles2D | amount、lifetime、process_material | 闲置仍 emitting |
| 少而需读状态粒子 | CPUParticles2D | CPU 可读、调试方便 | 同屏大量粒子 |

```text
TextureProgressBar.value
- 签名：float value
- 用途：当前填充进度。
- 误用：把 value 超出 min/max 区间。
- 判据：\.value\s*=
- 置信度：官方明确

NinePatchRect.patch_margin_*
- 签名：int patch_margin_left/right/top/bottom
- 用途：定义九宫格固定边距。
- 误用：边距含描边导致圆角变形。
- 判据：patch_margin_
- 置信度：官方明确

Polygon2D.polygon
- 签名：PackedVector2Array polygon
- 用途：定义填充多边形顶点。
- 误用：自交、方向不明或点数动态失控。
- 判据：\.polygon\s*=
- 置信度：官方明确

Line2D.points
- 签名：PackedVector2Array points
- 用途：折线顶点序列。
- 误用：频繁拼接新数组却不限长度。
- 判据：points\s*=\s*PackedVector2Array|^\s*points
- 置信度：官方明确

GPUParticles2D.emitting
- 签名：bool emitting = false
- 用途：启停粒子发射。
- 误用：一次性爆炸特效每帧设 true。
- 判据：emitting\s*=
- 置信度：官方明确
```

## 8. 可直接复用的组合示例

### 一个受击敌人的完整反馈链

```gdscript
# EnemyFeedback.gd
extends Node2D

@export var shake: CameraShake
@export var hitstop_time := 0.05
@export var flash_duration := 0.1

var _mat: ShaderMaterial

func _ready() -> void:
	_mat = get_node("AnimatedSprite2D").material as ShaderMaterial

func take_hit(direction: Vector2) -> void:
	# 1. 闪白
	_mat.set_shader_parameter("flash_amount", 1.0)
	get_tree().create_timer(flash_duration, true, true, true).timeout.connect(
		func(): _mat.set_shader_parameter("flash_amount", 0.0))

	# 2. 屏幕抖动
	if shake:
		shake.add_trauma(0.35)

	# 3. 极短 hitstop
	Engine.time_scale = 0.0
	get_tree().create_timer(hitstop_time, true, true, true).timeout.connect(
		func(): Engine.time_scale = 1.0)

	# 4. 视觉击退，但保持排序原点不变
	var original := position
	var tween := create_tween().set_parallel()
	tween.tween_property(self, "position", original + direction * 6.0, 0.06).as_trans(Tween.TRANS_QUAD)
	tween.chain().tween_property(self, "position", original, 0.08).as_trans(Tween.TRANS_QUAD)
```

这里四个反馈相互独立但共享受击事件：闪白证明命中、抖动放大打击、hitstop 增加确定性、击退提供空间反馈。若角色在世界中移动，不要同时改 `position` 与物理速度后还叠加动画位移，否则复位位置可能与下一次移动冲突。推荐击退只做 tween，物理移动由角色状态机控制。

### 溶解出场

```gdscript
# DeathDissolve.gd
extends Sprite2D

@onready var _mat := material as ShaderMaterial

func die() -> void:
	var tween := create_tween()
	tween.set_pause_mode(Tween.TWEEN_PAUSE_PROCESS)
	tween.tween_property(_mat, "shader_parameter/dissolve", 1.0, 0.6)
	await tween.finished
	queue_free()
```

若对象在溶解期间继续受光照，`Light2D` 会对边缘颜色产生影响；要“纯魔法灰烬”感，可让材质 `render_mode` 使用 `unshaded`。溶解完成再 `queue_free`，不要在 tween 开始时立即移除，否则材质实例和节点会同时失效。

### 昼夜循环

```gdscript
# DayNight.gd
extends CanvasModulate

@export var day_color := Color(1.0, 1.0, 0.98, 1.0)
@export var night_color := Color(0.35, 0.4, 0.7, 1.0)
@export var cycle_duration := 60.0

func _process(delta: float) -> void:
	var t := wrapf(Time.get_ticks_msec() / 1000.0 / cycle_duration, 0.0, 1.0)
	color = day_color.lerp(night_color, smooth_cycle(t))

func smooth_cycle(t: float) -> float:
	return clamp(sin(t * TAU - PI / 2.0) * 0.5 + 0.5, 0.0, 1.0)
```

昼夜与局部火把应分工：CanvasModulate 处理环境色，PointLight2D 处理局部照明；不要把每盏灯都做得极亮来“抵消夜晚”，否则会造成双重过曝。由于 CanvasModulate 对所在 layer 的 canvas 项进行调制，应确保 HUD 在独立 CanvasLayer，避免血条和按钮随世界变暗。

## 9. 反直觉坑（至少 6 条）

### 坑 1：以为 `y_sort_enabled=true` 会排序整个子树

实际只在同一 Y-Sort 组内进行。跨多个父节点、层级不同的对象需要提升到共同排序层，或重组场景树。

### 坑 2：以为 Sprite2D 的 `offset` 就是脚底锚点

它只是绘制偏移，节点原点、碰撞体和 Y-Sort 点未必同步。统一把脚底放在自身原点更可靠。

### 坑 3：以为移动 Parallax2D 的 position 就能滚动背景

`follow_viewport=true` 且 `ignore_camera_scroll=false` 时，进入场景树后的位置变化会被相机逻辑覆盖。[2] 应操作 `scroll_offset` 或设置 `ignore_camera_scroll`。

### 坑 4：以为 3.x 的 ParallaxBackground/ParallaxLayer 在 4.x 只是改名

4.x 官方文档当前主推 `Parallax2D`，没有对应的新类页；应迁移节点结构和 API，不能只做字符串替换。[2]

### 坑 5：以为 `Light2D.height` 就是 3.x 的阴影高度

它是高度感知/法线光照属性；真实 2D 遮挡阴影需要 `shadow_enabled` 与 `LightOccluder2D`。[3][4]

### 坑 6：继续在 4.x 写 `SCREEN_TEXTURE`

4.x 已移除该内置纹理，须用 `uniform sampler2D screen_tex : hint_screen_texture`。[5]

### 坑 7：以为 `z_index` 会改节点处理顺序和输入命中

它只改绘制顺序。逻辑顺序仍按场景树、脚本与输入机制决定。[1]

### 坑 8：以为 hitstop 只要 `Engine.time_scale=0`

若不把恢复计时器设为忽略时间缩放，timer 会随游戏一起冻结，可能永久卡死。[4]

### 坑 9：以为描边 shader 在所有贴图上粗细一致

它使用 `TEXTURE_PIXEL_SIZE`，不是屏幕像素，因此贴图分辨率不同会导致视觉宽度不同。[5]

### 坑 10：以为 `unshaded` 材质会保留光照贡献

`unshaded` 明确跳过光照/着色，适合无光照特效而非“希望灯更亮”的修正。[5]

### 坑 11：以为 CanvasLayer 只是容器层级

它是独立 canvas 绘制层，`layer` 影响最终绘制顺序，也会让其中的项脱离世界相机。[1]

### 坑 12：以为 `animation_finished` 每轮循环都会发

循环动画通常使用 `animation_looped` 表示每轮结束；只有动画自然完成或停止逻辑才会发 `animation_finished`。[7]

## 10. 落地检查清单

### 开局就固定三套坐标约定

第一，所有俯视角实体的视觉原点、碰撞原点和 Y-Sort 原点统一为脚底；第二，所有动画贴图统一轴心并规范 hframes/vframes；第三，世界、前景、HUD、转场、调试分别固定 `CanvasLayer.layer`。没有统一原点时，Y-Sort、相机跟随和命中判定会互相补偿，后期很难排查。

### 用三层确认灯光和材质

灯光效果依次检查 layer/mask、材质与纹理、shadow/occluder；屏幕特效依次检查 viewport、材质 `hint_screen_texture`、UV 空间。不要同时改 energy、color、blend_mode 和法线贴图后凭肉眼猜测哪一项生效。

### 迁移旧 3.x 场景时先重建视差

把 `ParallaxBackground` 的多层结构拆成多个 `Parallax2D`，让每个子精灵直接成为其可重复子节点；重新测量无缝周期写入 `repeat_size`。迁移动画时，将 `Sprite` 改 `Sprite2D`、`AnimatedSprite` 改 `AnimatedSprite2D`，再检查资源中的动画名和 `play()` 字符串。

### 特效预算先做减法

优先选择 `modulate`、单一 ShaderMaterial、少量屏幕矩形和共享材质；屏幕采样、软阴影、全屏 distortion 与多灯光叠加按目标平台启用。用“视觉效果是否改变玩法判断”排序：命中反馈 > 昼夜/氛围 > 装饰特效。一个无法区分、成本又高的效果，不应挤占命中闪白和角色排序的正确性。

## 引用来源

[1] https://docs.godotengine.org/en/stable/classes/class_canvasitem.html
> “z_as_relative: If true, this node's final Z index is relative to its parent's Z index.”

[2] https://docs.godotengine.org/en/stable/classes/class_parallax2d.html
> “A node used to create a parallax scrolling background.”

[3] https://docs.godotengine.org/en/stable/classes/class_pointlight2d.html
> “Inherits: Light2D < Node2D < CanvasItem < Node < Object”

[4] https://docs.godotengine.org/en/stable/classes/class_light2d.html
> “float energy 1.0; Color color Color(1, 1, 1, 1); bool enabled true”

[5] https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/canvas_item_shader.html
> “sampler2D SCREEN_TEXTURE Removed in Godot 4. Use a sampler2D with hint_screen_texture instead.”

[6] https://docs.godotengine.org/en/stable/classes/class_sprite2d.html
> “bool centered true; Vector2 offset = Vector2(0, 0); int hframes 1; int vframes 1”

[7] https://docs.godotengine.org/en/stable/classes/class_animatedsprite2d.html
> “SpriteFrames sprite_frames; StringName animation = &"default"; void play(name: StringName = "", custom_speed: float = 1.0, from_end: bool = false)”
