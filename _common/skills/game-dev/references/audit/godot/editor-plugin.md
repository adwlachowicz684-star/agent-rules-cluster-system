<!-- oversize-exempt: 反模式清单，审核用 -->
# editor-plugin — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/editor-plugin.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | `@tool` 是启用编辑器 UI | 是允许脚本**在编辑器进程运行** |
| 2 | 被 tool 脚本用的类不用加 | **也必须是 tool**，否则无法构造 |
| 3 | `is_editor_hint()` = 正在跑游戏 | 只表示编辑器进程，用 `has_feature("editor")` 区分 |
| 4 | `_ready()` 只调用一次 | 复制/撤销/资源持有都会重进 |
| 5 | 编辑器是沙箱 | 副作用会**真的写 .tscn/.tres** |
| 6 | setter 里 queue_free 没事 | 编辑器随后访问已释放对象 → **崩溃** |
| 7 | 隐藏 dock 就算注销 | 要**断开注册**，否则悬空回调 |
| 8 | 自己 new UndoRedo | 要用 `get_undo_redo()`，按对象选历史 |
| 9 | 首个 do 随便写 | 决定历史归属，写错**撤销顺序错乱** |
| 10 | 新建节点不用 reference | 要 `add_do_reference()` |
| 11 | `add_do_reference` 也能管资源 | 它是"历史丢弃时删除"语义 |
| 12 | 改了导入器会自动重导 | 要改 format_version 或清缓存 |
| 13 | importer_name 随便起 | 必须**全局唯一且稳定** |
| 14 | 4.x dock API 照旧 | 4.7 统一到 `EditorDock`，旧的已弃用 |
| 15 | 插件不用接 UndoRedo | 不接 = 用户无法撤销 = 不可发布 |
