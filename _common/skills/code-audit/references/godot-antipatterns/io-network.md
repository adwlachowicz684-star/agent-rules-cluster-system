<!-- oversize-exempt: 反模式清单，审核用 -->
# io-network — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于审核完成效果、约束边界。
> 「怎么做」看开发侧：`game-dev/references/godot/io-network.md`

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| `HTTPRequest` 未 `add_child` | 请求不执行 | GD47 |
| `FileAccess.open()` 不判 null | 崩 | 人工 |
| `FileAccess` 未 `close()` | 句柄泄漏 | GD41 |
| 写 `res://` | 导出后静默失败 | GD43 |
| Resource 调 `queue_free()` | 错的，它是 RefCounted | 人工 |
| `any_peer` RPC 不校验 | 客户端可作弊 | 人工 |
| 大文件不用 `download_file` | 全读进内存 | 人工 |
| 循环 `preload` | 解析期报错 | 人工 |
| 改了 load 出来的共享资源 | 所有引用处一起变 | 人工 |
