# Godot 4.x 遗物 / 局内构筑（Roguelite 养成层）

> **适用**：局内拾取遗物、三选一升级、构筑随局内选择变化的项目。
> **不适用**：只在局外配装、局内属性不变的项目（那是 `build-affix.md`）。
> ⚠ 本域是 `genres-roguelike.md` 的**养成层**：那篇讲"关卡怎么生成"，
> 本域讲"玩家在局内拿到什么、怎么组合"。

## 0. 先分清三件事

⚠ **"遗物""词条""局外解锁"在中文项目里经常混用，但归属不同。**

| 说法 | 归属 | 生命周期 |
|---|---|---|
| **遗物** | 局内获得，**整局保留** | 一局结束即清空 |
| **词条** | 附着在单件装备/技能上 | 换装即失效 |
| **局外解锁** | 永久，跨局保留 | 存档里 |

ⓘ 判据是**什么时候消失**：换装备就没的是词条，一局结束才没的是遗物，
存档里一直在的是局外解锁。

⛔ 三者共用一套"效果"结构是可以的，
但**不能共用一套"来源"结构**——它们的失效时机完全不同。

## 1. 遗物池三层：池 / 稀有度 / 实例

```gdscript
class_name RelicBase extends Resource      # 模板（配表，只读）
@export var relic_id: StringName
@export var rarity: int
@export var effects: Array[Dictionary]     # [{stat, value, op}]
@export var tags: PackedStringArray        # 用于协同判定

class_name RelicInstance extends Resource  # 实例（本局）
@export var relic_id: StringName
@export var instance_id: int
@export var stacks: int = 1                # 可叠加的遗物
```

⚠ **与 `gem-rune.md` 同构**：模板/实例两层。
⛔ 不要发明第三套——同项目的宝石、遗物、词条若各有一套，
做"遗物影响装备词条"时要写三份适配。

ⓘ `stacks` 容易被漏：很多遗物可叠加（"每层 +5% 攻速"），
⛔ 用"重复持有多个实例"表达会导致协同判定与 UI 都变复杂。

## 2. RNG：seed 与 state 是两个层级

⚠ **三选一不能走全局 RNG。**

```gdscript
var _rng := RandomNumberGenerator.new()

func start_run(seed_value: int) -> void:
    _rng.seed = seed_value      # ① 先设 seed
    _rng.state = _saved_state   # ② 后恢复 state（若有）
```

⛔ **官方原话：*"Changing the seed will reset the state, so make sure to
set the seed first."* —— 顺序反了，恢复的 state 会被 seed 覆盖掉。**

⚠ 症状极具迷惑性：读档后前几次抽取正常、之后逐渐与存档前不一致。
排查时容易被引到"是不是存档漏了字段"。

ⓘ 用全局 `randi()` 的话，玩家开菜单看一眼 UI、粒子系统随机抖动，
都会消耗序列 → **同一个种子两次抽取结果不同**，种子复现彻底失效。

## 3. 种子质量：RNG 没有雪崩效应

⚠ **官方原话：*"The RNG does not have an avalanche effect, and can output
similar random streams given similar seeds."***

⛔ 用局数 `1/2/3` 当种子 → 三局的遗物序列**高度相似**；
用玩家 ID 当种子 → 相邻 ID 的开局体验几乎一样。

✅ 种子必须先过哈希：`_rng.seed = hash(seed_value)`。

## 4. 权重抽取：空数组返回 -1

`RandomNumberGenerator.rand_weighted(weights)` 内部用累积权重二分，
ⓘ 与 `genres-roguelike.md#6. 道具池` 的手写做法等价。

⚠ **官方原话：数组为空时"输出错误并返回 `-1`"。**

⛔ 不判 -1 直接当索引用 → 取到 `pool[-1]` = **数组最后一个元素**，
不崩溃、不报错，只是**每次空池都固定给出同一件遗物**。
ⓘ 这个 bug 的特征是"某种稀有度抽完后再也不出别的"，极难归因。

**判据**：⚠ 每次 `rand_weighted` 后必须判 `-1`。

## 5. 协同：显式遗物，不要让词条互相感知

⚠ **"拿了 A 又拿 B 触发额外效果"必须做成显式规则。**

⛔ 让遗物互相感知（A 内部判断"我有没有 B"）的话，
规则散落在每个遗物里，**加一个新遗物要改所有相关遗物**。

✅ 做法是独立的协同表：

```gdscript
class_name RelicSynergy extends Resource
@export var require_ids: Array[StringName]   # 需同时持有
@export var effect: Dictionary
```

ⓘ 与 `gem-rune.md#6. 套装与共鸣` 同源：判定按**去重集合**，
⛔ 不是按数量（同一个遗物叠加 3 层不该触发需要 3 件不同的协同）。

## 6. 局内属性：脏标记快照，不是每帧遍历

⚠ **局内构筑的属性要一次算好存快照，拿遗物时才重算。**

⛔ 每帧遍历所有遗物累加 → 遗物越多越卡，
而这类卡顿在前期遗物少时**完全测不出来**。

ⓘ 与 `build-affix.md#5. 局内词条：脏标记快照` 同源：
同一个脏标记机制，遗物与词条共用。

⛔ **组合必须受约束**（`build-affix.md#3`）：
减伤类遗物叠加到 100% 会除零，表现为**属性变成 NaN 或负数**。

## 7. 局外解锁：关键节点即存

⚠ **局外解锁必须在获得瞬间落盘，不能等结算。**

⛔ 只在通关时存一次 → 中途崩溃则整局解锁全部丢失，
玩家会明确感知"我明明拿到了"。

ⓘ 与 `genres-roguelike.md#5. Meta 进度：关键节点即存` 同源。

⚠ 存档只写 `relic_id`（局外解锁的），⛔ 不写模板本身——
配表删掉某个遗物后旧存档会指向空，且**不报错**。

## 8. 待核对项（运行时验证）

> ⚠ 以下为本域**尚无统一法定数值/口径**的项，落地时必须实测确认。
> ⛔ 不要凭印象填数值——这些恰恰是各项目差异最大的地方。

- ⚠ 待核对：三选一的候选数量（3 还是 4）与是否保底出现高稀有度 · 验证：查目标项目的策划案，与 `economy.md` 的保底计数规则对齐（保底必须持久化且绑定池）
- ⚠ 待核对：遗物是否允许重复持有（叠加 stacks 还是池内移除）· 验证：查策划案；若允许重复，确认协同判定用的是去重集合
- ⚠ 待核对：局内构筑是否影响匹配/排行榜 · 验证：查 `netsync-advanced.md` 的服务端权威边界，确认客户端不可伪造遗物来源
- ⚠ 待核对：稀有度权重是否随局内进度动态调整 · 验证：查策划案；若动态，确认权重表与 `genres-roguelike.md` 道具池的累积权重两套逻辑不冲突

## 9. 相关文档

- 关卡生成与房间图 → `genres-roguelike.md`
- 词条与组合约束 → `build-affix.md`
- 宝石/符文（模板/实例同构）→ `gem-rune.md`
- 属性管线与经济 → `economy.md`
- 存档迁移 → `save-migration.md`
- 服务端权威 → `netsync-advanced.md`

## 10. 审核清单

> **反模式清单（不能怎么做，审核用）** → `audit/godot/relic-build.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-03`　数据与逻辑分离
【读】 `common/howto/principles.md#GC-05`　缓存必须有失效路径
