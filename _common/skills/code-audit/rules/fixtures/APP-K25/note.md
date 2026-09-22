# APP-K25 · 缺口补齐

对应判据条目：**K-25**（命令未在 invoke_handler 注册）

**tp**：定义了命令但 invoke_handler 里没有 → 前端调用必然失败（死代码）。
**fp**：已注册。
