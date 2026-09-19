<!-- oversize-exempt: 反模式清单，审核用 -->
# index — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于审核完成效果、约束边界。
> 「怎么做」看开发侧：`game-dev/references/godot/index.md`

## 常见漏写速查

写完对照一遍：

| 漏写 | 审查规则 |
|---|---|
| Autoload 信号未断开 | GD15 |
| `remove_child` 后没 `queue_free` | GD01 |
| `create_tween()` 未保存引用 | GD02 |
| `FileAccess` 未 `close()` | GD41 |
| 存档写 `res://` | GD43 |
| `instantiate()` 后未 `add_child()` | GD46 |
| 动态 `AudioStreamPlayer` 未 `queue_free()` | GD52 |
| `assert` 做运行时校验 | GD71 |
| `duplicate()` 浅拷贝 | GD73 |
| `print()` 留在正式代码 | GD74 |
| `await` 后未判 `is_instance_valid` | GD75 |
| 每帧赋值 `Label.text` | GD13 |
| `move_and_slide(...)` 带参 | GD09 |
| `velocity *= delta` | GD21 |

完整判据见 `../../code-audit/references/p-godot.md`。
