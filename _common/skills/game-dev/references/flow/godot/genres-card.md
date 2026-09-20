# Godot 4.x 卡牌 / 桌游类

卡牌的架构核心是**"数据即 Resource + 效果栈即状态机"**，
渲染节点只是观察者。

## 0. 四层分离

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
全局 `randf()/randi()` 与 `RandomNumberGenerator` 是不同状态，
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

> **反模式清单（不能怎么做，审核用）** → `audit/godot/genres-card.md`
