# K-03 · 缺口补齐

对应判据条目：**K-03**

**tp**：黑名单只按文件名比较，未经 `canonicalize`，`../` 可绕过。
**fp**：先 `canonicalize` 再 `starts_with(root)`，路径穿越被挡住。
