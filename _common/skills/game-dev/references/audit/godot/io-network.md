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
| 10 | load() 传相对路径 | 被自动加 `res://` 前缀 → 拿到空资源，只打印一句“文件未找到” | 官方 |
| 11 | 改了 load() 出来的共享资源 | 所有引用处一起变（与 #9 同源，本条是运行时加载路径） | 人工 |
| 12 | load_threaded_request 传 use_sub_threads=true 求“更快” | 抢占主线程，⛔ 加载画面自己开始卡，排查被引向磁盘 IO | 官方 |
| 13 | 加载未完成时调 load_threaded_get() | 阻塞调用线程，异步变同步卡顿且不报错 | 官方 |
| 14 | 用循环轮询 load_threaded_get_status | 占满主线程等结果（官方要求在不同帧调用） | 官方 |
| 15 | 对同一路径第二次调 load_threaded_get() | 任务取走即移除，之后返回 INVALID | 官方 |
| 16 | 调用 ResourceLoader 的 cancel / 取消加载 | ⛔ 官方无此 API，只能丢弃结果 + 令牌校验 | 官方 |
| 17 | 替换/热更资源沿用默认 CACHE_MODE_REUSE | 拿到旧缓存，换了等于没换 | 人工 |
| 18 | 写文件不是原子写（先写临时再 rename） | 断电/强杀留下半截文件，且下次读到它 | 人工 |
| 19 | 用 get_var() 反序列化下载或上传的数据 | ⛔ 官方 Warning：反序列化对象可含可执行代码（RCE） | 官方 |
| 20 | 后台线程 open 失败、主线程读 get_open_error() | 拿到的是主线程自己那次的结果，错误被擦掉 | 官方 |
| 21 | 写目录前不判存在、不建目录 | 写入失败而返回值看着正常 | 人工 |
| 22 | 不设 HTTPRequest.timeout | ⛔ 默认 0.0 = 永不超时，弱网下永久转圈 | 官方 |
| 23 | 自定义 header 里带 Accept-Encoding | ⛔ gzip 解压静默失效，body 是压缩字节，JSON 解析失败 | 官方 |
| 24 | 不设 body_size_limit | 默认 -1 无限制，响应体多大都读进内存 | 官方 |
| 25 | 一个 HTTPRequest 同时发两个请求 | 第二个返回 ERR_BUSY，⛔ 看着跟网络故障一模一样 | 官方 |
| 26 | 用 get_body_size() 做进度条分母 | 服务器不发长度 / chunked 时返回 -1，除零或负数 | 官方 |
| 27 | 只判 result == SUCCESS 不看 response_code | 500 / 404 被当成成功 | 人工 |
| 28 | download_file 指向未创建的子目录 | RESULT_DOWNLOAD_FILE_CANT_OPEN=10；⛔ 编辑器里目录已存在时是好的，导出后必然失败 | 官方 |
| 29 | 下载完成不校验大小 / 校验和 | 半截文件当完整用，且不报错 | 人工 |
| 30 | 断点续传不记录已下载字节 | 每次从头，弱网永远下不完 | 人工 |
| 31 | 把 peer_id 当稳定玩家身份 | 重连后变号，数据串号到别人身上 | 人工 |
| 32 | 连接失败不判 create_server / create_client 的错误码 | “服务端在跑但一个连接都接不进来” | 人工 |
| 33 | 手写 RPC 生成节点而两端 NodePath 不一致 | RPC 静默不调用，⛔ 无报错 | 人工 |
| 34 | 只写 @export 不配 MultiplayerSynchronizer 的 replication 列表 | 属性不同步，且面板上看不出差别 | 人工 |
| 35 | 把 spawn_limit 当权威上限 | 它是客户端复制上限，改包即可绕过 | 官方 |
| 36 | 断线重连后不重建 RPC / 同步关系 | 看着连上了，数据一直不动 | 人工 |
| 37 | 高频属性同步不设间隔 | 带宽打满，表现为“越玩越卡” | 人工 |
| 38 | 只在编辑器验运行时加载 | 导出后 convert_text_resources_to_binary 让 load 读不到（该设置默认 true） | 官方 |
| 39 | 只在局域网测联机 | NAT / 端口 / 公网问题全部漏掉 | 人工 |
| 40 | 只测成功路径 | 超时与重试分支从未执行过，故障期一触发就是成片 | 人工 |
| 41 | 用 ResourceLoader.list_directory 的顺序当地图加载顺序 | ⛔ 官方：顺序不确定，跨操作系统会变 | 官方 |
| 42 | 在联机基础域自创插值 / 回滚算法 | 与 `netsync` 既有口径冲突，两套同步逻辑互相覆盖 | 人工 |

## 审核时逐条问自己

1. `load()` 传的是绝对路径吗？（⛔ 相对路径会被自动加 `res://` 前缀）
2. 改过 `load()` 出来的资源吗？它是共享的。
3. 线程加载开了 `use_sub_threads` 吗？⛔ 那会让加载画面自己卡。
4. 有没有在加载未完成时调 `load_threaded_get()`？
5. 同一个路径取了两次吗？（取走即移除）
6. 写文件是原子写吗？断电后会不会留半截？
7. 反序列化的数据来源可信吗？（⛔ `get_var()` 会执行代码）
8. `HTTPRequest.timeout` 设了吗？⛔ 不设 = 永不超时。
9. 自定义 header 里有没有 `Accept-Encoding`？（⛔ 会让 gzip 解压失效）
10. 一个 `HTTPRequest` 有没有被并发使用？（`ERR_BUSY`）
11. `download_file` 的目录建了吗？（⛔ 不会自动建）
12. 下载完校验大小和校验和了吗？
13. `peer_id` 有没有被当成稳定身份？
14. `any_peer` 的 RPC 校验了发送者吗？
15. `spawn_limit` 有没有被当成权威上限？服务端自己数了吗？
16. 同步属性配进 replication 列表了吗？
17. 运行时加载在**导出包**里验过吗？（⛔ 编辑器通过不代表出包通过）
18. 超时与重试路径真跑过吗？⛔ 只测成功路径等于没测。

## 全局块（跨功能通用）


> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【审】 `common/audit/global.md#GA-07`　错误处理吞掉异常
