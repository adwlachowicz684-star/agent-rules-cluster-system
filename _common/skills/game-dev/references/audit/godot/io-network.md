<!-- oversize-exempt: 反模式清单，审核用 -->
# io-network — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/io-network.md`

## 常见漏写

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | `HTTPRequest` 未 `add_child` | 请求不执行 | GD47 |
| 2 | `FileAccess.open()` 不判 null | 崩 | 人工 |
| 3 | `FileAccess` 未 `close()` | 句柄泄漏 | GD41 |
| 4 | 写 `res://` | 导出后静默失败 | GD43 |
| 5 | Resource 调 `queue_free()` | 错的，它是 RefCounted | 人工 |
| 6 | `any_peer` RPC 不校验 | 客户端可作弊 | 人工 |
| 7 | 大文件不用 `download_file` | 全读进内存 | 人工 |
| 8 | 循环 `preload` | 解析期报错 | 人工 |
| 9 | 改了 load 出来的共享资源 | 所有引用处一起变 | 人工 |

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【审】 `common/audit/global.md#GA-07`　错误处理吞掉异常
