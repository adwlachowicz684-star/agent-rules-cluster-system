# RS-04 · Rust 语言包

对应判据条目：**RS-04**

**tp**：`.lock().unwrap()` 是 **std** 的锁（返回 Result），守卫跨 `.await` → 死锁。
**fp**：tokio 锁的 `.lock().await` 本身就是为跨 await 设计的。
注意：判据认的是 `.lock()` 后跟 `.unwrap()`，不是找 `tokio` 字样——
真实代码里类型名常是别名，文本里没有 tokio 三个字。
