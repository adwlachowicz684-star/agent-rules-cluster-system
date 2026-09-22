# 构筑（Deckbuilding）与词条/词缀系统（Godot 4.7.2）

**此前文档里「构筑 / 词条选择 / 协同 / 互斥」全部 0 命中。**

> ⚠ **与既有文档的分工**：
> `genres-card.md` 是**卡牌对战本身**（效果栈、洗牌、牌库回收、拖拽 UI）；
> `genres-roguelike.md` 是**关卡生成与 RNG**；
> `economy.md` 有装备词条存法（`affix_id + roll + generation_version`）。
> 本篇是它们的**抽象层**——构筑合法性与词条组合语义，卡牌 / Roguelite / ARPG / 自走棋通用。

⚠ **构筑和词条是两条独立规则，不要写进同一个对象。**

- **构筑**回答"这一局、这一赛制允许带哪些牌" → 持久化单位是**稳定标识的计数集合**
- **词条**回答"这些来源如何改变属性" → 持久化单位是**装备/实体上的参数化来源**
- **局内词条**是一次运行中临时或永久附加的来源

三层写进同一个对象，是后期最难拆的数据债务。

> 审核用反模式清单见 `audit/godot/build-affix.md`

## 0. 定义共享、实例独立（Godot 数据层第一条红线）

```
CardDefinition  只读：id / printing_id / balance_version / 费用 / 标签 / 效果步骤
AffixDefinition 只读：id / slot_tags / tier / weight / operations / 互斥 / 依赖
DeckList        玩家意图：ruleset_id + version + card_id 计数集合
AffixInstance   实例：只存能复现来源的最小信息
```

⚠ **共享 Resource 被多个装备引用时，原地修改会污染其他实例。**
运行时修改前用 `duplicate(true)`，或对场景开 `resource_local_to_scene`。
⛔ **不要把当前耐久、临时强化、局内词条塞进共享 `.tres`。**

`AffixOp` 不能只是一个"数值"字段，要表达为 **`stat × op × value × condition`**：

```gdscript
{stat="fire_damage",  op="add_flat",          value=8}
{stat="crit_chance",  op="add_percent_base",  value=0.10, cap=0.75}
{stat="damage_taken", op="multiply",          value=0.80, group="damage_reduction", cap=0.50}
```

⚠ 给每个乘除类操作明确的 **语义、分组和上限** ——
否则同一个百分比字段会被不同模块按不同顺序相乘。

## 1. 词条存最终值 = 数据失去重算能力

⚠ 最直接的失败不是加载错误，而是**改表后无法重算**。
装备在 v1 掉落时把 "+12%" 烘成 `fire_damage = 12`，策划 v2 调成 "+15%"，
历史装备只存 `12` → 系统无法判断这个数字来自旧规则、旧 roll 还是已固化强化。
更糟的是它又经过重铸、升级、改品质 → **多个历史版本混合，无法审计也无法统一重算**。

**持久化三层：**

| 层 | 字段 | 作用 |
|---|---|---|
| 定义标识 | `affix_definition_id`、`tier_id`、`slot_id` | 这是什么词条 |
| 随机参数 | `roll`（0.0–1.0 或离散）+ 生成上下文（等级、品质、profile） | 复现当时的随机 |
| 生成版本 | `generation_version`（掉落/槽位/池子）+ `balance_version`（数值表） | 决定能否迁移 |

⚠ **`generation_version` 与 `balance_version` 必须分开** ——
一次掉落管线的重构，不应被误当成词条数值热修（反之亦然）。

⚠ **重算不是"读到旧数值就覆盖"，而是按版本策略迁移。**
保存 `effective_state`（缓存）+ `source_state`（真相）。加载时版本低于兼容版 →
先尝试无副作用迁移；无法迁移则标记 `LEGACY_RECOMPUTE_REQUIRED`，
**不让它在战斗里继续产生旧属性**。

⚠ 迁移策略必须明确采用哪一种：回滚 / 重新随机 / 取旧最终值 / 锁定历史数值。
⛔ 不要只写"把旧装备转成新版本"——旧 roll 的映射规则变了就没法含糊过去。

## 2. 生成：先定候选空间，再按阶段约束

✅ 正确顺序：**基础装备 → 必选固有词条 → 决定随机槽位数 → 逐个抽 → 冲突校验 → 最终化**

⚠ **先从一个巨大全局池抽 N 条再删不合法的**，会出现实际槽位数远低于预期，
或为了凑满槽位反复重试。

```gdscript
func generate_affixes(base_item, ctx):
    var slots := resolve_slot_plan(ctx.profile.plan_for(base_item, ctx))
    var selected := []
    for slot in slots:
        var pool := filter_definitions(all_defs, slot.tags, base_item.tags, ctx.item_level)
        pool = remove_existing_conflicts(pool, selected)
        pool = apply_weight_overrides(pool, ctx)
        var def := weighted_pick(pool)
        if def: selected.append(roll_affix(def, slot, ctx))
    return finalize(selected)
```

⚠ **槽位应按"部位 + 槽位类型"声明**，不是只绑一个全局池：
`WEAPON {prefix_slots: 2, suffix_slots: 2, intrinsic_slots: 1}`，
每个槽位再指定标签。要跨部位套装时扩展成 `slot_predicate`，
⛔ 别给每个部位复制整张词条表。

⚠ **重复出现要由三重限制**：槽位容量 + `exclusive_group` + `max_total`（或 `uniqueness_group`）。
⛔ 只在 UI 层判断"名称相同就禁止"是错的——
燃烧伤害、燃烧持续时间、燃烧触发率三个定义**名称不同但同属一个唯一组**。

## 3. 组合必须受约束：减伤是最经典的崩坏点

⚠ **"任意词条自由组合"的问题不是数值不好看，是没有定义跨来源语义。**
若每个减伤都写 `damage_taken *= (1 - value)`：
两条 75% 减伤 → 承伤 6.25%，即 **93.75% 总减伤**，很快逼近无敌。

**固定管线：**

```
base_stat
→ flat_additive_group
→ base_percent_additive_group
→ multiplicative_group（组内先求和，组间才相乘）
→ final_cap / clamp
```

减伤尤其要设**全局承伤总下限**（如 `0.10`）：
`multiplier = 1 - clamp(sum, 0, 0.90)`。
两条 100% 减伤仍得到 100%，但**不会超过上限，也不会连续相乘**。

**词条定义至少要有这四个约束字段：**

| 字段 | 作用 |
|---|---|
| `exclusive_group` | 同组最多保留一个来源（如 `invulnerability_source`） |
| `requires` | 依赖其他词条/标签，不满足则不生效 |
| `conflicts_with` | 跨组小范围定向冲突 |
| `max_sources` / `scale_guard` | 全局来源数上限；乘算/概率/持续时间/触发频率的**硬上限** |

⚠ **互斥要在四个节点检查**：装备生成 · 装备更换 · 局内词条选择 · 属性聚合。
只在生成阶段检查会漏掉"先拿 A 再拿 B"、商店换装、遗物替换、临时增益永久化；
只在伤害时检查会让 UI、提示、回放和校验**互相不一致**。

⚠ **协同有两种本质不同的表达，不能都用"加 15%"**：
- **数值协同**（有 `fire_damage` 时 `burn_duration` +20%）→ 放聚合管线，以已确认来源集合为条件
- **触发协同**（火伤命中且目标有易伤 → 额外爆炸）→ 必须走事件或显式 trigger graph

写成无条件乘法会让协同**始终生效**，反而绕过设计门槛。

⚠ **"X 与 Y 共存时给 50%"会形成 O(n²) 声明。**
更稳的是 `trigger` 持有 `condition_set`，条件满足时执行固定 effect；
新词条只声明条件与效果，**不需要为每个配对手写规则**。

⚠ 避免组合爆炸：词条拆小但强交互集中在少数类型 · 用 group/互斥/唯一组压缩合法笛卡尔积 ·
把"组合奖励"做成显式遗物而非让词条互相感知 · **只枚举玩家实际拥有的来源**。

## 4. 构筑不是抽卡：校验要在三个时点

⚠ **构筑是玩家赛前主动选择 + 复制限制 + 替换与策略；抽卡是随机获得结果。**
用"随机 reward pool"代替组卡 UI，会失去复制限制、构筑版本、禁用表和**玩家意图**。

```gdscript
class_name DeckList extends Resource
@export var ruleset_id: StringName
@export var ruleset_version: int
@export var leader_id: StringName
@export var entries: Array[DeckEntry]   # card_id + printing_id + count
```

⚠ **保存的是"玩家意图"，不是 30 张物理卡。**
持久化 `card_id + count` 即可，加载时再展开为 `Array[CardHandle]` 实例句柄。

**三层校验（⛔ 不是只在点"开始"时校验一次）：**

| 时点 | 做什么 |
|---|---|
| **组卡时** | 增量校验，UI 立即提示"还差 5 张""某牌超过上限" |
| **保存时** | 完整校验并**硬拦截** |
| **开局/匹配时** | **再次校验** —— 赛制、解锁、禁用表、轮换、卡牌可用性可能已变 |

⚠ **在线对局要由服务端重跑同一套 `DeckValidator` 并把结果签名。**
本地合法、服务端按新规则判非法只是最轻的后果，更严重的是客户端篡改牌组或打印版本。

⚠ **卡牌数值改了，不能默认旧构筑继续可用。**
客户端看到 `list.balance_version < catalog.min_deck_version` →
**禁止直接开在线对局**，提供"迁移预览"。
迁移策略：保留稳定 `card_id` · 自动移除已删除卡 · 按新上限截断副本 ·
对改名/重做卡显示**手动替换**（⛔ 不要随机替换）。

⚠ **禁用/限用表与轮换要做成可热更数据**，不要写死。

## 5. 局内词条：脏标记快照，不是每帧遍历

⚠ **不要在每次伤害计算时遍历所有词条。**
用 **source table + dirty snapshot**：来源注册触发条件，事件命中条件集合时才求值；
属性访问读经过固定管线计算、由**脏标记控制**的快照。

⚠ **临时词条必须有明确的消失时机**（`combat_ended` / `room_cleared` 等事件），
否则会跨局残留。

⚠ **三选一**先做分类和候选池 + 重复保护 + 未命中计数。
ⓘ **"三选一必然有核心构筑牌"不是通用规则**，属项目设计，待策划确认。

## 6. 服务端权威边界

必须服务端：赛制与禁用/限用表 · 构筑完整校验与保存签名 ·
在线对局的抽牌序列/洗牌/随机 reward · 影响排位与经济与掉落与成就的结果 ·
词缀生成（或至少对客户端生成结果做规则验证）· 战斗结束后的 build 持久化和迁移

客户端可缓存 catalog、做即时校验和展示，⚠ **但两端不一致时以服务端为准**，
且服务端要返回完整 `ValidationReport` 与迁移建议，⛔ 不能只返回"非法"。

⚠ **服务端权威不代表在 Godot 里复制一遍逻辑。**
把核心规则抽成纯 GDScript/C# 模块，或导出 JSON schema 由服务端用相同规则验证。
关键是**同一份规则定义、同一份评估顺序** ——
两端各自手写条件分支，版本漂移会重新制造无敌、非法牌组和不可复现战斗。

## 7. 落地顺序（先建三张表，再写战斗和 UI）

1. `card_catalog` + `affix_catalog`（含稳定 id、版本、赛制、槽位、互斥、依赖、权重）
2. `DeckList` / `DeckValidator` / `Ruleset`
3. `AffixInstance` / `EquipmentInstance` / `BuildState`（**不存最终值**）
4. 固定属性管线（先覆盖减伤、暴击、增伤等高危字段）
5. 互斥组/依赖组/重复上限，**四个入口调同一个 validator**
6. source table + dirty snapshot（基准测试：100 词条 / 1000 实体不应每帧全遍历）
7. 最后接表现层、存档、回放、服务端签名

**最低限度自动化测试**：两条 100% 减伤不低于全局承伤下限 ·
三条同类百分比不先两两相乘 · 同一 `uniqueness_group` 无法跨槽超量 ·
组卡/保存/开局三处分别触发相应错误 · 禁用卡移除后旧构筑不被静默按新数值使用 ·
`duplicate(true)` 的嵌套共享行为符合预期 · 临时词条在局末消失 ·
服务端能在 catalog 更新后拒绝旧 `ruleset_version`

## 8. 待核对项（运行时验证）

⚠ 待核对：核心牌保底是否必须存在 · 验证：**无资料确认这是通用规则**，属策划承诺，须项目明确

⚠ 待核对：纯事件图 vs 混合管线的取舍 · 验证：取决于技能数量与性能目标，本轮未给唯一答案

⚠ 待核对：旧装备迁移策略（回滚/重随机/取旧值/锁定） · 验证：须由策划与后端共同确认，本轮只列出四种并说明差异

## 9. 相关文档

- 卡牌对战本身（效果栈、洗牌、牌库）→ `genres-card.md`
- Roguelike 生成与 RNG → `genres-roguelike.md`
- 装备词条存法与强化期望 → `economy.md`
- 掉落保底与随机表 → `economy.md`、`genres-roguelike.md`
- 多人同步与 authority → `multiplayer.md`
