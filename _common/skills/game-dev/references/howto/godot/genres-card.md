# Godot 4.x 卡牌 / 桌游类

卡牌的架构核心是**"数据即 Resource + 效果栈即状态机"**，
渲染节点只是观察者。

## 0. 四层分离

> 本篇讲**卡牌对战本身**（效果栈、洗牌、牌库回收、拖拽 UI）。
> 构筑合法性、赛制与禁用表、词条/词缀的组合语义 → 见 `build-affix.md`。

| 层 | 职责 |
|---|---|
| **数据层** | `CardData` Resource：id / cost / effects / tags |
| **牌堆层** | `Deck` / `Hand` / `Pile` 各自持有数组 |
| **结算层** | `EffectStack` 效果栈 + `ResolveContext` |
| **表现层** | `CardView` 纯 UI，监听数据变化 |

⚠ **卡牌必须是 Resource 不是 Node/PackedScene** ——
同一张"火球"在牌库、手牌、弃牌堆各一份场景实例会成倍消耗内存与实例化时间。
只有要显示的 `CardView` 是场景。

## 1. CardData 与 Effect

```gdscript
# card_data.gd
class_name CardData extends Resource

@export var id: StringName
@export var cost: int = 1
@export var effects: Array[Effect] = []
@export var tags: PackedStringArray = []

# effect.gd
class_name Effect extends Resource

enum Timing { ON_PLAY, ON_DRAW, ON_TURN_START, ON_DEATH }
@export var timing: Timing = Timing.ON_PLAY

func resolve(ctx: ResolveContext) -> EffectResult:
    return EffectResult.new(true)
```

## 2. 效果结算用显式栈，不是信号

```gdscript
var _stack: Array[Effect] = []

func resolve_all(ctx: ResolveContext) -> void:
    var guard := 0
    while not _stack.is_empty() and guard < MAX_DEPTH:
        guard += 1
        var e := _stack.pop_back()      # 后进先出 = 连锁
        var r := e.resolve(ctx)
        if r.spawned:
            _stack.append_array(r.spawned)
```

⚠ **"连锁"不是"信号连接"** —— 用 `signal` 触发效果无法控制结算顺序、
无法入栈、无法在中间插入响应、无法取消。

⚠ **无保护的响应链会相互触发无限递归** —— 必须设最大栈深度
与"本轮已响应"标记，且每步校验目标是否仍合法。

## 3. 伤害要生成事件入栈，不要直接调用

```gdscript
# 错：跳过响应链
target.take_damage(5)

# 对：入栈，让"受伤时"类效果有机会响应/修改/取消
_stack.push_back(DamageEvent.new(source, target, 5))
```

⚠ **伤害数字、特效、飘字都应从结算结果驱动**，而非逻辑内直接播放。

## 4. 洗牌必须走同一个 rng 实例

```gdscript
var rng := RandomNumberGenerator.new()

func new_run(seed_str: String) -> void:
    rng.seed = hash(seed_str)

func shuffle(arr: Array) -> void:
    for i in range(arr.size() - 1, 0, -1):
        var j := rng.randi_range(0, i)
        var t = arr[i]; arr[i] = arr[j]; arr[j] = t
```

⚠ **`Array.shuffle()` 用的是全局 RNG 状态** —— 无法复现、无法做服务器校验。

⚠ **所有随机都要走同一个 `rng` 实例** ——
全局 `randf()/randi()` 与 `rng.randf()`（`RandomNumberGenerator` 实例）是**两套独立状态**，
⚠ **混用会导致同种子下每次结果不同** —— 一部分洗牌走了实例、一部分走了全局流，
回放与验证都无从谈起。
⛔ 项目内统一只用一种；参与结果的**一律用带种子的实例**。
混用会让"同种子不同结果"。

## 5. 牌库空了重新洗弃牌堆要防同帧回抽

```gdscript
func draw() -> CardData:
    if _deck.is_empty():
        if _discard.is_empty():
            return null
        _reshuffle()                 # 洗弃牌堆进牌库
    return _deck.pop_back()
```

⚠ **"洗弃牌堆"与"抽一张"混在同一帧无保护，会抽到刚洗进去的同一张**。
标准做法是洗后把新牌库视为已就绪，但本轮该次抽牌按"洗前判定"处理，
或显式标记 `is_reshuffling` 跳过本次。

## 6. 存档用 Resource，不要用 JSON

⚠ **JSON 无法表达 Resource 引用与类型信息** ——
卡牌 `targets` 里的节点引用、Effect 子类必须用 `.tres`/`.res`
或自定义二进制协议。

```gdscript
ResourceSaver.save(state, "user://run.res", ResourceSaver.FLAG_COMPRESS)
```

⚠ **`FLAG_COMPRESS`（Zstandard）仅对二进制资源有效** ——
`.tres`/`.tscn` 是文本格式，压缩标志对它们无意义。

⚠ **换存档槽要带 `FLAG_CHANGE_PATH`** —— 官方语义是该标志
*"Changes the `Resource.resource_path` of the saved resource to match its new location."*
⛔ 只写 `save(state, "user://slot2.res")` 不带这个标志，
`state.resource_path` 仍是旧槽位，之后任何**不带路径的自动保存**都会写回旧槽
（不带路径时官方语义是尝试用 `Resource.resource_path`），
表现为"玩了半天发现覆盖了另一个存档"，且不报错。

⚠ **外部子资源要带 `FLAG_BUNDLE_RESOURCES`** —— 官方语义是
*"Bundles external resources."*
⛔ 不带则存档里只有一行路径引用，内容仍在原 `.tres` 里；
原文件一变（换版本、热更、改数值），读档拿到的就是**新的**数据。

## 7. 拖拽 UI

```gdscript
func _get_drag_data(_pos: Vector2) -> Variant: ...
func _can_drop_data(_pos: Vector2, data: Variant) -> bool: ...
func _drop_data(_pos: Vector2, data: Variant) -> void: ...
```

⚠ **开局洗牌、整副重抽时避免在循环里 `instantiate()`** ——
手牌区用固定容量池，抽牌只绑定新数据、动画入场；弃牌直接解绑不释放。

⚠ **UI 侧 `Control` 的子节点数量、布局重算比纹理更耗** ——
`NOTIFICATION_SORT_CHILDREN` 与 `queue_redraw()` 滥用会拖垮拖拽帧。

## 8. ⛔ Resource 带缓存：load() 拿的是同一个实例

官方口径：`ResourceLoader` **会缓存加载结果**，
*"Once a resource has been loaded by the engine, it is cached in memory for faster access,
and future calls to the load method will use the cached version."*

⚠ 所以 `load("res://cards/fireball.tres")` 每次返回的是**同一个对象** ——
牌库、手牌、弃牌堆里所有同名"火球"是同一个实例，
改一处全变，**且不报错**。

⛔ 表现是"本回合费用 −1 一生效，牌库里剩下的火球全变 0 费"，
排查时 `Array[CardData]`、`Resource`、`@export` 全部检查都对 ——
因为错的不是类型，是**同一性**。

ⓘ 判据：手牌与牌库里的同名卡 `get_instance_id()` 必须不同。
⛔ 只在注释里写"别改定义"没有约束力，需要一处可断言的复制边界。

## 9. ⛔ duplicate() 的深拷边界（版本相关）

⚠ **`duplicate(true)` 不等于"深拷成功"** ——
数组与字典里的子资源在 **4.2–4.4 不会被复制**（已知问题），
4.5 起该行为修正并新增 `duplicate_deep()`（PR #100673）。

⛔ 而 `CardData.effects` **正是** `Array[Effect]` ——
于是"卡复制了、效果没复制"：改副本的效果参数，原卡跟着变。
这是比完全不复制更难查的形态：
检查时 `duplicate()` 确实调了，返回值也确实是新对象。

ⓘ 另需注意同一版本族内的语义变更：
4.5 起默认 `duplicate()` 对数组/字典是**只引用不复制**，
⛔ 抄一段 4.2 时代的写法在 4.5 上会得到另一种错。

```gdscript
# ⛔ 不要指望 duplicate(true) 深拷数组内的 Effect
func clone_card(src: CardData) -> CardData:
    var c := src.duplicate() as CardData
    c.effects = []
    for e in src.effects:
        c.effects.append(e.duplicate())
    c.resource_path = ""        # 切断与原 .tres 的关联
    return c
```

## 10. 流程：按什么顺序做

→ `flow/godot/card/00-域流程总览.md`（7 个功能点 / 37 Step）

⛔ 先定"卡牌是定义还是实例、随机走哪个源、连锁由谁收口"，
再动手 —— 01 的同一性问题与 02 的随机源问题
都是**事后补代价极高、且不报错**的。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-card.md`
