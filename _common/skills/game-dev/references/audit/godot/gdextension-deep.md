<!-- oversize-exempt: 反模式清单，审核用 -->
# gdextension-deep — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/gdextension-deep.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | godot-cpp 用最新 master | 是 Beta，要 pin 到 4.7 同步的 commit |
| 2 | 4.7.2 有专属 tag | 未见，**固定 commit + api_version=4.7** |
| 3 | `GDCLASS` 就是继承 | 真正继承靠 C++ 类声明，宏只做注册 |
| 4 | 初始化层级随便选 | Node/Resource 都在 **SCENE** 层 |
| 5 | RefCounted 能用裸指针持有 | **必须 `Ref<T>`**，否则悬空 |
| 6 | 单例什么都能放 | **不能放 RefCounted** |
| 7 | `callable_mp` 能跨线程改场景 | 只排到主线程，不代表线程安全 |
| 8 | entry_symbol 差不多就行 | C ABI 字符串，**严格匹配** |
| 9 | 不支持的平台留空行 | 写了路径就必须有文件 |
| 10 | 4.7 的 is_class 用法照旧 | 参数变 `StringName` |
| 11 | `object_cast_to` 还能用 | 已弃用 |
| 12 | 依赖的 dylib 自动打包 | 要在 `[dependencies]` 声明 |
| 13 | reloadable=true 方便调试就留着 | 发布库建议**关** |
| 14 | 编译产物放哪都行 | CI 汇集到 `addons/<name>/` |
| 15 | 旧版扩展能用在新版 | **反向通常不行** |
