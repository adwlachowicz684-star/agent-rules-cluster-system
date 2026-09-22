# RS-01 · Rust 语言包

对应判据条目：**RS-01**

**tp**：`#[tauri::command]` 里 `.unwrap()` —— panic 被翻译成前端的模糊错误，
真正的路径/权限原因丢失。
**fp**：把错误转成 `Result` 往上传。
