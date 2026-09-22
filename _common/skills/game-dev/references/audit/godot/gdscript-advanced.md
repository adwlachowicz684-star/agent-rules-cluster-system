<!-- oversize-exempt: 反模式清单，审核用 -->
# gdscript-advanced — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/gdscript-advanced.md`

## `await` 的坑

### 不要在 `_physics_process` 里 await

```gdscript
# 反例：物理帧被跳过
func _physics_process(_d: float) -> void:
    await get_tree().create_timer(0.1).timeout      # 挂起
    velocity = ...                                   # 恢复后状态已不可信
```

⚠ `_physics_process` 挂起会导致**物理帧跳过**、状态错乱。
需要延时就用状态机或 Timer 节点，别在固定步里 await。

### await 之后对象可能已释放

```gdscript
func _on_attack() -> void:
    await get_tree().create_timer(1.0).timeout
    # 这一秒内玩家可能已死、场景已切换
    if not is_instance_valid(self):          # 必须判
        return
    _apply_damage()
```

⚠ 这是最常见的 await 崩溃原因（审查 GD75）。

### await 不是"后台执行"

```gdscript
await some_signal      # 挂起当前协程，等信号
```

它不会让代码变快，只是让出执行权。**耗时计算放 WorkerThreadPool**（见 `performance.md`）。

## 常见漏写

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | `@onready` 不标类型 | 无补全 | 人工 |
| 2 | `as` 后不判空 | 空引用崩溃 | 人工 |
| 3 | 用 `if x` 判已释放对象 | 崩溃 | 人工 |
| 4 | `_physics_process` 里 await | 物理帧跳过 | 人工 |
| 5 | await 后不判 is_instance_valid | 崩溃 | GD75 |
| 6 | `@export Resource` 不 duplicate | 所有实例共享，改一个全变 | GD95 |
| 7 | 3.x 信号写法 | 静默失效 | GD72 |
| 8 | 热路径字符串比较 | 逐字符 | GD92 |
| 9 | 每帧新建容器 | GC 压力 | GD12 |
| 10 | `@tool` 脚本不隔编辑器逻辑 | 污染场景/卡编辑器 | 人工 |
