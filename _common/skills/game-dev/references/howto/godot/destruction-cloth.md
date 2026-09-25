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

ⓘ 三条全局块在本篇的落点（详见 `common/howto/principles.md`）：

| 块 | 在本篇的落点 |
|---|---|
| `GC-03` 数据与逻辑分离 | 冲量权重、活动上限写进资产/配置，不硬编码在 `shatter()` 里 |
| `GC-04` 事件解耦 | 伤害只发事件，由可破坏物件自己订阅并决定碎裂 |
| `GC-06` 性能：先定位再优化 | 峰值在切分/凸包/刚体创建，不在长尾物理——先 profile 再动手 |


## 13. 相关全局块

【读】 `common/howto/principles.md#GC-02`　频繁生成/销毁的东西要池化（碎片池与寿命回收）
【读】 `common/howto/principles.md#GC-03`　数据与逻辑分离（冲量权重与预算可配，不硬编码）
【读】 `common/howto/principles.md#GC-04`　事件解耦 vs 直接引用（伤害只发事件，碎裂自己订阅）
【读】 `common/howto/principles.md#GC-06`　性能：先定位再优化（碎裂峰值在切分/凸包，不在长尾物理）

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

## 8. 物理插值：碎片瞬移必须 reset，软体完全不受插值影响

⚠ 官方关于物理插值的三条，每一条都直接砸在破坏/布料上：

| 官方事实 | 对本域的含义 |
|---|---|
| *"physics interpolation currently does not affect soft bodies"* | 软体想更平滑**只能**加 `Physics Ticks per Second` |
| 传送/初始放置后要调 `reset_physics_interpolation()` | ⛔ 碎片从池里取出即瞬移，不 reset 会 **streaking（拖一条长影）** |
| 移动物理对象的 `Tween`/`AnimationPlayer` 必须走物理 tick 时序 | 碎片淡出用普通 `Tween` 会抖 |

⛔ **碎片池化与物理插值是一对硬冲突**：池化必然"从旧位置瞬移到新位置"，
这正是官方明确要求 reset 的场景——不是可选优化。

```gdscript
func _spawn(t: Transform3D) -> void:
    global_transform = t
    reset_physics_interpolation()   # ⛔ 少了这行 → 碎片拖影
```

ⓘ 相机在物理插值下同样要特殊处理：`top_level = true`、
在 `_process()` 里更新、读 `get_global_transform_interpolated()`。
⚠ 屏震（`camera` 域）若抖的是"物理跟随的相机"，插值会把抖动**平滑掉**。

## 9. 小而快的碎片会穿墙：continuous_cd 与 tick 率

⚠ 官方对 `ConcavePolygonShape3D` 的第三条警告说它**空心**、
*"extra prone to being tunneled through by (small) fast physics bodies"*。

ⓘ 数值直觉：3D 物理默认 60 Hz，60 m/s 的物体**每 tick 走 1 米**——
沿运动方向的墙厚小于每 tick 位移就有穿透风险。

✅ 三条对策（按成本从低到高）：

| 对策 | 代价 |
|---|---|
| `continuous_cd = true`（扫掠检测） | 每刚体一点开销 |
| 提高 `physics/3d/physics_ticks_per_second` | CPU 近似翻倍 |
| 换 Jolt（对多数体型默认走扫掠式 CCD） | 要重调既有参数 |

⛔ 别指望 `contact_monitor` 能"救"穿透——它是**事后**上报接触，
穿透已经发生了。另注意它还有个默认值陷阱：
`max_contacts_reported` 默认 0，**一条接触都不报**。

## 10. 布娃娃：别用默认的 PinJoint

ⓘ 生成路径：`Skeleton3D` → Skeleton 菜单 → **Create Physical Skeleton**。
驱动用 `physical_bones_start_simulation()`，与动画靠 `Influence` 混合。

| 部位 | 关节 | 理由 |
|---|---|---|
| 肩 / 髋 / 颈 | `ConeJoint` | 有锥角限制，不会反折 |
| 肘 / 膝 | `HingeJoint` | 单轴 |
| ⛔ 全身用默认 | `PinJoint` | 经验：**容易 crumple（皱缩塌成一团）** |

⛔ 布娃娃骨骼要放在**与角色胶囊不同的碰撞层**——
否则骨骼会把角色自己顶起来，表现为"尸体原地抽搐"。

## 11. 软体：父碰撞忽略、钉固点依附、4.7 质量默认值变更

⛔ **`Parent Collision Ignore` 是官方教程的"最后一步"**：

> *"The last step is to avoid clipping by adding the CharacterBody3D Player
> (the scene's root node) to the Parent Collision Ignore property of the
> SoftBody3D."*

不做这一步 → **披风与角色穿模/抖动**，而其余参数全是对的。
ⓘ 症状极易误判成"软体参数没调好"，于是去反复调 stiffness，越调越糟。

ⓘ 钉固点可以**依附到节点**（`set_point_pinned` 的 `attachment_path`，
编辑器里是 Attachments → Spatial Attachment Path）。
✅ 披风钉在 `BoneAttachment3D`（选 Neck 骨）上即可跟随骨骼；
⛔ **不要把 `SoftBody3D` 直接挪到 `BoneAttachment3D` 下面**。

⚠ **4.7 破坏性变更（迁移指南）**：

| 项 | 4.6 及以前 | 4.7（Jolt） |
|---|---|---|
| `SoftBody3D` mass 默认 0 | 每点 1 kg → **总质量极高** | 默认 1 kg（整体） |
| `linear_stiffness` | 旧算法 | 应用方式变了 → **升级后必须重调 `linear_stiffness` 与 `damping_coefficient`** |

⛔ 从 4.6 升到 4.7 后"软体手感全变了"不是玄学，就是这两条。

⚠ 顺带一条 4.7：`WorldBoundaryShape3D.plane.d` 在 Jolt 下**符号约定反转**，
迁移时等号要翻。

ⓘ 4.5+ 新增 `apply_central_impulse()` / `apply_central_force()`：
把力/冲量**分布到所有模拟点**。做爆炸击退比逐点 `apply_impulse` 省事得多。

## 12. 风力只作用于软体（跨域澄清）

⚠ 官方在 `Area3D.wind_force_magnitude` 与 `wind_source_path` 两处**各写了一遍**：

> *"Wind force only applies to SoftBody3D nodes. Other physics bodies are
> currently not affected by wind."*

⛔ 所以 `weather` 域的风**吹不动碎片、吹不动刚体**，只吹得动 `SoftBody3D`。
想让碎片被风吹必须自己施力——而碎片若已休眠，`apply_force` **唤不醒**（见第 4 节），
要先用 `apply_impulse` 或显式置 `sleeping = false`。

⚠ 风向是 `wind_source_path` 指向节点**本地 Z 轴的反方向**，原点即该节点原点。
⛔ 搞反表现为"旗帜往反方向飘"，且看起来像风力大小设错了。

ⓘ 还有一条官方实现清单里的：碰撞形状与刚体**不要带 scale**，
要改大小就用形状自身的尺寸参数。缩放节点会让物理表现不可预期。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/destruction-cloth.md`
