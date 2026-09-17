# APP-G12 · 缺口补齐

对应判据条目：**G-12**（构建不可复现）

**tp**：`:latest` 未固定，同一份源码两次构建产物不同，无法回滚定位。
**fp**：用 digest 固定。

---
# APP-G12

Dockerfile / compose 里基础镜像用 latest 或无标签 → 构建不可复现，上游一变结果就变。
固定到具体版本（含 digest）则不算；`$VAR` 变量引用无法静态判断，跳过。

- `tp.d/` —— **必须命中**（node:latest）
- `fp.d/` —— **必须不命中**（node:20.11.1-alpine）
