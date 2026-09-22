# APP-G05 · 缺口补齐

对应判据条目：**G-05**（占位资源未替换）

**tp**：identifier 仍是 `com.example.*` 脚手架默认。
**fp**：已改正式标识。

---
# APP-G05

配置/清单文件里仍是脚手架占位值（com.example.* / your-app / CHANGE_ME）→ 会随包发布。
换成真实标识则不算。只查配置文件，源码里的 example 是正常标识符，不报。

- `tp.d/` —— **必须命中**（com.example.*）
- `fp.d/` —— **必须不命中**（真实包名）
