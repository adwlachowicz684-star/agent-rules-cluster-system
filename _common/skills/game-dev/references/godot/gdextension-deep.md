# GDExtension 实战（Godot 4.7.2）

能照着从零做出一个可发布的扩展。
概览（决策/ABI/热重载）见 `gdext-plugin.md`，本文讲**骨架与代码**。

## 0. 版本与组织

⚠ **godot-cpp 主干仍是 10.x Beta，未见 `4.7.2-stable` 专属 tag**。
推荐**固定一个与 4.7 API JSON 同步的 commit**，并显式 `api_version=4.7`，
**不要迷信最新 master**。

```python
# SConstruct 关键行
env = SConscript("godot-cpp/SConstruct", {"api_version": "4.7"})
```

⚠ **4.7 有两处 API 变化必须核对**：
`Object::is_class()` 参数变成 `StringName`；
旧的 `object_cast_to` / `classdb_get_class_tag` 已弃用。

**组织建议**：godot-cpp 放成 pinned submodule，
扩展目录与 Godot 项目分离，CI 把各平台产物汇集到 `addons/<name>/`。

## 1. `.gdextension` 清单

```ini
[configuration]
entry_symbol = "my_gdextension_library_init"
compatibility_minimum = "4.7"
reloadable = false          # 发布库建议关，避免重载顺序导致状态错误

[dependencies]
; 第三方 .dll/.so/.dylib 也写 res:// 路径，导出器才会自动包含
;windows.x86_64 = "res://addons/my_gdext/bin/minisat.windows.x86_64.dll"

[libraries]
linux.debug.x86_64 = "res://addons/my_gdext/bin/my_gdext.linux.debug.x86_64.so"
linux.release.x86_64 = "res://addons/my_gdext/bin/my_gdext.linux.release.x86_64.so"
windows.debug.x86_64 = "res://addons/my_gdext/bin/my_gdext.windows.debug.x86_64.dll"
windows.release.x86_64 = "res://addons/my_gdext/bin/my_gdext.windows.release.x86_64.dll"
macos.debug = "res://addons/my_gdext/bin/my_gdext.macos.debug.framework"
macos.release = "res://addons/my_gdext/bin/my_gdext.macos.release.framework"
android.release.arm64 = "res://addons/my_gdext/bin/my_gdext.android.release.arm64.so"
ios.release.arm64 = "res://addons/my_gdext/bin/my_gdext.ios.release.framework"
web.release.wasm32 = "res://addons/my_gdext/bin/my_gdext.web.release.wasm32.wasm"
```

⚠ **`entry_symbol` 是 C ABI 字符串，必须严格匹配** ——
有 `extern "C"` 与可见性属性，不能被 C++ name mangling 改变。
`.gdextension` 里的引号字符串、注册函数名、编译产物三者要一致。

⚠ **不要给不支持的平台留空行占位** —— 写了路径就必须有对应文件。

## 2. register_types（库入口）

```cpp
// src/register_types.cpp
#include "register_types.hpp"
#include "batch_drawer.hpp"
#include "godot_cpp/core/class_db.hpp"

using namespace godot;

void initialize_mygdext_module(ModuleInitializationLevel p_level) {
    // 只在场景层注册：Node、Resource、脚本类都在 SCENE 层可见
    if (p_level != MODULE_INITIALIZATION_LEVEL_SCENE) {
        return;
    }
    GDREGISTER_CLASS(BatchDrawer);
}

void uninitialize_mygdext_module(ModuleInitializationLevel p_level) {
    if (p_level != MODULE_INITIALIZATION_LEVEL_SCENE) {
        return;
    }
}

extern "C" {
GDExtensionBool GDE_EXPORT my_gdextension_library_init(
        GDExtensionInterfaceGetProcAddress p_get_proc_address,
        const GDExtensionClassLibraryPtr p_library,
        GDExtensionInitialization *r_initialization) {
    godot::GDExtensionBinding::InitObject init_obj(
            p_get_proc_address, p_library, r_initialization);
    init_obj.register_initializer(initialize_mygdext_module);
    init_obj.register_terminator(uninitialize_mygdext_module);
    init_obj.set_minimum_library_initialization_level(
            MODULE_INITIALIZATION_LEVEL_SCENE);
    return init_obj.init();
}
}
```

⚠ **不要为了"更早初始化"挪到 SERVERS/EDITOR** ——
顺序错会导致依赖未准备好。Node/Resource/脚本类都在 SCENE 层。

## 3. 最小可编译类

```cpp
// wave_config.hpp
#pragma once
#include "godot_cpp/classes/resource.hpp"
#include "godot_cpp/variant/typed_array.hpp"
namespace godot {
class WaveConfig : public Resource {
    GDCLASS(WaveConfig, Resource)
protected:
    static void _bind_methods();
private:
    int _count = 10;
    String _label;
public:
    int get_count() const { return _count; }
    void set_count(int p) { _count = p; emit_signal("changed"); }
};
}
```

```cpp
// wave_config.cpp
void WaveConfig::_bind_methods() {
    ClassDB::bind_method(D_METHOD("get_count"), &WaveConfig::get_count);
    ClassDB::bind_method(D_METHOD("set_count", "count"), &WaveConfig::set_count);
    ADD_PROPERTY(PropertyInfo(Variant::INT, "count"), "set_count", "get_count");
    ADD_SIGNAL(MethodInfo("changed"));
}
```

⚠ **`GDCLASS(MyType, Parent)` 不是普通继承声明** ——
真正继承仍由 `class WaveConfig : public godot::Resource` 完成。
宏的第一个参数是最派生类型，第二个是它在 Godot 类树里的**直接父类**。

## 4. 绑定 API 速查

| 要绑的东西 | 用法 |
|---|---|
| 方法 | `ClassDB::bind_method(D_METHOD("name", "arg"), &Class::method)` |
| 属性 | `ADD_PROPERTY(PropertyInfo(...), "setter", "getter")` |
| 带索引的属性 | `ADD_PROPERTYI(...)` |
| 信号 | `ADD_SIGNAL(MethodInfo("name", ...))`，C++ 侧 `emit_signal("name")` |
| 枚举/常量 | `BIND_ENUM_CONSTANT` / `BIND_CONSTANT` |
| RPC | `ClassDB::bind_method` 里标 `GODOT_METHOD_RPC_MODE_*` |

**PropertyHint 常用值**：范围、枚举、文件路径、资源类型、多行文本等，
决定 Inspector 里长什么样。

## 5. 类型系统与所有权

| Godot 侧 | C++ 侧 |
|---|---|
| `Variant` | `godot::Variant` |
| `String` / `StringName` | 各自对应类（注意 4.7 的 `StringName` 变化） |
| `Array[T]` | `TypedArray<T>` |
| `Dictionary` / `Packed*Array` | 对应类 |

⚠ **`Ref<T>` 与裸指针的边界**：
Node 走 `memnew` + 场景树生命周期；
**RefCounted 派生类必须放进 `Ref<T>`**。
用裸指针长期持有 RefCounted 是**最常见的悬空访问来源**。

⚠ **单例只适用于 Object/Node，不能放 RefCounted**。

## 6. 线程安全

⚠ **`callable_mp` 不是线程通行证** ——
它只解决"怎么安全地把调用排到主线程"，不代表你可以从任意线程改场景树。

从非主线程改引擎状态必须 `call_deferred` 排回主线程。

## 7. 编译与排错

```bash
scons platform=linux target=template_release -j8
```

⚠ **编辑器里加载失败的排查顺序**：
1. `entry_symbol` 是否严格匹配
2. `compatibility_minimum` 是否 ≤ 引擎版本
3. 各平台库路径是否真的存在
4. 依赖的第三方库是否在 `[dependencies]` 里声明

⚠ **C++ 输出到 Godot 控制台**用 `UtilityFunctions::print()`。

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/gdextension-deep.md`


## 8. 相关文档

- 决策树 / ABI / 热重载 → `gdext-plugin.md`
- 编辑器插件 → `editor-plugin.md`
- 多平台构建与导出 → `platform-export.md`
- C#/.NET → `csharp.md`
- 版本差异 → `version-47-48.md`
