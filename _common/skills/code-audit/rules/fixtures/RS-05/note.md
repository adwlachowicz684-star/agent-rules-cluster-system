# RS-05 · Rust 语言包

对应判据条目：**RS-05**

**tp**：命令入参直接进 `fs::read_to_string`，无 canonicalize / starts_with → 路径穿越。
**fp**：canonicalize 后与根目录比对。
