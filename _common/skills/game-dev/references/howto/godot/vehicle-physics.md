# 载具物理与物理进阶（Godot 4.7.2）

> **本篇分工：载具/物理「物理」层** —— 街机求解器、SoftBody3D、关节、摩擦合成、穿模与卡帧。
> ⚠ **载具系统（节点结构 / 车轮 / 悬挂 / 乘员 / 上下车事务）不在这里** → `vehicle.md`。两篇按「物理 vs 系统」分工，互指不重复。

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

### VehicleWheel3D 参数速查（默认值单位混杂，照抄必错）

| 属性 | 默认 | 单位 | 调整起点 |
|---|---:|---|---|
| `wheel_radius` | 0.5 | m | 按视觉轮胎半径 |
| `wheel_rest_length` | 0.15 | m | 完全压缩位置向下到静止悬挂长度 |
| `suspension_travel` | 0.2 | m | 越野/轿车 0.1–0.3；越大越易侧倾 |
| `suspension_stiffness` | 5.88 | N/mm | 越野 <50，赛车 50–100，F1 约 200 |
| `suspension_max_force` | 6000 | N | 应 > 车身质量 1/4；经验约 3–4× 该阈值 |
| `damping_compression` | 0.83 | 无量纲 | 普通车约 0.3，赛车约 0.5 |
| `damping_relaxation` | 0.88 | 无量纲 | **必须略高于 compression** |
| `wheel_friction_slip` | 10.5 | 滑移 | 1.0 正常，0 无抓地 |
| `wheel_roll_influence` | 0.1 | 无量纲 | 1.0 易翻，0 抗侧倾 |
| `engine_force` | 0.0 | 牵引力 | 1000kg 车从 25–50 开始 |
| `brake` | 0.0 | 制动力 | 1000kg 车紧急制动约 25–30 |
| `steering` | 0.0 | **rad** | 按角速度/速度曲线限制 |

⚠ **建模顺序：先定位锚点 → 再设 rest length → 最后调悬挂。**
把 `VehicleWheel3D` 原点 gizmo 放在**完全压缩时车轮所在位置**，再用 `wheel_rest_length` 把车轮放到静止姿态。
→ `rest_length=0` 却把节点挪到视觉位置，悬挂零点会错，车默认悬空或车轮穿过车身。

⚠ **悬挂抖动先查单位与质量，不要无限加 damping。**
常见原因：刚度远高于质量、rest length 与 travel 冲突、车轮锚点离质心过远、CCD/时间步不足、
**车轮节点与车身碰撞形状互相重叠**。
处方：先固定 mass 与 wheel_radius → stiffness 按 **10 倍步长**扫描 → compression/relaxation 用 **0.3/0.5** 起步
→ travel 限 0.1–0.3 → **关闭车身与车轮自碰撞** → 验证 60/120Hz 差异。

⚠ **高速不稳定是官方承认问题**：360 km/h、60Hz 时每步约 **1.67m**，既可能隧穿小物体，也让射线/接触采样缺少信息。
应对：① **提高 physics ticks**（首选）② 大尺度碰撞形状、避免薄墙/薄地板/拼接缝隙 ③ 降速或改运动学 ④ 地面碰撞要连续。

⚠ **内置车轮更像一组向下射线，不是厚轮胎**：提供 `is_in_contact()`、`get_contact_body()`、
`get_contact_normal()`、`get_contact_point()`、`get_rpm()`、`get_skidinfo()`。
→ 薄墙、护栏、有缝隙的拼接路面会被**漏检**（车"跨"过栏杆、上下坡悬挂突然复位、高速瞬移）。

⚠ `engine_force`/`brake`/`steering` 必须在 **`_physics_process()`** 里算，视觉轮才用插值平滑。
⚠ `steering` 是**整车转向输入（弧度）**，不是视觉轮网格角度。
⚠ `wheel_friction_slip` 默认 10.5 **不是"10.5 倍抓地力"的统一标尺**，它与接触表面摩擦结合。

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

### 关节参数速查

⚠ `Joint3D` 是**共同基类，不是可实例化组件**。`node_a`/`node_b` 两端必须继承 `PhysicsBody3D`；
任一端为空则接到固定世界。`exclude_nodes_from_collision=true` **只**阻止两个被连接体互撞，不关闭与地形的碰撞。

| 节点 | 正确用途 | 关键参数 | 典型误用 |
|---|---|---|---|
| `PinJoint3D` | 球铰、钟摆、破碎链点 | `params/bias=0.3`、`damping=1.0`、`impulse_clamp=0.0` | 用单点锁刚体姿态 → 万向节不稳定 |
| `HingeJoint3D` | 门、车轮、摆臂、马达 | `angular_limit/{enable,lower,upper,bias}`、`motor/{enable,target_velocity,max_impulse}` | 把车轮摩擦/转向交给铰链马达 |
| `SliderJoint3D` | 活塞、滑轨、电梯 | `linear_limit/{lower,upper}_distance` | 期望它替代 `CharacterBody3D` 精确运动 |
| `ConeTwistJoint3D` | 布娃娃肩、球窝 | `bias=0.3`、`softness=0.8`、`relaxation=1.0`、`swing_span=π/4`、`twist_span=π` | 当角色"站起来"的稳定器 |
| `Generic6DOFJoint3D` | 自定义悬挂、机械臂 | 每轴 `enabled`/limit/spring/motor、ERP/softness/damping | 一上来六个轴全开 |

- ⚠ **铰链轴是局部 Z，默认无限制、无马达**（`angular_limit/enable=false`）。
  门最小可用配置是**启用限位并设弧度角**；只在场景里旋转节点**不会**自动产生限位。
- ⚠ `SliderJoint3D` 默认滑轨 −1m~+1m，**角限位均为 0** —— 零角自由度 + 非零线性范围才是"直轨"。
- ⚠ ConeTwist 的 **twist 轴初始是关节局部 X**；`twist_span` 低于 0.05 会锁住扭转。肩/肘/脊椎要**分别**设。
- ⚠ **6DOF 只设 `softness` 不启用 spring 不会产生弹簧力。**

**软参数不是"越大越硬"**：`bias` 保持**位置**关系，`damping` 保持**速度**关系，`impulse_clamp` 限制每步冲量（**0 = 不限制**）。

⚠ **`solver_priority` 只在 GodotPhysics 生效，Jolt 直接忽略**（值越低越优先，默认 1）。
→ Jolt 项目不能靠调它，只能改质量、约束结构、时间步。

**抖动/爆炸判别顺序**：`时间步 → 质量/尺寸 → 锚点 → 限位 → 求解顺序 → 冲量钳制`

| 症状 | 原因 |
|---|---|
| 低速也发抖 | 时间步不足 |
| 小质量体被弹出 | 相邻链节质量差过大 |
| 模型与锚点明显偏差 | 锚点不在铰接几何中心 |
| 限位边缘反复回弹 | 限位/阻尼配置 |
| 链条末端甩动放大 | 求解顺序或链过深 |
| 两体突然相距几千单位 | 冲量未钳制 |

处方：相邻链节质量差**不超约 1:10** · 锚点设在**真实铰接几何中心** · 串珠链**不超 6 节** ·
⚠ **不要逐帧 `remove_child`/`add_child` 关节**，用 `joint_clear()`/`free_rid()` 明确生命周期。

### 2D 关节（语义不能套用 3D）

| 节点 | 默认值要点 |
|---|---|
| `PinJoint2D` | `angular_limit_enabled=false`、`softness=0.0`（越高越易弯曲） |
| `GrooveJoint2D` | `initial_offset=25.0`、`length=50.0`（沿局部 Y 的沟槽长度） |
| `DampedSpringJoint2D` | `damping=1.0`、`length=50.0`、`rest_length=0.0`、`stiffness=20.0` |

⚠ **`DampedSpringJoint2D.length` 是最大伸长上限，不是静止长度**（静止长度是 `rest_length`）。
⚠ `damping`：0 = 无阻尼，**1 = 临界阻尼**，>1 = 过阻尼。
⚠ **2D 关节没有公开的 `solver_priority`** —— `Joint2D` 只有 `bias=0.0`（0 回退到项目设置）。

### 运行时创建关节必须用 PhysicsServer

```gdscript
var j := PhysicsServer3D.joint_create()
PhysicsServer3D.joint_make_pin(j, body_a, local_a, body_b, local_b)
PhysicsServer3D.joint_set_solver_priority(j, 1)
# 销毁：先解除引用，再 PhysicsServer3D.free_rid(j)
```

⚠ **不要在 `_physics_process()` 里每帧 new 关节节点。**
⚠ 钩索反模式：建 `PinJoint3D` 却不保存 RID、不处理目标死亡
→ 内存增长、钩索仍拉住已 `queue_free()` 的对象、两帧内重复连接。**RID、两体引用、有效期要存在同一组件里。**

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

> **反模式清单（不能怎么做，审核用）** → `audit/godot/vehicle-physics.md`


## 5. 待核对项（运行时验证）

⚠ 待核对：4.7.2 项目设置中 `max_physics_steps_per_frame` 的确切默认值 · 验证：编辑器项目设置搜索框核对

⚠ 待核对：Jolt 后端下软体的实际表现 · 验证：切换 Jolt 后跑布料原型

## 6. 相关文档

- **载具系统（节点结构 / 车轮 / 悬挂 / 乘员 / 上下车事务）** → `vehicle.md`
- 基础物理 → `physics.md`
- 3D 场景与碰撞 → `3d.md`
- 骨骼动画与布娃娃 → `animation-skeletal.md`
- 性能剖析 → `perf-profiling.md`
- 确定性（物理不保证） → `replay.md`
- 4.7 新特性 → `version-47-48.md`
