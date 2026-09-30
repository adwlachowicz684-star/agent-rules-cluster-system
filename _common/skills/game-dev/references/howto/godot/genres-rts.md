# Godot 4.x RTS / 即时战略

RTS 的架构核心是**"命令模式 + 组选择 + 降频 AI"**，
不是"每个单位一个 Node 自己跑逻辑"。

## 0. 四层分离

| 层 | 职责 |
|---|---|
| **选择层** | 单选/框选/编组 |
| **命令层** | 每个单位一个 `Array[Command]` |
| **执行层** | 单位消费队首命令、编队偏移 |
| **感知层** | 战争迷雾、视野 |

## 1. 命令是数据，不是信号

```gdscript
# command.gd
class_name Command extends Resource

enum Type { MOVE, ATTACK_MOVE, ATTACK_TARGET, HOLD, PATROL }
@export var type: Type = Type.MOVE
@export var target_pos: Vector2
@export var target_unit_id: int = -1
@export var queued: bool = false   # Shift 追加
```

⚠ **指令队列不要用信号串起来** —— 信号适合"事件已经发生"，
不适合"待执行的意图"。命令要支持插入、取消、替换，
并在单位死亡/目标失效时做有效性检查。

```gdscript
func _tick() -> void:
    while not _queue.is_empty():
        var cmd := _queue[0] as Command
        if not _is_valid(cmd):
            _queue.remove_at(0)
            continue
        if not _execute(cmd):
            break           # 未完成的命令继续占用队首
        _queue.remove_at(0)
```

## 2. 框选：世界坐标转换 + Rect2，不要用 Area2D 套

### ⚠ 查询结果默认只返回 32 个

⚠ **官方签名**：`intersect_point(parameters, max_results: int = 32)`、
`intersect_shape(parameters, max_results: int = 32)`、
`collide_shape(parameters, max_results: int = 32)`。

⛔ **RTS 里这是直接的功能 bug**：框选 200 个单位，只回来 32 个，
玩家看到的是"选了一部分"，且**没有任何报错**。

⚠ 更隐蔽的是**它按返回顺序截断，不是按优先级** ——
被丢掉的 168 个是"引擎先碰到的 32 个之外的"，
不是"最该选中的"。表现就是框选结果**随单位摆放顺序变化**。

```gdscript
var q := PhysicsShapeQueryParameters2D.new()
q.shape = rect_shape
q.collision_mask = UNIT_LAYER
var hits := space.intersect_shape(q, MAX_SELECT)   # ⚠ 显式传，别用默认
```

✅ 两条应对：
1. **显式传 `max_results`**，值取"最多可同时选中数 × 余量"
2. ⚠ **满了要能判断"可能还有"** —— 返回数 == max_results 时应提示或改用空间哈希自算

ⓘ 第二条常被漏：达到上限时静默截断，
玩家以为全选了，实际漏了一大半。**没有任何迹象**。

⚠ **`Camera2D` 没有 `screen_to_world_point()` 方法。**
屏幕点转世界坐标：

```gdscript
func screen_to_world(p: Vector2) -> Vector2:
    return get_screen_transform().affine_inverse() * p
```

```gdscript
var rect := Rect2(drag_start, drag_end - drag_start).abs()
for u in _units:
    if rect.has_point(screen_to_world(u.global_position)):
        _select(u)
```

⚠ **`Rect2.has_point()` 约定右边缘与底边缘上的点不算包含** ——
做"框到才算选中"时要手动加容差。

## 3. 编队：算偏移位，不要所有单位同目标点

```gdscript
func formation_offsets(n: int) -> Array[Vector2]:
    # 菱形/网格偏移，避免大军挤在一点
    var out: Array[Vector2] = []
    var cols := int(ceil(sqrt(float(n))))
    for i in n:
        var r := i / cols
        var c := i % cols
        out.append(Vector2(c - cols / 2.0, r) * SPACING)
    return out
```

⚠ **把所有单位指向同一目标点，RVO 能缓解但会引入抖动**。
正确做法是各 agent 各自寻路到偏移位。

## 4. 战争迷雾是独立的格子状态，不是 Light2D

⚠ **`Light2D` 不是"视野可见性系统"** —— 它管的是 2D 光照与阴影
（`range_z_min/max`、`height`、`shadow_item_cull_mask`）。

RTS 迷雾的标准做法：

```gdscript
# 独立 TileMapLayer，每格 visible / explored 两态
var _dirty: Array[Vector2i] = []

func reveal(world_pos: Vector2, radius: int) -> void:
    var center := fog_layer.local_to_map(world_pos)
    for c in _cells_in_radius(center, radius):
        _dirty.append(c)

func _flush() -> void:   # 逻辑帧末尾一次性提交
    for c in _dirty:
        fog_layer.set_cell(c, SRC_FOG, ATLAS_VISIBLE)
    _dirty.clear()
```

⚠ **迷雾层要关掉 `navigation_enabled`** —— 否则会生成无意义的导航区域。

## 5. 单位管理：持有数组，不要每帧遍历场景树

```gdscript
var _units: Array[Unit] = []   # UnitManager 持有
```

⚠ **不要每帧 `get_nodes_in_group("units")`** —— 那是全树扫描。
启停只改数组，不碰场景树。

## 6. 性能三档降级

| 规模 | 方案 |
|---|---|
| ≤ 200 单位 | 完整 `CharacterBody2D` + `move_and_slide` + avoidance |
| 200–800 | `NavigationAgent2D` 取路径点 + 直接位置赋值（跳过物理） |
| > 800 | 逻辑网格单元 + 批量 `MultiMesh` 渲染；C# 或 GDExtension 结算 |

⚠ **1000 个 `CharacterBody2D` 各跑 `move_and_slide` + avoidance
在 GDScript 下会迅速掉帧。**

⚠ **2D RTS 别指望 Jolt 加速** —— Jolt 自 4.4 实验、4.6 起是**3D**默认物理，
2D 默认仍是 Godot Physics。

## 7. 视野更新做脏区批量

⚠ **100 个单位每帧各写一次 `set_cell` 会反复触发导航/渲染重算**。
收集本轮变化的格子，逻辑帧末尾一次性提交。

## 8. 避障与寻路：三条官方约束

⚠ **`avoidance_enabled` 默认是 `false`。** 置 true 后代理会在
`NavigationServer2D` 上注册 RVO 避障回调，完成后用 `safe_velocity`
经 `velocity_computed` 信号返回。

⛔ **官方原话（性能）**：_"Avoidance processing with many registered agents
has a significant performance cost and should only be enabled on agents
that currently require it."_

⛔ RTS 里"给 1000 个单位全开避障"是**官方点名的开销源** ——
而且它不是掉帧那么简单：`target_position` 设下去后路径逻辑不推进，
单位表现为"卡住不动原地挤"，⛔ 这时看 `velocity` 与碰撞都正常，
排查会被引向寻路网格而不是避障开关。

⚠ **官方 Note（必须每物理帧调一次）**：设了 `target_position` 之后，
**必须每物理帧调用一次** `get_next_path_position()` 来更新内部路径逻辑。

⛔ **更隐蔽的是递归**：官方写明 `get_next_path_position()` 等方法
**会触发新的路径计算**，在 `waypoint_reached` 这类信号的回调里调用它
**会导致无限递归**。

⛔ 而"到点后取下一个点"恰恰是 RTS 最自然的写法 ——
于是卡死表现为"单位走到第一个路径点后停住"，
日志里**没有报错**，只是再也不动了。

```gdscript
# ⛔ 典型错法：在信号回调里取下一个点 → 官方警告会无限递归
func _on_waypoint_reached(_d: Dictionary) -> void:
    _next = agent.get_next_path_position()      # ⛔

# ✅ 放在物理步里取，帧末再改 target
func _physics_process(_d: float) -> void:
    if not agent.is_navigation_finished():
        _next = agent.get_next_path_position()   # ✅ 每物理帧一次
```

ⓘ **避障在物理之前计算**（官方口径），所以避障结果可以安全地用于物理步。

## 9. 相机与屏幕坐标：官方口径

⚠ **官方 Note**：`Camera2D` 的 `global_position`
**不代表屏幕的实际位置** —— 平滑（smoothing）与边界限制（limits）
会让它与真实屏幕位置不同；要看真实位置用 **`get_screen_center_position()`**。

⚠ 同一条也适用于 **`global_rotation`**（旋转平滑会导致不同），
要用 **`get_screen_rotation()`**。

⛔ RTS 相机几乎必然开平滑与边界限制 ——
用 `camera.global_position` 反推屏幕中心来算框选矩形，
框出来的区域与实际看到的**差一个平滑偏移量**，
表现为"框选边缘的单位选不中 / 多选"，⛔ 而相机代码一处都没错。

⚠ **屏幕→世界的变换要经 viewport，不是相机节点**：

```gdscript
# ✅ 官方口径：viewport 的 screen_transform 与 canvas_transform 组合
func screen_to_world(screen_pos: Vector2) -> Vector2:
    var vp := get_viewport()
    return (vp.get_screen_transform() * vp.get_canvas_transform()).affine_inverse() * screen_pos
```

⛔ **不要用 `Camera2D` 继承来的 `get_screen_transform()` 做这件事** ——
它是 `CanvasItem` 的方法，含义是**该节点自身变换到屏幕**的变换，
其逆变换把屏幕点换到**该节点的局部空间**，不是世界空间。
相机节点不在世界原点时，框选结果整体偏移，
⛔ 而相机平滑关掉时偏移恰好为 0 —— **于是只在开了平滑之后才暴露**。

ⓘ `_input()` / `_unhandled_input()` 里 `event.position` 是
**viewport 坐标**（官方论坛口径），换算前不要当成世界坐标用。

## 10. 流程：按什么顺序做

> 选择层 / 命令层 / 执行层 / 感知层四层按什么顺序落地、
> 大规模单位怎么分档降级、验收要跑哪些敌意场景
> → `flow/godot/rts/`

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-rts.md`
