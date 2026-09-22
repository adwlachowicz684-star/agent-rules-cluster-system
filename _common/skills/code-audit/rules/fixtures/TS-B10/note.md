# TS-B10 · 缺口补齐

对应判据条目：**B-10**

**tp**：`curl -s` 未配 `-f`/`-w`，HTTP 4xx/5xx 的 body 照样流进管道；
`'sha' in resp` 用字段存在性代替状态码。
**fp**：配了 `-f`（错误即非 0 退出）；`resp.ok && resp.status` 直接看状态码。
