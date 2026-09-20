# 生活职业 / 采集生产 / 家园建造（Godot 4.7.2）

**此前文档里「农场 / 钓鱼 / 挖矿 / 烹饪 / 炼金 / 家园 / 领地」全部 0 命中。**

> ⚠ **与既有文档的分工**：
> `time-progression.md` 是**时间推进的跨品类内核**（离线结算锚点、余数写回、封顶、
> 周期重置、生产队列）。本篇**引用它**，只讲生活玩法本身的资源流。
> `economy.md` 是货币与装备养成；`genres-idle-sim.md` 是放置品类。

⚠ **生活玩法不是四个独立玩法，是同一个材料闭环的三个闸门：**

```
采集（时间/风险/探索 → 材料） → 加工链（中间物/成品/副产物/损耗） → 家园（消耗终点 + 局部增益）
```

分开实现的后果：**同一种材料在不同系统里有不同 ID、不同堆叠规则、
不同绑定状态和不同权威源。**

> 审核用反模式清单见 `audit/godot/lifeskill-housing.md`

## 0. 稳定 ID 与绑定必须随物品流动

```
item_id                 材料或成品
recipe_id               一个加工动作
node_template_id        矿点/树点等采集模板
furniture_template_id   家具或建筑
instance_id             某次被采完的世界节点 / 某件已放置家具
```

```gdscript
class_name ItemStack extends Resource
@export var item_id: StringName
@export var quantity: int = 0
@export var bound_to: int = 0      # 0 = 未绑定
@export var flags: int = 0

func can_merge(other: ItemStack) -> bool:
    return other.item_id == item_id and other.bound_to == bound_to and other.flags == flags
```

⚠ **绑定状态必须随物品流动，不能只作为 UI 文本。**
否则玩家把绑定矿石交给公共加工设施，再用另一个角色取走。
✅ 默认策略：**成品继承最严格绑定**（任一输入为绑定则输出绑定）——简单、可解释。

⚠ **`Resource.duplicate(false)` 是浅拷贝** —— 数组、字典、嵌套 Resource 仍共享。
模板 Resource 可安全共享；**实例状态必须另建对象并深拷贝**。
`resource_local_to_scene` 只是场景级局部状态，⛔ **不能替代服务端持久状态**。

## 1. 采集点 = 模板 + 世界实例，不是一个场景脚本

⚠ **矿点不能继承节点后保存 HP、刷新时间、占有者；节点只是世界实例 ID 的视图。**
一张地图 2,000 个矿点若各自成节点 → 节点树、处理循环、碰撞对象、
序列化、draw call、编辑器加载**全部线性叠加**。

```gdscript
class_name GatherTemplate extends Resource
@export var template_id: StringName
@export var yield_table: Array[YieldEntry] = []
@export var gather_seconds: float = 2.5
@export var charges: int = 3
@export var respawn_minutes: Vector2i = Vector2i(30, 45)
@export var tool_tags: Array[StringName] = [&"pickaxe"]
@export var min_skill: int = 0

class_name WorldNodeState extends RefCounted
var instance_id: int
var template_id: StringName
var cell: Vector3i
var charges: int
var available_at: int      # ⚠ Unix 秒绝对时间，不是倒计时
var owner_peer: int = 0
```

⚠ **刷新必须同时有"下一次可用的绝对时间"和"世界池"，不能只做相对倒计时。**
相对倒计时在停服、分区、离线结算、时钟校正时会**累积漂移**。
→ `available_at` 用绝对锚点（与 `time-progression.md` 同一套口径），
服务端从 `node.available_at <= now` 推出可见性。

**两种刷新语义要分开：**

| 场景 | 策略 |
|---|---|
| 开放世界矿点 | **共享节点池**：区域登记若干 `spawn_slot`，采空后在窗口内重新随机占用空槽 |
| 私有领地 / 个人资源岛 | **按角色或领地实例生成独立节点**，他人不可见 |

⚠ 两者不能用同一套逻辑：开放世界强调竞争与路线，私人空间强调确定性与离线收益。
⚠ 共享池用随机占槽，可避免"固定点位时钟完全同步"导致玩家整点蹲守。

## 2. 产出：四层随机模型，保底进状态

```
基础权重 → 品质修正 → 保底计数 → 最终产出
```

⚠ **保底要进入状态（未命中计数持久化），而不是放大 RNG。**
失败、损耗、稀有材料**全部服务端结算**。

## 3. 加工链是有向无环图 + 原子事务

⚠ **单输入单输出只是特例。** 真正的链是"原矿 → 锭 → 部件 → 成品"的多级图。
配方要显式表达**中间产物、副产物、损耗、不可逆失败**：

```gdscript
class_name Recipe extends Resource
@export var inputs: Array[Ingredient] = []
@export var outputs: Array[OutputSlot] = []
@export var byproducts: Array[OutputSlot] = []
@export var failure_chance: float = 0.05
@export var loss_on_failure: float = 0.5
@export var station_tags: Array[StringName] = []
```

⚠ **入队 ≠ 消耗**：先构建 `required` 与 `will_lose` 两个快照，
**开始制作时才做原子扣减**。否则"队列允许 10 个，中途第 3 个已无材料"。

⚠ **批量制作要拆成 N 个相同任务，不能把数量塞进单次 RNG** ——
否则大批量一次性承担极高损失，玩家也难以逐件控制失败。

⚠ **多级链必须检查循环依赖**：加载配方时建图做拓扑检查。
否则一个"通用回收配方"就可能形成**无限增值**。
两种缓存都要有最大展开深度：向上展开"做个成品要多少原始材料"、
向下展开"一个原材料最终能变成什么"。

⚠ **材料不足要有四种状态**：`READY` / `MISSING_INPUTS` / `WAITING_STATION` / `PAUSED`。
**自动暂停优于静默删除**；自动找替代又容易让玩家以为成品已锁定。
替代组必须在数据层显式配置，⛔ 不让客户端按名称模糊匹配。

### 失败与损耗必须承担经济功能

| 档位 | 失败率 | 失败损失 |
|---|---:|---:|
| 普通配方 | 5%–15% | 25%–75% 材料 + 固定低价值副产品 |
| 高级配方 | 25%–40% | 同上 |

⚠ 失败保留全部材料 → 品质堆叠没有风险；
失败清空所有材料 → 新玩家无法接受。
⚠ **暴击、完美、稀有成功要互相独立**，
⛔ 不能形成"暴击必完美 + 完美必无损"的叠加。

**结算五个阶段每步都要对：**

| 阶段 | 必须动作 | 错误示例 |
|---|---|---|
| 校验 | 拒绝非法 RPC | 客户端声称站在工作台旁 |
| 预扣 | 创建可逆预留 | 直接改数量且不记录任务 |
| 开始 | 写队列与完成锚点 | ⛔ 用客户端本地时间 |
| 完成 | 扣输入、roll 输出 | ⛔ 客户端上报结果 |
| 回滚 | 退回预留或按规则损耗 | 队列删除后材料消失 |

## 4. 熟练度：三张表 + 硬上限

配方发现与熟练度共享 **知识（已解锁）/ 等级（熟练度）/ 权重（产出品质）** 三张表。

⚠ **熟练度提升的边际不能线性** —— 线性涨价/线性增产会崩。
⚠ **回收率、技能收益、暴击概率都要硬上限**，
否则出现：完美闭环（自己种自己炼无损循环）、供给通胀、**无损刷熟练度**。

## 5. 家园是确定性占格系统，不是物理摆放

⚠ **不能让 `StaticBody` 碰撞决定是否合法。**
物理碰撞回答"两个形状这一帧是否重叠"（受浮点、休眠、CCD、旋转顺序、
缩放、图层、射线误差影响）；放置系统要回答"这个 footprint 在领地版本下是否被允许"
—— 后者必须**可回放、可存档、可服务端校验**。

```gdscript
func snap(world: Vector3, step: float) -> Vector3i:
    return Vector3i(floori(world.x/step), floori(world.y/step), floori(world.z/step))
```

⚠ 网格用整数 `Vector3i`，旋转限制为 **90° 枚举**（避免连续角度），
世界坐标到网格用**整数除法**并统一向下取整。
⚠ **所有客户端与服务端共用同一个 `snap()`**，
⛔ 禁止让 Godot 物理查询分别决定。

**校验顺序（任何前置失败都不进入物理阶段）：**

```
模板存在 → 有权限 → 领地版本匹配 → 旋转合法 → 网格在边界内
→ footprint 未占用 → 地面/墙面条件 → 无家具重叠
→ 不超过密度/重量/装饰上限 → 扣费成功 → place()
```

⚠ **`home.version` 不匹配要返回 `stale_version` 冲突** ——
多人同时摆放会产生覆盖与幽灵家具。

### 家具加成必须分阶段累加并封顶

```
flat_total   = sum(flat)
percent_total = clamp(sum(percent), floor, cap)
final        = (base + flat_total) * (1 + percent_total) + post_flat
```

⚠ 至少要设 `max_furniture`、`total_bonus_cap`、`per_stat_cap`、**同类家具生效上限**。
否则玩家摆上千张同模型桌子叠加无限加工速度。

## 6. 家园多人同步：只同步批准后的状态

⚠ **可见性与编辑权是两个权限维度：**
可见性（私有/好友/公会/同实例/公开）× 编辑权（所有者/共建者/访客/无）。
⚠ **访客不能触发会改变经济状态的 RPC。**

⚠ **只同步批准后的状态，不同步物理查询结果** ——
物理结果不可回放，会让两端不一致。

## 7. 经济平衡：从净产出速率反推

⚠ **纯产出会导致通货膨胀。** 要从"净产出速率"反推采集速率与回收比例。
⚠ 绑定/非绑定材料的比例直接影响经济（非绑定可交易 → 工作室刷金）。

## 8. Godot 实现：数据层 / 视图层 / 权威层分离

⚠ **成千上万个 `MeshInstance3D` 逐个提交会很慢** —— 官方明确指出这点，
要用 `MultiMesh`（一次绘制成千上万实例），但它**仍要求外部提供可见性 AABB**。

⚠ 采集点、家具、配方、制作队列**都以数据为主**，渲染节点由数据按需生成。

⚠ **Godot 官方建议**：竞争性、持久化游戏把客户端输入视为**不可信**，
在修改状态前校验 RPC 参数。

## 9. 服务端权威清单

必须服务端：采集判定与产出 · 刷新与 `available_at` · 材料扣减与产出 ·
合成失败与损耗 · 占格与放置 · 家园权限 · `home.version` 递增

客户端只做：输入、预测、表现

## 10. 待核对项（运行时验证）

⚠ 待核对：失败率、损耗率、熟练度收益曲线、回收比例的具体取值 ·
验证：本轮给的是**设计区间**，须经济回测核实

⚠ 待核对：绑定材料跨加工的规则（是否允许付费/NPC 解绑）·
验证：须单列配置，本轮默认"继承最严格绑定"

⚠ 待核对：数值窗口与通货膨胀的临界点 ·
验证：须按真实产出/消耗速率回测

## 11. 相关文档

- 时间推进内核（离线结算、队列、重置）→ `time-progression.md`
- 货币与装备养成 → `economy.md`
- 放置/模拟经营品类 → `genres-idle-sim.md`
- 多人同步与 authority → `multiplayer.md`
