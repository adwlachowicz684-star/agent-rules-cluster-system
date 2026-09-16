# APP-G12

Dockerfile / compose 里基础镜像用 latest 或无标签 → 构建不可复现，上游一变结果就变。
固定到具体版本（含 digest）则不算；`$VAR` 变量引用无法静态判断，跳过。

- `tp.d/` —— **必须命中**（node:latest）
- `fp.d/` —— **必须不命中**（node:20.11.1-alpine）
