<!-- oversize-exempt: 引擎专项查表文档，含生命周期/所有权/迁移/性能四张对照表，需整体查阅 -->
# Godot 引擎专项

通用缺陷按场景分见 `s-numerics.md`（数值边界）、`s-structures.md`（数据结构）、`s-lifecycle.md`（成对配对 / 热路径）、`s-contracts.md`（死契约）。
本文件只写**引擎特有**的规则——换个引擎不成立的部分。

结构照 `references/engine-template.md` 的 16 节骨架，与 `p-cocos.md` 对齐。

> **置信度标注**：本文件主要依据 Godot 4.0—4.7 官方文档编写（节末引用）。
> 标注 `需实测` 的条目是本仓库尚未在真实验证的规则，命中后请先验证再下结论。
> 4.x 各小版本在个别默认行为、调试 API、废弃警告上可能有差异。

## 适用场景

**适用**：Godot 4.x 的 GDScript（`.gd`）与 C#（`.cs`）脚本。

**不适用**（别硬套）：
- Godot 3.x 项目（生命周期与 API 大量不同，见「迁移对照」）
- C++ GDExtension（内存模型是手动管理，与 GDScript/C# 的引用语义完全不同）
- 构建产物与引擎缓存（`.godot/` `build/` `bin/` `obj/` `.mono/`）
- 纯 `.tscn` / `.tres` 资源文件（本文件判的是脚本；场景文件里编辑器连的信号扫不到）

**GDScript 与 C# 的差异必须分开看**：Godot 的信号自动断开在两侧行为不同
（C# 的 lambda 捕获不会自动断开），所以下面几乎所有规则都分两列写。

## 前置依赖

```bash
python3 --version                          # 需 3.7+
python3 scripts/godot-audit.py --rules     # 确认脚本可调用
```

无 Python 3.7+ 或脚本缺失 → 只能按「审核清单」人工逐项检查。
无法访问项目路径 → 请用户指名具体文件，不要凭空猜测代码结构。

## 第 1 步 · 引擎层静态扫描

```bash
python3 scripts/godot-audit.py <项目路径或脚本>            # 全量
python3 scripts/godot-audit.py <路径> --level P0           # 只看阻塞级（CI 卡口）
python3 scripts/godot-audit.py <路径> --lang gd            # 只看 GDScript
python3 scripts/godot-audit.py <路径> --rule GD01          # 只看某条规则
python3 scripts/godot-audit.py <路径> --json               # 机器可读
python3 scripts/godot-audit.py --self-test                 # 改规则后必跑
```

**规则一览**（`--rules` 可列）：

| ID | 级别 | 判据 |
|---|---|---|
| **GD01** | P0 | `remove_child` 后无 `queue_free`/`free`/重新 `add_child` |
| **GD02** | P0 | `create_tween()` 返回值未保存且无 `kill`/`bind_node` |
| **GD03** | P1 | `create_timer()` 返回值丢弃且非 `await` |
| GD04 | P1 | 旧式字符串信号 `connect("sig", ...)` |
| GD05 | P1 | `export` / `onready` 缺 `@` 前缀 |
| GD06 | P1 | `yield(` |
| GD07 | P1 | 3.x 类名（`KinematicBody2D` / `Spatial` / `Position3D`） |
| GD08 | P1 | `.instance()` / `.Instance()` |
| GD09 | P1 | `move_and_slide` / `MoveAndSlide` 带参 |
| GD10 | P1 | C# 用 lambda 订阅信号（`+= (s,e) =>`） |
| GD11 | P1 | 帧回调内 `get_node` / `GetNode` / `find_child` |
| GD12 | P1 | 帧回调内 `instantiate` / `new` |
| GD13 | P2 | 帧回调内赋值 `text` / `Text` |
| GD14 | P1 | `_process` 内做物理移动 |
| GD15 | P1 | 有连接但 `_exit_tree` / `_ExitTree` 里无断开 |

**领域规则**（GD2x 物理 / GD3x UI / GD4x IO / GD5x 输入·音频·动画）见下方
「领域判据」一节，完整 API 级判据在 `references/godot-api/`。

**退出码**：有 P0 返回 1（可直接接 CI），否则 0。

⚠ **静态扫描的产出是「候选」，不是结论。** Godot 的信号自动断开、Tween 绑定、
C# lambda 捕获、Resource 缓存都依赖运行期对象关系，命中不等于泄漏。

## 第 2 步 · 生命周期配对（人工，扫描器扫不全）

**顺序**：`_init` → `_enter_tree`（父先子后）→ `_ready`（子先父后）→
`_process` / `_physics_process` → `_exit_tree` / `tree_exiting`

| 回调 | 该放什么 | 常见误用 |
|---|---|---|
| `_init` | 纯数据初始化 | 访问子节点 / `get_node`（此时节点未入树，子节点未就绪 → null） |
| `_enter_tree` | 连接**跨对象/全局**信号、加入组 | 假定子节点已就绪 |
| `_ready` | 缓存子节点引用、连接**局部**信号 | 反复连接同一信号而不去重 |
| `_process(delta)` | 输入、视觉动画、计时 | 做物理移动、每帧查找节点 |
| `_physics_process(delta)` | 物理积分、`move_and_slide` | 混进纯视觉逻辑，浪费固定步预算 |
| `_exit_tree` / `tree_exiting` | **断开跨生命周期连接**、停 Timer | 空实现；或在此后再访问外部状态 |

**关键**：`tree_exiting` 才是「节点仍有效」的反初始化点；`_exit_tree` 之后节点已离开树。
父子递归是**父先 `_enter_tree`、子先 `_ready`**——与直觉相反，决定了 `_ready` 里
才能安全访问子节点。

**必须断开的是「跨生命周期」的连接**，不是所有连接：
Autoload、全局事件总线、长期存活的 manager、仍在跑的 Timer/Tween。
同树父子节点之间，任一方释放时连接通常自动断开，**不要求显式 disconnect**。

## 六大泄漏源（按出现频率排序）

### 1. `remove_child` ≠ 释放（Godot 最经典）

`remove_child()` 只解除父子关系。**节点、脚本字段、信号连接、闭包引用全都还在。**

```gdscript
get_parent().remove_child(self)
# 之后既没有 queue_free，也没重新 add_child，也没交给对象池 → 孤儿节点
```

确认去向三选一：要销毁 → `queue_free()`；要复用 → 重新 `add_child()`；要缓存 → 对象池保管。
C# 的 `RemoveChild(this)` 同理。

### 2. 信号连接未断开（跨生命周期）

| | 正例 | 反例 |
|---|---|---|
| GDScript | `_exit_tree` 里 `if bus.sig.is_connected(h): bus.sig.disconnect(h)` | `_ready` 里连 Autoload 信号，`_exit_tree` 空 |
| C# | `_ExitTree(){ timer.Timeout -= _tick; }` | `button.Pressed += (s,e) => ...`（lambda 无法 `-=`） |

⚠ **C# lambda 捕获外部变量后，Godot 无法把它关联到创建实例，因此不会随实例释放自动断开**。
这是 GDScript 与 C# 行为不一致的关键点。

`CONNECT_ONE_SHOT` 是一次性的，不要求再 disconnect。

### 3. Tween 未 kill

官方：绑定对象释放时 Tween 自动销毁；绑定对象不在树中会暂停。
所以「节点释放后 Tween 一定泄漏」**不准确**。真正可检出的是：
**未保存引用又无 `bind_node`，却在可重复触发的地方 `create_tween()`**——
旧 Tween 仍持有属性写入权，且无法主动停止。

```gdscript
# 反例：每次触发都新建，无从 kill
func flash(): create_tween().tween_property(self, "modulate", Color.WHITE, 0.2)

# 正例：保存引用，重启前 kill
var _tween: Tween
func flash():
    if _tween != null and _tween.is_running(): _tween.kill()
    _tween = create_tween()
    _tween.tween_property(self, "modulate", Color.WHITE, 0.2)
```

C# 用 `_tween?.Kill()`；**不要用 `new Tween()`** —— Tween 应由 SceneTree 或 Node 创建。

### 4. Timer 与 SceneTreeTimer 混淆

`get_tree().create_timer()` 返回的是 **`SceneTreeTimer`（RefCounted）**，
不是 Timer 节点——**它没有 `start()` / `stop()`**。

- `await get_tree().create_timer(1.0).timeout` → 安全，await 持有引用
- `get_tree().create_timer(1.0)` 值被丢弃 → 只能等它自然到点，无法停止
- Timer **节点**是 Node，不 `queue_free()` 就不会释放；`remove_child` 也不释放它

需要停止/复用 → 用 Timer 节点，或保存 SceneTreeTimer 引用。

### 5. Node 未 `queue_free`

`queue_free()` 在**当前帧结束时**删除节点及其子树；`free()` 立即删除。
默认用 `queue_free()`——在信号回调链里 `free()` 可能导致后续处理器访问已释放对象。

⚠ `queue_free()` 之后**同一帧内**不能假设对象已消失。

### 6. 闭包与长期单例

Autoload 事件总线订阅、静态字段持有 Node、C# lambda 捕获 —— 都在节点树外形成引用环。
静态扫不出，只能靠运行时计数（见第 3 步）。

### 关于 Resource（不是泄漏，但常被误判）

Resource 继承 `RefCounted`，**引用归零才释放**；`load()` / `preload()` 走全局缓存，
同路径返回同一份。所以：

- 普通 Resource **不需要** `queue_free()` / `free()`（对它调 Node 的释放 API 是错的）
- 真正常见的问题是**最后一个强引用没删**（Autoload、静态字段长期持有大纹理/音频）
- `preload` 在脚本解析期加载（更早常驻），`load` 在运行时加载；不等于双倍内存

## 第 3 步 · 运行时验证（静态扫描 0 项也要做）

Godot 的判定标准比 Cocos 更直接——**对象计数**是可观测的：

```gdscript
print(Performance.get_monitor(Performance.OBJECT_COUNT))
print(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT))
```

| 观察量 | 含义 |
|---|---|
| `OBJECT_COUNT` | 存活 Object 总数 |
| `OBJECT_ORPHAN_NODE_COUNT` | **不在场景树里的 Node 数** —— 孤儿节点直接指标 |

**判定方法**：进场景记基线 → 反复开关 UI / 生成销毁对象 / 切场景 → 回初始态比较。
计数单调增长 = 所有权问题；**对象数不涨但内存涨** = Resource 缓存 / 纹理 / C# 托管对象。

补充手段：编辑器 Debugger 的 Monitors 面板、Profiler（Script / Physics 耗时）、
C# 侧 `.NET` 内存分析器。

## 性能项

### 2D 批处理

Godot 的 DrawCall 打断因素写成**清单**而非单一指标：
`CanvasGroup`（会读 backbuffer，`fit_margin` / `use_mipmaps` 有代价）、
不同 `material`、裁剪嵌套（`clip_children` 与 CanvasGroup **不能嵌套**）、
ShaderMaterial 每帧重建。

```gdscript
# 反例：每帧 new 材质，状态碎片化
func _process(_d): 
    var m = ShaderMaterial.new(); sprite.material = m
# 正例：共享材质，只改参数
mat.set_shader_parameter("color", c)
```

### 文本

⚠ **Godot 4 的 Label 没有 Cocos 式 `cacheMode`** —— 没有一键开关。
只能：值未变化则不赋值、降低更新频率、避免超大文本 + 自动换行 + 裁剪叠加。

### 物理选型（按控制方式选，不按命名习惯）

| 类型 | 适用 |
|---|---|
| `CharacterBody2D/3D` | 脚本驱动的角色；**不受物理力影响** |
| `RigidBody2D/3D` | 受冲量/扭矩/碰撞自然影响的物体 |
| `StaticBody2D/3D` | 不动的碰撞体 |
| `AnimatableBody2D/3D` | 按代码或动画移动、能带动碰撞体的平台 |

典型错误：RigidBody 上每帧直接覆盖 `position` / `linear_velocity`（物理积分失效）；
CharacterBody 在 `_process` 里 `move_and_slide`（步长随帧率变化）。

### 物理查询

`PhysicsDirectSpaceState` 的 `intersect_shape` / `intersect_point` 等要设 `max_results`
限制返回数量；缓存查询对象、复用参数、用碰撞层掩码。

### 包体

| 手段 | 做法 |
|---|---|
| 导出模板裁剪 | 去掉未用模块（3D / 物理 / 特定平台） |
| PCK 分包 | 内容放独立 PCK，主包只留启动场景 |
| 纹理压缩 | 按平台选 ASTC / ETC2 / PVRTC |
| Web 导出 | 体积敏感，注意 WASM 与资源分离 |

## 定位思路

先看 **Script** 还是 **Physics / Rendering** 耗时——搞反了会白优化。
Godot 的 Profiler 能直接分开这几项；C# 侧还要区分托管堆分配与引擎侧。

## 输出格式

按 P0 → P1 → P2 分级，每条含**文件:行号 · 问题 · 为什么 · 怎么改**四项。
不确定的标"待确认"，不硬判——尤其是所有权类条目。

## 领域判据（API 级）

核心判据（GD01–GD15）只覆盖所有权与迁移。**具体 API 的用法错误**在
`references/godot-api/` 四份查表文档里，按领域分：

| 领域 | 文档 | 行数 | 路由信号 |
|---|---|---|---|
| 物理 | `godot-api/physics.md` | 505 | `move_and_slide` · `RigidBody` · `collision_layer` · `intersect_ray` |
| UI / 2D 渲染 | `godot-api/ui.md` | 489 | `Label` · `CanvasGroup` · `TileMap` · `ShaderMaterial` |
| 资源 / IO / 网络 | `godot-api/io.md` | 1483 | `FileAccess` · `ResourceLoader` · `HTTPRequest` · `user://` |
| 输入 / 音频 / 动画 / Tween | `godot-api/anim.md` | 1433 | `Input.` · `AnimationTree` · `create_tween` · `AudioStreamPlayer` |
| 3D / 渲染 | `godot-api/3d.md` | 718 | `Node3D` · `MeshInstance3D` · `Camera3D` · `Light3D` · `Environment` · `SubViewport` · `GPUParticles3D` · `set_shader_parameter` |
| 语言 / 工程 / 调试 | `godot-api/lang.md` | 633 | `@export` · `@rpc` · `await` · `ProjectSettings` · `Performance.` · `change_scene` · `assert` |

**不要一次全读**（合计 ~3900 行）。跑 `route.py --src=<根>` 会按代码里
实际出现的 API 名列出命中的领域；也可查 `godot-api/index.md` 的路由表。

已落进扫描器的领域规则：

| ID | 级别 | 判据 |
|---|---|---|
| GD21 | P1 | `velocity *= delta` 后调 `move_and_slide()`（引擎内部已积分 → 二次积分） |
| GD22 | P1 | 帧/物理回调里 `apply_impulse`（一次性冲击，每帧应改 `apply_force`） |
| GD23 | P1 | 改 `target_position` 未 `force_raycast_update()`（同帧读旧缓存） |
| GD24 | P1 | `intersect_ray(from, to, ...)` 位置参数（4.x 只收参数对象） |
| GD26 | P1 | 连 `body_entered` 但未开 `contact_monitor`（信号永不触发） |
| GD31 | P1 | 帧回调里 `new ShaderMaterial`（材质碎片化，打断合批） |
| GD32 | P1 | `CanvasGroup`（禁与 `clip_children` 嵌套，读 backbuffer 有代价） |
| GD33 | P1 | `set_cell(数字, ...)` 层号优先 = 4.3 前的旧签名 |
| GD34 | P1 | `Light2D`（3.x 类名，4.x 拆为 Point/Directional/Spot） |
| GD41 | P1 | `FileAccess.open()` 未见 `close()`（句柄泄漏） |
| GD43 | P1 | 往 `res://` 写（导出后只读，静默失败） |
| GD45 | **P0** | `bytes_to_var` / `str_to_var` 反序列化（不可信输入 = 任意对象构造） |
| GD46 | P1 | `instantiate()` 未见 `add_child()`（不进树不触发 `_ready`） |
| GD47 | P1 | `HTTPRequest` 未见 `add_child`（不进树不处理请求） |
| GD48 | P1 | `File.new()` / `Directory.new()`（3.x 写法） |
| GD51 | P1 | 非输入回调里 `Input.is_action_just_pressed()`（掉帧会漏输入） |
| GD52 | **P0** | 动态 `AudioStreamPlayer` 未见 `queue_free()`（Node 累积） |
| GD53 | P2 | `AnimationTree` 参数路径字面量（拼错静默失效） |
| GD54 | P2 | 动画名字面量（重命名后静默不播） |
| GD61 | P2 | 直接赋值 `global_position`（会被物理步/父变换/插值覆盖） |
| GD62 | P2 | `spot_angle` 超 89°（不生效或异常阴影） |
| GD63 | P1 | `editor_only=true`（导出后白占性能预算） |
| GD64 | P2 | `set_shader_parameter` 用字面量名（与 uniform 名不一致时静默失效） |
| GD65 | P2 | `visibility_aabb`（包围盒不足时粒子被整体剔除，**不报错**） |
| GD71 | P1 | `assert` 做运行时校验（release 下 assert 不求值，校验整段消失） |
| GD72 | P2 | `emit_signal()`（3.x 写法，4.x 用 `.emit()`） |
| GD73 | P1 | `duplicate()` 无参（Array/Dictionary/Resource 是**浅拷贝**） |
| GD74 | P2 | `print()` 调试输出（release 仍执行） |
| GD75 | P1 | `await` 后未判 `is_instance_valid`（协程恢复时对象可能已释放） |
| GD81 | P1 | 加密存档但无签名（AES-CBC 无认证，可被比特翻转，解密不报错） |
| GD82 | P1 | 密钥/口令明文写在脚本（PCK 可解包，等于没加密） |
| GD83 | P1 | 用 `get_unix_time_from_system()` 做时间判定（改系统时钟即绕过） |
| GD84 | P2 | 用 `==` 比对 HMAC（时序侧信道） |
| GD85 | P1 | `is_debug_build()` 检测后直接退出/弹窗（暴露检查点） |
| — | 人工 | 客户端加密当防作弊（结构性无效，密钥必在客户端）；联网逻辑必须在服务端 |
| GD91 | P0 | 帧回调内同步 `load()`（每帧磁盘 I/O） |
| GD92 | P1 | 帧回调内用字符串字面量查输入动作（应 `&"jump"`） |
| GD93 | P1 | 浮点值直接 `==` 比较（精度误差，几乎永不成立） |
| GD94 | P1 | `distance_to()` 做阈值比较（多余开方，应 `distance_squared_to`） |
| GD95 | P0 | `@export` 的 Resource 未 `duplicate()`（所有实例共享，改一个全变） |
| GD96 | P0 | `_physics_process` 内 `await`（挂起会跳过物理帧） |
| GD97 | P2 | 函数体只有 `pass`（占位或应删） |
| GD98 | P2 | 自赋值 / 自比较（通常是笔误） |
| GD99 | P2 | 函数体超 80 行（职责过多） |
| — | 人工 | 物理层与掩码设同值、SubViewport 过度嵌套、未用类型化数组 |

**没进扫描器的**（需要跨文件或运行时对象关系，只能人工看）：
碰撞层位值混用、`StaticBody` 移动当平台、RigidBody 每帧覆盖 `position`、
`is_on_floor()` 做边沿检测。这些在 `godot-api/physics.md` 里有判据描述，
但静态命中会大量误报，所以留给人工。

## 迁移对照（3.x → 4.x）

| 维度 | 3.x | 4.x |
|---|---|---|
| 角色节点 | `KinematicBody2D/3D` | `CharacterBody2D/3D` |
| 空间节点 | `Spatial` | `Node3D` |
| 标记节点 | `Position3D` | `Marker3D` |
| 移动 | `move_and_slide(velocity, up)` | `velocity` / `up_direction` 为属性，`move_and_slide()` |
| 导出 | `export var` | `@export var` |
| 延迟就绪 | `onready var` | `@onready var` |
| 协程 | `yield(get_tree(), "idle_frame")` | `await get_tree().process_frame` |
| 信号完成 | `yield(sig, "completed")` | `await sig` |
| 实例化 | `scene.instance()` | `scene.instantiate()` |
| 信号连接 | `connect("pressed", self, "_on_pressed")` | `button.pressed.connect(_on_pressed)` |

C# 侧注意 **PascalCase**：`QueueFree`、`CreateTween`、`Instantiate`、`SignalName.Pressed`。

⚠ `move_and_slide()` 的无参化最容易造成「能编译但行为改变」——
旧代码把参数传进去，4.x 会当成自定义参数或报错。

## 失败处理

| 情况 | 判据 | 动作 |
|---|---|---|
| 扫描 0 项 | 不代表没问题 | 闭包 / Autoload / Resource 长期引用扫不出 → 仍需第 2、3 步 |
| GD01 大量命中 | 对象池 / 状态机合法移出 | 看是否重新 `add_child` 或交池保管；合法则忽略 |
| GD15 误报 | 同树父子连接 | 任一方释放会自动断开，可忽略 |
| 无法判断 | 跨文件连接 | 标"待确认"，不计 P0 |
| 内存涨但对象数不涨 | Resource / 纹理 / 托管堆 | 明说"静态无法确认，建议 Monitors 对比" |

## 关键判断依据

**为什么 `remove_child` 无释放定 P0**：跨场景反复切换会累积孤儿节点，
`OBJECT_ORPHAN_NODE_COUNT` 单调增长，且节点上的信号/闭包一并滞留。

**为什么 C# lambda 单列**：`+= (s,e) => ...` 之后**无法**精确 `-=`
（委托身份不保留）。是"写了也断不掉"而非"忘了断"，成因与改法都不同。

**为什么 Resource 不进泄漏规则**：它是引用计数对象，手动 `queue_free()` 反而是错的。
真正的风险是强引用没删，那属于架构问题，不是单行代码特征。

**为什么 DrawCall 不进扫描项**：取决于场景结构与批次配置，静态扫脚本看不出来。

## 扫描器的已知局限

| 局限 | 表现 | 处理 |
|---|---|---|
| 只判**方法内**上下文 | `remove_child` 与 `queue_free` 跨方法 → 会误报 | 看是否交对象池 / 重新 add_child |
| 无法跟踪**跨文件** | A 连、B 断 → 两边都报 | 人工确认 |
| 编辑器连的信号扫不到 | 信号连接在 `.tscn` 里 | 扫脚本看不到，需查场景文件 |
| C# 自定义方法体不提取 | 只认 `_Ready` 这类回调 | 匹配不到方法时退化为邻近行判断，可能漏 |
| 闭包 / Autoload / Resource 强引用 | 完全扫不出 | 必须人工第 2、3 步 |
| GDScript 动态类型 | 同名方法、动态派发会误判 | 标"待确认" |

⚠ 本扫描器的规则**没有经过真机或真实项目验收**（仅自检样本验证）。
首次在真实项目上使用时，请抽样核对命中项，把误报反馈回规则表。

## 已知坑

- ⚠ 本能以为 `remove_child` 会释放节点，但**它只解除父子关系**，节点与它的信号、闭包引用都还在
- ⚠ 本能以为信号连接会随对象释放自动断开，但 **C# 捕获变量的 lambda 不会**
- ⚠ 本能以为 Tween 一定随节点释放，但**未绑定/未保存的 `create_tween()` 不会**
- ⚠ 本能以为 `create_timer()` 返回的是 Timer 节点，但它**没有 `start()` / `stop()`**
- ⚠ 本能以为 Resource 要 `queue_free()`，但它是 **RefCounted**，调 Node 的释放 API 是错的
- ⚠ 本能以为 `preload` 与 `load` 各生成副本，但**同路径进全局缓存，是同一份**
- ⚠ 本能以为 `queue_free()` 立即销毁，但它**在帧末才删除**，同一帧内不能假设对象已消失
- ⚠ 本能以为 `_ready` 里子节点一定可用（对），但 **`_init` 里不可用**（此时未入树）
- ⚠ 本能以为 `_exit_tree` 里节点还活着，但**`tree_exiting` 才是仍有效的清理点**
- ⚠ 本能以为 `_process` 和 `_physics_process` 都能放移动，但**速率与权威状态不同**
- ⚠ 本能以为 Label 有 `cacheMode`，但 **Godot 4 的 Label 没有这个属性**
- ⚠ 本能以为 CharacterBody 受力控制，但它**不受物理力直接影响**

## 可复用片段

**所有权安全的组件模板（GDScript）**：

```gdscript
extends Node2D

@onready var _label: Label = $Label
var _tween: Tween
var _timer: Timer

func _ready() -> void:
    _label.text = "ready"
    _timer = $TickTimer
    _timer.timeout.connect(_on_tick)

func _physics_process(_delta: float) -> void:
    pass   # 移动逻辑放这里，不放 _process

func flash() -> void:
    if _tween != null and _tween.is_running():
        _tween.kill()
    _tween = create_tween()
    _tween.tween_property(self, "modulate", Color.WHITE, 0.2)

func despawn() -> void:
    get_parent().remove_child(self)
    queue_free()                       # remove_child 之后必须释放或重新入树

func _exit_tree() -> void:
    if _timer.timeout.is_connected(_on_tick):
        _timer.timeout.disconnect(_on_tick)
    if _tween != null:
        _tween.kill()

func _on_tick() -> void:
    pass
```

**C# 对称版本要点**：`[Export]` 属性 · `_Ready` 里缓存 `GetNode<T>()` ·
具名方法订阅信号并保存 delegate · `_ExitTree` 里 `-=` 并 `_tween?.Kill()`。

## 审核清单（扫描器不可用时的兜底）

```
□ 每个 remove_child 之后都有 queue_free / 重新 add_child / 交对象池
□ 跨生命周期（Autoload / 全局总线）的连接在 _exit_tree 里断开
□ C# 不用 lambda 订阅需要 -= 的信号
□ create_tween() 结果已保存，重复触发前 kill
□ 区分 Timer 节点与 SceneTreeTimer（后者无 start/stop）
□ 需要销毁的 Node 都 queue_free（不是只 remove_child）
□ _process 内无 get_node / find_child / instantiate / new
□ 物理移动在 _physics_process，不在 _process
□ 无 3.x 遗留（字符串信号 / export 无 @ / yield / .instance() / KinematicBody）
□ move_and_slide 无参，速度与朝向走属性
□ 帧内改 text 前先比较值
□ 运行时验证：反复切场景后 OBJECT_ORPHAN_NODE_COUNT 不单调增长
```

## 参考来源

Godot 官方文档（4.x）：Node / Signal / Tween / SceneTreeTimer / Resource /
CharacterBody2D / PhysicsDirectSpaceState2D / CanvasItem / CanvasGroup / Label /
C# signals 与 C# API 差异；以及社区升级指南（3.x→4.x 破坏性变更）。
