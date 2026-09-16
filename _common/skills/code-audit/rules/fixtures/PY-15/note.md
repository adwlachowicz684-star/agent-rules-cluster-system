# PY-15 subprocess 输入方向缺编码容错

- **TP 必须命中**：`subprocess.run(..., text=True)` 且有 `input=`，但无 `errors=`
- **TP2 必须命中**：同一文件里输出方向已修、输入方向漏（最易误判为已修）
- **FP 必须不命中**：传 bytes，或双端显式 `errors=`；无 `input=` 参数的不算

实测来源：某推送工具 L470 的 `git()` 正确写了 `errors="surrogateescape"`，
甚至配注释警告「只修输出不修输入，崩溃只是换个地方（实测）」；
而 L512 `local_blob_sha()` 的 `input=os.readlink(full)` 恰恰漏在输入方向
→ symlink 目标含 `\xff` 时实测抛 `UnicodeEncodeError`。
