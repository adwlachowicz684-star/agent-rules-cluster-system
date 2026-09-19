# 数据驱动配置与配表工作流（Godot 4.7.2）

大型项目的地基。**此前 55 份文档里"配表" 0 命中。**

## 0. 为什么必须把数据搬出代码

数值写死在代码里：改一个数值要改代码、要重新导出，**程序员成为瓶颈**。

**配表 vs 硬编码的边界**：策划需要调的、会频繁变的、需要批量对比的 → 配表；
结构性逻辑、算法 → 代码。

## 1. 数据源格式对比

| 格式 | 适合 | 不适合 |
|---|---|---|
| **CSV / Excel** | 策划直接编辑、多人协作、diff 友好 | 嵌套结构 |
| **JSON** | 纯外部交换、程序生成 | 人工编辑易错、无注释 |
| **`.tres` / `.res`（Resource）** | 运行时载体、类型安全 | 手工编辑大量数据 |
| **SQLite** | 千表级、复杂查询、多人同时写 | 小项目杀鸡用牛刀 |
| ⚠ `ConfigFile` | 简单设置 | **不适合当配表** |

⚠ **推荐方案（中大型）**：策划编辑 Excel/CSV → 提交 **UTF-8 无 BOM** 的 CSV →
自定义导入器生成带 schema 的 `.tres`，同时**生成 ID 常量** →
运行时只持有只读模板，**运行时实例必须 `duplicate(true)`**。

## 2. Resource 作为配表载体

```gdscript
class_name SkillData extends Resource

@export var id: StringName          # 全局唯一 ID，运行时索引键
@export var name_key: String        # ⚠ 本地化 key，不要直接放多语言文本
@export var base_damage: int
@export var icon: Texture2D
@export var require_skill: StringName  # ⚠ 外键存 ID，不存 Resource 引用
```

⚠ **表结构里的"运行时状态"禁止写进 Resource** ——
每行同一份 Resource 会被共享，写进去就全改了。

⚠ **外键存 ID 不存引用** —— 便于删行、合并和文本编辑。

### duplicate 陷阱（Godot 4 的 #1 新手 bug）

⚠ **`duplicate()` 的默认浅拷贝会共享子资源** —— 这才是"改一个全改"的源头。

| 调用 | 行为 |
|---|---|
| `duplicate(false)` | 只复制 `@export` 与存储属性，**不复制嵌套 Array/Dict/Resource** |
| `duplicate(true)` | 递归复制数组、字典、packed array；**其中的 Resource 取决于模式** |

4.7 的 `DeepDuplicateMode` 有三级：不复制子资源 / 只复制本地无路径子资源 / 复制所有。

```gdscript
# 递归深拷贝要用这个，不是只传 deep=true
return template.duplicate_deep(Resource.DEEP_DUPLICATE_INTERNAL) as SkillData
```

## 3. 导入期校验是必做步骤

至少校验四类：

1. **主键重复** —— `push_error("duplicate skill id %s")` 并阻止导入
2. **类型错** —— CSV 全是字符串，转换失败要报出来
3. **范围** —— 负数、超上限
4. **外键悬空** —— 指向不存在的 ID

⚠ **校验失败应该报错并阻止导入**，不是警告——
否则坏数据进了包，问题会在运行时以完全无关的形式出现。

## 4. 运行时加载

⚠ **`preload()` 在编译期加载** —— 启动时全加载，内存与启动时间都是代价。
⚠ **`load_threaded_request()` 才是异步路径**，不是 `load()` 放线程里。

⚠ **热重载不是"重新 `load()` 一次"** ——
已有实例和运行时索引不会自动刷新，需要明确通知、重建索引，或重启当前关卡。

## 5. ID 规范

- 数值 ID vs 字符串 ID：字符串可读但需要常量生成防拼写错
- ⚠ **ID 要命名空间**（`skill.fireball` 而非 `fireball`），否则不同表会撞车
- 删除一条数据后，引用它的地方要有检查（导入期校验能拦住新增，拦不住历史存档）

## 6. 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 数值写代码里也行 | 改一次就要**重新导出** |
| 2 | `ConfigFile` 能当配表 | 不适合，无 schema 无校验 |
| 3 | Resource 存运行时状态没事 | **会被共享**，改一个全改 |
| 4 | `duplicate()` 就安全了 | 默认**浅拷贝**，子资源仍共享 |
| 5 | `duplicate(true)` 是深拷贝 | Resource 取决于 **DeepDuplicateMode** |
| 6 | 外键存引用更方便 | 删行、合并、文本编辑都会炸 |
| 7 | CSV 导入器够了 | **没有校验**，坏数据直接进包 |
| 8 | 校验失败警告一下就行 | 要**阻止导入** |
| 9 | `load()` 放线程就是异步 | 要用 **`load_threaded_request()`** |
| 10 | 改了表重新 load 就热重载了 | **已有实例不会刷新** |
| 11 | ID 用数字省内存 | 需要常量生成，否则**拼写错查不到** |
| 12 | 表名前缀没必要 | 不同表 **ID 会撞车** |
| 13 | `preload()` 很方便 | **编译期加载**，启动变慢 |
| 14 | 本地化文本直接放表里 | 要放 **key** |

## 7. 相关文档

- 存档与序列化 → `io-network.md`
- 经济与掉落 → `economy.md`
- 技能/战斗数值 → `combat.md`
- 调试工具 → `debugging.md`
- 导入管线 → `advanced-topics.md`
- 资源与美术 → `art-assets.md`
