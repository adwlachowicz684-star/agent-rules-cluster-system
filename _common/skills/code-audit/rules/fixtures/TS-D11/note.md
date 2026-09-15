# TS-D11 · 缺口补齐

对应判据条目：**D-11**

**tp**：`Map<string, Set<string>>` 直接 `delete(key)`，内部 Set 未清——
若别处持有该 Set（如正在遍历的快照），内容不会随外层删除释放。
**fp**：先 `get(key)?.clear()` 再 `delete`。
