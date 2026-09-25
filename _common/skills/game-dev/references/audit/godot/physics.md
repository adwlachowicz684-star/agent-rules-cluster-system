<!-- oversize-exempt: 反模式清单，审核用 -->
# physics — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/physics.md`
> 「按什么顺序做」见 `flow/godot/physics/`

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

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | 碰撞层写层号当位值 | 语义全错（第3层写3） | 人工 |
| 2 | 改 `target_position` 未 `force_raycast_update` | 读到旧缓存 | GD23 |
| 3 | `intersect_ray(from,to)` 位置参数 | 3.x 残留，4.x 报错/不生效 | GD24 |
| 4 | RigidBody 连 `body_entered` 未开 `contact_monitor` | 信号永不触发 | GD26 |
| 5 | 每帧 `apply_impulse` | 力放大 60 倍 | GD22 |
| 6 | 移动平台用 StaticBody | 角色滑落/卡住 | 人工 |
| 7 | AnimatableBody 未设 `sync_to_physics` | 站在上面会抖 | 人工 |
| 8 | 物理逻辑放 `_process` | 低帧率抖动/穿模 | GD14 |
| 9 | `intersect_shape` 未调大 `max_results` | 结果静默截断为 32 | 人工 |
| 10 | ⛔ 缩放物理体/碰撞形状 | 引擎不支持 → 视觉与碰撞脱节，**不报错** | 人工 |
| 11 | ⛔ 碰撞形状挂在视觉表示之下 | 父节点缩放被带过去 | 人工 |
| 12 | 改共享形状资源未 `duplicate()` | 场景中同资源节点全部跟着变 | 人工 |
| 13 | 角色用 `CylinderShape3D` | 官方已知不稳定，建议 box/capsule | 人工 |
| 14 | 切换物理引擎未点 Save & Restart | 仍在用旧引擎，参数改了没反应 | 人工 |
| 15 | ⛔ Jolt 下单 body 关节未复核 | `node_a`/`node_b` 语义相反 → **限位反转** | 人工 |
| 16 | Jolt 下小形状用默认 margin | 先缩小再加壳，小形状出问题 | 人工 |
| 17 | 把 GodotPhysics 的调参经验平移到 Jolt | 稳定化语义不同（弹簧 vs 仅位置） | 人工 |
| 18 | ⛔ 开插值后传送未 `reset_physics_interpolation()` | 拖影 | 人工 |
| 19 | 开插值却在物理 tick 外设 transform | 引擎只给软告警，抖动 | 人工 |
| 20 | 以为 3D 也会自动 reset | ⓘ 只有 2D 首次入树自动，3D 全靠手动 | 人工 |
| 21 | 2D 用 `GPUParticles2D` 却期待插值 | 官方：只有 CPU 版支持 | 人工 |
| 22 | 高速物体未开 Continuous CD | 穿透（tunneling） | 人工 |
| 23 | 静态碰撞体太薄 | 穿透 / 薄物体抖动 | 人工 |
| 24 | 堆叠抖动却不提高 TPS | 力相互对抗，堆越多越强 | 人工 |
| 25 | 跨 tile 颠簸未做 composite collider | 撞到已被覆盖的边缘（已知问题） | 人工 |
| 26 | 接触时掉帧却不简化碰撞形状 | 凸形状过于复杂 | 人工 |
| 27 | ⛔ 未设 `Max Physics Steps per Frame` | 物理螺旋死亡，帧率掉到 1–2 FPS | 人工 |
| 28 | 远离世界原点未做处理 | 浮点精度退化 → 地图边缘碰撞飘 | 人工 |
| 29 | ⛔ 在地面仍无条件施加重力 | 斜坡无输入下滑 + `is_on_floor()` 闪烁 | 人工 |
| 30 | `floor_max_angle` 小于实际坡度 | 坡被当成墙 | 人工 |
| 31 | 移动平台用 StaticBody | 角色滑落/卡住 | 人工 |
| 32 | AnimatableBody 未设 `sync_to_physics` | 站在上面会抖 | 人工 |
| 33 | 平台的 Tween 跑在 idle 而非物理 tick | 开插值后抖 | 人工 |
| 34 | 3D 开插值却未逐节点设 `physics_interpolation_mode` | 该关的没关（如自己插值的相机） | 人工 |
| 35 | ⓘ 验收只用 60 TPS 常态测 | 拖影/插值问题抓不到（应临时降到 10 TPS） | 人工 |
| 36 | 以为摩擦取相加或取其一 | ⛔ 默认取**最低**，被低值物体拉走 | 人工 |
| 37 | `max_physics_steps_per_frame` 只朝一个方向调 | 太低→物理变慢；太高→螺旋死亡，⛔ 是同一设置的两面 | 人工 |
| 38 | ⛔ 直接写 `linear_velocity` 做持续推动 | 覆盖物理积分 → 碰撞与摩擦失效（只有传送才改 position） | 人工 |
