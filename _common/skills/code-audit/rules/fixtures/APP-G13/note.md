# APP-G10

构建配置里 sourcemap / minify 写成字面量常量 → 不随 profile 变化，生产包可能带 sourcemap。
用 `mode === ...` 三元或 isProd 判断则不算（作者已处理 profile 差异）。

- `tp.d/` —— **必须命中**（字面量 true）
- `fp.d/` —— **必须不命中**（按 mode 判断）
