# 审核条目 —— 植被 / 大规模散布物

> 用法：按功能点收尾时逐条对照。格式：本能以为 → 实际 → 审查规则

| # | 本能以为 | 实际 | 审查规则 |
|---|---|---|---|
| 1 | 一万个 `MeshInstance3D` 慢慢加就行 | 节点遍历/剔除/变换更新逐个参与，加第二棵前就崩 | ⛔ 必须 `MultiMeshInstance3D` |
| 2 | 用了 MultiMesh 就快了 | 整个 MultiMesh **共享一个 AABB**，看到一棵就画全部 | ⚠ 必须分块 |
| 3 | `custom_aabb` 引擎会自己算 | 代码填 transform 前已算好 → 退化成原点零尺寸盒 | ⚠ 填完后显式写 |
| 4 | AABB 用实例中心扩就行 | 中心刚在视锥外的实例**边缘被切掉** | ⚠ 末尾 `grow(mesh_radius)` |
| 5 | 分块后能逐实例剔除 | 官方：**不逐实例剔除**，那正是 MultiMesh 的意义 | ⛔ 别指望自动 |
| 6 | `visible_instance_count` 能做空间剔除 | 只能隐藏**索引靠后**的，不做空间判断 | ⚠ 需配距离排序 |
| 7 | 植被边缘闪，开 MSAA | 官方：MSAA **对 alpha scissor 无效** | ⚠ MSAA + alpha AA **组合** |
| 8 | 只开 alpha antialiasing 就够 | 官方：依赖 alpha to coverage，**没有 MSAA 退化成抖动** | ⛔ MSAA 3D 至少 2× |
| 9 | 改了 scissor threshold 不用管 edge | 官方：edge **必须严格低于** threshold | ⚠ 两者联动 |
| 10 | 设 `MSAA 2D` 就行 | `MSAA 2D` 与 `MSAA 3D` 是两个独立设置 | ⚠ 改 `MSAA 3D` |
| 11 | 双面叶片设 Disabled 无所谓 | 背面也渲染 → 植被填充率翻倍 | ⚠ 需双面才显式设 |
| 12 | cull mode 是 Blender 的事 | 官方：Blender 默认关闭背面剔除 → 导出为 Disabled | ⚠ 导出前开 Backface Culling |
| 13 | 透明植被用默认 Depth Draw | 官方：**Depth Pre-Pass** 点名用于 grass/foliage | ⚠ 透明叶片要用 |
| 14 | 风动画逐个改 transform | 抵消 MultiMesh 全部意义 | ⛔ 走顶点着色器 |
| 15 | `set_shader_parameter` 改每株 | 那是改所有实例共享的那个 | ⚠ 用 `set_instance_shader_parameter` |
| 16 | 每株自己算风强度 | 天气系统改了风，植被不跟着变 | ⛔ 风是全局状态 |
| 17 | 设了 fade 就有过渡 | 官方：FADE 模式下 margin **必须 > 0** | ⚠ margin 留 0 会硬弹 |
| 18 | `visibility_range_begin=0` 表示距离 0 | 官方：默认 0 = **不做范围检查** | ⚠ 别误会默认值 |
| 19 | 远处靠 visibility range 就行 | 那是突然消失，不是变稀疏 | ⚠ 近高模 + 远低模/billboard 交叉 |
| 20 | 砍树把实例缩放到 0 | **索引错位**，第二次砍错树 | ⛔ 与末尾交换 + 降 count |
| 21 | 交换实例不用管状态表 | 状态表不跟着换 → 砍 A 倒 B | ⛔ 状态表同步交换 |
| 22 | 每株网格顶点数无所谓 | MultiMesh 只省 draw call，**顶点处理仍随 实例数×顶点数** | ⚠ 有顶点上限 |
| 23 | 转视角顶点数不降是正常 | 说明 AABB 还是错的 | ⚠ 必须能降 |
| 24 | 静态植被每帧刷新 buffer | 白付 CPU→GPU 传输 | ⛔ transform 不变就只写一次 |
| 25 | 先发放采集物再置空状态 | 中途失败则物品已发但植被还在 → **反复采集同一株** | ⛔ 发放与置空在同一事务内 |

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局审查块，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【审】 `common/audit/global.md#GA-01`　参数类型不符
【审】 `common/audit/global.md#GA-03`　硬编码易变值
【审】 `common/audit/global.md#GA-04`　每帧做本该事件驱动的事
【审】 `common/audit/global.md#GA-06`　状态机只写 enter 不写 exit
