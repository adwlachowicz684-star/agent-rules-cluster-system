# Godot 4.x 开放世界与大场景

流式加载、地形、LOD、**大世界坐标精度**、剔除。
小项目测不出问题，做大世界才会暴露——这是本文存在的理由。

## 0. 两个核心风险

1. **加载卡顿**：不是"异步加载"就行，要可预测的预算 + 稳定的 chunk 状态机
2. **坐标精度**：离原点越远精度越差，**小项目完全测不出来**

## 1. Chunk 流式加载

### 三条半径构成滞回（hysteresis）

```
load_radius    ← 进入就请求加载
unload_radius  ← 超出才卸载（必须 > load_radius）
unload_delay   ← 超出后再等一会儿才真卸载
```

⚠ **没有滞回，玩家在 chunk 边界来回走会触发抖动式加载/卸载**，
表现为周期性卡顿。这个 bug 在测试时很容易被当成"资源太大"。

### 加载状态机要分开

```
请求 → 解码 → 实例化 → 就绪 → 预热 → 卸载
```

⚠ `ResourceLoader.load_threaded_request` 把**解析**移出主线程，
但 `load_threaded_get` 未完成时**仍会阻塞**。

⚠ **`PackedScene.instantiate()` 必须回主线程**。
所以"异步加载"不等于"不卡"，实例化和 `add_child` 才是主要开销。

### 分帧预算

```gdscript
const FRAME_BUDGET_MS := 4.0

func _process(_d: float) -> void:
    var start := Time.get_ticks_usec()
    while not _pending.is_empty():
        _instantiate_one(_pending.pop_front())
        if (Time.get_ticks_usec() - start) / 1000.0 > FRAME_BUDGET_MS:
            break        # 超预算，下一帧继续
```

⚠ 一帧内实例化几十个场景 = 一帧卡顿几十毫秒。
必须按时间预算切分，而不是按数量。

### 节点池

```gdscript
class_name ChunkNodePool
extends Node

var _free: Dictionary = {}      # scene_path -> Array[Node]

func acquire(path: String, parent: Node) -> Node:
    var arr: Array = _free.get(path, [])
    var n: Node
    if arr.is_empty():
        n = load(path).instantiate()
    else:
        n = arr.pop_back()
    parent.add_child(n)
    return n

func release(path: String, n: Node) -> void:
    n.get_parent().remove_child(n)
    _free.get_or_add(path, []).append(n)
```

⚠ 高频加载卸载的场景（草、石头、树木）**必须池化**。
反复 `instantiate` + `queue_free` 是 GC 压力的主要来源。

## 2. 地形

⚠ **Godot 4 没有内置可编辑地形节点**。选项是：

| 方案 | 适合 |
|---|---|
| **Terrain3D**（GDExtension，MIT） | 开放世界、需要笔刷编辑 |
| 高度图 + 自写网格生成 | 中小规模、程序化生成 |
| 普通 mesh | 小规模、美术手工做的地形 |

⚠ Terrain3D 有**引擎版本要求**（官方页要求 4.4–4.6+，以仓库为准）。
它是 GDExtension，**ABI 必须与引擎版本对齐**（见 `plugins.md`）。

⚠ **双精度引擎 + 单精度插件 = 插件内部仍按 32 位工作**。
换双精度前要确认所有 GDExtension 都有对应构建。

### 地形着色

多层纹理混合通常按**高度 + 坡度**混合，不是简单叠：

```
坡度高 → 岩石
高度低且坡度低 → 草地
```

## 3. 纹理 VRAM：4.8 的 mip 级流送

⚠ **这是 4.8 特性（dev 阶段，Q4 2026 预计 stable），不是 4.7**。

按相机相对位置**只加载需要的 mipmap 层级**，显著降低 VRAM。
需要先在项目设置开启（**要重启编辑器**），纹理以新类型
**"Texture2D Streamed"** 导入，可逐纹理覆盖 min/max 分辨率。

⚠ **只在 Mobile 与 Forward+ 实现**，Compatibility 没有（GLES 3.0 读回限制）。
⚠ **Mobile 渲染器缺 depth pre-pass**，用 alpha scissor / `discard` 时会强制
early-z，**性能可能反而更差**。
⚠ 官方说 2D 用法没怎么测，**主要面向 3D**。
⚠ 它与下面的 chunk 流式加载是**互补不是替代**：那个管场景节点，这个管纹理 VRAM。

⚠ **传送玩家后要调 `flush_texture_streaming()`**。默认按渐变与 I/O 节流加载，
传送过去会**先糊后清**（从低分辨率渐变上来）。官方说明该调用
"在加载画面或传送玩家时有用"，另有 `flush_completed` 信号可以等。
⛔ 表现为"传送后一片模糊，走两步才清楚"，
极易被当成纹理压缩或各向异性设置的问题去查。

⚠ **超预算会自动降分辨率**：按 VRAM 预算工作，
超出时降低纹理分辨率以守住上限，可用 `get_memory_budget_bytes_used()` 查当前占用。
⛔ 表现为"远处贴图莫名变糊"，而去查一个根本没开的 LOD bias。

## 4. LOD

| 方式 | 说明 |
|---|---|
| importer 自动生成 | glTF/blend/FBX 支持；**OBJ 不自动生成** |
| 手动多 mesh + 距离切换 | 可控但繁琐 |
| `VisibilityRange` | 距离剔除（超出直接不画） |

⚠ **自动 LOD 按屏幕覆盖度选，不是按距离**。
不能按"远 30 米切一级"估算收益。

⚠ LOD 切换的 popping（突跳）用 **dither fade** 缓解，
比直接切好看很多，代价很小。

## 5. 大世界坐标精度（重点）

### 症状出现的顺序

```
远处轻微抖动
  → 贴地与碰撞位置 snap
  → 光照/阴影在网格间跳跃
  → 射线查询不稳定
  → 明显位移错误
```

⚠ **因为角色常在原点附近，远处山体只做渲染，
小项目在几千米内测试完全测不出问题。** 等你发现时世界已经建好了。

### 官方建议的最大范围（单精度）

| 类型 | 建议上限（离原点距离） |
|---|---|
| 第一人称 | 4096 |
| 第三人称 | 8192 |
| 俯视 | 32768 |
| 一般 3D | 65536 |

⚠ **这是「区间上限」，不是区间本身。** 官方表按 2 的幂划分区间，
把"最大推荐范围"标注在该区间的**上界**（如 `[2048; 4096]` 标注第一人称，
即上限 4096；`[32768; 65536]` 标注"任何 3D 游戏"，并注明
**超过此值通常需要双精度**）。

⛔ 记成"4096–8192"会整体错一档、上限翻倍。按错的值把世界建到一半才暴露，
那时地形、寻路、存档都已按错误规模定型。

⚠ 这是**建议值不是硬阈值**。误差随 2 的幂成倍变化，
不存在"8192 米以内绝对安全"。

### 方案 A：原点重置（floating origin）—— 推荐

思路：游戏逻辑用世界坐标 `W`，场景里存 `L = W - O`。
`O` 移动超过阈值就整体偏移一次。

```gdscript
class_name FloatingOrigin
extends Node

@export var origin_node: Node3D
@export var recenter_threshold := 500.0
@export var recenter_interval := 1.0

var active_origin := Vector3.ZERO
var _elapsed := 0.0

func _process(delta: float) -> void:
    if not origin_node:
        return
    _elapsed += delta
    if _elapsed < recenter_interval:
        return
    var o := origin_node.global_position
    if o.length() < recenter_threshold:
        return
    _elapsed = 0.0
    recenter(o)

func recenter(delta_origin: Vector3) -> void:
    active_origin += delta_origin
    var tree := get_tree()
    for g in ["floating_origin_actor", "floating_origin_static"]:
        for node in tree.get_nodes_in_group(g):
            if node is Node3D:
                node.global_position -= delta_origin
    _notify_systems(delta_origin)      # 物理/导航/网络/音频/存档都要听

func world_to_local(world: Vector3) -> Vector3:
    return world - active_origin

func local_to_world(local: Vector3) -> Vector3:
    return local + active_origin
```

⚠ **核心不是"移动相机"，是让所有读 `global_transform` 的系统都同步**。
只重置玩家和相机，不重置远处 NPC、音频监听器、粒子、
后处理目标、导航和物理对象 → **世界瞬间错位**。

⚠ **多人游戏里原点重置尤其危险**：服务端用全局坐标、
客户端用本地浮动坐标时，每个网络包都要 `world ↔ local` 转换。
处理不一致会"跳格"，单机看起来却正常。

### 方案 B：双精度构建

⚠ **不是勾一个设置**。要：

1. 重新编译 editor
2. 为**所有目标平台**编译 export template（`precision=double`，产物带 `.double`）
3. 导出预设里指定自定义模板
4. 重新导入测试资源
5. 验证插件、着色器、导航、物理
6. 重建 CI 与分发流程

⚠ 官方构建**默认不启用双精度**（性能与内存原因）。
⚠ 有性能与内存开销，32 位 CPU 上尤其明显。

### ⛔ 开了双精度，渲染照旧抖

⚠ **位置在送 GPU 前会被降回单精度**。官方用 emulation 模拟双精度渲染
（shader 里**不用** double，出于性能）。所以"开了双精度构建，
远处物体照旧抖"**不是玄学**：

- ⛔ **Metal（所有 Apple 设备）不支持 shader 里的 double**
- ⛔ 部分集成显卡用双精度 shader **直接崩溃**（官方博客实测）
- 因此只在 `MODELVIEW_MATRIX` 的计算上保精度，其余仍是单精度

⚠ **低端移动设备不要用双精度。** 官方：低端设备上表现不好；
⛔ 低端平台的官方建议是改用**原点重置**（方案 A），而不是双精度。
官方同时提示：原点重置在**多人游戏**里会给游戏逻辑引入更多复杂性。

## 6. 剔除

| 方式 | Godot 4 现状 |
|---|---|
| 视锥剔除 | 自动做 |
| 遮挡剔除 | 有相关支持，需按版本核对具体用法 |
| 手动剔除 | 大量实例时自己做 |

⚠ `visible = false` / 移出树 / `queue_free` 三者代价不同：

```
visible=false   最轻，但仍在树里（仍参与 process）
remove_child    中等，但对象还在内存
queue_free      最彻底，但重建有成本
```

高频切换用 `visible` + 池化，不要 `queue_free`。

## 7. 存档与大世界

⚠ **不是所有东西都该存**：

| 存 | 重建 |
|---|---|
| 玩家修改的地形数据 | 未修改的自然地形 |
| 建筑/箱子里的内容 | 植被、装饰 |
| 任务进度 | 随机生成的野怪 |

⚠ 玩家修改的地形要存**增量**（diff），
存全量高度图会让存档文件巨大。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/openworld.md`


## 8. 相关文档

- 性能优化 → `performance.md`
- 调试卡顿 → `debugging.md`
- 插件引入（Terrain3D 属 GDExtension）→ `plugins.md`
- 版本兼容 → `version-migration.md`
- 存档 → `security.md`
