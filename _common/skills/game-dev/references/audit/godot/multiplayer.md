<!-- oversize-exempt: 反模式清单，审核用 -->
# multiplayer — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/multiplayer.md`

## 常见坑

| 坑 | 后果 |
|---|---|
| `@rpc` 不标 mode 就当客户端能调 | 静默忽略，不报错 |
| `any_peer` 不校验 sender | 任何人可伪造他人操作 |
| await 后取 sender | 变成 0 |
| 每帧都 reliable | 重传阻塞，延迟雪崩 |
| Synchronizer 当插值用 | 抖动 |
| `replication_interval = 0` | CPU/带宽打满 |
| authority 转移不广播 | 客户端不知道谁控制 |
| 子节点后加不设 authority | 该节点谁都能控（或没人能控） |
| 用本地时钟做跨端时间戳 | 时钟不同步 |
| 服务器跑 UI/相机 | 浪费资源，可能崩溃 |
| 客户端算伤害 | 改内存即可秒杀 |
| 断线靠下次 RPC 失败才发现 | 资源泄漏，应用 `peer_disconnected` |
| WebRTC 当 ENet 用 | 默认全网格，N² 连接 |
| 预测只存位置 | 无法回滚重放 |
