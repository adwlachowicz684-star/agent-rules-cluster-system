# APP-R11

文件读取无路径约束（可越权读取）。

- `tp.rs` —— **必须命中**：`pub fn` 对外命令，`fs::read_to_string(p)` 的 `p` 直接来自 IPC，
  整个函数体无 `resolve_within` / `canonicalize` / `starts_with`
- `fp.rs` —— **必须不命中**：同样读外部传入的 path，但先经 `resolve_within` 收敛到授权根内

**来源**：2026-09-14 nexus-panel 第三轮。由另一份审查报告指出：
`fs_op` 建了 `resolve_within` + 授权根目录的完整模型，但只覆盖 `fs_op` 一个命令；
旁边的 `fpx_read_file` → `fpx/content.rs::read_preview` 直接 `fs::read_to_string(p)`，
能读任意文本文件（`invoke('fpx_read_file', {path:'~/.ssh/id_rsa'})`）。

**已知精度**：规则只看"上下文有没有路径约束"，无法判断调用方是否已保证安全。
实测 nexus-panel 命中 5 处，其中 2 处为私有工具函数（`fn read_head` / `fn read_json`）
属误报 —— 需人工确认是否为内部函数。
