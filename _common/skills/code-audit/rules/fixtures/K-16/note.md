# K-16 · 缺口补齐

对应判据条目：**K-16**

**tp**：Tcp 连接不设读写超时，对端慢速不发包即可永久占住连接。
**fp**：设了 `set_read_timeout` / `set_write_timeout`。
