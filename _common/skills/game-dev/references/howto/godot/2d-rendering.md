# Godot 4.x 2D 渲染与屏幕特效

2D 精灵、Y 排序、视差、2D 光照、着色器、屏幕效果。给可直接用的配方。

## 1. Y-Sort：俯视角 2D 的地基

做俯视角（类似星露谷、塞尔达）时，角色走到树前面应该挡住树，走到后面应该被挡住。

### 正确结构

```
Level (Node2D)  ← y_sort_enabled = true，开在父节点
├── Ground      (TileMapLayer)
├── SortRoot    (Node2D)  ← 也可以单独给排序组开
│   ├── Player  (CharacterBody2D)
│   ├── Tree    (Node2D)  ← 和 Player 同级
│   └── Rock    (Node2D)
└── UI          (CanvasLayer)
```

⚠ **`y_sort_enabled` 要开在父节点上**，不是每个子节点自己开。

⚠ Y-Sort **只对同级子节点排序**。Player 和 Tree 在不同父节点下就不会互排 ——
要么提到同一父节点，要么给各自的父节点也开 y_sort。

### 脚底对齐

排序用的是**节点原点（position）**。如果精灵图是"脚在下方"，
原点却在图片中心，角色会出现"半个身子陷进树里"。

两种解法：

```gdscript
# 方案一：用 offset 把精灵下移，让节点原点=脚底
@onready var _sprite: Sprite2D = $Sprite2D

func _ready() -> void:
    _sprite.offset.y = -_sprite.texture.get_height() / 2.0
    # 或者用 y_sort_origin 单独指定排序基准
    y_sort_origin = 8
```

推荐**方案一**（统一脚底在原点），碰撞体、Y 排序、射线检测全部对齐，后面省事。

## 2. 精灵与动画

```gdscript
@onready var _sprite: AnimatedSprite2D = $AnimatedSprite2D

func _ready() -> void:
    # SpriteFrames 资源：编辑器里建，代码里也能加
    var frames := SpriteFrames.new()
    frames.add_animation("run")
    frames.set_animation_speed("run", 10.0)
    frames.set_animation_loop("run", true)
    _sprite.sprite_frames = frames
```

| 节点 | 用在哪 |
|---|---|
| `Sprite2D` | 单张静态图 |
| `AnimatedSprite2D` | 帧动画（多张图轮播） |
| `TextureRect` | **UI 用**（在 Control 体系里） |
| `AnimationPlayer` | 改任意属性（不只贴图） |

⚠ 游戏世界用 `Sprite2D`，UI 里用 `TextureRect`。
反过来用会出现布局/排序的怪问题。

## 3. Parallax2D 视差背景

**4.x 用 `Parallax2D` 节点**，3.x 的 `ParallaxBackground`/`ParallaxLayer` 已不推荐。

```
Background (Node2D)
├── Sky      (Parallax2D)  scroll_scale = (0.1, 0.1)  ← 远，动得慢
├── Mountains(Parallax2D)  scroll_scale = (0.3, 0.3)
└── Trees    (Parallax2D)  scroll_scale = (0.6, 0.6)  ← 近，动得快
```

每个 Parallax2D 下面放 `Sprite2D` 子节点，并设：

| 属性 | 值 | 说明 |
|---|---|---|
| `scroll_scale` | 0.1 ~ 0.9 | 越小越"远" |
| `repeat_size` | 贴图宽度 | 无缝循环 |
| `repeat_times` | 3 | 重复几次填满屏幕 |
| `autoscroll` | 可选 | 自动滚动（云、水） |
| `ignore_camera_scroll` | false | 跟随相机滚动 |

⚠ **不要改 Parallax2D 的 `position`** —— `follow_viewport=true` 时会被相机逻辑覆盖。
要手动滚就操作 `scroll_offset`，或设 `ignore_camera_scroll = true`。

⚠ `repeat_size` 要和贴图尺寸一致，否则循环处会跳。

## 4. 2D 光照

```
Lights (Node2D)
├── PointLight2D        ← 火把、灯泡
├── DirectionalLight2D  ← 微弱方向光（夜景）
└── CanvasModulate      ← 整体压暗（做夜景关键）
```

### 夜景做法

```gdscript
@onready var _modulate: CanvasModulate = $CanvasModulate

func set_night() -> void:
    _modulate.color = Color(0.3, 0.35, 0.55)    # 压暗偏蓝
    for light in _lights.get_children():
        light.enabled = true

func set_day() -> void:
    _modulate.color = Color.WHITE
    for light in _lights.get_children():
        light.enabled = false
```

**PointLight2D 关键属性**：

| 属性 | 说明 |
|---|---|
| `texture` | 光照贴图（白色渐变圆） |
| `energy` | 强度 |
| `height` | 法线贴图感知高度（**不是阴影高度**） |
| `shadow_enabled` | 投影（要配合 LightOccluder2D） |
| `shadow_filter` | 阴影平滑度 |
| `range_item_cull_mask` | 哪些层参与 |

⚠ 3.x 的 `Light2D` 在 4.x **拆成了三个**：`PointLight2D` / `DirectionalLight2D` / `SpotLight2D`。

⚠ `height` 是给法线贴图用的，**不是** 3.x 的阴影高度。要投影靠 `shadow_enabled` + `LightOccluder2D`。

### 遮挡阴影

```
Wall (Node2D)
├── Sprite2D
└── LightOccluder2D      ← occluder = 新建 OccluderPolygon2D，画遮挡轮廓
```

⚠ 没有 `LightOccluder2D`，`shadow_enabled` 什么也不挡。

## 5. CanvasItem 着色器配方

`shader_type canvas_item`。几个能直接抄的：

### 受击闪白

```glsl
shader_type canvas_item;
render_mode blend_mix;

uniform float flash_amount = 0.0;
uniform vec4 flash_color : source_color = vec4(1.0);

void fragment() {
    vec4 tex = texture(TEXTURE, UV);
    tex.rgb = mix(tex.rgb, flash_color.rgb, clamp(flash_amount, 0.0, 1.0));
    COLOR = tex;
}
```

```gdscript
const P_FLASH := "flash_amount"      # 常量化，避免拼错

func flash() -> void:
    var mat := $Sprite.material as ShaderMaterial
    mat.set_shader_parameter(P_FLASH, 1.0)
    var tw := create_tween()
    tw.tween_method(func(v): mat.set_shader_parameter(P_FLASH, v), 1.0, 0.0, 0.15)
```

### 溶解（死亡消散）

```glsl
shader_type canvas_item;
render_mode blend_mix;

uniform sampler2D noise_tex : source_color, filter_linear_mipmap;
uniform float dissolve = 0.0;        // 0 完整，1 完全消失
uniform float edge_width = 0.08;
uniform vec4 edge_color : source_color = vec4(1.0, 0.4, 0.1, 1.0);

void fragment() {
    vec4 tex = texture(TEXTURE, UV);
    float n = texture(noise_tex, UV).r;
    // 低于阈值的直接丢弃
    if (n < dissolve) discard;
    // 边缘发光
    float edge = smoothstep(dissolve, dissolve + edge_width, n);
    tex.rgb = mix(edge_color.rgb, tex.rgb, edge);
    COLOR = tex;
}
```

### 描边

```glsl
shader_type canvas_item;
render_mode blend_mix;

uniform vec4 outline_color : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform float outline_width = 1.0;

void fragment() {
    vec2 ps = TEXTURE_PIXEL_SIZE * outline_width;
    vec4 col = texture(TEXTURE, UV);
    float a = col.a;
    // 采样四周，任一不透明则算边缘
    a = max(a, texture(TEXTURE, UV + vec2(ps.x, 0.0)).a);
    a = max(a, texture(TEXTURE, UV - vec2(ps.x, 0.0)).a);
    a = max(a, texture(TEXTURE, UV + vec2(0.0, ps.y)).a);
    a = max(a, texture(TEXTURE, UV - vec2(0.0, ps.y)).a);
    COLOR = vec4(mix(outline_color.rgb, col.rgb, col.a), a);
}
```

⚠ 描边会让精灵**变大一圈**，碰撞体不变的话有视觉误差。
要么预留透明边距，要么把 outline 放子节点。

### 水面/热扭曲

```glsl
shader_type canvas_item;
render_mode unshaded;

uniform sampler2D screen_tex : hint_screen_texture;
uniform float strength = 0.02;
uniform float speed = 1.0;

void fragment() {
    vec2 uv = SCREEN_UV;
    float w = sin(uv.y * 40.0 + TIME * speed) * strength;
    COLOR = texture(screen_tex, uv + vec2(w, 0.0));
}
```

⚠ **4.x 没有 `SCREEN_TEXTURE`**（3.x 的内置变量）。
必须自己声明 `uniform sampler2D xxx : hint_screen_texture`。

⚠ 屏幕纹理的分辨率取决于 viewport，窗口缩放/多 viewport 下效果会变。

### 常用内置

| 变量 | 作用域 | 含义 |
|---|---|---|
| `VERTEX` | `vertex()` | 顶点局部坐标 |
| `UV` | 两者 | 贴图 UV |
| `COLOR` | `fragment()` | 最终输出颜色 |
| `TEXTURE` | `fragment()` | 精灵贴图 |
| `TEXTURE_PIXEL_SIZE` | `fragment()` | 1/贴图尺寸，做像素级偏移 |
| `SCREEN_UV` | `fragment()` | 屏幕空间 UV |
| `TIME` | 两者 | 运行时间（秒），做动画 |
| `POINT_COORD` | `fragment()` | 粒子内坐标 |

`render_mode` 常用：`blend_mix`（默认）/ `blend_add`（发光）/ `unshaded`（不参与光照）/ `blend_mul`（阴影）。

## 6. 屏幕抖动（Trauma 模型）

直接每帧随机 offset 会在衰减时"持续高频抖"。用 trauma 更自然：

```gdscript
# camera_shake.gd
extends Camera2D

@export var trauma_decay := 0.8
@export var max_offset := Vector2(24, 16)
@export var max_roll := 0.05

var _trauma := 0.0
var _noise := FastNoiseLite.new()

func _ready() -> void:
    _noise.noise_type = FastNoiseLite.TYPE_SIMPLEX
    _noise.seed = randi()

func add_trauma(amount: float) -> void:
    _trauma = clampf(_trauma + amount, 0.0, 1.0)

func _process(delta: float) -> void:
    if _trauma <= 0.0:
        offset = Vector2.ZERO
        rotation = 0.0
        return
    _trauma = maxf(_trauma - trauma_decay * delta, 0.0)
    var shake := _trauma * _trauma          # 平方，衰减更自然
    var t := Time.get_ticks_msec() / 1000.0
    offset.x = _noise.get_noise_1d(t * 100.0) * max_offset.x * shake
    offset.y = _noise.get_noise_1d(t * 100.0 + 1000.0) * max_offset.y * shake
    rotation = _noise.get_noise_1d(t * 100.0 + 2000.0) * max_roll * shake
```

**调用**：受击时 `camera.add_trauma(0.35)`，爆炸 `add_trauma(0.8)`。
多次受击**可叠加**，比固定力度好。

⚠ 抖动写 `offset`，跟随写 `position` —— 分开，否则相机跟随会把抖动吃掉。

## 7. 命中停顿（Hitstop）

打击感的关键。命中瞬间冻结几十毫秒。

```gdscript
# hitstop.gd —— Autoload
extends Node

@export var hitstop_time := 0.06

func stop(duration: float = hitstop_time) -> void:
    if Engine.time_scale == 0.0:
        return                              # 已在停顿中，别重入
    Engine.time_scale = 0.0
    # 第四个参数 ignore_time_scale=true：否则 time_scale=0 时计时器也不走
    await get_tree().create_timer(duration, true, true, true).timeout
    Engine.time_scale = 1.0
```

⚠ `create_timer` 第四个参数 `ignore_time_scale` **必须是 true** ——
否则 `time_scale = 0` 时计时器也停了，游戏永久卡死。

⚠ `Engine.time_scale = 0` 会让 Tween、Timer、粒子、动画**全部停**。
只想停部分东西就别用它，改用给各自的 `set_process(false)`。

⚠ 一定要有恢复路径。异常退出时 `time_scale` 停在 0，整个游戏假死。

## 8. 转场

```gdscript
# 全屏 shader 转场（比 ColorRect 淡入更花哨）
shader_type canvas_item;
render_mode unshaded;

uniform float progress : hint_range(0.0, 1.0) = 0.0;
uniform vec4 fade_color : source_color = vec4(0.0);

void fragment() {
    float d = distance(UV, vec2(0.5));
    float a = smoothstep(progress - 0.1, progress + 0.1, d);
    COLOR = vec4(fade_color.rgb, 1.0 - a);
}
```

配合 `ColorRect`（`mouse_filter = Ignore`）铺满 + Tween 驱动 `progress`。

⚠ 转场用的 ColorRect 必须设 `mouse_filter = Ignore`，
否则过场期间挡住所有点击（表现为"过场后点不了按钮"）。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/2d-rendering.md`

