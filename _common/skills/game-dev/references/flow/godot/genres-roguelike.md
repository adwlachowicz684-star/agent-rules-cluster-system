# Godot 4.x Roguelike / Roguelite

Roguelike 的架构核心是**"生成管线 + 房间图 + 道具池 + 可复现 RNG"**，
meta 进度是另一条独立数据链。

## 0. 生成管线四阶段，每阶段独立 RNG 分支## 0. 生成管线四阶段，每阶段独立 RNG 分支

> 本篇讲**关卡生成与 RNG**（seed/state、AStar、道具池权重）。
> 局内三选一词条、遗物与构筑的组合语义 → 见 `build-affix.md`。

```
① 房间摆放    rng_rooms
② 房间图/连通  rng_graph
③ 内容填充道具 rng_loot
④ 敌人/陷阱    rng_encounter
```

**为什么要分分支**：只改敌人种子时房间布局不变，
便于做"固定房间 + 随机遭遇"的混合模式，也便于断点复现。

```gdscript
var rng_rooms := RandomNumberGenerator.new()
var rng_graph := RandomNumberGenerator.new()
var rng_loot  := RandomNumberGenerator.new()

func generate(seed_str: String) -> Dungeon:
    var h := hash(seed_str)
    rng_rooms.seed = h
    rng_graph.seed = h ^ 0x9E37
    rng_loot.seed  = h ^ 0x85EB
    ...
```

## 1. 先建纯数据中间表示，再批量提交

```gdscript
var d := Dungeon.new()          # 纯数据：房间/走廊/道具/敌人
_build_rooms(d, rng_rooms)
_connect(d, rng_graph)
_fill(d, rng_loot)

if not _validate(d):            # 连通性、钥匙/门、出口可达
    return generate(seed_str + "_retry")

_commit(d)                      # 一次性写入 TileMapLayer
```

⚠ **不要生成后直接 `set_cell` 刷满整张图** ——
失败时难以回滚，且逐格 `set_cell` 会触发多次重算。

⚠ **防卡关是解谜/Roguelike 的生死线** ——
底线是"任何状态都存在一条回到已知安全状态的路径"。
连通性校验要在设计文档阶段写进检查清单，不是后期补。

## 2. RNG 的 seed 与 state 是两个层级

```gdscript
rng.seed = hash("myseed")     # 初始化整条序列
var s := rng.state            # 可存可取
...
rng.state = s                 # 回到先前状态
```

⚠ **回溯尝试摆放房间失败后必须还原 RNG** ——
否则一次失败尝试会污染后续随机序列，同种子不再复现。

⚠ **不要把 `randi()`/`randf()` 当"确定性随机"** ——
全局随机函数与 `RandomNumberGenerator` 实例是不同状态，混用就不复现。

## 3. 房间图：AStar2D，瓦片级：AStarGrid2D

```gdscript
# 房间级：房间之间怎么连
var g := AStar2D.new()
g.add_point(id, room_center, 1.0)
g.connect_points(a_id, b_id, true)
var path := g.get_point_path(from_id, to_id)

# 瓦片级：格子内寻路
var grid := AStarGrid2D.new()
grid.region = Rect2i(0, 0, W, H)
grid.cell_size = Vector2(CELL, CELL)
grid.update()
var p := grid.get_id_path(Vector2i(0,0), Vector2i(9,9))
```

⚠ **`AStar2D` 与 `NavigationServer2D` 是两套完全独立的 API** ——
官方明确 NavigationServer 不处理 AStar 的寻路。选错会让生成多绕弯路。

⚠ **房间坐标要对齐到 `cell_size` 整数倍** ——
否则走廊连接点落在非格心，A* 图无法对齐。

## 4. 写入 TileMapLayer 前先关导航

⚠ **每个 `set_cell` 都可能触发导航区域更新** ——
批量生成时应先关掉相关层的 `navigation_enabled`，生成完最后一次提交再开。

```gdscript
ground_layer.navigation_enabled = false
for c in d.cells:
    ground_layer.set_cell(c, SRC, atlas_of(c))
ground_layer.navigation_enabled = true
```

## 5. Meta 进度：关键节点即存，不要只存一次

⚠ **不要在 `_exit_tree` 或 `NOTIFICATION_WM_CLOSE_REQUEST` 里只存一次** ——
崩溃、强杀进程会丢。正确做法是"关键节点变化即存"
（过关结算后、解锁时），且写文件用"写临时文件 + 原子重命名"防半截文件。

```gdscript
func save_atomic(res: Resource, path: String) -> void:
    var tmp := path + ".tmp"
    ResourceSaver.save(res, tmp)
    DirAccess.rename_absolute(
        ProjectSettings.globalize_path(tmp),
        ProjectSettings.globalize_path(path))
```

⚠ **Meta 存档用 `user://` 但要含签名校验** ——
`FLAG_COMPRESS` 是压缩不是加密，玩家可改本地文件。

## 6. 道具池：累积权重二分，不要每次重算总权重

```gdscript
var _cum: Array[float] = []      # 累积权重，池变动时才重建

func pick(rng: RandomNumberGenerator) -> int:
    var t := rng.randf() * _cum[-1]
    return _cum.bsearch(t)
```

⚠ **每抽一张重新遍历全池算总权重是 O(n)** ——
用累积权重二分降到 O(log n)，或用别名法（Vose）到 O(1)。

## 7. 性能

⚠ **生成期 GC 尖峰** —— 逐房间 `Array` 拼接、频繁 `Dictionary` 分配
会在进入新层时卡顿。预分配数组、复用临时缓冲。

⚠ **生成可放后台线程**（`Thread` / `WorkerThreadPool`），
但结果要排队回主线程提交到 `TileMapLayer`（Godot 有主线程锁）。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-roguelike.md`
