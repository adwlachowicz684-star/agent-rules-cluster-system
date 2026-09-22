# RS-02 · Rust 语言包

对应判据条目：**RS-02**

**tp**：`as u32` 窄化，高位静默截断；release 下**不 panic**，debug 下才 panic
（正好掩盖问题）。
**fp**：`try_from` 显式处理溢出。
