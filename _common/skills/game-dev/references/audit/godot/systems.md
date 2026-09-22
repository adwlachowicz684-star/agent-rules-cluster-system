<!-- oversize-exempt: 反模式清单，审核用 -->
# systems — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/systems.md`

## 常见漏写

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | 存档写 `res://` | 导出后静默失败，存档丢失 | GD43 |
| 2 | `FileAccess` 未 `close()` | 句柄泄漏 | GD41 |
| 3 | Autoload 信号未断开 | 节点释放不了，内存累积 | GD15 |
| 4 | Resource 调 `queue_free()` | 错的，Resource 是 RefCounted | 人工 |
| 5 | 对象池用 `queue_free` 回收 | 失去池化意义 | 人工 |
| 6 | 池化对象未重置状态 | 复用后残留上次状态 | 人工 |
| 7 | `instantiate()` 后未 `add_child()` | 不进树，不触发 `_ready` | GD46 |
| 8 | 切换后立刻读 `current_scene` | 官方：新场景**帧末**才入树，此刻为 null；要 `await scene_changed` |
| 9 | 旧场景 `_exit_tree` 里调 `get_tree()` | 官方：已移出树，返回 **null**；⛔ 别在那里做收尾 |
| 10 | `reload_current_scene()` 能重置全局 | ⚠ **不重载 Autoload**，`@onready` 持有的节点引用全部失效 |
| 11 | 重复 `load_threaded_request` 同一路径 | 返回 `ERR_ALREADY_IN_USE`；要接返回值并区分 |
| 12 | 加载完立刻切场景 | ⓘ 小场景进度条**闪一下**比不显示更像卡顿；要有最小展示时间 |
| 13 | 切完还想用局部变量取数据 | ⚠ 当前场景节点**全部销毁**；要存 Autoload 或存档 |
