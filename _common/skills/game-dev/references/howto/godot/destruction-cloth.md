# Godot 4.x 可破坏物件 / 布料 / 软体

## 0. 先认清：没有内置破坏系统

⚠ **Godot 没有 `DestructibleBody3D`、实时网格切割节点或 Voronoi 破碎器** ——
这些都是自实现。

**生产最稳路径**：

```
离线/加载时把原始网格预切分为凸碎片
  → 隐藏完整网格，用 StaticBody3D/RigidBody3D + ConvexPolygonShape3D 代理
    → 受击时切到"碎片容器"，按连通/冲量分配初速度
      → 限制活动碎片总数与寿命
```

## 1. 预切分 vs 动态切割

| 方案 | 适用 | 说明 |
|---|---|---|
| **预切分凸碎片** | 绝大多数情况 | 离线做，运行时只切状态 |
| **动态切割** | 短裂纹/规则切缝 | 要自己做 CSG/BSP、凸分解、拓扑缝合、法线 UV 重建 |
| **预设破坏簇 + 装饰粒子** | 全网格任意破坏 | 降级方案 |

⚠ **实时动态切割只有短裂纹适合运行时** ——
全网格任意破坏建议降级为预设破坏簇和装饰粒子。

## 2. 碎片池化与预算

```gdscript
const MAX_ACTIVE := 64

func shatter(center: Vector3, impulse: Vector3) -> void:
    var n := mini(_fragments.size(), MAX_ACTIVE)
    for i in n:
        var f := _pool.acquire()
        f.global_transform = _fragments[i].global_transform
        f.apply_impulse(impulse * _fragments[i].impulse_scale)
        _alive.append(f)
```

⚠ **碎裂峰值来自切分、凸包生成、刚体创建和渲染实例上传，
不是长尾物理** —— 要预烘焙凸包、限制碎片数量、批量休眠和回收。

⚠ **不要破坏瞬间从零计算全部顶点** —— 主线程会卡死。

⚠ **凹网格不能直接转单一碰撞体** —— 要用凸代理，不是 `Mesh` 碰撞体。

⚠ **碎片碰撞形状不是越精确越好** —— 凸近似足够，精确形状反而更贵。

⚠ **切分时不要复制全部材质/纹理** —— 共享材质，避免无谓的 `Resource.duplicate()`。

⚠ **远处碎片可降级成 `GPUParticles3D` 或公告板**。

## 3. 布料：优先动画，SoftBody3D 只用于必要变形

⚠ **`SoftBody3D` 继承自 `MeshInstance3D`，可见网格本身就是模拟网格** ——
不是"给普通网格加组件"。

**适合**：旗帜、软垫、果冻。
**不适合**：任意角色服装、长绳索、关卡机制。

绳索优先用 `Joint3D` / `Generic6DOFJoint3D` 链、骨骼布娃娃或离线模拟。

```gdscript
soft.total_mass = 2.0
soft.linear_stiffness = 0.5
soft.damping_coefficient = 0.01
soft.simulation_precision = 5
soft.pin_point(0, true)          # 固定顶点
```

⚠ **`SoftBody3D` 不能替代 `AnimationPlayer` 或骨骼** —— 它不响应动画轨道形变目标。

⚠ **`drag_coefficient` 在默认物理实现中可能未被使用** ——
调参前要在目标引擎下验证（4.6+ 新项目默认 Jolt）。

⚠ **软体不受物理插值影响** —— 提高视觉平滑度只能增加
`Physics Ticks per Second`。

⚠ **成本随顶点数与 `simulation_precision` 上升，不是随 `total_mass`** ——
先用低模软体，再以蒙皮网格显示细节。

## 4. 碎片刚体的休眠与回收

⚠ **碎裂的性能瓶颈不是"长尾物理"，是峰值** ——
切分、凸包生成、刚体创建、渲染实例上传集中在一帧。
但**第二贵的**是"64 个碎片一直醒着"，这条容易被忽略。

### ⚠ `apply_force` 唤不醒休眠的刚体

⚠ **休眠刚体对 `apply_force` 无反应**（需要超过唤醒阈值）。
✅ 一次性冲击用 `apply_impulse`（**任何非零冲量都会立即唤醒**）；
持续力要先显式置 `sleeping = false`：

```gdscript
func apply_wind(dir: Vector3) -> void:
    if sleeping:            # ⚠ 持续力必须先手动唤醒
        sleeping = false
    apply_force(dir * 2.0)

func shatter_push(v: Vector3) -> void:
    apply_impulse(v)        # ✅ 冲量自动唤醒
```

⛔ 症状：碎片落地休眠后，"爆炸把它们推开"完全没反应——
不是力太小，是**根本没唤醒**。

### 三条休眠策略（按优先级）

| 策略 | 适用 |
|---|---|
| ✅ **允许休眠**（默认 `can_sleep = true`） | 绝大多数碎片 |
| ⚠ 调低 `Sleep Threshold Linear` / 提高 `Time Before Sleep` | 需要碎片"自然停稳"的物理谜题 |
| ⛔ `can_sleep = false` | ⚠ **慎用**：200 个常醒刚体远贵于 200 个可休眠的 |

ⓘ 官方默认：线速度阈值 0.1、进入休眠 0.5s。
低速运动的碎片可能**提前休眠**（表现为"差一点没碰到开关"）。

### ⚠ 回收优先于休眠

⚠ **休眠只是省 CPU，不省内存和实例数。**
碎片池必须有**寿命回收**（超时淡出或直接回池），
否则打碎 100 个物件后场景里有几千个节点——
即使全部休眠，遍历与内存仍在涨。

ⓘ 官方对"永远冻结"的建议同样值得记：
*"For a body that is always frozen, use `StaticBody3D` or `AnimatableBody3D`
instead."* —— 需要"不动但能挡"的碎片别用 `freeze = true` 的 RigidBody3D。

## 5. 碰撞形状选型：官方的性能排序

⚠ 官方对 `ConcavePolygonShape3D` 的明确警告（三条都是硬的）：

| 官方原话要点 | 含义 |
|---|---|
| *"the **slowest** collision shape to check collisions against"* | 应限于关卡几何 |
| *"intended to work with **static** PhysicsBody3D... will not work with `CharacterBody3D` or `RigidBody3D`"* | ⛔ 动态碎片**不能用** trimesh |
| *"**hollow**... extra prone to being tunneled through by (small) fast physics bodies"* | 小而快的碎片会**穿过去** |

✅ 所以碎片一律用 `ConvexPolygonShape3D`：它是**实心**的，能检测"完全在内部"的碰撞。

⚠ 但官方也说了 `ConvexPolygonShape3D` **比球/盒等基元形状慢**，
且建议"先考虑基元形状" —— 碎片形状能用一个盒子近似就别用凸包。

ⓘ 生成方式（官方两条路径）：
编辑器里选中 `MeshInstance3D` → 视口上方 Mesh 菜单 →
**Create Multiple Convex Collision Siblings**；
脚本里 `MeshInstance3D.create_multiple_convex_collisions()`（运行时凸分解）。

⚠ 运行时凸分解**正是"碎裂峰值"的一部分** —— 能离线预烘焙就不要运行时算。

## 6. 软体：官方教程里的四条硬警告

⚠ **`SoftBody3D` 没有子节点。** 官方原话：*"it does not have a
`CollisionShape3D` or a `MeshInstance3D` child node. Instead, the collision
shape is **derived from the mesh** assigned to the node. This mesh is also
directly used for rendering."*

⛔ 给它加 `CollisionShape3D` 子节点是常见错误——**不生效**。

### ① `simulation_precision` 别低于 5

⚠ 官方原话：*"Try to keep the Simulation Precision **above 5**; otherwise, the
soft body may **collapse**."*

ⓘ 源码范围 `1,100,1`，默认 5。提高能显著改善效果，但**直接增加成本**。

### ② `pressure_coefficient > 0` 要求网格封闭

⚠ 官方原话：*"if the shape is **not completely closed** and you set pressure to
a value greater than 0.0, the soft body will **fly around like a plastic bag
under strong wind**."*

⛔ 症状极具迷惑性：软体莫名乱飞，看起来像物理引擎坏了，其实只是网格没封口。

### ③ `drag_coefficient` 是**未使用**的

⚠ 官方文档明确：*"This value is **currently unused** by Godot's default
physics implementation."*

⛔ 调它没有任何效果。**4.6+ 新项目默认 Jolt**，但调参仍要在**目标引擎下实测**。

### ④ 软体受 Area3D 的风力影响

ⓘ 官方：SoftBody3D *"is subject to wind forces defined in `Area3D`"*，
对应 `Area3D.wind_source_path` / `wind_force_magnitude` / `wind_attenuation_factor`。

✅ 旗帜飘动不必自己施力 —— 用 Area3D 的风即可。
ⓘ 这是布料表现里最省事的一条路径，文档里此前完全没提。

### ⑤ 视觉平滑度只能靠提高 tick

⚠ 官方原话：*"physics interpolation **currently does not affect soft bodies**.
If you want soft body simulation to look smoother at higher framerates, you'll
have to increase `Physics > Common > Physics Ticks per Second`, which comes at a
**performance cost**."*

⛔ 开了物理插值就以为软体会变平滑——**不会**。

ⓘ 还有个 4.x 属性此前没提：**`shrinking_factor`**（范围 -1–1）。

## 7. 物理引擎选择

⚠ **官方建议 `SoftBody3D` 用 Jolt Physics** ——
`physics/3d/physics_engine` 项目设置可切换，
**4.6 及以后新项目默认 Jolt，旧项目必须手动切换**。

⚠ **社区破坏/破碎插件要校验是否针对 4.7 的 API 和 Jolt 重新编译** ——
不能直接假设兼容。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/destruction-cloth.md`
