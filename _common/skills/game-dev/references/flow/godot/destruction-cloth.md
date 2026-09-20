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

## 4. 物理引擎选择

⚠ **官方建议 `SoftBody3D` 用 Jolt Physics** ——
`physics/3d/physics_engine` 项目设置可切换，
**4.6 及以后新项目默认 Jolt，旧项目必须手动切换**。

⚠ **社区破坏/破碎插件要校验是否针对 4.7 的 API 和 Jolt 重新编译** ——
不能直接假设兼容。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/destruction-cloth.md`
