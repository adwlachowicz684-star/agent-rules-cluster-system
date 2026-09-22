# 02 表结构与 schema 定义（配置表域）

> **前置**：01 已定"什么进表"与数据源格式
> **本步交付**：每行一个 `Resource` 类定义——外键存 ID、文本存 key、不含运行时状态
> **对应**：做法 `howto/godot/datatable.md` · 审核 `audit/godot/datatable.md`

## 0. 交付物定义

做完这一步，应该能**当场演示**：

1. 每个表有一个 `class_name XxxData extends Resource`
2. ⚠ 外键字段存的是 **ID 字符串**，不是 Resource 引用
3. ⚠ 文本字段存的是**本地化 key**，不是明文
4. ⚠ 类里**没有**任何运行时状态字段
5. ⛔ `_init()` **没有**必需参数（否则 `duplicate()` 会失败）

**产出物**（下游按名字对接）：

```text
class_name SkillData extends Resource   等各表的类定义
每个表的 ID 命名前缀（skill.fireball）
外键字段清单（存 StringName）
```

## 1. 前置检查清单

- [ ] 01 的进表清单已定稿
- [ ] ⚠ 已确认 ID 命名规则（含前缀）
- [ ] 已确认哪些字段是外键
- [ ] 已确认哪些字段是展示文本
- [ ] ⛔ 已确认**没有**带必需参数的 `_init()`

## 2. 工序

### Step 1　定义 Resource 类　`[datatable/02#S1]`

【读】`howto/godot/datatable.md#2. Resource 作为配表载体`

【做】
```gdscript
class_name SkillData extends Resource

@export var id: StringName           # 全局唯一 ID，运行时索引键
@export var name_key: String         # ⚠ 本地化 key，不要直接放多语言文本
@export var base_damage: int
@export var icon: Texture2D
@export var require_skill: StringName  # ⚠ 外键存 ID，不存 Resource 引用
```

⚠ **表结构里的"运行时状态"禁止写进 Resource** ——
每行同一份 Resource 会被共享，写进去就全改了。

【产出】每个表一个类，字段类型明确

【判据】⚠ 类里**没有任何** `current_*` / `_cd` / `runtime_*` 之类字段

【审】`audit/godot/datatable.md#3`（Resource 存运行时状态没事 → 会被共享）

### Step 2　外键存 ID 不存引用　`[datatable/02#S2]`

【读】`howto/godot/datatable.md#2. Resource 作为配表载体` 的 ⚠

【做】⚠ **外键存 ID 不存引用** —— 便于删行、合并和文本编辑。

⛔ 存引用的话：删掉被引用的行 → 引用悬空；
合并两张表 → 引用路径全变；手工编辑 `.tres` → 引用格式易写错。

【产出】所有跨表/跨行引用字段都是 `StringName`

【判据】⚠ 类定义里**没有** `@export var xxx: SkillData`（引用类型外键）

【审】`audit/godot/datatable.md#6`（外键存引用更方便 → 删行、合并、文本编辑都会炸）

### Step 3　文本存 key 不存明文　`[datatable/02#S3]`

【读】`howto/godot/i18n.md`

【做】⚠ 面向玩家的文本字段存 **key**（`skill.fireball.name`），
⛔ 不直接放"火球术"。

⛔ 存明文的话，加一种语言就要改 CSV，
而且同一个名字在多个表重复出现，改一处漏一处。

【产出】所有展示文本字段是 key

【判据】⚠ CSV 里**没有任何**中文/英文展示文本（只有 ID、数值、key）

【审】`audit/godot/datatable.md#14`（本地化文本直接放表里 → 要放 key）

### Step 4　ID 命名空间　`[datatable/02#S4]`

【读】`howto/godot/datatable.md#5. ID 规范`

【做】⚠ **ID 要命名空间**（`skill.fireball` 而非 `fireball`），
否则不同表会撞车——"火球"和"火球药水"都叫 `fireball` 就完了。

| | 字符串 ID | 数值 ID |
|---|---|---|
| 可读 | ✅ | ⛔ |
| 内存/带宽 | 略大 | 小 |
| 拼错 | ⚠ 需要常量生成 | 一样需要 |

⚠ 字符串可读但**需要常量生成防拼写错**——
手敲 `"skill.firebal"` 少一个 l，运行时才发现。

【产出】ID 规则已定（含前缀），且有常量生成计划

【判据】⚠ 所有表的 ID 都带表名前缀，全库**无重复** ID

【审】`audit/godot/datatable.md#11` `audit/godot/datatable.md#12`

### Step 5　⛔ 不要带必需参数的 _init()　`[datatable/02#S5]`

【读】`howto/godot/datatable.md#7. duplicate 的精确语义（4.x 官方文档口径）`

【做】⚠ **对自定义 Resource，若 `_init()` 定义了必需参数，`duplicate()` 会失败**
—— 这是官方文档明确写的。

配表类想用带参构造（`SkillData.new(id, dmg)`）就会踩这条，
而且失败发生在**运行时拷贝实例时**，不是定义时，很难定位。

✅ 配表类**不要定义带必需参数的 `_init()`**，改成无参构造 + 属性赋值。

【产出】所有配表类的 `_init()` 无必需参数

【判据】⚠ 对每个配表类调 `template.duplicate(true)`，**不报错且非 null**

【审】`audit/godot/datatable.md#4` `audit/godot/datatable.md#5`

## 3. 参考实现

```gdscript
# skill_data.gd
class_name SkillData extends Resource

# ⛔ 不要写成 func _init(p_id: StringName, p_dmg: int) —— duplicate() 会失败

@export var id: StringName
@export var name_key: String          # ⚠ key 不是明文
@export var desc_key: String
@export var base_damage: int
@export var cooldown: float
@export var require_skill: StringName # ⚠ 外键存 ID
@export var icon: Texture2D

# ⛔ 禁止出现下面这类字段（运行时状态）：
# @export var current_cooldown: float
# @export var unlock_level: int
```

⚠ `Texture2D` 这类资源引用**可以**存（它是美术资产不是运行时状态），
因为配表模板本来就共享同一份纹理——这正是想要的行为。

ⓘ 判断标准很简单：**这个字段会不会因为玩家行为而改变？**
会 → 运行时状态，禁止进模板；不会 → 可以存。

## 4. 验收清单

- [ ] 每个表有 `class_name XxxData extends Resource`
- [ ] 无运行时状态字段
- [ ] 外键全是 `StringName` 存 ID
- [ ] 文本字段全是 key
- [ ] ID 带表名前缀，全库无重复
- [ ] 配表类 `_init()` 无必需参数，`duplicate(true)` 成功

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 改一个全改了 | 存了运行时状态 | S1 |
|---|---|---|
| 删一行后一堆引用悬空 | 外键存了引用 | S2 |
| 加语言要改 CSV | 存了明文 | S3 |
| 两个表的 ID 撞车 | 没加前缀 | S4 |
| 运行时 duplicate 返回 null | `_init()` 有必需参数 | S5 |

## 6. 下一步

→ **03 导入管线与常量生成**（本步的类定义是它的目标类型）

## 7　整体审核（功能点级收尾）

ⓘ 各 Step 的【审】是**步骤级即时检查**；本节是**功能点级复查**，两级都要走。

- [ ] 逐条过 `audit/godot/datatable.md`，每条说出"我们是怎么避免的"
  - ⛔ 不能"应该没这个问题"
- [ ] 步骤级【审】列过的条目**再过一遍**
- [ ] ⚠ 实测参数已回填，⛔ 不留示例值
- [ ] 若属大功能 → ⚠ **还要集成验收**：各部件合格 ≠ 拼起来能用
