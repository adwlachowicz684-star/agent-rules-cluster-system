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

> **反模式清单（不能怎么做，审核用）** → `audit/godot/datatable.md`


## 6. 导出与运行时加载的冲突（隐藏最深的一条）

⚠ **项目设置 `editor/export/convert_text_resources_to_binary` 若为 `true`，
导出后 `load()` 读不了被转换的文件。**

官方文档的原文是：开启该选项时 `@GDScript.load` 将**无法读取**导出项目中
被转换的文件；若要在运行时加载 PCK 内的文件，必须把该选项设为 `false`。

⛔ 症状极具迷惑性：**编辑器里一切正常，导出后配表全空**。
而报错往往不是"文件不存在"，而是拿到一个空资源，
问题会在运行时以完全无关的形式出现（"技能伤害全是 0"）。

```text
editor/export/convert_text_resources_to_binary = false   # 运行时要读 .tres 就必须关
```

## 7. duplicate 的精确语义（4.x 官方文档口径）

⚠ 文档里"深拷贝"这个词在 Godot 里**不是**"全复制"，要按官方口径理解：

| 调用 | 官方说明 |
|---|---|
| `duplicate(false)` | 浅拷贝：嵌套的 Array / Dictionary / **Resource 都不复制，与原对象共享** |
| `duplicate(true)` | 递归复制嵌套数组、字典、packed array；⚠ **其中的 Resource 只有 "local" 的才复制**，等价于 `duplicate_deep(DEEP_DUPLICATE_INTERNAL)` |

`DeepDuplicateMode` 三级：`DEEP_DUPLICATE_INTERNAL`（无路径或场景本地路径的子资源）
/ `DEEP_DUPLICATE_ALL`（全部，含单独存的大资源）/ 不复制。

```gdscript
template.duplicate_deep(Resource.DEEP_DUPLICATE_INTERNAL) as SkillData
```

⚠ **两个额外约束，官方文档明确写了**：

1. ⛔ **对自定义 Resource，若 `_init()` 定义了必需参数，`duplicate()` 会失败。**
   配表类想用带参构造函数（比如 `SkillData.new(id, dmg)`）就会踩这条——
   ⚠ 配表类**不要定义带必需参数的 `_init()`**，改成无参构造 + 属性赋值。

2. `duplicate(true)` 时**每个资源只复制一次**：
   若 A 引用了 B 两次，得到的新 A' 会引用**同一个** B' 两次
   （⛔ 不是两个独立的 B'）。这对"想让每行完全独立"的预期是个意外。

还有两个 property usage 标记会覆盖上述行为：
`PROPERTY_USAGE_ALWAYS_DUPLICATE`（总是复制）/ `PROPERTY_USAGE_NEVER_DUPLICATE`（从不复制）。

⚠ `resource_local_to_scene` 也能让资源在每个场景实例里唯一，
但官方文档写明：**运行时改这个属性对已创建的副本无效**。

## 8. 异步加载的三个 API 与一个阻塞陷阱

```gdscript
ResourceLoader.load_threaded_request(path)      # 返回 Error
ResourceLoader.load_threaded_get_status(path, _progress)   # 每帧轮询
ResourceLoader.load_threaded_get(path)          # ⚠ 可能阻塞
```

⚠ **`load_threaded_get()` 在加载未完成时，会阻塞调用线程直到加载结束** ——
官方原话就是这个。所以 ⛔ 不能在轮询之外"顺手"调它，
必须在 `get_status()` 返回 `THREAD_LOAD_LOADED` 之后再取。

⚠ **重复对同一路径 `load_threaded_request()` 会返回 `ERR_ALREADY_IN_USE`** ——
玩家连点两次触发、或同一表被两个系统同时请求，都会刷出这个错误。
✅ 用一个"请求中"的集合做守卫。

```gdscript
var _pending: Dictionary = {}      # path -> true

func request(path: String) -> void:
    if _pending.has(path):
        return                      # ⚠ 守卫
    var err := ResourceLoader.load_threaded_request(path)
    if err != OK:
        push_error("异步加载请求失败 %s: %d" % [path, err])
        return
    _pending[path] = true

func _process(_delta: float) -> void:
    for path in _pending.keys():
        var st := ResourceLoader.load_threaded_get_status(path, _progress)
        if st == ResourceLoader.THREAD_LOAD_LOADED:
            var res := ResourceLoader.load_threaded_get(path)   # ✅ 已就绪才取
            _pending.erase(path)
            _on_loaded(path, res)
        elif st == ResourceLoader.THREAD_LOAD_FAILED:
            push_error("异步加载失败 %s" % path)
            _pending.erase(path)
```

ⓘ `use_sub_threads = true` 会更快，但官方文档说明它**可能影响主线程造成卡顿**。

## 9. 缓存、热重载与"重新 load 没用"

⚠ **热重载不是"重新 `load()` 一次"** —— 已有实例和运行时索引不会自动刷新。

三个相关事实：

1. `ResourceLoader.has_cached(path)` 可查询是否已缓存；
   资源一旦加载就**缓存在内存**，后续 `load()` 返回的是同一个引用。
2. `Resource.take_over_path(path)` 可以**覆盖**某个路径上的缓存条目
   （而直接设 `resource_path` 在该路径已有缓存时会报错）。
3. 想真正热重载，必须：重新生成资源 → `take_over_path` → **重建索引**
   → **通知持有旧实例的地方重建**，或干脆重启当前关卡。

⚠ `ResourceSaver.save()` 的 flags 里 `FLAG_REPLACE_SUBRESOURCE_PATHS`
会接管已存子资源的路径（即 `take_over_path()`），批量保存时有用。

## 10. UID 与路径变更（4.4+）

Godot 4.4 起的 UID 系统：每个资源有 `uid://` 标识，
保存在 **`.uid` 伴随文件**里。⚠ **移动或重命名资源时 UID 不变**，
引用得以保持——这解决了"策划改了表格文件名，代码里全断"的问题。

ⓘ 相关 API：`ResourceSaver.get_resource_id_for_path(path, generate)`、
`ResourceSaver.set_uid(path, uid)`、`ResourceUID.create_id()`。

⚠ 官方文档注明：**项目运行时生成的 UID 不会被保存**
（那段代码只在编辑器模式执行）。所以导入器生成资源时
不要指望运行时自动补 UID。

## 11. 版本演进：删行与历史存档

⚠ **导入期校验能拦住"新增的悬空引用"，拦不住历史存档里已有的 ID。**

玩家存档里存着 `skill.fireball`（v3），而 v5 删掉了这一行——
导入期校验通过（表里没问题），运行时读档才炸。

三种处理：

| 策略 | 做法 | 代价 |
|---|---|---|
| **永不删除** | 只标记 `deprecated` | 表会膨胀，但最安全 |
| **重定向表** | 保留 `old_id -> new_id` 映射，读档时翻译 | 要维护映射 |
| **兜底替换** | 找不到就换成默认项并记录 | 玩家会感到物品变了 |

⚠ 无论选哪种，**读档时都不要崩**——
配表问题是数据问题，不应该让玩家丢档。

## 12. 相关文档

- 存档与序列化 → `io-network.md`
- 经济与掉落 → `economy.md`
- 技能/战斗数值 → `combat.md`
- 调试工具 → `debugging.md`
- 导入管线 → `advanced-topics.md`
- 资源与美术 → `art-assets.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-03`　数据与逻辑分离
【读】 `common/howto/principles.md#GC-05`　缓存必须有失效路径
【读】 `common/howto/principles.md#GC-08`　常见架构模式速查
