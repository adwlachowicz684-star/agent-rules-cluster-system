# 载具物理与物理进阶（Godot 4.7.2）

"VehicleBody3D 载具""软体""布料""绳索""物理材质" 此前基本空白。

## 0. VehicleBody3D 是街机求解器，不是高保真

⚠ **官方类参考直接承认它有已知问题、并非为逼真车辆物理设计**
—— 它是基于射线车轮的求解器，不是 BeamNG 式轮胎模型。

### ⚠ "一开就翻"通常不是碰撞形状的问题

真正原因通常是：
- **几何中心被当成质心**
- 车身过窄 / 重心过高 / 阻尼过低

⚠ 不要用 `CollisionShape3D` 的位置去"视觉上压低重心" ——
碰撞体偏移会影响重心计算和碰撞响应，**不能替代 `center_of_mass`**。

正确做法：`CENTER_OF_MASS_MODE_CUSTOM` 显式下移质心，
让自定义质心位于**车身局部原点下方**。

**关键参数**：`engine_force` / `brake` / `steering` / `suspension_*` /
`friction_slip` / `wheel_roll_influence`（0.0–0.2，降低翻车概率，过高会失真）

## 1. ⚠ SoftBody3D 官方存在（很多人以为没有）

**"Godot 4 没有 SoftBody3D" 是错的** —— 真正要核对的是**版本和物理后端**。

`SoftBody3D` 继承 `MeshInstance3D`，是可变形三维物理网格，
用于**布料、橡胶和其他柔性材料**。

- 碰撞形状由网格生成，网格也直接用于渲染
- 关键参数：`linear_stiffness` / `damping_coefficient` / `drag_coefficient` /
  `pressure_coefficient` / `total_mass` / `simulation_precision` / 逐点 pinned

⚠ **官方 4.7 建议软体优先用 Jolt**（更快更可靠）。
⚠ **4.7 的 Jolt 改了默认总质量、刚度解释和 Area 重叠行为**
→ **4.6 资产不能不加验证地升级**。

## 2. 关节：连上不等于稳

五类：`HingeJoint3D` / `PinJoint3D` / `SliderJoint3D` / `ConeTwistJoint3D` / `Generic6DOFJoint3D`

⚠ **误差会沿链条放大** 的来源：
- 相邻刚体**质量差过大**
- 锚点错位
- 弹簧轴互相串联
- 睡眠策略不当

布娃娃用 `PhysicalBone`（见 `animation-skeletal.md`）。

## 3. ⚠ 摩擦是"两个物体共同决定"的

**默认取所有碰撞物体中的最低摩擦**，不是相加也不是取其一：

| 情况 | 有效摩擦 |
|---|---|
| 都 `rough=false` | **取最低** |
| 都 `rough=true` | 取最高 |
| 只有一个 `rough` | 取标记为粗糙的那个 |

⚠ 所以"冰面 0.1、车轮 10.0 → 摩擦 10.0"是**错的**，默认组合下有效值是 **0.1**。

⚠ **更可控的策略**：轮胎和地面都保持 `rough=false`，
用**质量、悬挂、驱动参数**调牵引，别用 `rough` 全局强行覆盖。

弹性不是简单平均 —— 由 `absorbent` 选择相加或相减语义。

## 4. 穿模与卡帧

**高速穿模**：`continuous_cd` + 加厚碰撞体 + 提高 `physics_ticks_per_second`。

⚠ 只开 CCD 对**非常薄的墙**不够。墙厚至少要考虑单步位移：

```
允许位移 ≈ linear_velocity.length() / physics_ticks_per_second + 物体特征尺寸
```

⚠ **卡帧时引擎最多追赶 `max_physics_steps_per_frame` 步**（默认 8），
之后**真实时间与实际模拟时间分离** —— 物理会"变慢"而不是跳帧。

## 5. 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | VehicleBody3D 是真实车辆物理 | 是**街机求解器**，官方承认有已知问题 |
| 2 | 翻车是碰撞形状问题 | 通常是**质心/重心**问题 |
| 3 | 移碰撞体能压低重心 | **不能替代** `center_of_mass` |
| 4 | Godot 4 没有 SoftBody3D | **官方存在** |
| 5 | 软体用默认后端就行 | 官方建议 **Jolt** |
| 6 | 4.6 物理资产能直接升级 | 4.7 Jolt **改了默认值** |
| 7 | 关节连上就稳 | **质量差/锚点错位**会放大误差 |
| 8 | 摩擦取其中一个 | 默认**取最低** |
| 9 | 冰面+粗糙轮胎=高摩擦 | 默认是 **0.1**（最低） |
| 10 | 弹性是平均值 | 由 `absorbent` 定**相加/相减** |
| 11 | 开 CCD 就不会穿模 | 薄墙还要**加厚** |
| 12 | 卡帧物理会跳帧 | 是**变慢**（追赶有上限 8 步） |
| 13 | 物理步长恒定所以时间准 | 卡帧后**真实时间与模拟时间分离** |
| 14 | 布料只能用社区方案 | 有 **SoftBody3D** |
| 15 | 绳索要复杂方案 | **PinJoint 串联**够用 |

## 6. 待核对项（运行时验证）

⚠ 待核对：4.7.2 项目设置中 `max_physics_steps_per_frame` 的确切默认值 · 验证：编辑器项目设置搜索框核对

⚠ 待核对：Jolt 后端下软体的实际表现 · 验证：切换 Jolt 后跑布料原型

## 7. 相关文档

- 基础物理 → `physics.md`
- 3D 场景与碰撞 → `3d.md`
- 骨骼动画与布娃娃 → `animation-skeletal.md`
- 性能剖析 → `perf-profiling.md`
- 确定性（物理不保证） → `replay.md`
- 4.7 新特性 → `version-47-48.md`
