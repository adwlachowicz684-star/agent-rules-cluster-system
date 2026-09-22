<!-- oversize-exempt: 引擎 API 查表文档，按 API 索引，需整体查阅 -->
# Godot 4.x 语言层与工程层 API 级审查判据

## 摘要
本包只覆盖 GDScript 语言层、项目与导出配置、调试测试，以及场景树与节点通用层；不重复物理、UI、IO、动画、3D 已有审查。审查以「成员级签名—误用模式—静态判据—运行时确认」为主轴：优先使用静态类型、`get_node_or_null()`/场景唯一名称、一次性连接与 `queue_free()`；对 `Array`/`Dictionary` 默认按共享引用审查，复制时显式区分浅/深拷贝；对 `await` 审查对象生命周期和信号是否真的会发射。官方明确指出 `Array`、`Dictionary`、Object、Node、Resource 及 packed array 按引用共享，基础类型按值传递[1]。

工程侧，`ProjectSettings` 的键是完整路径字符串，运行时 `set_setting()` 未必等价于导出键；`application/config/name`、`main_scene`、`rendering/renderer/rendering_method` 与输入映射都应作为资产基线。调试器指标有模式差异：`MEMORY_STATIC`、`MEMORY_MESSAGE_BUFFER_MAX` 在 release 中不可用，部分指标最多延迟 1 秒[4]。本任务范围内建议设 8 类红线、17 类警告；最重要的可机审目标包括裸 `get_node()`、裸 `connect()`、`await` 后直接信任对象、同 `Callable` 重复连接、`free()` 同步释放、未判断返回值的资源加载与场景切换、`duplicate()` 默认浅拷贝。

## 1. 审查包定位与判据口径

**本包负责“语言与工程边界”，不替既有模块判断表现层对错。** 既有的物理/UI/IO/动画/3D 审查通常从节点功能与调用结果入手；本包把同一段 `.gd/.cs` 重新切成四条链：一是 GDScript 编译期/静态分析可识别的风险，二是配置和资源生命周期，三是调试与测试可观察性，四是节点进入/离开树、暂停、释放产生的状态风险。这样可以避免重复“是否调用了正确的物理 API”，而集中回答“调用是否类型安全、生命周期正确、配置可复现、失败可观测”。

判据分两级。**红线**是若误用，生产运行大概率产生崩溃、数据竞争、泄漏、悬空引用或功能失效，应在合并前阻断；**警告**是可读性、维护性或存在更安全的替代，可走代码评审与豁免。`判据` 列的意图是给出可用单文件正则，而不要求穷尽 C# 与 GDScript 语法；`.gd` 优先匹配 GDScript，`.cs` 再补 `GetTree()`、`QueueFree()`、`GetNode<T>()`、`Connect()`、`EmitSignal()` 等。所有正则都应允许前后空白与参数变化，不建议用正则判定类型语义，复杂情况交给 Godot 编辑器静态分析、gdlint、单元测试或自定义 AST 扫描。

**`确认` 以可复现运行代替肉眼读代码。** 一份 `.gd` 通过静态扫描只能证明“写了什么”，不能证明“运行时对象仍有效、信号确实发射、拷贝是否深、pause 模式是否符合预期”。因此本包的确认动作统一为：在编辑器内执行一次真实场景路径；导出 debug 与 release 两个模板；以 Performance 计数器和场景树快照检查对象与孤儿节点；用节点退出树、信号不发射、资源加载失败三类对抗用例验证。对于 release 行为，不能用编辑器“Run”替代导出构建。

## 2. GDScript 语言特性审查表

**静态类型是默认首选，类型注解只消除部分歧义，不保证元素级运行时安全。** `var x: int`、`:=`、函数参数与返回类型都应视作基线要求；对于公开 API、跨场景脚本、资源保存字段，缺失类型时至少产生警告。`Array[Type]` 从 4.0 起可用；`Dictionary[K,V]` 从 4.4 起可用。类型化数组允许元素类型校验、循环变量推断与部分操作检查；类型化字典的读写会校验键值类型，但字典方法返回值仍是 `Variant`，因此“声明为类型化”不能推出所有方法链都返回类型化结果。嵌套类型化集合仍是审查重点：官方明确不支持 `Array[Array[int]]` 和 `Dictionary[String, Dictionary[String, int]]`；若需求天然嵌套，应定义具名包装类或统一转换成 `Array`/`Dictionary` 后加强运行时不变量检查。

![类型化 Array 与 Dictionary 支持边界](/data/workspace/dr-godot-lang/fig_typed_containers.png)
*图 1：类型化 `Array` 与 `Dictionary` 在 4.4 可用，嵌套类型化容器仍不可用。数据来源：Static typing in GDScript（4.2/4.4）[1]*

### `var x: int`
- **签名**：`var x: int = 0` / `int x = 0;`
- **用途**：限定变量类型，供编辑器、静态检查和调用约定使用。
- **误用**：写成 `var x = 0` 虽可推断为 `int`，但跨函数边界与导出字段的类型意图不够明确；把 Variant 资源字段写成无类型，会使重构难以定位。
- **判据**：`var\s+\w+\s*=(?!=)` 且无后续 `:\s*\w+`；公开函数参数/返回值无 `:` 或 `->`。
- **确认**：编辑器静态检查无 `UNTYPED_DECLARATION`；调用处出现类型错误时编辑器报错。
- **置信度**：官方明确。

### `var x := value`
- **签名**：`var v := Vector2()` / `var v = Vector2();`
- **用途**：按初始化值推断变量类型。
- **误用**：值本身为 `null`/无类型资源或返回 `Variant` 时推断失效；`Variant` 推断默认可能触发警告或错误。
- **判据**：`var\s+\w+\s*:=`，随后检查右值是否为字面量、`new()`、强返回类型函数或 `preload()`。
- **确认**：将鼠标悬停变量查看推断类型；对返回 `Variant` 的字典/资源接口显式补类型。
- **置信度**：官方明确。

### `Array[Type]` / `Array` 类型化数组
- **签名**：`var scores: Array[int] = [1, 2, 3]` / `Godot.Collections.Array<int> scores = ...`
- **用途**：约束同质元素、循环变量和赋值。
- **误用**：把异构配置硬塞进 `Array[int]`；期望 `push_back()` 等方法也强类型；使用 `Array[Array[int]]`。
- **判据**：`Array\[[A-Za-z0-9_]+\]`；出现两个以上嵌套 `[` 时提升为红线。
- **确认**：故意插入错误类型，验证编辑器报错；打印 `typeof(arr[0])`。
- **置信度**：官方明确。

### `Dictionary[K,V]` 类型化字典
- **签名**：`var costs: Dictionary[String, int] = {}` / `Godot.Collections.Dictionary<string, int>`
- **用途**：约束键值类型，减少 `Variant` 转型错误。
- **误用**：误以为 `.keys()`、`.values()` 或索引器返回值都自动是目标类型；写 `Dictionary[String, Dictionary[String, int]]`。
- **判据**：`Dictionary\[[A-Za-z0-9_]+,\s*[A-Za-z0-9_]+\]`；两个逗号或三层嵌套 `[` 判红线。
- **确认**：尝试插入错误键/值，检查编辑器与运行时提示。
- **置信度**：官方明确（4.4+）。

### `Callable` / `Signal`
- **签名**：`var cb: Callable = $Node.method`；`signal died` / `Signal died`
- **用途**：把方法或信号作为一等值传递。
- **误用**：`Callable` 绑定的对象已释放后仍保存；把信号名字符串化，失去重构与类型检查。
- **判据**：`var\s+\w+\s*:\s*Callable`；出现 `Callable.From(`；跨脚本传字符串信号名。
- **确认**：对来源节点用 `is_instance_valid()`；`cb.is_valid()`/`is_null()` 检查；用 `bind()` 后打印 bound arguments。
- **置信度**：官方明确。

### `Variant`
- **签名**：`var v: Variant` / `Variant v;`
- **用途**：作为真正需要运行时多态的边界类型。
- **误用**：默认把资源、节点、字典值声明为 `Variant`，从而失去静态检查；把 `Variant` 当作普通类型使用类型推断。
- **判据**：`:\s*Variant\b` 或 `Variant\s+\w+`；资源/节点/数值字段缺少具体类型。
- **确认**：统计 `Variant` 字段占比，逐处说明为何不能收窄；编辑器检查相关警告。
- **置信度**：官方明确。

### `as` / `is`
- **签名**：`var node = body as Player`；`if body is Enemy:` / `body as Player`
- **用途**：缩小类型并做运行时判断。
- **误用**：转型失败时 `as` 返回 `null`，后续不空检查；`is` 检查后未本地化窄类型。
- **判据**：`\bas\b(?!h)` 且左侧非变量声明；`\bis\b`；后两行内无 `if ... is`/`if ...:` 的 null 分支。
- **确认**：对错误类型资源做失败用例，确认返回 `null` 而非异常。
- **置信度**：官方明确。

### `class_name` / `extends` / `inner class` / `enum` / `const`
- **签名**：`class_name Rifle extends Node2D`；`class Inner`；`enum Dir {LEFT, RIGHT}`；`const MAX = 10`
- **用途**：注册全局类型、复用继承、封装有限枚举和编译期常量。
- **误用**：跨脚本依赖未用 `class_name` 的脚本；循环 `class_name` 依赖；`const` 引用可变引用类型后误当“深不可变”。
- **判据**：`^class_name\s+\w+`；`extends\s+\w+`；`class\s+\w+`；`enum\s+\w+`; `const\s+\w+\s*=`。
- **确认**：检查类图标仅在 `class_name` 后生效；重构类名后全局搜索是否断裂。
- **置信度**：官方明确。

**容器与字符串的审查核心是“共享引用 vs 值语义”，不是表面写法。** `Array`、`Dictionary`、Object、Node、Resource 和 packed array 在赋值时共享；基础类型按值复制[1]。这决定了缓存、配置初始化、技能数据、存档、撤销/重做、关卡生成都会产生跨状态污染。`Dictionary.duplicate()` 默认浅拷贝，深拷贝需要 `duplicate(true)`；`Array` 同理。但深拷贝不能越过对象边界：共享 `Node`、共享资源、包含原生对象或跨线程对象时，仍需按业务定义“深”的语义。

### `Array`/`Dictionary` 引用语义
- **签名**：`var a = [1]; var b = a; b[0] = 2` / `var b = a;`
- **用途**：避免大量值拷贝，共享可变数据。
- **误用**：把默认值、模板配置、临时筛选结果当作独立副本；在函数中修改“入参副本”。
- **判据**：`var\s+\w+\s*=\s*\w+(?:\.|\[)` 指向数组/字典；函数参数无 `const`/不可变设计而直接写入；初始化默认值用可变容器字面量。
- **确认**：写 `a==b`、对象 ID/引用检查；对配置模板执行 `a.duplicate()` 后改 `a`，验证 `b` 不变。
- **置信度**：官方明确。

### `Array.duplicate()` / `Dictionary.duplicate(deep)`
- **签名**：`arr.duplicate()`；`arr.duplicate(true)`；`dict.duplicate()`；`dict.duplicate(true)` / `.Duplicate()`
- **用途**：制作浅拷贝或递归深拷贝。
- **误用**：默认 `duplicate()` 不复制嵌套容器元素；`duplicate(true)` 也不能定义自定义资源/节点的业务深克隆。
- **判据**：`\.duplicate\s*\(`；默认浅拷贝处若有嵌套容器则警告；资源类有循环引用时深拷贝也可能不合法。
- **确认**：对比 `duplicate()` 与 `duplicate(true)` 对二级 `Array`/`Dictionary` 的共享情况；检查递归深度与性能。
- **置信度**：官方明确。

### `String % value(s)` 格式化
- **签名**：`"HP: %d" % hp`；`"pos: %s" % [x, y]` / `string.Format`
- **用途**：插值构造日志、UI 文本和资源路径。
- **误用**：类型占位符与实参不一致；多个参数不放在数组里；本地化后占位顺序变化却仍按位置。
- **判据**：`"[^"]*%[diouxXeEfFgGs%][^"]*"\s*%`；本地化字符串仍硬编码中文格式串。
- **确认**：测试负数、小数、0、`null`、超长字符串；逐语言验证。
- **置信度**：官方明确。

### `StringName` / `str()` / `String.num()`
- **签名**：`&"my_group"`；`str(value)`；`"%.2f" % value` 或 `String.num(x,2)` / `StringName("...")`
- **用途**：用 `StringName` 做比较/通知/组名快路径；用 `str()` 调试；用 `String.num()` 控制数值展示。
- **误用**：每次帧循环把动态字符串转 `StringName`，抵消内部驻留优势；本地化数字直接拼接。
- **判据**：`&"[A-Za-z0-9_]+"`；高频 `_process` 中 `StringName(`；`str(` 留在发布逻辑而非仅日志。
- **确认**：用 Profiler 比较字符串与 `StringName` 热路径；本地化数字对照语言设置。
- **置信度**：官方明确。

### `preload()` / `load()`
- **签名**：`const Bullet = preload("res://bullet.tscn")`；`load(path)` / `ResourceLoader.Load`
- **用途**：解析期加载常量资源；运行期按路径/变量加载资源。
- **误用**：`preload()` 使用非常量路径；`load()` 返回 `null` 后不判断；在编辑器中用 `load()` 误触发资源导入/IO。
- **判据**：`preload\s*\([^"]*[^A-Za-z0-9_/]+\s*`；`load\s*\([^)]*\)(?!\s*\?)`；`ResourceLoader\.Load\(`
- **确认**：路径不存在、文件被删除、类型错误三种失败；检查主场景启动耗时与内存峰值。
- **置信度**：官方明确。

## 3. 注解、信号与协程审查表

**注解是编辑器契约，不只是显示美化。** `@export` 决定数据持久化和 Inspector 可用性；`@onready` 决定初始化时机；`@tool` 决定脚本是否在编辑器中执行；`@rpc` 决定网络调用语义。审查时不能只看“有没有写”，还要看参数默认值、与生命周期交互、是否被错误忽略警告。尤其是导出资源/节点，若自定义类型未通过 `class_name` 注册为全局类，Inspector 支持会退化。

### `@export` 系列
- **签名**：`@export var hp: int = 10`；`@Export] int hp = 10;`；`@export_range(0,100)`、`@export_enum`、`@export_file`、`@export_dir`、`@export_global_file`、`@export_node_path`、`@export_multiline`、`@export_color_no_alpha`、`@export_flags_*`、`@export_category/group/subgroup`
- **用途**：将字段暴露到 Inspector 与场景文件。
- **误用**：编辑器路径未用 `res://`/绝对路径校验；导出 Node 但未使用 `class_name`；导出可变数组/字典后误保存共享模板；flag 位掩码与 enum 语义混淆。
- **判据**：`@export(_[a-z_]*)?\s*(?:\([^)]*\))?\s*var`；随后检查是否缺类型、缺范围/文件路径约束。
- **确认**：切换 debug/release、移动资源文件、打开 `.tscn`，验证路径重写与默认值持久化；导出位字段逐一勾选。
- **置信度**：官方明确。

### `@onready`
- **签名**：`@onready var label: Label = $Label` / `[OnReady] private Label _label;`
- **用途**：在节点 ready 前完成对场景子节点的引用。
- **误用**：节点尚未进树时访问；`_init()` 中使用；与 `@export` 混用导致导出值被默认赋值覆盖。
- **判据**：`@onready\s+var\s+\w+\s*=\s*(?:\$|\%|get_node|%)`；构造函数/`_init` 访问 `@onready` 成员。
- **确认**：打印赋值、场景实例化和导出的先后顺序；用 `is_node_ready()` 检查访问时机。
- **置信度**：官方明确。

### `@tool`
- **签名**：`@tool extends Node` / `[Tool]`
- **用途**：允许脚本在编辑器内运行。
- **误用**：编辑器脚本执行耗时操作、弹系统对话框、创建/删除资源、假定场景在运行时树中；发布后仍依赖 `@tool` 副作用。
- **判据**：`@tool\s*$` 且在类定义前；脚本内调用 `OS.alert()`、文件写入、网络、阻塞等待。
- **确认**：以 `--headless` 编辑器导入项目；检查资源目录未被工具脚本污染；`Engine.is_editor_hint()` 分支覆盖。
- **置信度**：官方明确。

### `@icon`
- **签名**：`@icon("res://icon.svg")` / `[Icon("res://icon.svg")]`
- **用途**：为使用 `class_name` 注册的脚本设置节点图标。
- **误用**：图标路径运行时才确定；将图标放在 `@onready`/`const` 非字面量位置；内部类套用脚本图标。
- **判据**：`@icon\s*\(`；路径非字符串字面量。
- **确认**：在项目设置/场景树检查图标；移动 SVG 后验证资源 UID 与路径。
- **置信度**：官方明确。

### `@warning_ignore`
- **签名**：`@warning_ignore("unreachable_code")` / `[Warning("ignore:...")]`
- **用途**：显式抑制明确且有理由的警告。
- **误用**：用裸注释“以后再说”；一次忽略多个无关警告；错误码写错、版本升级后已不适用；`return` 后仍有代码。
- **判据**：`@warning_ignore\s*\(`；同注释区域没有说明原因；`return|break|continue|throw` 后仍有可执行语句。
- **确认**：删除注解后跑一次静态检查，确认目标警告确实复现。
- **置信度**：官方明确。

### `@rpc(mode, sync, transfer_mode, channel)`
- **签名**：`@rpc("any_peer","unreliable_ordered")` / `[Rpc(MultiplayerApi.RpcMode.AnyPeer, ...)]`
- **用途**：声明远程过程调用。
- **误用**：默认 `"authority"` 与预期权限相反；把状态变更写进不可靠 RPC 且不幂等；`call_local` 产生本地/远程双执行；通道超过实现限制；把 RPC 当作信号广播而不做鉴权。
- **判据**：`@rpc\s*\(`；其后参数组合；权威校验函数未调用 `get_multiplayer_authority()`。
- **确认**：双端抓包/打印来源 peer；断线重连、乱序、重复包、权限切换测试。
- **置信度**：官方明确。

### `signal name(args)`
- **签名**：`signal health_changed(old_hp, new_hp)` / `[Signal] delegate void HealthChangedEventHandler(int oldHp, int newHp);`
- **用途**：声明对象事件及参数。
- **误用**：声明参数却 `emit()` 不传；参数顺序在重构后错位；信号名与已有属性/方法冲突。
- **判据**：`^\s*signal\s+\w+(\([^)]*\))?`；`emit()` 实参与声明参数个数不一致。
- **确认**：连接前后打印 `get_connections()`；用错误类型参数发射。
- **置信度**：官方明确。

### `Signal.emit()` / `emit_signal()`
- **签名**：`health_changed.emit(old, new)`；4.x 不再推荐 `emit_signal("health_changed", old, new)` / `EmitSignal("health_changed", ...)`
- **用途**：类型安全、可读性更高的发射方式。
- **误用**：仍用字符串 `emit_signal()` 丢失信号名检查；参数不匹配；编辑器内对大量节点每帧发射。
- **判据**：`emit_signal\s*\(` 与 `\.emit\s*\(`；字符串信号名；同帧热点路径高频发射。
- **确认**：重命名信号，验证旧字符串调用是否报错；Profiler 测热点。
- **置信度**：官方明确（4.x 推荐 `.emit()`）。

### `connect()` / `disconnect()` / `is_connected()`
- **签名**：`pressed.connect(_on_pressed)`；`pressed.disconnect(_on_pressed)`；`pressed.is_connected(_on_pressed)` / `Connect`
- **用途**：连接、断开和查询信号回调。
- **误用**：重复连接同一 `Callable` 报 `ERR_INVALID_PARAMETER`；断开不存在连接报错；动态生成 `Callable` 无法匹配旧连接；`Object.CONNECT_REFERENCE_COUNTED` 的特殊语义未记录。
- **判据**：`\.connect\s*\(`；没有 `CONNECT_ONE_SHOT`/`CONNECT_DEFERRED` 时使用相同 lambda；`disconnect(` 前未 `is_connected(`；`Callable` 绑定后无身份说明。
- **确认**：第二次连接同一回调应报错；退出树前只断开自有连接；测试引用计数连接的对称连接/断开。
- **置信度**：官方明确。

### `CONNECT_ONE_SHOT` / `CONNECT_DEFERRED` / `CONNECT_PERSIST`
- **签名**：`area_entered.connect(_on_hit, CONNECT_ONE_SHOT)` / `ConnectFlags.OneShot`
- **用途**：一次性、延迟到帧末、跨场景保存连接。
- **误用**：一次性连接被隐式复用；延迟连接中对象已释放；`PERSIST` 连接跨场景造成生命周期泄漏；连接执行顺序依赖帧末队列。
- **判据**：`CONNECT_ONE_SHOT|CONNECT_DEFERRED|CONNECT_PERSIST`；`_deferred` 回调内未检查对象有效性。
- **确认**：连接触发一次后再次发射信号；释放对象后再验证是否报错；检查场景重入。
- **置信度**：官方明确。

**协程的首要风险是“永远挂起”，而不是语法错误。** `await signal` 会挂起当前函数并将控制权返回调用者；如果被等待的对象释放、条件分支不发射信号、场景切换打断流程，后续清理和 return 值都不会执行。调用协程却不 `await` 时，函数不会在此处挂起，而是异步继续；试图立即取返回值时会产生错误[1]。因此应审查“等待对象生命周期”“信号发射覆盖”“超时与取消”“调用者是否真的需要结果”四项。

### `await signal`
- **签名**：`await button.pressed` / `await button.Pressed;`
- **用途**：在信号到来前暂停协程。
- **误用**：等待的对象在信号发射前被 `queue_free()`；等待可能永不发射的内部信号；协程后的状态机未取消。
- **判据**：`await\s+\w+(\.\w+)?`；没有超时、取消令牌、对象有效性检查或备选完成条件。
- **确认**：手动释放对象、跳过发射、超时，验证协程是否泄漏/是否永远不恢复。
- **置信度**：社区共识；官方明确 `await` 行为[1]。

### `await get_tree().process_frame`
- **签名**：`await get_tree().process_frame` / `await GetTree().ProcessFrame;`
- **用途**：推迟到下一渲染帧处理，常用于下一帧布局、动画、场景切换。
- **误用**：审查只停留在 `await`，未考虑当前节点已经退出树；依赖“下一帧所有子系统都准备好”，但各帧回调顺序只有引擎保证。
- **判据**：`await\s+get_tree\(\)\.process_frame`；节点/场景切换后立即依赖新树状态。
- **确认**：在切换场景中比较 `process_frame` 与 `_process` 的执行顺序；编辑器与导出版都跑。
- **置信度**：官方明确。

### `await get_tree().create_timer(x).timeout`
- **签名**：`await get_tree().create_timer(1.0).timeout` / `await GetTree().CreateTimer(1.0).Timeout;`
- **用途**：非阻塞延时，避免自写计时变量。
- **误用**：不保存 `SceneTreeTimer` 引用导致无法提前取消；暂停期间定时器按 `process_always` 继续；4.3+ 忽略 `time_scale` 的新参数误用于老版本。
- **判据**：`create_timer\s*\(([^)]*)\)\.timeout`；未保存 timer；未设置 `process_in_physics`/`ignore_time_scale` 却依赖行为。
- **确认**：暂停、改变 `Engine.time_scale`、提前释放 owner 时分别验证。
- **置信度**：官方明确。

![create_timer 参数版本变化](/data/workspace/dr-godot-lang/fig_create_timer_version.png)
*图 2：`create_timer()` 在 4.3 新增 `process_in_physics` 与 `ignore_time_scale`，旧版本只接受两个位置参数。数据来源：SceneTree 4.x 类参考[5]*

### `await coroutine`
- **签名**：`var r = await do_async()` / `var r = await DoAsync();`
- **用途**：等待另一个协程完成并接收结果。
- **误用**：被调用函数不是协程却写 `await`；单参数返回单个值、多参数返回 `Array`，调用方误判类型；不 `await` 而直接当结果使用。
- **判据**：`await\s+\w+\s*\(`；没有对返回类型/参数数量的处理；需要结果处无 `await`。
- **确认**：用一个、多个、零个信号参数发射，检查协程返回形式。
- **置信度**：官方明确。

### `await` 期间节点释放竞态
- **签名**：协程中 `await enemy.died` / `await enemy.Died;`
- **用途**：等待对象事件后推进逻辑。
- **误用**：敌人被另一系统 `queue_free()`，协程不再恢复；节点重入 `_ready()` 时旧协程仍持有旧字段引用。
- **判据**：跨系统 `queue_free()` 与 `await obj.signal` 共存；协程没有 `tree_exiting`/`NOTIFICATION_EXIT_TREE` 取消路径。
- **确认**：在发射前释放对象，检查协程是否永久挂起；用对象 ID 与弱引用设计替代方案。
- **置信度**：社区共识；与官方对象释放/信号断开语义一致[3]。

## 4. 项目与导出配置审查表

**项目配置审查必须同时检查“键存在、值合法、作用域正确”。** `ProjectSettings.get_setting()`/`set_setting()`/`has_setting()` 以完整路径字符串访问配置；`save()` 的权限、运行阶段和调用频率都要审查。资源路径方面，`res://` 属于项目内部资源，`user://` 属于用户数据；`localize_path()`/`globalize_path()` 分别向项目路径和操作系统路径转换。移动端/Web 上应避免假设可自由写任意绝对路径；导出模板、PCK 加载、热更新策略若没有签名与完整性校验，不应直接放行。

### `ProjectSettings.get_setting/has_setting/set_setting`
- **签名**：`ProjectSettings.get_setting("display/window/size/viewport_width")`；`has_setting()`；`set_setting(name, value)` / `ProjectSettings.GetSetting`
- **用途**：读取、判断和覆写项目设置。
- **误用**：键名拼错；运行时 `set_setting()` 后假定所有子系统的启动期设置立即生效；未先 `has_setting()` 却使用 `null` 默认。
- **判据**：`ProjectSettings\.(get_setting|set_setting|has_setting)\s*\(`；字符串中无完整路径；`set_setting` 在 `_process` 中调用。
- **确认**：输出未知键测试；查阅设置文档判断是否支持运行时变更；保存后重载配置。
- **置信度**：官方明确。

### `ProjectSettings.localize_path/globalize_path/save/load_resource_pack`
- **签名**：`ProjectSettings.globalize_path("res://data.json")`；`localize_path(abs)`；`save()`；`load_resource_pack(pack_path)` / `LoadResourcePack`
- **用途**：转换路径、持久化配置、运行期加载 PCK。
- **误用**：把不可写位置当 `user://`；导出后调用 `save()` 无权限；PCK 来源未校验、版本不兼容；路径分隔符跨平台不一致。
- **判据**：`(localize_path|globalize_path|save|load_resource_pack)\s*\(`；PCK 无校验；`save()` 返回值被忽略。
- **确认**：Windows/macOS/Linux/移动端检查路径；只读文件系统和沙盒失败用例；PCK 签名校验。
- **置信度**：官方明确。

### `application/config/name` / `main_scene`
- **签名**：`ProjectSettings.set_setting("application/config/name", "Demo")`；`application/run/main_scene = "res://main.tscn"`
- **用途**：定义产品名与启动场景。
- **误用**：产品名含版本/调试后缀进入发布配置；`main_scene` 缺失、移动或被错误分支覆盖；Autoload 依赖尚未加载的主场景。
- **判据**：`application/config/name` 文本；`application/run/main_scene`；键重复或指向不存在文件。
- **确认**：新建空项目、重命名主场景、清理导入缓存各测一次；检查导出模板一致性。
- **置信度**：官方明确。

### `display/window/size/*` / `rendering/renderer/rendering_method`
- **签名**：`ProjectSettings.get_setting("display/window/size/viewport_width")`；`rendering/renderer/rendering_method` 取 `gl_compatibility`/`mobile`/`forward_plus`
- **用途**：配置视口与渲染路径。
- **误用**：把编辑器的渲染器当成导出目标的渲染器；低配设备默认 `forward_plus`；DPI 设置关闭后导致 HiDPI 模糊/窗口管理问题。
- **判据**：`rendering/renderer/rendering_method`；各平台 feature tag 覆盖；窗口尺寸是固定像素且无多分辨率策略。
- **确认**：Windows/macOS/Linux/Android/iOS/Web 各导出模板跑一遍；记录 GPU/驱动最低支持。
- **置信度**：官方明确。

### `physics/common/physics_ticks_per_second` / `application/config/quit_on_go_back`
- **签名**：`ProjectSettings.set_setting("physics/common/physics_ticks_per_second", 120)`；`quit_on_go_back = true/false`
- **用途**：控制固定步频率与移动端返回键退出。
- **误用**：只改 `physics_ticks_per_second` 却不调 `Engine.max_physics_steps_per_frame`，导致掉帧时明显变慢；Android 返回键行为未明确。
- **判据**：`physics/common/physics_ticks_per_second`；同时缺 `max_physics_steps_per_frame`；`quit_on_go_back` 无移动端策略。
- **确认**：CPU 压力、长短帧、时间缩放测试；Android 返回键导航与后台切换。
- **置信度**：官方明确。

### `input/*`
- **签名**：`InputMap.has_action("jump")` / `Input.IsActionJustPressed("jump")`
- **用途**：读取输入映射与当前动作状态。
- **误用**：动作名硬编码、拼错；映射在不同输入设备/平台不一致；UI 与游戏同时消费同一动作且无处理顺序。
- **判据**：`Input(?!Event)\.(is_action|action_press|map_)`；字符串动作名；自定义 `input/*` 设置无默认值。
- **确认**：手柄、键盘、触屏、空映射、重复键位分别测试。
- **置信度**：官方明确。

### `OS.get_name/has_feature/get_user_data_dir/get_cmdline_args`
- **签名**：`OS.get_name()`；`OS.has_feature("mobile")`；`OS.get_user_data_dir()`；`OS.get_cmdline_args()` / `OS.GetName()`
- **用途**：判断平台、获取用户数据与命令行。
- **误用**：用 `get_name()` 替代 feature tag；把 `user_data_dir` 当作缓存目录；命令行参数解析不区分引擎参数与用户参数。
- **判据**：`OS\.get_name\s*\(` 后跟字符串比较；`get_user_data_dir()` 与临时文件混用；未校验 `get_cmdline_args()` 长度。
- **确认**：交叉编译与导出模板测试；检查各平台数据目录沙盒。
- **置信度**：官方明确。

### `OS.alert/execute/shell_open/request_permissions`
- **签名**：`OS.alert("msg")`；`OS.execute(path, args)`；`OS.shell_open(url)`；`OS.request_permissions()` / `OS.Alert`
- **用途**：弹原生提示、启动进程、打开 URI、请求移动权限。
- **误用**：`alert()` 阻塞；`execute()` 的路径/参数注入；`shell_open()` 打开不受控 URL；Android 权限请求结果不等待。
- **判据**：`OS\.(alert|execute|shell_open|request_permissions?)\s*\(`；外部输入进入命令/URL；无超时、无返回值判断。
- **确认**：错误路径、拒绝权限、Web/主机沙盒环境；进程退出码与输出缓冲。
- **置信度**：官方明确。

### `OS.get_screen_refresh_rate()` / `delta`
- **签名**：`var hz = OS.get_screen_refresh_rate()`；`_process(delta)` / `DisplayServer.ScreenGetRefreshRate`
- **用途**：读取刷新率、取得帧步进。
- **误用**：Web 可能返回 `-1.0` 却当作合法值；把 `delta` 当作恒定固定步；用刷新率推算物理而不是 `physics_ticks_per_second`。
- **判据**：`get_screen_refresh_rate\s*\(` 且返回值未检查 `<=0`；`delta` 被缓存或误用于 `_physics_process`。
- **确认**：60/120/可变刷新率、窗口模式切换、Web 导出测试。
- **置信度**：官方明确。

### `Engine.get_frames_per_second/physics_ticks_per_second/max_physics_steps_per_frame/time_scale/has_singleton`
- **签名**：`Engine.get_frames_per_second()`；`Engine.physics_ticks_per_second`；`Engine.max_physics_steps_per_frame`；`Engine.time_scale`；`Engine.has_singleton(name)` / `Engine.GetFramesPerSecond()`
- **用途**：查询/修改引擎运行参数、检查单例。
- **误用**：运行时持续降低 `time_scale` 后未恢复；只提高 tick 频率却不调最大每帧步数；自定义 Autoload 未注册却 `has_singleton()` 后直接强转。
- **判据**：`Engine\.(set_)?(physics_ticks_per_second|max_physics_steps_per_frame|time_scale)\s*=`；`has_singleton\(` 后无类型校验。
- **确认**：长时间暂停、变速、低帧率、重连；自动测试前后恢复初始值。
- **置信度**：官方明确。

### `DisplayServer` / `Window` 窗口模式与多显示器
- **签名**：`DisplayServer.window_set_mode(DisplayServer.WINDOW_MODE_FULLSCREEN)`；`get_primary_screen()`；`Window.mode` / `DisplayServer.WindowSetMode`
- **用途**：设置全屏/窗口化、边框、位置、显示器与 DPI。
- **误用**：假定启动期窗口设置可运行时热切换；多屏索引跨平台不一致；无边框/标题栏/可调整性配置冲突。
- **判据**：`DisplayServer\.window_*`；`Window\.mode`；全屏切换无恢复路径、无分辨率枚举。
- **确认**：窗口/独占全屏、Alt-Tab、DPI 变化、主屏关闭、多屏拖动。
- **置信度**：官方明确。

## 5. 调试、测试与可观测性审查表

**断言、日志和性能计数器必须按构建模式分层，不能承担发布逻辑。** `assert()` 在 release 中不求值，因此带副作用的表达式不能放入断言；`push_error()`/`push_warning()` 会进入编辑器消息系统，滥用会掩盖真实错误；`print()` 可用于开发，但不应泄漏敏感数据或造成 IO 热点。`Performance.get_monitor()` 与调试器同源，部分指标在 release 返回 0 且更新存在延迟，所以线上监控要另走平台/APM 能力。

![Performance 调试可用性](/data/workspace/dr-godot-lang/fig_performance_availability.png)
*图 3：内存类 Performance 指标在 release 中返回 0；对象、渲染指标可用于调试。数据来源：Performance 类参考（4.0）[4]*

### `print` / `print_debug` / `print_stack`
- **签名**：`print("x", value)`；`print_debug(...)`；`print_stack()` / `GD.Print`
- **用途**：开发期追踪值与调用栈。
- **误用**：发布包残留大量 print；日志拼接耗时、包含账号/存档路径；`print_stack()` 在正常路径中调用。
- **判据**：`print(_debug)?\s*\(`；敏感字段/密钥字符串；`_process/_physics_process` 内无条件打印。
- **确认**：导出 debug/release，检查日志量、文件大小和敏感信息。
- **置信度**：官方明确。

### `push_error/push_warning`
- **签名**：`push_error("save failed")`；`push_warning("deprecated")` / `GD.PushError`
- **用途**：把结构化错误/警告送入消息系统。
- **误用**：用错误流输出普通信息；条件重复触发时每帧推送；被脚本异常处理后未区分。
- **判据**：`push_error\s*\(`；热路径无条件 `push_warning`；用户数据进错误字符串。
- **确认**：故意制造失败，检查调试器、日志文件和 CI 失败阈值。
- **置信度**：官方明确。

### `assert(cond, msg)`
- **签名**：`assert(hp >= 0, "hp must not be negative")` / `GD.Assert`
- **用途**：只在 debug 中验证前置条件。
- **误用**：表达式有加载、计数、状态修改等副作用；依赖断言失败来阻止发布逻辑；缺少有意义的消息。
- **判据**：`assert\s*\([^,)]*[,)]`；断言体含函数调用/赋值/资源加载；发布安全校验仅由 `assert` 承担。
- **确认**：导出 release 并验证表达式未执行；把真正的安全/资源校验改写为 `if/return/error`。
- **置信度**：官方明确。

### `Performance.get_monitor(Monitor)`
- **签名**：`Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT)` / `Performance.GetMonitor`
- **用途**：取得对象、内存、消息队列、渲染对象、物理对象等运行时数据。
- **误用**：把调试指标当发布指标；期望实时刷新；在同一帧高频轮询；监测器索引使用魔术数字。
- **判据**：`Performance\.get_monitor\s*\(`；`MEMORY_STATIC|MEMORY_MESSAGE_BUFFER_MAX` 用于发布遥测；轮询频率异常。
- **确认**：debug/release 分别读取；人为制造 1000 个对象并观察最多 1 秒延迟。
- **置信度**：官方明确。

### `OBJECT_COUNT` / `OBJECT_ORPHAN_NODE_COUNT`
- **签名**：`Performance.get_monitor(Performance.OBJECT_COUNT)` / `OBJECT_ORPHAN_NODE_COUNT`
- **用途**：检测对象增长与游离节点。
- **误用**：用绝对阈值取代趋势；把游离节点数与“一定泄漏”划等号；测试期间未清理 Autoload 与共享资源。
- **判据**：测试代码只断言 `==0`；监控只取一次；无基线/上限阈值。
- **确认**：进入/退出场景 N 次后比较增量；调用 `Node.print_orphan_nodes()`。
- **置信度**：官方明确。

### `MEMORY_STATIC` / `MEMORY_MESSAGE_BUFFER_MAX`
- **签名**：`Performance.get_monitor(Performance.MEMORY_STATIC)`；`MEMORY_MESSAGE_BUFFER_MAX` / `MemoryStatic`
- **用途**：观察静态内存与延迟调用消息队列峰值。
- **误用**：release 中读取却判定为 0 异常；把消息队列峰值小视为“无积压”；无限制增长未被告警。
- **判据**：release 构建读取上述枚举；未设增长斜率告警；无清理基准。
- **确认**：构造大量延迟调用、断网重连、资源热替换；导出模板验证。
- **置信度**：官方明确。

### `RENDER_TOTAL_OBJECTS_IN_FRAME` / `RENDER_TOTAL_DRAW_CALLS_IN_FRAME` / `PHYSICS_2D_ACTIVE_OBJECTS`
- **签名**：`Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME)`；`RENDER_TOTAL_DRAW_CALLS_IN_FRAME`；`PHYSICS_2D_ACTIVE_OBJECTS`
- **用途**：观察每帧渲染/物理对象负载。
- **误用**：把剔除后对象数当“场景中全部对象”；单次采样作性能结论；与 `OBJECT_NODE_COUNT` 混为一谈。
- **判据**：性能测试只测首帧；无稳定态预热；无 p95/p99 统计。
- **确认**：多分辨率、遮挡剔除、显示/隐藏节点前后采样；记录 GPU/CPU 端到端延迟。
- **置信度**：官方明确。

### GdUnit4 / GUT
- **签名**：社区框架各自的 `@Test`/`test_*`、`assert_*`；GUT 文档 9.5.0 对应 Godot 4.5
- **用途**：组织单元测试、模拟、参数化测试与断言。
- **误用**：把集成测试当单元测试；测试依赖真实文件系统/网络；断言只在编辑器跑，CI 未执行无头测试；测试日志覆盖真实错误信息。
- **判据**：测试目录存在但无 CI 命令；用例访问主场景/Autoload 而未设置测试环境；`assert_*` 返回值被忽略。
- **确认**：失败用例显式红、断言消息可读；无头运行、重复随机种子、资源泄漏检查。
- **置信度**：社区共识；GUT 9.5.0 文档属于社区维护[6]。

### 断点与远程调试
- **签名**：编辑器 Debugger、远程调试端口、部署到手机/主机的开发构建
- **用途**：检查调用栈、变量、信号与场景树。
- **误用**：发布模板开启远程调试；端口/防火墙未隔离；断点条件表达式有副作用；调试器性能改变了时序问题。
- **判据**：CI/发布配置含调试端口；资源打包包含调试符号而无访问控制；调试构建与发布构建行为假设相同。
- **确认**：局域网/公网隔离测试；断点命中后查看场景树与 Performance 计数。
- **置信度**：社区共识。

## 6. 场景树与节点通用 API 审查表

**场景切换、节点释放和暂停模式是“看似同步、实际存在时序”的高发区。** `change_scene_to_file()`/`change_scene_to_packed()` 会切换到新的 `PackedScene` 实例；`current_scene` 的更新时机不能由同一行代码假定。安全的做法是以 `scene_changed` 或显式 `await` 等待。节点加入/离开树要分清 `_enter_tree()`、`_ready()`、`_exit_tree()`；子节点的 `_ready()` 顺序依赖场景结构，不能跨节点依赖同一帧完成顺序。

### `SceneTree.change_scene_to_file/to_packed/reload_current_scene`
- **签名**：`get_tree().change_scene_to_file("res://level.tscn")`；`change_scene_to_packed(packed)`；`reload_current_scene()` / `ChangeSceneToFile`
- **用途**：加载并切换主运行场景。
- **误用**：不处理返回 `Error`；立即访问新场景节点；`current_scene` 未更新；旧场景释放时机未设计。
- **判据**：`change_scene_to_(file|packed|node)\s*\(`；返回值未与 `OK` 比较；调用后同行访问 `current_scene`。
- **确认**：加载失败、重复切换、中途退出场景；`scene_changed` 与 `unload_current_scene()` 交互。
- **置信度**：官方明确。

### `SceneTree.create_timer/create_tween`
- **签名**：`create_timer(1.0, true, false, false)`；`create_tween()` / `CreateTimer`
- **用途**：延时等待与链式补间。
- **误用**：4.0/4.1 传入 4.3+ 四参数；Timer 引用丢失无法取消；Tween 目标释放后继续引用属性。
- **判据**：`create_timer\s*\(([^)]*)\)` 参数数量与最低支持版本不符；timer/tween 返回值未保存。
- **确认**：暂停、释放目标、改变 `time_scale`；版本矩阵测试。
- **置信度**：官方明确。

### `SceneTree.paused/quit/root/current_scene`
- **签名**：`get_tree().paused = true`；`quit()`；`root`；`current_scene` / `Paused`
- **用途**：全局暂停、退出、访问根窗口和当前场景。
- **误用**：全局 pause 影响菜单/暂停 UI；`PROCESS_MODE_ALWAYS` 节点在暂停时继续改变状态；退出前异步保存未完成；`root` 与 `get_viewport()` 混用。
- **判据**：`get_tree\(\)\.paused\s*=`；无白名单 `PROCESS_MODE_ALWAYS`；`quit()` 前无 flush；`root` 用于获取 viewport 相关属性。
- **确认**：菜单、动画、网络、输入各层暂停测试；平台退出回调与自动保存。
- **置信度**：官方明确。

### `process_frame` / `physics_frame`
- **签名**：`get_tree().process_frame.connect(_on_frame)`；`physics_frame` / `ProcessFrame`
- **用途**：在每帧/物理步前统一推进逻辑。
- **误用**：把 `process_frame` 当物理步；两信号中执行顺序与帧率依赖未记录；热路径每帧分配 lambda。
- **判据**：`process_frame|physics_frame`；同帧内两信号都做相同状态计算；帧回调中长耗时任务。
- **确认**：30/60/120 帧与高低负载；physics interpolation 开关。
- **置信度**：官方明确。

### `Node.add_child/remove_child/queue_free/free`
- **签名**：`add_child(node)`；`remove_child(node)`；`queue_free()`；`free()` / `AddChild`
- **用途**：管理节点生命周期。
- **误用**：仍持有 `NodePath`/引用时 `free()` 同步释放；帧中段 `free()` 破坏遍历；`queue_free()` 后立即假定节点已消失；未从 group 和信号移除。
- **判据**：`\.free\s*\(` 出现在帧中段或异步回调；`queue_free\s*\(\)` 后同行访问状态；`add_child` 无 parent 有效性判断。
- **确认**：释放前打印树、断开显式连接；检查重复释放与悬空回调；验证引用计数资源是否真正释放。
- **置信度**：官方明确。

### `is_instance_valid()` / `get_node() vs $`
- **签名**：`if is_instance_valid(node): node.queue_free()`；`var l = $Label`；`get_node("Label")` / `IsInstanceValid`
- **用途**：判断对象实例有效性、按路径取子节点。
- **误用**：路径错误时 `get_node()` 报错；节点改名/重父级导致 `$` 断裂；对象有效但已退出树；脚本对象而非 `Object` 的语义混淆。
- **判据**：`get_node\s*\(` 且未用 `try/except` 或 `get_node_or_null()`；`\$[\w/]+` 指向深层/易改名节点；有效性检查只执行一次。
- **确认**：重命名、重父级、场景实例化、释放节点测试；优先场景唯一名称 `%Name`。
- **置信度**：官方明确。

### `find_child/get_children/get_child/get_node_or_null`
- **签名**：`find_child("Enemy", true, true)`；`get_children()`；`get_child(i)`；`get_node_or_null("Maybe")` / `FindChild`
- **用途**：按名称/索引查询子节点。
- **误用**：默认递归遍历大型树；`get_child(i)` 越界；`get_children()` 返回快照却被长期持有；`find_child` 忽略大小写/owned 标志。
- **判据**：`find_child\s*\(`；每帧重复 `get_children()`/`find_child()`；索引访问无边界检查。
- **确认**：空节点、多个同名子节点、内部节点；检查返回值和 owned 参数。
- **置信度**：官方明确。

### `is_in_group/add_to_group/add_to_group(persistent)`
- **签名**：`is_in_group("enemies")`；`add_to_group("enemies")`；`add_to_group("save", true)` / `IsInGroup`
- **用途**：按语义分组查询与广播。
- **误用**：字符串组名散落各处；动态组无生命周期清理；误以为 persistent group 跨运行持久化；组调用执行顺序依赖。
- **判据**：`add_to_group|is_in_group|remove_from_group\s*\(`；裸字符串组名；无集中常量定义。
- **确认**：场景切换前后组数量；同名组跨节点重复调用；组调用异常隔离。
- **置信度**：官方明确。

### `process_mode`
- **签名**：`process_mode = Node.PROCESS_MODE_ALWAYS` / `ProcessMode.Always`
- **用途**：定义节点在暂停树中的处理行为。
- **误用**：只设父节点模式却依赖继承；`PAUSABLE` 在全局暂停时停止关键输入；`DISABLED` 与“不可见/未激活”混淆；逐帧修改产生编辑器/运行时差异。
- **判据**：`process_mode\s*=`；无暂停白名单；树中同时存在隐式 `INHERIT` 与显式模式但无文档。
- **确认**：暂停/恢复、父节点模式变化、层级变化；菜单/战斗/网络同步测试。
- **置信度**：官方明确。

### `reparent(new_parent, keep_global_transform)`
- **签名**：`node.reparent(new_parent)`；`reparent(parent, false)` / `Reparent`
- **用途**：在 4.1+ 中以可选保持全局变换的方式改变父节点。
- **误用**：在 4.0 使用；未保持全局变换导致位置跳变；新父节点不在同一树或已释放；重父级破坏 group/owner 关系。
- **判据**：`\.reparent\s*\(`；最低版本为 4.0；无全局变换策略；前后未同步碰撞/物理状态。
- **确认**：2D/3D 位置、旋转、缩放；不同世界/子树、暂停状态、物理对象。
- **置信度**：官方明确。

### `get_path/owner/name`
- **签名**：`node.get_path()`；`node.owner`；`node.name` / `GetPath`
- **用途**：取得节点路径、所有者、名称。
- **误用**：保存 `NodePath` 字符串后重构树；`owner` 仅用于场景保存而非运行时父子关系；`name` 重复或无唯一约束。
- **判据**：持久化 `String(NodePath)`；`owner` 与 `get_parent()` 混用；动态 `name` 拼接进入查询。
- **确认**：保存/加载场景、复制实例、重命名；检查 owner 是否为预期场景根。
- **置信度**：官方明确。

### `Viewport.get_visible_rect/get_mouse_position/set_input_as_handled/gui_get_focus_owner`
- **签名**：`get_viewport().get_visible_rect()`；`get_mouse_position()`；`set_input_as_handled()`；`gui_get_focus_owner()` / `GetVisibleRect`
- **用途**：取得视口几何、鼠标坐标、标记输入已处理、读取焦点控件。
- **误用**：把 viewport 坐标当屏幕/窗口坐标；鼠标捕获模式下坐标语义变化；事件未被处理后仍调用 handled；跨 viewport/子窗口焦点查询。
- **判据**：`get_mouse_position|get_visible_rect|set_input_as_handled|gui_get_focus_owner\s*\(`；屏幕/视口坐标未转换；事件链中重复标记。
- **确认**：DPI、缩放、全屏、多 viewport、捕获鼠标；焦点切换顺序与键盘导航。
- **置信度**：官方明确。

## 7. 八条反直觉坑与对应审查动作

**坑 1：本能以为 `var b = a` 复制了数组或字典，实际两者共享同一容器。** `Array`、`Dictionary`、Object、Node、Resource 及 packed array 均为引用共享[1]。审查动作：默认把可变容器字段当共享状态；公开 API 的入参和返回值在文档中写明所有权；测试 `b[0]` 变化是否影响 `a`。

**坑 2：本能以为 `duplicate()` 是深拷贝，实际默认浅拷贝。** 嵌套 `Array`/`Dictionary`、共享资源和对象不会被自动深复制。审查动作：需要独立配置/存档时明确 `duplicate(true)`，并在深拷贝后仍处理共享 `Resource`/`Node` 的业务语义。

**坑 3：本能以为 `await obj.signal` 总会恢复，实际对象释放、场景切换、条件不发射都会永久挂起。** 审查动作：等待外部对象前检查有效性；设计超时/取消；释放路径断开自有连接；测试“发射前释放”场景。

**坑 4：本能以为 `assert(load_resource())` 只是断言，实际 release 中不求值。** 任何加载、初始化、状态变更不得放在 `assert` 中。审查动作：发布构建跑一次安全/资源校验路径，断言只验证 debug 前置条件。

**坑 5：本能以为 `@export` 一定覆盖 `@onready`，实际 `@onready` 的默认赋值在导出值之后，可能覆盖导出的实例值。** 审查动作：避免同一字段混用；导出默认值只负责模板，场景实例值优先于运行时节点查询。

**坑 6：本能以为 Performance 指标生产环境可稳定监控，实际内存指标在 release 返回 0、部分指标最多延迟 1 秒[4]。** 审查动作：debug 用于开发诊断，release 遥测采用平台 API/自定义计数，并统一采样周期。

**坑 7：本能以为 `connect()` 幂等，实际同一 `Callable` 重复连接会报 `ERR_INVALID_PARAMETER`，除非使用 `CONNECT_REFERENCE_COUNTED`[3]。** 审查动作：建立“谁连接、谁断开”清单；动态 lambda 用 `is_connected()` 或一次性连接；不依赖重复连接实现重订阅。

**坑 8：本能以为 `free()` 与 `queue_free()` 可随意互换，实际同步 `free()` 会在帧中段破坏仍遍历该节点的代码。** 审查动作：默认 `queue_free()`；只在清楚对象生命周期且安全时使用 `free()`；异步回调重新取得对象后用 `is_instance_valid()`。

补充三条同样常见但并非复制性的陷阱：`StringName` 的驻留优势只在稳定、可复用的名字上成立，热路径每帧由动态字符串构造会适得其反；`time_scale` 只改变引擎时间，不能代替物理固定步频率，提高 `physics_ticks_per_second` 后还需提高 `max_physics_steps_per_frame` 以避免掉帧明显变慢；`current_scene` 的场景切换不是“调用后立即生效”的普通赋值，应以 `scene_changed` 或显式等待确认新场景就绪。

## 8. 可机审清单、分级与实施顺序

**先扫描会立即导致崩溃/数据丢失的红线，再处理可维护性与模式一致性。** 推荐在预提交钩子中执行：正则扫描输出疑似问题；随后 Godot 编辑器静态检查；最后由无头命令行运行 GdUnit4/GUT 或自定义场景测试。正则只能产生候选，特别是 `await` 对象有效性、`@onready` 与 export 顺序、信号发射覆盖、协程取消属于控制流/运行时问题，必须靠测试而非文本匹配。

### 红线（阻断）
1. `free()` 在帧中段、信号回调、`_process/_physics_process` 或可能共享遍历处。
2. `await external_obj.signal` 无对象有效性、超时、取消或释放路径。
3. `assert()` 内存在资源加载、状态变更、计数、IO 等副作用。
4. 同一 `Callable` 在无幂等设计下重复连接；`disconnect()` 前不判断。
5. 加载/切换场景/获取配置返回 `Error`/`null` 后直接使用。
6. `Array`/`Dictionary` 默认浅拷贝却当作独立数据，尤其配置模板和存档。
7. `MEMORY_STATIC`/`MEMORY_MESSAGE_BUFFER_MAX` 用于发布遥测。
8. `@tool` 脚本在编辑器内执行网络/弹窗/阻塞/未授权文件写入。

### 警告（评审/豁免）
1. 公开字段缺少静态类型；Variant 字段可收窄。
2. `get_node()` 而非 `get_node_or_null()`/场景唯一名称；深层 `$Path` 易重构断裂。
3. `String %` 多参数未使用数组；本地化后位置格式仍硬编码。
4. `@warning_ignore` 无原因；忽略多个无关规则。
5. `create_timer()` 参数数量与目标 Godot 4.x 版本不一致。
6. `reparent()` 用于 4.0；未明确 `keep_global_transform`。
7. `process_mode` 无暂停白名单，菜单/网络节点依赖 `INHERIT`。
8. 组名、输入动作名字符串未集中定义。
9. 热路径每帧创建 `StringName`、lambda、容器或调用 print。
10. `Performance` 单次采样即断言；没有预热和统计窗口。

### 版本与验证矩阵
| 版本维度 | 必须验证的项 | 最低结论 |
|---|---|---|
| 4.0 | `reparent()` 不可用；`create_timer()` 两参数 | 禁止使用 4.1+ 专用 API 或显式多版本兼容 |
| 4.1 | `reparent()` 可用 | 检查全局变换和父节点有效性 |
| 4.2 | 类型化数组增强；for 循环变量类型 | 检查嵌套类型化数组 |
| 4.3+ | `create_timer(time, process_always, process_in_physics, ignore_time_scale)` | 检查老版本签名兼容 |
| 4.4+ | `Dictionary[Key, Value]` | 嵌套类型化字典不可用 |
| Debug 导出 | `assert`、内存指标、消息队列峰值 | 确认诊断逻辑有效 |
| Release 导出 | 指标返回 0、断言不求值、资源路径 | 不得依据 debug 行为判断生产可用性 |

### 建议的最小 CI 证据集
1. 正则扫描报告与豁免记录。
2. Godot 编辑器静态检查结果。
3. 空场景启动、`main_scene` 切换、释放节点、`process_frame` 等待四组日志。
4. 进入/退出场景 10 次的 `OBJECT_COUNT`、`OBJECT_ORPHAN_NODE_COUNT` 增量图。
5. Debug 与 release 的 `MEMORY_STATIC`、消息队列峰值对照。
6. `await` 三组对抗测试：正常发射、对象提前释放、永不发射。
7. 4.0、目标最低版、最新稳定版各一次成功导出。

最终交付的可审查对象应是“源码判据 + 版本化场景测试 + 构建模式差异”三件套。仅扫描 `.gd/.cs` 无法覆盖协程取消、对象释放、pause、计时器参数版本与性能指标的发布差异；反过来，只做运行时测试也无法稳定发现类型缺失、重复连接、裸 `get_node()` 等广泛模式。两者结合后，本包内的 17 类警告与 8 类红线可以落到具体文件、行号和测试用例，而不是停留在笼统的“规范建议”。

## 引用来源
[1] https://docs.godotengine.org/en/stable/reference/gdscript.html?highlight=yield
> "Array, Dictionary, and packed arrays ... are passed by reference so they are shared."

[2] https://docs.godotengine.org/en/4.0/classes/class_@gdscript.html
> "@rpc ... Mark the following method for remote procedure calls."

[3] https://docs.godotengine.org/en/4.0/classes/class_signal.html
> "If the signal is already connected, returns ERR_INVALID_PARAMETER and pushes an error message."

[4] https://docs.godotengine.org/en/4.0/classes/class_performance.html
> "Some of the built-in monitors are only available in debug mode and will always return 0 when used in a project exported in release mode."

[5] https://docs.godotengine.org/ko/4.x/classes/class_scenetree.html
> "create_timer(time_sec: float, process_always: bool = true, process_in_physics: bool = false, ignore_time_scale: bool = false)"

[6] https://gut.readthedocs.io/
> "Gut 9.5.0 (Godot 4.5) — GUT 9.5.0 documentation."

[7] https://docs.godotengine.org/en/4.0/classes/class_projectsettings.html
> "Use get_setting, set_setting or has_setting to access them."

[8] https://docs.godotengine.org/en/4.0/classes/class_engine.html
> "The maximum number of physics steps that can be simulated each rendered frame."

[9] https://docs.godotengine.org/en/4.1/classes/class_node.html
> "void reparent(Node new_parent, bool keep_global_transform=true)"

[10] https://docs.godotengine.org/en/4.3/classes/class_viewport.html
> "Vector2 get_mouse_position() const"

[11] https://docs.godotengine.org/pt_BR/4.x/classes/class_os.html
> "Provides access to common operating system functionalities."

[12] https://docs.godotengine.org/en/4.1/tutorials/inputs/mouse_and_input_coordinates.html
> "Use ... functions in nodes to obtain the mouse coordinates and viewport size."
