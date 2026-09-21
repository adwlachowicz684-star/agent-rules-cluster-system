# Godot 4.x 自走棋 / 战棋

自走棋是**"回合状态机 + 棋盘模型 + AI 托管"**；
战棋则强调**"行动点 / 视野 / 朝向"**。两者共用棋盘与单位模型。

## 0. 棋盘必须双表示

```
逻辑坐标 (q,r) 或 (x,y,z)   ← 所有规则在这里算
        ↓
渲染坐标 (TileMapLayer / Node2D)  ← 只负责画
```

⚠ **判定不能依赖 `TileMapLayer` 的 tile 数据** ——
它是呈现层，不是规则层。旋转/缩放影响渲染，不该影响规则。

```gdscript
class_name Board extends RefCounted

var cells: Array[Array] = []      # cells[y][x] -> Cell

func at(c: Vector2i) -> Cell:
    if not in_bounds(c): return null
    return cells[c.y][c.x]
```

## 1. 六边形用轴向坐标（axial）

```
cube: x + y + z = 0
axial: (q, r)  →  cube: x=q, z=r, y=-q-r
```

六个邻居方向（尖顶/平顶两套公式**不能混**）：

```gdscript
const AXIAL_DIRS := [
    Vector2i(+1, 0), Vector2i(+1, -1), Vector2i(0, -1),
    Vector2i(-1, 0), Vector2i(-1, +1), Vector2i(0, +1),
]

func distance(a: Vector2i, b: Vector2i) -> int:
    var dq := a.x - b.x
    var dr := a.y - b.y
    return (absi(dq) + absi(dq + dr) + absi(dr)) / 2
```

⚠ **不要用 `TileMapLayer` 的格子坐标直接算六边形邻居** ——
`TileMapLayer` 是正交网格，轴向坐标的 6 邻居映射必须自己写。

## 2. 朝向是离散枚举，不是角度

```gdscript
enum Facing { N, NE, SE, S, SW, NW }   # 六向
# 影响：侧面/背面命中率、扇形技能范围
```

⚠ **朝向不是"面朝目标的方向角"** ——
战棋的"面朝"是离散枚举，影响命中率与扇形技能；
`Node2D.rotation` 只负责视觉插值，不代表规则朝向。

```gdscript
func facing_to(a: Vector2i, b: Vector2i) -> int:
    # 逻辑坐标 → 六向枚举，再插值到 rotation 做表现
```

## 3. 行动点与移动力是两件事

| 概念 | 性质 | 计算 |
|---|---|---|
| **移动力** | 路径成本累加 | `AStarGrid2D` 权重和 |
| **行动点 AP** | 资源结算 | 固定数值扣减 |

⚠ **二者都要在命令合法性校验阶段算清，不能边执行边发现不够**。

```gdscript
func can_execute(u: Unit, cmd: Command) -> bool:
    var cost_path := _path_cost(u.cell, cmd.target_cell)
    var cost_ap := cmd.ap_cost
    return cost_path <= u.move_left and cost_ap <= u.ap_left
```

## 4. 战斗结算用事件队列，不是帧驱动

⚠ **同回合多单位同时行动、暴击触发额外攻击会造成执行顺序依赖** ——
用 `CombatEventQueue` 按时间/优先级排序，逐步推进到稳定态。

```gdscript
var _q: Array[CombatEvent] = []

func step() -> void:
    _q.sort_custom(func(a, b): return a.priority < b.priority)
    while not _q.is_empty():
        var e := _q.pop_front()
        _apply(e)
        for spawned in e.spawned_events():
            _q.append(spawned)
```

## 5. AI 托管战斗：离散棋盘上规划，表现再插值

⚠ **AI 不要直接 `move_and_slide` 到目标** ——
托管战斗是在离散棋盘格上做目标选择与路径规划，
落地位置是格坐标，移动表现再插值。

```gdscript
var path := grid.get_id_path(u.cell, target_cell)   # AStarGrid2D
# 逐格推进，每格用 Tween 插值表现
```

⚠ **AI 不需要每物理帧思考** —— 按"战斗 tick"（如 0.2s 一次）推进，
表现插值填补视觉。长思考用 `WorkerThreadPool` 避免长帧。

## 6. 渲染：静态棋盘一次画，单位用共享纹理

| 内容 | 方案 |
|---|---|
| 棋盘底板 | `TileMapLayer` 一次画 |
| 单位（种类少） | `MultiMeshInstance2D` + 共享纹理 |
| 动态 UI | 独立 `CanvasLayer` |

⚠ **每帧改 `visible` 会触发 CanvasItem 绘制状态变化** ——
静态部分不要每帧动。

⚠ **`visible` 只表示"本节点允许绘制"** ——
是否真的绘制还取决于所有祖先是否可见，用 `is_visible_in_tree()` 综合判断。

## 7. z_index 排序

⚠ **`z_index` 在 Node2D 与 Control 之间共享同一概念** ——
战棋单位的遮挡排序要统一规划，别让 UI 与单位混在同一 z 空间打架。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-tactics.md`
