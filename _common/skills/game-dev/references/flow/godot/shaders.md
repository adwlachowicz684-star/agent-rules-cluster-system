# Godot 4.x 着色器（GDShader）

⚠ **GDShader 不是标准 GLSL**。它是 Godot 自己的方言，语法近似 GLSL ES 3.0 但有差异。
从网上抄的 GLSL 代码多数不能直接跑。

## 0. 五种 shader 类型

```gdshader
shader_type canvas_item;    // 2D（Control / Node2D）
shader_type spatial;        // 3D
shader_type particles;      // 粒子
shader_type sky;            // 天空
shader_type fog;            // 体积雾
```

文件后缀 `.gdshader`，挂到 `ShaderMaterial` 的 `shader` 属性。

## 1. 语言基础

### 结构

```gdshader
shader_type canvas_item;              // 1) 类型
render_mode unshaded, blend_mix;      // 2) 渲染模式

uniform vec4 u_tint : source_color = vec4(1.0);   // 3) uniform
varying float v_height;                            // 4) varying

void vertex() { ... }
void fragment() { ... }
void light() { ... }
```

⚠ **默认值必须写在提示之后**：`uniform vec4 u : source_color = vec4(1.0);`
顺序写反会编译失败。

### 数据类型

`bool/int/uint/float`、`vec2–vec4`、`ivec2–ivec4`、`uvec2–uvec4`、`bvec2–bvec4`、
`mat2–mat4`、`sampler2D`。

⚠ **局部变量不会默认初始化为 0.0**。使用未赋值变量会读取未定义数据。
所以"只在 `if` 成功分支写输出"会让失败像素输出垃圾值，不是保持原值。

⚠ **没有隐式类型转换**。`int` 与 `float` 不能隐式转换，`1` 与 `1.0` 不等价。
所有浮点字面量写 `.0`。

### uniform 提示（hint）完整清单

| 类型 | 提示 | 作用 |
|---|---|---|
| `vec3`/`vec4` | `source_color` | 作为颜色（sRGB 语义） |
| `int` | `hint_enum("A","B","C")` | 编辑器下拉 |
| `int`/`float` | `hint_range(min,max[,step])` | 范围与步进 |
| `sampler2D` | `source_color` | **颜色纹理必加，否则发白** |
| `sampler2D` | `hint_normal` | 法线贴图 |
| `sampler2D` | `hint_default_white/black/transparent` | 空槽默认值 |
| `sampler2D` | `hint_anisotropy` | flowmap |
| `sampler2D` | `hint_roughness[_r/_g/_b/_a/_normal/_gray]` | 粗糙度限制器 |
| `sampler2D` | `filter[_nearest/_linear][_mipmap][_anisotropic]` | 过滤模式 |
| `sampler2D` | `repeat[_enable/_disable]` | 重复模式 |
| `sampler2D` | `hint_screen_texture` | **当前屏幕纹理** |
| `sampler2D` | `hint_depth_texture` | 场景深度纹理 |
| `sampler2D` | `hint_normal_roughness_texture` | 仅 Forward+ |

⚠ **`source_color` 不只是编辑器控件，它是颜色空间语义**。
Forward+ / Mobile 的颜色纹理、启用 HDR 2D 的 canvas_item **必须加**，否则颜色发白。
法线、粗糙度、金属度、高度**不能加**（它们不是显示颜色）。

⚠ **`hint_enum` 存的是整数**。`set_shader_parameter()` 必须传整数，
传字符串名称**静默无效**。

```gdshader
group_uniforms Albedo;          // 开启分组（只影响检查器 UI）
uniform vec4 u_tint : source_color;
group_uniforms Albedo.Detail;   // 子组
uniform float u_detail;
group_uniforms;                 // 关闭
```

### varying

可从 `vertex()` 传向 `fragment()`；也可在 `fragment()` 写入后供 `light()` 读。

⚠ **不能在普通 helper 函数里给 varying 赋值**，也不能在 `light()` 中给从顶点阶段传入的 varying 赋值。

```gdshader
varying float v_h;              // 默认 smooth（透视校正插值）
varying flat int v_id;          // flat 关闭插值，适合离散索引
```

### 精度限定符

`lowp` / `mediump` / `highp`，可用于变量、uniform、varying、函数返回。

| 用 `highp` | 可用 `mediump` |
|---|---|
| 世界坐标、屏幕 UV | 颜色权重 |
| `TIME`、深度重建 | 归一化后的局部方向 |
| 远距离法线插值 | `0–1` 参数 |

⚠ **移动端降级精度会在桌面预览完全正常，只在特定设备出现远处闪烁**。
必须在真机验证。

### 常用内置函数

| 类别 | 函数 |
|---|---|
| 插值/限制 | `mix` `clamp` `smoothstep` `step` `min` `max` |
| 数学 | `abs` `fract` `mod` `pow` `exp` `sqrt` `inversesqrt` `fma` |
| 几何 | `length` `distance` `dot` `cross` `normalize` `reflect` `refract` |
| 三角 | `sin` `cos` `tan` `atan` |
| 纹理 | `texture(sampler, uv[, bias])` `textureSize(sampler, lod)` |
| 比较 | `lessThan` `greaterThan` `equal` `notEqual` |

⚠ **浮点不要用 `==` 比较**。用 `abs(x - target) < eps`，且 eps 要按数值范围选。

---

## 2. CanvasItem（2D）

### 内置变量

| 变量 | 含义 |
|---|---|
| `VERTEX` | **局部像素坐标**（不是归一化） |
| `UV` | 归一化纹理坐标 |
| `COLOR` | 顶点/最终颜色（fragment 里写它） |
| `TEXTURE` | 默认采样器 |
| `TEXTURE_PIXEL_SIZE` | 归一化像素尺寸 |
| `SCREEN_UV` | 当前像素的屏幕坐标 |
| `NORMAL` | 2D 法线（有法线贴图时） |
| `TIME` | 时间 |

⚠ **2D 顶点是像素坐标，不是 0–1**。`UV` 和 `SCREEN_UV` 不可互换。

⚠ **4.x 的单 pass 光照**：`AT_LIGHT_PASS` 恒为 `false`。
3.x 用 `AT_LIGHT_PASS` 区分 pass 的写法**在 4.x 失效**。

### render_mode 常用值

```
unshaded              完全自己控制颜色（跳过光照）
light_only            只显示光照结果
blend_mix/add/sub/mul/premul_alpha
skip_vertex_transform 引擎不做模型→视图变换
```

### 配方 1：屏幕后处理（色差 + 暗角）

**结构**：`CanvasLayer` + `ColorRect`（锚点设为 Full Rect）+ `ShaderMaterial`。

```gdshader
shader_type canvas_item;

uniform sampler2D u_screen : hint_screen_texture, filter_linear_mipmap;
uniform float u_vignette : hint_range(0.0, 2.0, 0.01) = 0.8;
uniform float u_chroma : hint_range(0.0, 0.02, 0.0005) = 0.003;

void fragment() {
    vec2 dir = SCREEN_UV - 0.5;
    vec2 uv = clamp(SCREEN_UV, vec2(0.0), vec2(1.0));
    float r = texture(u_screen, clamp(uv + dir * u_chroma, vec2(0.0), vec2(1.0))).r;
    float g = texture(u_screen, uv).g;
    float b = texture(u_screen, clamp(uv - dir * u_chroma, vec2(0.0), vec2(1.0))).b;
    float falloff = smoothstep(0.8, 0.2, length(dir));
    COLOR = vec4(vec3(r, g, b) * mix(1.0, falloff, u_vignette), 1.0);
}
```

⚠ **屏幕 UV 不会自动 clamp**，强偏移会读到边缘拉伸像素。
生产代码必须 `clamp(uv, vec2(0.0), vec2(1.0))`。

⚠ **多 pass 后处理**要堆叠多个 `CanvasLayer` + `ColorRect`，
后一层读前一层结果。两趟分离高斯优于单趟 9×9，且应在降采样 RT 上做。

⚠ **Godot 不支持同时渲染多个 G-buffer**。自定义后处理只能拿到已渲染的颜色帧，
拿不到法线/深度（除非用 `hint_depth_texture`）。

### 配方 2：描边（沿法线外扩）

```gdshader
shader_type canvas_item;

uniform sampler2D u_tex : source_color;
uniform vec4 u_outline : source_color = vec4(0.0, 0.0, 0.0, 1.0);
uniform float u_width : hint_range(0.0, 10.0, 0.1) = 2.0;

void fragment() {
    vec2 px = TEXTURE_PIXEL_SIZE * u_width;
    vec2 dir = normalize(NORMAL.xy + vec2(1e-5));
    vec4 center = texture(u_tex, UV);
    float outline = max(texture(u_tex, UV + dir * px).a,
                        texture(u_tex, UV - dir * px).a) * (1.0 - center.a);
    COLOR.rgb = mix(center.rgb, u_outline.rgb, outline);
    COLOR.a = center.a + outline;
}
```

⚠ **没有 2D 法线贴图时这个配方不成立**。改用离线外扩 mesh、
轮廓 pass 或预烘焙 dilation 图。

⚠ 像素级边缘在半透明、缩放、非闭合几何上容易断裂。

### 配方 3：溶解

```gdshader
shader_type canvas_item;

uniform sampler2D u_tex : source_color;
uniform sampler2D u_noise : repeat_enable;
uniform float u_progress : hint_range(0.0, 1.0, 0.01) = 0.0;
uniform float u_edge : hint_range(0.0, 0.3, 0.005) = 0.05;
uniform vec4 u_edge_color : source_color = vec4(1.2, 0.5, 0.1, 1.0);

void fragment() {
    vec4 base = texture(u_tex, UV);
    float n = texture(u_noise, UV).r;
    float burned = step(n, u_progress);
    float edge = step(n, u_progress + u_edge) - burned;
    COLOR.rgb = mix(base.rgb, u_edge_color.rgb, edge);
    COLOR.a = base.a * (1.0 - burned);
}
```

### 配方 4：受击白闪

```gdshader
shader_type canvas_item;

uniform float u_flash : hint_range(0.0, 1.0, 0.01) = 0.0;

void fragment() {
    vec4 c = texture(TEXTURE, UV);
    COLOR = vec4(mix(c.rgb, vec3(1.0), u_flash), c.a);
}
```

从脚本驱动：

```gdscript
material.set_shader_parameter("u_flash", 1.0)
var tw := create_tween()
tw.tween_method(func(v): material.set_shader_parameter("u_flash", v), 1.0, 0.0, 0.15)
```

### 配方 5：灰度 / 去色

```gdshader
shader_type canvas_item;

uniform float u_amount : hint_range(0.0, 1.0, 0.01) = 1.0;

void fragment() {
    vec4 c = texture(TEXTURE, UV);
    float g = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    COLOR = vec4(mix(c.rgb, vec3(g), u_amount), c.a);
}
```

---

## 3. Spatial（3D）

### 内置输出（fragment）

| 变量 | 含义 |
|---|---|
| `ALBEDO` | 基础色 |
| `NORMAL` / `NORMAL_MAP` | 法线 |
| `ROUGHNESS` | 粗糙度 |
| `METALLIC` | 金属度 |
| `SPECULAR` | 默认 0.5，通常**不用改** |
| `EMISSION` | 自发光（可 >1 做 HDR） |
| `AO` | 环境光遮蔽 |
| `ALPHA` | 透明度 |
| `ALPHA_SCISSOR_THRESHOLD` | 硬裁剪阈值 |

### 坐标空间（最容易出错的地方）

```
MODEL_MATRIX           模型/局部 → 世界
MODELVIEW_MATRIX       模型/局部 → 视图
PROJECTION_MATRIX      视图 → 裁剪
CAMERA_MATRIX          视图 → 世界（不是相机对象的变换！）
INV_PROJECTION_MATRIX  裁剪 → 视图
```

```gdshader
vec4 world_pos = MODEL_MATRIX * vec4(VERTEX, 1.0);
```

⚠ **`CAMERA_MATRIX` 是从视图空间回到世界空间**，
不要当相机对象的变换矩阵用。

⚠ `world_vertex_coords` 启用后 `VERTEX`/`NORMAL` **已在世界空间**，
再乘 `MODEL_MATRIX` 会**双重变换**。

⚠ `skip_vertex_transform` 启用后引擎不做变换，
必须自己变换 `VERTEX`/`NORMAL`/`TANGENT`/`BITANGENT`。

⚠ **`POSITION` 不是第二个 `VERTEX`**。一旦在任何分支写入 `POSITION`，
投影不再自动发生。没把握就改 `VERTEX`。

### 配方 6：卡通着色（toon）

```gdshader
shader_type spatial;
render_mode unshaded;

uniform vec4 u_shadow : source_color = vec4(0.2, 0.22, 0.35, 1.0);
uniform vec4 u_light : source_color = vec4(1.0, 0.95, 0.9, 1.0);
uniform float u_threshold : hint_range(0.0, 1.0, 0.01) = 0.2;
uniform float u_smooth : hint_range(0.0, 0.05, 0.001) = 0.01;
uniform vec3 u_light_dir_view = vec3(0.4, 0.7, 0.6);

void fragment() {
    vec3 n = normalize(NORMAL);
    float ndotl = dot(n, normalize(u_light_dir_view));
    float band = smoothstep(u_threshold - u_smooth, u_threshold + u_smooth, ndotl);
    ALBEDO = mix(u_shadow.rgb, u_light.rgb, band);
}
```

⚠ 要用引擎光照与阴影，应自定义 `light()` 并离散化 `DIFFUSE_LIGHT`。
上面这个 `unshaded` 版本**不吃场景光照和阴影**。

### 配方 7：边缘光（rim）

```gdshader
shader_type spatial;
render_mode unshaded;

uniform vec4 u_rim : source_color = vec4(0.9, 0.95, 1.0, 1.0);
uniform float u_power : hint_range(0.0, 8.0, 0.05) = 2.5;
uniform float u_strength : hint_range(0.0, 3.0, 0.02) = 1.0;

void fragment() {
    vec3 view_dir = normalize(VIEW);
    float f = 1.0 - max(dot(normalize(NORMAL), view_dir), 0.0);
    ALBEDO = u_rim.rgb * pow(f, u_power) * u_strength;
}
```

⚠ **`max(..., 0.0)` 是必需的** —— 对负数做 `pow()` 会产生 NaN。

### 配方 8：顶点动画（风吹草动）

```gdshader
shader_type spatial;

uniform float u_strength : hint_range(0.0, 1.0, 0.01) = 0.08;
uniform float u_freq : hint_range(0.0, 10.0, 0.05) = 2.0;
uniform float u_height : hint_range(0.0, 10.0, 0.1) = 2.0;

void vertex() {
    float h = clamp(VERTEX.y / max(u_height, 1e-4), 0.0, 1.0);
    vec4 wp = MODEL_MATRIX * vec4(VERTEX, 1.0);
    float wave = sin(TIME * u_freq + wp.x * 1.3 + wp.z * 0.9);
    VERTEX += vec3(wave * u_strength * h, 0.0, wave * u_strength * 0.5 * h);
}
```

⚠ 上面的 `h` 假定**根在局部原点、上方为局部 y**。根位置不同的 mesh 要先平移。
⚠ 吹动后若法线仍参与精确光照，应重新计算。

### 配方 9：三平面映射（triplanar）

适合地形/悬崖，避免 UV 拉伸：

```gdshader
shader_type spatial;

uniform sampler2D u_tex : source_color;
uniform float u_scale : hint_range(0.01, 2.0, 0.01) = 0.2;

void fragment() {
    vec3 n = abs(normalize(NORMAL));
    n /= (n.x + n.y + n.z);
    vec3 wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz * u_scale;
    vec3 cx = texture(u_tex, wp.zy).rgb;
    vec3 cy = texture(u_tex, wp.xz).rgb;
    vec3 cz = texture(u_tex, wp.xy).rgb;
    ALBEDO = cx * n.x + cy * n.y + cz * n.z;
}
```

⚠ **三次纹理采样**，是昂贵的。只在确实需要时用。

---

## 4. 粒子 / 天空 / 雾

⚠ **4.x 的粒子 shader 函数名变了**：3.x 的 `vertex()` 不存在，
改为 `start()` 和 `process()`。

```gdshader
shader_type particles;

void start() {
    // 粒子诞生时
}

void process() {
    // 每帧
}
```

⚠ 自定义粒子 shader 可重新定义 `INSTANCE_CUSTOM` 的字段含义
（默认 x=旋转弧度，y=生命周期 0–1，z=动画帧）。

天空 shader 用 `shader_type sky`，输出 `COLOR`（`EYEDIR` 是视线方向）。
体积雾用 `shader_type fog`。

---

## 5. Compute Shader（RenderingDevice）

⚠ **这部分 API 名称请以目标版本官方文档为准**，以下为通用结构说明。

适用：GPU 粒子、烘焙、大批量并行计算。
**不适用于**：普通材质效果 —— 复杂度远超收益。

基本结构（`RenderingDevice`）：

```gdscript
var rd := RenderingServer.create_local_rendering_device()
var shader_file := load("res://compute.glsl")
var spirv: RDShaderSPIRV = shader_file.get_spirv()
var shader := rd.shader_create_from_spirv(spirv)
var pipeline := rd.compute_pipeline_create(shader)
```

⚠ **compute 的 `global_size = work_groups * local_size`**。
不匹配会导致 dispatch 无效且**通常不报错**。

⚠ **每帧 `buffer_get_data()` 回读会强制同步**，是最常见的性能杀手。
应批量、异步、减少回读次数。

---

## 6. 性能工程（重点）

### 变体爆炸

```
一个 shader 可能有几十个以上管线
```

管线由这些组合决定：渲染器、功能开关、纹理提示、`render_mode`、
透明度状态、灯光/阴影、特化常量。

⚠ **代码行数不是有效指标**。N 个独立编译期宏开关，最坏组合数 2^N。

**降变体的第一选择**：把运行时差异变成 **uniform** 而不是宏开关。
uniform 分支通常不产生新 shader 版本。

### `if` 的代价

- **uniform 控制的 `if`**：通常较友好（分支条件跨线程一致）
- **逐像素高度不一致的 `if`**：GPU 可能仍保留两条路径

⚠ 不能简单理解成"永远不要用 if"。对大块区域、uniform 条件、昂贵函数，
分支能显著减少无效计算。连续变化的效果用 `mix/step/smoothstep` 更稳。

### `discard`

⚠ **`discard` 会阻止有效利用深度 prepass**。
即使像素最终被 discard，顶点阶段仍执行 ——
"把所有像素都 discard"不会比不渲染该物体更便宜。

适合 alpha scissor 无法接受的硬孔，不适合做移动端透明优化。

### 纹理

- 每次 `texture()` 访问显存，可能 cache miss
- 重复采样同一坐标时**先缓存结果**
- 屏幕后处理应在**降采样 RT** 执行
- 像素艺术：nearest、关 mipmap；3D 颜色纹理：linear mipmap

### 性能反模式（按影响排序）

1. 全分辨率多 pass 后处理，大半径多采样
2. 每像素动态分支且条件随机
3. fragment 里重复采样同一纹理
4. 大量独立材质导致 draw 增加 + 变体扩散
5. 三平面/复杂噪声每个角色每像素执行
6. 循环中调用 `pow/sin/noise` 且无固定上限
7. 世界坐标/屏幕 UV 用 `lowp/mediump`
8. 每帧大量 `buffer_get_data()` 回读
9. Mobile 全屏 pass 无限制读屏幕纹理（破坏 tile 优化）
10. 大量 `discard` 模拟透明又叠加覆盖面积

### 预热

4.4 起会在加载 mesh/添加节点时检测所需管线并多线程预编译，但**仍可能**在
玩家改分辨率、首次进新区域、动态灯光配置、运行时换材质时生成新管线。

有效预热清单：

1. 加载界面主动实例化代表网格 + 材质 + 灯光组合
2. 覆盖目标质量档位的渲染器与阴影设置
3. 对常见分辨率执行**代表性 draw**，不只创建 RID
4. 异步预热时保持加载状态，不假定单帧完成
5. 记录运行时动态创建的材质
6. 不在主菜单测 Compatibility 却在游戏里切 Forward+

---

## 7. 调试

**第一原则：先隔离阶段，再比较数值。**

| 症状 | 先查 |
|---|---|
| 全黑 | `ALBEDO`/`COLOR` 是否写入 |
| 颜色异常 | `source_color`、纹理导入、混合 |
| 坐标异常 | 模型/世界/视图空间、`skip_vertex_transform` |
| 部分像素错 | 分支、varying 插值、精度、纹理边界 |
| 只有首次卡顿 | 管线编译，不是算法 |

**把中间值映射成颜色**（比读数字快）：

```gdshader
COLOR.rgb = vec3(value);              // 标量
COLOR.rgb = NORMAL * 0.5 + 0.5;       // 法线
COLOR.rgb = vec3(SCREEN_UV, 0.0);     // 屏幕 UV
COLOR.rgb = vec3(fract(x));           // 周期值
```

可以用 `uniform bool u_debug` 保护调试路径，发布时关掉。

### 常见错误对照

| 错误 | 原因 | 处理 |
|---|---|---|
| `undeclared identifier SCREEN_TEXTURE` | 3.x 全局采样器 | 声明 `sampler2D : hint_screen_texture` |
| 颜色发白/发灰 | 颜色纹理缺 `source_color` | 加提示 |
| `particles` 报 vertex 不存在 | 3.x API | 改 `start()`/`process()` |
| 2D 光照逻辑失效 | 4.x 单 pass | 重写 `light()` |
| varying 赋值报错 | 在 helper/`light()` 里赋值 | 在允许的阶段赋值 |
| 编译后无输出 | 只在 `if` 分支写输出 | **所有分支都要给输出** |
| `hint_enum` 设置无效 | 传字符串 | 传整数 |
| 远处闪烁 | 低精度世界数据 | 改 `highp` |

### VisualShader

它是**创建** shader 的视觉方案，后台转成脚本 shader，编辑器可查看生成代码。

⚠ 没有暴露 GDShader 的全部特性（复杂算法、include、宏、精细优化仍需手写）。

⚠ **端口有隐式转换会掩盖逻辑错误**：
标量→向量是所有分量取该标量；向量→标量是取分量**平均值**。
不等于自动 swizzle。

---

## 8. 3.x → 4.x 迁移

| 3.x | 4.x |
|---|---|
| `hint_albedo` / `hint_color` | **`source_color`** |
| `hint_white` / `hint_black` | `hint_default_white` / `hint_default_black` |
| 全局 `SCREEN_TEXTURE` | **声明** `sampler2D : hint_screen_texture` |
| 粒子 `vertex()` | `start()` / `process()` |
| `AT_LIGHT_PASS` | 恒 `false`（单 pass 光照） |
| 深度 NDC Z 范围 | Forward+/Mobile 用 `[0,1]` 公式 |

⚠ 迁移要**全局替换**，不是改个别材质。
只有个别材质偏亮 = 漏改一处；多个材质异常 = 全局检查。

---

> **反模式清单（不能怎么做，审核用）** → `audit/godot/shaders.md`


## 9. 相关文档

- 2D 渲染特效 → `2d-rendering.md`
- 3D 与材质 → `3d.md`
- 管线预热 → `rendering-advanced.md`
- 性能排查 → `debugging.md`、`performance.md`
