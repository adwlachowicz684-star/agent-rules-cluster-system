<!-- oversize-exempt: 反模式清单，审核用 -->
# devtools — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/devtools.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 调试代码上线前删掉 | 是**长期内部工具层** |
| 2 | 自定义参数随便加 | 要放 `--` 后用 `get_cmdline_user_args()` |
| 3 | `--headless` 等于完整运行 | 取决于**模板与平台** |
| 4 | 面板开销可忽略 | **它自己在消耗帧时间** |
| 5 | Performance 数字都是真的 | release **恒为 0**，部分有 1 秒延迟 |
| 6 | FPS 查得勤就细 | **每秒只更新一次** |
| 7 | 开无敌测出来的结果有效 | 要**持久视觉标识** |
| 8 | 作弊不用记录 | 要**审计日志**，否则 bug 复现不了 |
| 9 | 有官方 DebugDraw3D | **没有**，只有 Viewport Debug Draw |
| 10 | 旧 ImmediateGeometry 示例能用 | 4.x **API 与生命周期已变** |
| 11 | `@tool` 里可以随便操作场景树 | 官方：**无保护**，`queue_free`（→ `editor-plugin.md`） 会**崩溃** |
| 12 | 移除 tool 脚本后效果会复原 | 官方：编辑器内修改**是永久的** |
| 13 | `@tool` 代码只在编辑器跑 | 无 `is_editor_hint()` 包裹的部分**两边都跑** |
| 14 | `EditorScript` 已被移除 | 4.x **仍存在**，File>Run / Ctrl+Shift+X 执行 |
| 15 | `EditorScript` 的 print 会在 Output 面板 | 官方：输出到**启动编辑器的 stdout** |
| 16 | `EditorScript` 里 await 没问题 | 它是 **RefCounted**，异步中会被销毁 |
| 17 | `add_root_node()` / `get_scene()` 能用 | 4.x 均**已废弃**；`add_root_node` 曾标"实现被禁用" |
| 18 | 检视器插件不实现 `_can_handle` 也行 （→ `editor-plugin.md` 第 3 节）| 官方：**必须实现** |
| 19 | `EditorProperty` 有个按钮就行 | 缺 `_update_property` 或 `emit_changed`（→ `editor-plugin.md`） 都不完整 |
| 20 | 自定义属性控件自动能聚焦 | 要 `add_focusable()`（→ `editor-plugin.md`）；且需 `updating` 守卫防回环 |
| 21 | 插件脚本用 `instantiate()` | 官方示例用 `new()`（加载的是脚本非场景） |
| 22 | 编辑器改完资源会自动存盘 | **不会**，必须 `ResourceSaver.save()` |
| 23 | 批量改资源可以就地跑 | 改错无撤销，**必须先备份/版本控制** |
| 24 | 编辑器 API 引用不会影响导出 | `@tool` 脚本**会被导出**，需条件判断或 `#if TOOLS` |
| 25 | 禁用插件等于插件失效 | `_exit_tree` 不调 `remove_inspector_plugin` 仍生效 |（→ `editor-plugin.md` 第 3 节）（→ `editor-plugin.md` 第 3 节）
| 26 | 调试绘制可以留着 | 要 **Debug 构建门控** |
| 27 | 崩溃有报错就行 | **日志是唯一线索**，要兜底 |
| 28 | 跳关功能以后再说 | **决定迭代速度** |
| 29 | 调试面板显示裸数字 | 要显示**数据有效性** |
| 30 | 每个系统自己检测 headless | 要**分开渲染层与逻辑层** |
