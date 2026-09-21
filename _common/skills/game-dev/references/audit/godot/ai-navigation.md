<!-- oversize-exempt: 反模式清单，审核用 -->
# ai-navigation — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/ai-navigation.md`

## 沿当前路径走。抽出来避免四个状态各写一遍
func _follow_path(spd: float) -> void:
    if _agent.is_navigation_finished():
        velocity = Vector2.ZERO
        return
    var next := _agent.get_next_path_position()
    velocity = global_position.direction_to(next) * spd

func _try_attack() -> void:
    if _attack_timer > 0.0:
        return
    _attack_timer = attack_cooldown
    if _target and _target.has_method("take_damage"):
        _target.take_damage(10)
    print_debug("attack")

## separation：群体里互相推开，避免叠在一起
func separation(neighbors: Array[Node2D], radius: float) -> Vector2:
    var push := Vector2.ZERO
    for n in neighbors:
        if n == self:
            continue
        var d := global_position.distance_to(n.global_position)
        if d > 0.0 and d < radius:
            push += (global_position - n.global_position).normalized() / d
    return push * 100.0
```

用的时候合成：

```gdscript
func _physics_process(_delta: float) -> void:
    var steer := seek(_target.global_position, speed)
    steer += separation(get_tree().get_nodes_in_group("enemy"), 40.0) * 0.5
    velocity = steer.limit_length(speed)
    move_and_slide()
```

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| 每帧重设 `target_position` | 敌人原地抖 | 人工 |
| `RayCast` 改完未 `force_raycast_update` | 隔墙能看见 | GD23 |
| 开避障时自己又 `move_and_slide()` | 重复积分，速度翻倍 | 人工 |
| 目标已释放只判 `if _target` | 访问已释放对象 | 人工 |
| `lose_range` ≤ `detect_range` | 边界反复横跳 | 人工 |
| `AStarGrid2D` 改了不 `update()` | 不生效 | 人工 |
| 导航多边形不重新烘焙 | 改了地形寻路还是走旧的 | 人工 |
| 状态转换散在各处 | 调试时理不清 | 人工 |
| `patrol_points` 为空 | `% 0` 除零崩溃 | 人工 |
