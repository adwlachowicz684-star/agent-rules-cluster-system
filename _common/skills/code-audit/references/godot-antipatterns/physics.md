<!-- oversize-exempt: 反模式清单，审核用 -->
# physics — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于审核完成效果、约束边界。
> 「怎么做」看开发侧：`game-dev/references/godot/physics.md`

## 碰撞层：位掩码是最大的坑

`collision_layer`（我是谁）和 `collision_mask`（我能撞谁）是**位掩码**，
不是层号。第 N 层的值是 `1 << (N-1)`：

| 层 | 值 | 二进制 |
|---|---|---|
| 第 1 层 | `1` | `0001` |
| 第 2 层 | `2` | `0010` |
| 第 3 层 | `4` | `0100` |
| 第 4 层 | `8` | `1000` |

⚠ **第 3 层是 4，不是 3**。写 `collision_layer = 3` 表示"同时属于第 1 和第 2 层"，
是合法值但不是你想要的（审查 GD 里的层值混用检测）。

**推荐做法**：在项目设置里给层命名（项目设置 → Layer Names → 2D Physics），
然后用常量而不是裸数字：

```gdscript
# layers.gd —— 与项目设置里的命名一一对应
class_name Layers

const PLAYER := 1 << 0      # 第 1 层
const ENEMY  := 1 << 1      # 第 2 层
const WORLD  := 1 << 2      # 第 3 层（值 = 4）
const ITEM   := 1 << 3      # 第 4 层（值 = 8）

# 玩家：我是 PLAYER，能撞 WORLD / ENEMY / ITEM
const PLAYER_MASK := WORLD | ENEMY | ITEM
```

```gdscript
func _ready() -> void:
    collision_layer = Layers.PLAYER
    collision_mask = Layers.PLAYER_MASK
```

### 单向平台

`CollisionShape2D.one_way_collision = true` —— 只能从上面站上去，下面能跳穿。
配合 `one_way_collision_margin` 调容差。

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| 碰撞层写层号当位值 | 语义全错（第3层写3） | 人工 |
| 改 `target_position` 未 `force_raycast_update` | 读到旧缓存 | GD23 |
| `intersect_ray(from,to)` 位置参数 | 3.x 残留，4.x 报错/不生效 | GD24 |
| RigidBody 连 `body_entered` 未开 `contact_monitor` | 信号永不触发 | GD26 |
| 每帧 `apply_impulse` | 力放大 60 倍 | GD22 |
| 移动平台用 StaticBody | 角色滑落/卡住 | 人工 |
| AnimatableBody 未设 `sync_to_physics` | 站在上面会抖 | 人工 |
| 物理逻辑放 `_process` | 低帧率抖动/穿模 | GD14 |
| `intersect_shape` 未调大 `max_results` | 结果静默截断为 32 | 人工 |
