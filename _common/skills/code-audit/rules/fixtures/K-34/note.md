# K-34 · 缺口补齐

对应判据条目：**K-34**

**tp**：`fs::metadata(p).unwrap()` 用在路径列表上——悬空 symlink、并发删除、
权限变更都会 panic，一个坏路径拖垮整批。
**fp**：`.ok()` / `filter_map` 有兜底。
