# Godot 4.x Shader API 审查判据

⚠ 本文件是**审查查表**：每条给出可匹配的源码特征、级别、确认方法。
正确写法见 `game-dev/references/howto/godot/shaders.md`（本文档不重复代码）。

## 1. 语言与类型（GDS01–GDS08 已进扫描器）

| ID | 级别 | 特征 | 为什么是问题 | 确认方法 |
|---|---|---|---|---|
| **GDS01** | P1 | `hint_albedo` / `hint_color` | 3.x 提示，4.x 改 `source_color` | 全局替换后看颜色是否恢复 |
| **GDS02** | P1 | `hint_white` / `hint_black` | 4.x 改 `hint_default_white/default_black` | 换提示后编译 |
| **GDS03** | P1 | 裸 `SCREEN_TEXTURE` | 4.x 无此全局量，直接编译失败 | 能否编译 |
| **GDS04** | P1 | `AT_LIGHT_PASS` | 4.x 单 pass，恒 false，光照分支失效 | 对比有无光照的画面 |
| **GDS05** | P1 | 颜色名 sampler 无提示 | 缺 `source_color` → 发白 | 切换 Forward+ 看是否发白 |
| **GDS06** | P2 | `shader_type particles` + `vertex()` | 4.x 改 `start()`/`process()` | 能否编译 |
| **GDS07** | P2 | `discard` | 破坏深度 prepass，顶点仍执行 | 移动端帧时间对比 |
| **GDS08** | P2 | 低精度世界/屏幕 varying | 桌面正常，真机远处闪烁 | **必须在真机验证** |

## 2. 人工判据（未进扫描器，需人看）

以下不适合正则：会大量误报，或需要跨文件/运行时信息。

| 判据 | 级别 | 为什么不适合机扫 |
|---|---|---|
| 局部变量未初始化就在分支外使用 | P1 | 需要数据流分析 |
| 只在 `if` 分支写输出（其他分支未定义） | P1 | 需要控制流分析 |
| `CAMERA_MATRIX` 当相机变换用 | P1 | 语义错误，静态不可判 |
| `world_vertex_coords` 后再乘 `MODEL_MATRIX` | P1 | 需理解 render_mode 语义 |
| `POSITION` 只在部分分支写入 | P1 | 需控制流分析 |
| 对可能为负的值做 `pow()` | P2 | 需值域分析 |
| 浮点用 `==` 比较 | P2 | 需语义判断（有些是合法的） |
| 全分辨率多 pass 后处理 | P1 | 需理解场景结构 |
| 每帧 `buffer_get_data()` 回读 | P1 | 需跨文件看调用频率 |
| 视觉基线未人工确认 | P2 | 完全无法机扫 |

## 3. 版本敏感（标待核对）

| 项 | 状态 |
|---|---|
| `hint_normal_roughness_texture`（仅 Forward+） | 官方确认，但渲染器相关 |
| `INSTANCE_CUSTOM` 粒子字段含义 | 官方确认默认值，自定义 shader 可重定义 |
| Compute shader 的 `RenderingDevice` API 名 | **待核对**，以目标版本为准 |
| 4.4 ubershader 预热机制 | 官方确认存在，具体行为需实测 |
| `ALPHA_HASH_SCALE` / `ALPHA_ANTIALIASING_EDGE` | 官方确认存在 |

## 4. 与开发文档的分工

- **正确写法、完整代码、配方** → `game-dev/references/howto/godot/shaders.md`
- **判据、特征、级别、确认方法** → 本文件
- 两边用规则 ID 互相指向，不复制内容
