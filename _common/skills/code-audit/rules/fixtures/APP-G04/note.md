# APP-G04

有 package.json（或 Cargo.toml / requirements.txt / go.mod）但缺对应 lock 文件 → 依赖版本不可复现。
有 lock 文件则不算。

项目级规则：`tp.d/` / `fp.d/` 内容原样铺到扫描根。

- `tp.d/` —— **必须命中**（有声明无 lock）
- `fp.d/` —— **必须不命中**（有 lock）
