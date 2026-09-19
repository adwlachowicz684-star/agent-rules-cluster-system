# Godot 4.x 关卡搭建与 TileMap

## ⚠ 先看版本：4.3 前后是两套 API

这是 Godot 4.x 里改动最大的一块，**用错版本的表现是"代码不报错但图块不出现"**。

| | 4.0–4.2 | 4.3+ |
|---|---|---|
| 节点 | `TileMap`（一个节点含多层） | **`TileMapLayer`**（一个节点一层） |
| `set_cell` 首参 | `layer: int` | `coords: Vector2i` |
| 状态 | 4.3 起 **deprecated** | 官方推荐 |

```gdscript
# 4.0–4.2
tilemap.set_cell(0, Vector2i(3, 4), source_id, atlas_coords)

# 4.3+
tilemap_layer.set_cell(Vector2i(3, 4), source_id, atlas_coords)
```

**怎么判断自己在哪个版本**：编辑器底部/项目管理器看版本号。
4.3+ 建 TileMap 节点时会提示改用 TileMapLayer。

本文件以 **4.3+ 的 TileMapLayer 为主**，4.2 及以下的写法在文末对照。

## 1. TileSet 资源：先配置再画

TileMap 用之前必须先有 `TileSet`。

### 创建流程

1. 准备好图集 PNG（每个 tile 等大）
2. 建 `TileMapLayer` 节点 → Inspector 里 `Tile Set` → 新建 TileSet
3. 底部面板打开 TileSet 编辑器 → 拖入图集 → 自动切分
4. 切分不对就调 `TileSetAtlasSource` 的 `texture_region_size`

### 关键配置

| 配置 | 位置 | 作用 |
|---|---|---|
| `tile_size` | TileSet | 单个图块像素尺寸 |
| 物理层 | TileSet → Physics Layers → Add | 给图块加碰撞 |
| 地形集 | TileSet → Terrain Sets | 自动拼接（见第 3 节） |
| 导航层 | TileSet → Navigation Layers | 给寻路用 |
| 自定义数据层 | TileSet → Custom Data Layers | 标记"这是水""这是墙" |

⚠ **必须先在 TileSet 里加"物理层"，才能在图块上画碰撞**。
没加的话 Paint 面板里根本没有 Physics 选项 —— 表现为"加了碰撞但角色穿过去了"。

## 2. 坐标转换（最常用）

TileMap 有三套坐标，混用是 bug 来源：

```
世界坐标（像素）  ←→  图块坐标（格子）
```

```gdscript
@onready var _layer: TileMapLayer = $Ground

# 世界 → 图块
var cell := _layer.local_to_map(_layer.to_local(global_pos))

# 图块 → 世界（返回图块中心）
var world := _layer.to_global(_layer.map_to_local(cell))
```

⚠ `local_to_map()` 接收的是**相对该节点的局部坐标**，
传 `global_position` 要先 `to_local()`。这是最常错的一处。

⚠ `map_to_local()` 返回的是图块**中心**的局部坐标，不是左上角。

### 实战：点击放置/破坏图块

```gdscript
func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseButton and event.pressed:
        if event.button_index == MOUSE_BUTTON_LEFT:
            place_tile(event.position)
        elif event.button_index == MOUSE_BUTTON_RIGHT:
            erase_tile(event.position)

func place_tile(screen_pos: Vector2) -> void:
    var world := get_global_mouse_position()
    var local := _layer.to_local(world)
    var cell := _layer.local_to_map(local)
    _layer.set_cell(cell, SOURCE_ID, ATLAS_COORDS)

func erase_tile(screen_pos: Vector2) -> void:
    var cell := _layer.local_to_map(_layer.to_local(get_global_mouse_position()))
    _layer.erase_cell(cell)
```

用 `get_global_mouse_position()` 而不是 `event.position` ——
后者是视口坐标，相机移动/缩放后会错位。

## 3. 地形自动拼接（Terrain）

手动画每个拼接变体太累。Terrain 让你画一笔就自动选对应边角的图块。

### 配置

1. TileSet → Terrain Sets → Add Terrain Set（模式选 `Match Corners and Sides`，16 宫格）
2. 加 Terrain（如 `Grass`、`Water`）
3. 在图集里选中每个 tile → Paint 面板 → Terrain → 设置它在 16 宫格里对应哪个位置

### 使用

```gdscript
const TERRAIN_SET := 0
const TERRAIN_GRASS := 0

func paint_grass(cells: Array[Vector2i]) -> void:
    _layer.set_cells_terrain_connect(cells, TERRAIN_SET, TERRAIN_GRASS)
```

⚠ `set_cells_terrain_connect` 是**批量**接口（传数组），
不是 `set_cells_terrain_connect(单个 cell, ...)`。传单个会报错。

⚠ 图集里的 tile 必须先设好 terrain peering bit，
否则 `set_cells_terrain_connect` 什么都不画（不报错）。

## 4. 自定义数据：判断"踩的是什么"

用 Custom Data Layer 标记图块属性，比建一堆 Area2D 高效得多。

1. TileSet → Custom Data Layers → Add（类型选 `bool` 或 `String`）
2. 图集里给水 tile 勾上 `is_water = true`

```gdscript
func get_tile_data(cell: Vector2i) -> TileData:
    return _layer.get_cell_tile_data(cell)

func is_water_at(world_pos: Vector2) -> bool:
    var cell := _layer.local_to_map(_layer.to_local(world_pos))
    var data := _layer.get_cell_tile_data(cell)
    if data == null:
        return false
    return data.get_custom_data("is_water") as bool

# 用法
func _physics_process(_delta: float) -> void:
    if is_water_at(global_position):
        speed = swim_speed
    else:
        speed = walk_speed
```

⚠ `get_cell_tile_data()` 在空格子返回 `null`，**必须判空**。

## 5. 场景图块：放出生点、宝箱

`TileSetScenesCollectionSource` 让你可以把一个当图块画上去。

1. TileSet 编辑器 → 加 Source → Scenes Collection
2. 添加场景（如 `res://scenes/chest.tscn`）
3. 像画图块一样画到地图上

```gdscript
# 读取场景图块
func get_spawn_points() -> Array[Vector2]:
    var out: Array[Vector2] = []
    for cell in _entity_layer.get_used_cells():
        var data := _entity_layer.get_cell_tile_data(cell)
        if data and data.get_custom_data("kind") == "spawn":
            out.append(_entity_layer.to_global(_entity_layer.map_to_local(cell)))
    return out
```

## 6. 程序化生成地图

```gdscript
extends TileMapLayer

@export var map_size := Vector2i(64, 64)
@export var noise_scale := 0.1
@export var water_threshold := 0.0

const SRC_GROUND := 0
const ATLAS_GRASS := Vector2i(0, 0)
const ATLAS_WATER := Vector2i(1, 0)

var _noise := FastNoiseLite.new()

func generate(seed_value: int) -> void:
    _noise.seed = seed_value
    _noise.frequency = noise_scale

    for x in map_size.x:
        for y in map_size.y:
            var h := _noise.get_noise_2d(float(x), float(y))
            var atlas := ATLAS_WATER if h < water_threshold else ATLAS_GRASS
            set_cell(Vector2i(x, y), SRC_GROUND, atlas)

    print_debug("地图生成完成: %d 格" % (map_size.x * map_size.y))
```

⚠ 大地图（200×200 以上）逐格 `set_cell` 会卡一下。
生成时先 `set_physics_process(false)`，生成完再开，或者分帧生成。

⚠ `FastNoiseLite` 的 `frequency` 是"频率"不是"缩放" ——
值越大地形越碎。想让地形平缓要调**小**（0.01~0.05）。

## 7. 多层组织

```
Level (Node2D)
├── GroundLayer      (TileMapLayer, z_index 0)  ← 地面
├── DecorationLayer  (TileMapLayer, z_index 1)  ← 装饰
├── CollisionLayer   (TileMapLayer, 有物理层, 可设为不可见)
└── EntityLayer      (TileMapLayer, 场景图块)
```

⚠ 4.3+ 是**一个节点一层**，4.2 及以前是一个 TileMap 节点里多个 layer。
迁移时把每个 layer 拆成独立节点。

⚠ `y_sort_enabled` 要开在**父节点**上（`Node2D`），
不是 TileMapLayer 自己 —— 开了父的，同级子节点才会按 Y 排序。

## 8. 运行时动态修改

```gdscript
# 破坏地形
func damage_tile(world_pos: Vector2, damage: int) -> void:
    var cell := _layer.local_to_map(_layer.to_local(world_pos))
    var hp := _tile_hp.get(cell, 3)
    hp -= damage
    if hp <= 0:
        _layer.erase_cell(cell)
        _tile_hp.erase(cell)
        # 改了地形要重烘焙导航
        _nav_region.bake_navigation_polygon()
    else:
        _tile_hp[cell] = hp
```

⚠ 破坏地形后**必须重烘焙 NavigationRegion**，否则寻路还走旧路径（敌人往坑里走）。

## 9. 4.2 及以下写法对照

```gdscript
# 4.0–4.2：TileMap 节点，一个节点多 layer
@onready var _tm: TileMap = $TileMap

func _ready() -> void:
    _tm.set_cell(0, Vector2i(3, 4), 0, Vector2i(0, 0))     # layer 在前
    var used := _tm.get_used_cells(0)                       # 要传 layer
    _tm.clear_layer(0)
```

| 4.3+ (TileMapLayer) | 4.0–4.2 (TileMap) |
|---|---|
| `set_cell(coords, src, atlas)` | `set_cell(layer, coords, src, atlas)` |
| `get_used_cells()` | `get_used_cells(layer)` |
| `erase_cell(coords)` | `erase_cell(layer, coords)` |
| 每节点一层 | 每节点多层，`clear_layer(layer)` |

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/tilemap.md`

