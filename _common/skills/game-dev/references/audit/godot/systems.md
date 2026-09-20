<!-- oversize-exempt: 反模式清单，审核用 -->
# systems — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/systems.md`

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| 存档写 `res://` | 导出后静默失败，存档丢失 | GD43 |
| `FileAccess` 未 `close()` | 句柄泄漏 | GD41 |
| Autoload 信号未断开 | 节点释放不了，内存累积 | GD15 |
| Resource 调 `queue_free()` | 错的，Resource 是 RefCounted | 人工 |
| 对象池用 `queue_free` 回收 | 失去池化意义 | 人工 |
| 池化对象未重置状态 | 复用后残留上次状态 | 人工 |
| `instantiate()` 后未 `add_child()` | 不进树，不触发 `_ready` | GD46 |
