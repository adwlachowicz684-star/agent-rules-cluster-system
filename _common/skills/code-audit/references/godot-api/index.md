<!-- oversize-exempt: 引擎 API 领域索引，路由表 + 核心判据，需整体查阅 -->
# Godot API 领域索引

九份 API 查表文档合计约 7000 行，**不要一次全读**。
按代码里实际出现的 API 名，只加载对应领域。

> 本文件是 `route.py` 里 `GODOT_API_DOMAINS` 的人类可读版本。
> 改了这边要同步改那边——两边的映射不一致时，路由会指向错的文档。

## 1. 领域路由表

| 领域 | 触发信号（代码里出现即算命中） | 加载文件 | 行数 |
|---|---|---|---|
| **物理** | `move_and_slide` · `CharacterBody` · `RigidBody` · `Area2D` · `AnimatableBody` · `StaticBody` · `collision_layer/mask` · `intersect_ray/shape` · `RayCast` · `apply_impulse` · `is_on_floor` | `godot-api/physics.md` | 505 |
| **UI / 2D 渲染** | `Control` · `Label` · `Button` · `TextureRect` · `CanvasItem` · `CanvasGroup` · `CanvasLayer` · `Camera2D` · `Parallax2D` · `TileMap` · `Sprite2D` · `ShaderMaterial` · `queue_redraw` | `godot-api/ui.md` | 489 |
| **资源 / IO / 网络** | `ResourceLoader` · `ResourceSaver` · `FileAccess` · `DirAccess` · `PackedScene` · `instantiate` · `HTTPRequest` · `ConfigFile` · `JSON.parse` · `var_to_bytes` · `bytes_to_var` · `user://` · `res://` | `godot-api/io.md` | 1483 |
| **输入 / 音频 / 动画 / Tween / Timer** | `Input.` · `InputEvent` · `InputMap` · `AudioStreamPlayer` · `AudioServer` · `AnimationPlayer` · `AnimationTree` · `Tween` · `create_tween` · `SceneTreeTimer` · `Timer` · `_input` · `_unhandled_input` | `godot-api/anim.md` | 1433 |
| **3D / 渲染** | `Node3D` · `MeshInstance3D` · `BaseMaterial3D` · `StandardMaterial3D` · `Camera3D` · `Light3D` · `DirectionalLight3D` · `OmniLight3D` · `SpotLight3D` · `Environment` · `WorldEnvironment` · `ReflectionProbe` · `VoxelGI` · `LightmapGI` · `SubViewport` · `GPUParticles3D` · `ParticleProcessMaterial` · `Shader` · `set_shader_parameter` | `godot-api/3d.md` | 718 |
| **寻路 / AI** | `NavigationAgent` · `NavigationRegion` · `AStarGrid2D` · `velocity_computed` · `get_next_path_position` · `bake_navigation_polygon` · `NavigationServer2D/3D` | `godot-api/navigation.md` | 725 |
| **2D 渲染 / 特效** | `y_sort_enabled` · `Parallax2D` · `PointLight2D` · `LightOccluder2D` · `CanvasModulate` · `shader_type canvas_item` · `hint_screen_texture` · `SCREEN_UV` · `GPUParticles2D` | `godot-api/render2d.md` | 841 |
| **语言 / 工程 / 调试** | `@export` · `@onready` · `@tool` · `@rpc` · `class_name` · `signal ` · `await` · `ProjectSettings` · `OS.` · `Engine.` · `Performance.` · `SceneTree` · `change_scene` · `print_debug` · `push_error` · `assert` · `is_instance_valid` | `godot-api/lang.md` | 633 |

**没有命中任何领域** → 说明是纯逻辑脚本，只需 `p-godot.md` 的核心判据，不必加载查表文档。

### 路由怎么用

```bash
python3 scripts/route.py --src=<根>          # 输出会带「Godot API 领域」一行
python3 scripts/godot-audit.py --src=<根>    # 先跑规则
```

route 命中 `p-godot` 后，会额外列出检测到的 API 领域与建议加载的文件。
**先跑 `godot-audit.py` 看命中哪条规则，再按规则 ID 去对应领域文档查细节。**

## 2. 规则 ID → 领域 对照

`godot-audit.py` 的规则 ID 分段，中段字母即领域：

| 段 | 领域 | 查哪份文档 |
|---|---|---|
| `GD01`–`GD15` | 所有权 / 迁移（核心） | `p-godot.md` |
| `GD2*` | 物理 | `godot-api/physics.md` |
| `GD3*` | UI / 2D 渲染 | `godot-api/ui.md` |
| `GD4*` | 资源 / IO / 网络 | `godot-api/io.md` |
| `GD5*` | 输入 / 音频 / 动画 / Tween | `godot-api/anim.md` |
| `GD6*` | 3D / 渲染 | `godot-api/3d.md` |
| `GD7*` | 语言 / 工程 / 调试 | `godot-api/lang.md` |

## 3. 各领域的核心判据（速查）

### 物理

| 判据 | 级别 | 为什么 |
|---|---|---|
| `move_and_slide(...)` 带参 | P0 | 4.x 无参化，速度/朝向走属性；带参是 3.x 残留 |
| `velocity *= delta` 后调 `move_and_slide()` | P1 | 引擎内部已做时间积分，再乘 delta 是二次积分 |
| 碰撞层写成 `3`/`5`/`6`/`7` | P1 | 位掩码语义：第 3 层是 `4` 不是 `3`；可疑值说明层号与位值混用 |
| 移动 `StaticBody` 当平台 | P1 | StaticBody 移动是**传送**，不会推动角色；应改用 `AnimatableBody` |
| 每帧覆盖 RigidBody 的 `position`/`linear_velocity` | P1 | 物理积分失效；应 `apply_force`/`apply_impulse` |
| RayCast 改 `target_position` 后未 `force_raycast_update()` | P1 | 同帧读取的是旧缓存 |
| `intersect_ray(from, to, ...)` 位置参数 | P1 | 4.x 只收参数对象（`PhysicsRayQueryParameters*.create()`） |
| `body_entered` 但 `contact_monitor=false` | P1 | 信号永不触发 |

### UI / 2D 渲染

| 判据 | 级别 | 为什么 |
|---|---|---|
| 每帧改 `Label.text` | P2 | **Godot 4 没有 `cacheMode`**，只能靠降频/关 autowrap |
| 每帧 `ShaderMaterial.new()` | P1 | 材质状态碎片化，打断合批 |
| `clip_children` / `CanvasGroup` 嵌套 | P1 | 官方明确禁止嵌套 |
| `TileMap.set_cell(layer, ...)` | P1 | 4.3+ 已 deprecated，迁移 `TileMapLayer.set_cell(coords, ...)` |
| `Light2D` | P1 | 3.x 类名，4.x 拆为 Point/Directional/SpotLight2D |

### 资源 / IO / 网络

| 判据 | 级别 | 为什么 |
|---|---|---|
| `FileAccess.open()` 后未 `close()` | P0 | 句柄泄漏，导出后文件被占用 |
| `FileAccess.open()` 结果未判 `null` | P1 | 4.x 失败返回 `null`（不是 3.x 的 File 对象） |
| 写 `res://` | P1 | **导出后只读**，存档必须 `user://` |
| Resource 调 `queue_free()`/`free()` | P1 | Resource 是 RefCounted，调 Node 释放 API 是错的 |
| `bytes_to_var` / `str_to_var` 反序列化 | P0 | 不可信输入边界，可任意对象构造 |
| `instantiate()` 后未 `add_child()` | P1 | 节点不在树里，不参与 `_ready`/渲染 |
| `HTTPRequest` 未 `add_child` | P1 | 不进树不处理请求 |
| `File.new()` / `Directory.new()` | P1 | 3.x 写法，4.x 用 `FileAccess.open()`/`DirAccess.open()` |

### 输入 / 音频 / 动画 / Tween / Timer

| 判据 | 级别 | 为什么 |
|---|---|---|
| `_process` 里 `Input.is_action_just_pressed()` | P1 | 可能漏帧；应在 `_unhandled_input` 或固定步 |
| 动态 `AudioStreamPlayer` 未 `queue_free()` | P0 | 播完仍在树里累积 |
| `AnimationTree` 参数路径字面量（`"parameters/..."`） | P1 | **拼错静默失效**，不报错也不生效 |
| `AnimationPlayer.play("字面量")` | P2 | 动画名重命名后静默失效，应集中常量 |
| `create_tween()` 未保存引用 | P0 | 无法 kill，重复触发时旧 Tween 仍持有属性写入权 |
| `VideoStreamPlayer` 等未停 | P2 | 离场仍在播放 |

### 3D / 渲染

| 判据 | 级别 | 为什么 |
|---|---|---|
| 直接赋值 `global_position` | P2 | 它只是变换链的计算结果，下一帧会被物理步/父变换/插值覆盖 |
| `spot_angle` 超 89° | P2 | 超出范围不生效或产生异常阴影 |
| `editor_only=true` | P1 | 忘了关 → 导出后仍占性能预算 |
| `set_shader_parameter` 字面量名 | P2 | 与 shader uniform 名不一致时**静默失效** |
| `visibility_aabb` 不足 | P2 | 粒子被整体剔除**不报错**，表现为屏幕边缘突然消失 |
| 共享材质直接改 | 人工 | 改动会跨对象传播；需 `duplicate()`（静态无法判，靠比对 Resource 身份） |

### 语言 / 工程 / 调试

| 判据 | 级别 | 为什么 |
|---|---|---|
| `assert` 做运行时校验 | P1 | release 导出模板下 assert **不被求值**，校验整段消失 |
| `await` 后未判 `is_instance_valid` | P1 | 协程恢复时节点可能已被 `queue_free` |
| `duplicate()` 无参 | P1 | Array/Dictionary/Resource 默认**浅拷贝**，嵌套仍共享 |
| `emit_signal()` | P2 | 3.x 写法，4.x 是 `signal.emit()` |
| `print()` 调试输出 | P2 | release 仍执行；应 `print_debug()` |
| `Performance` 监视器返回 0 | 人工 | 部分指标在非 debug 构建下恒为 0，不能当"没问题" |

## 4. 各文档的组织方式

四份领域文档统一按 `### <类名>.<成员名>` 组织，每条含：

- **签名**：GDScript 写法 / C# 写法
- **用途**：一句话
- **误用**：具体什么时候出问题
- **判据**：能从 `.gd`/`.cs` 正则匹配到的源码特征
- **确认**：怎么验证（运行时/Profiler/日志）

**想查某个 API** → 直接在对应领域文档里搜 `类名.成员名`。
**想加新规则** → 从文档的「判据」字段取正则，加进 `godot-audit.py` 并配自检用例。

## 5. 置信度与版本

领域文档主要依据 Godot 4.x 官方文档（4.0–4.4 稳定版），每条标注
`官方明确` / `社区共识` / `推测`。

⚠ 4.x 各小版本在个别默认行为、废弃警告、调试 API 上可能变化。
首次在真实项目使用请抽样核对，把误报反馈回规则表。
