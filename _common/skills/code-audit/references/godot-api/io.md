<!-- oversize-exempt: 引擎 API 查表文档，按 API 索引，需整体查阅 -->
# Godot 4.x 资源、文件 IO、序列化与网络 API 级代码审查判据

## 摘要

本报告以 Godot 官方 4.x 文档为基准，把 6 组 API 拆成可由 `.gd`/`.cs` AST 或正则扫描触发的审查规则。最重要的生命周期结论是：`Resource` 继承 `RefCounted`，引用归零后自动释放，不应、也通常不能调用 `Node.free()`/`queue_free()`；自定义资源也不会自动发射 `changed` [1][2]。第二个关键点是 4.x 的 `FileAccess.open()` 在失败时返回 `null`，而不是沿用 3.x 的 `File.new()`；写文件必须处理返回值和后续错误，虽然对象离开作用域或赋 `null` 时会自动关闭，但显式 `close()` 仍是明确所有权边界 [7]。第三，资源加载遵循路径缓存，`load()` 与 `preload()` 对相同资源路径可能返回同一实例，因此共享可变资源必须依靠 `resource_local_to_scene` 或 `duplicate()` 隔离 [1][5]。第四，导出后的 `res://` 不能当作存档盘；用户数据应落在 `user://`，写入前建立目录并校验解析后的绝对路径 [7]。第五，反序列化与 RPC 都属于不可信输入边界：`bytes_to_var/get_var/str_to_var` 打开 `allow_objects/full_objects`，或 RPC 使用 `any_peer` 而不校验发送者与参数，均应列为高风险 [10][14]。最后，4.x 多人 API 已围绕 `MultiplayerAPI`、`@rpc` 注解、`MultiplayerSpawner` 和 `MultiplayerSynchronizer` 重构，规则库不应再以 3.x 的 `Node.set_network_master()`、`slave/master` 为目标模式 [13][15]。

## 1. Resource 生命周期：共享引用可以跨实例持续存在，释放责任不可交给 Node API

### 1.1 规则总体模型与风险分级

本章规则把“Resource 的持有方式”作为核心数据流。Resource 不是场景树节点，它没有父子关系、进入/离开树通知或可排队销毁语义；其生命周期由引用计数决定。判据因此不能只看“是否调用了释放函数”，还要看跨脚本赋值、信号回调、数组/字典存储、导出变量和场景实例化的传播路径。

| 级别 | 判定含义 | 处置建议 |
|---|---|---|
| BLOCKER | 官方明确违反生命周期、导出后必然写入失败，或可信边界被绕过 | 阻断合入/打包 |
| MAJOR | 共享可变状态、资源泄漏、路径穿越或缺少错误处理 | 要求修复 |
| MINOR | 可读性、性能或未来维护风险 | 建议修复 |

**Resource 实例不是节点，调用 Node 的释放 API 属于类型语义错误。** `Resource` 继承自 `RefCounted`，后者再继承 `Object`；官方文档明确说明，引用计数对象在无引用时自动释放，不需要用 `Object.free()` 手动释放 [2]。GDScript 中若代码对 Resource 调用 `queue_free()`，既误用了异步节点销毁语义，也可能掩盖设计问题；`.free()` 虽是 `Object` 的方法，但对一个正在被引擎或脚本引用的 `RefCounted` 强行释放，会造成悬挂引用。`RefCounted.reference()`/`unreference()` 官方也明确归为高级接口，误用会出问题 [2]。

```text
### Resource（类型身份）
- **签名**：`extends Resource` / `class MyResource : Resource`
- **用途**：作为可引用、可序列化、可由资源系统缓存的数据/资产对象。
- **误用**：把它当成 Node 处理，调用 `queue_free()`，或对仍在使用的资源 `free()`。
- **判据（源码特征）**
  - GDScript：`^\s*class_name\s+\w+.*$|^\s*extends\s+Resource\b`
  - C#：`class\s+\w+\s*:\s*Resource\b`
  - 释放误用：`\.queue_free\s*\(|obj\.free\s*\(\s*\)`
- **确认**
  1. 检查 `.queue_free()`/`.free()` 的接收者是否可静态判定为 `Resource` 或其子类。
  2. 确认它是否仍处于导出变量、资源缓存、数组、`meta` 或信号连接所持有的引用图中。
  3. 若只是希望切断业务引用，应改为清除变量、从容器移除，或让 `RefCounted` 自然离开作用域。
- **置信度：官方明确**
```

**`RefCounted` 引用循环会让对象长期存活，而不是“互相释放”。** 官方对循环引用的建议是至少将一个引用改为 `weakref()` [2]。静态扫描不能证明循环必然存在，但可标记长期容器持有 Resource、Resource 反向持有 Node、Node 的脚本又持有 Resource 的组合。这里的 BLOCKER 应是“明确的循环构造”，如两个 `RefCounted` 的脚本属性相互赋值，或对象把自身注册到长生命周期全局单例且没有提供注销路径。

```text
### RefCounted.reference / RefCounted.unreference
- **签名**：`reference()` / `unreference()`（C# 没有稳定、等价的普通手写生命周期 API）
- **用途**：高级用户手动调整内部引用计数。
- **误用**：业务代码用“配对调用”模拟智能指针；在已有脚本引用时 `unreference()`，或在信号/跨线程边界重复 `reference()`。
- **判据（源码特征）**
  - GDScript：`:\s*reference\s*\(|unreference\s*\(`
  - 反模式：同一函数中出现 `reference()` 却没有对称、可证明安全的释放路径
- **确认**
  1. 检查调用者是否同时持有 GDScript 变量引用；若有，手动计数通常多余。
  2. 检查是否存在异常/提前返回导致不配对。
  3. 用 `print(_reference_count())` 仅适合临时调试，不得作为生产逻辑。
- **置信度：官方明确（高级 API）；是否构成泄漏为审查判断**
```

**`WeakRef`/`weakref()` 只是降低泄漏风险，不阻止目标被回收。** `weakref(object)` 可让一个引用不阻止对象释放；读取时仍需 `get_ref()` 并处理 `null`。反模式是“保存弱引用却假定它永远非 null”，或把弱引用作为跨帧缓存而不重新校验对象身份。

```text
### WeakRef / weakref
- **签名**：`weakref(object)` / `WeakRef.GetRef()`；GDScript 也常直接访问 `reference`
- **用途**：保存不阻止回收的引用。
- **误用**：假定弱引用长期有效，或把 `get_ref()` 的结果跨帧复用而不重新判空。
- **判据（源码特征）**
  - GDScript：`weakref\s*\(|get_ref\s*\(`
  - 风险组合：`get_ref\(\)\.[A-Za-z_]`（下一行未判空就访问）
- **确认**
  1. 在 `get_ref()` 后立即检查 `is_instance_valid(ref)` 或判空。
  2. 检查调用链是否在持有所谓“仍存活”假设后执行状态修改。
- **置信度：官方明确**
```

**`is_instance_valid()` 回答“实例是否仍有效”，不能回答“引用类型对不对”。** 官方文档说明 `is_instance_valid(instance)` 可检测已释放的 Object；它不能替代 `is_node_ready()`、`is_inside_tree()` 或资源类型检查。Resource 在引用归零释放后也可能成为失效实例，但对它的访问证据通常来自 WeakRef、保存的 Object 引用或跨信号回调。

```text
### @GlobalScope.is_instance_valid
- **签名**：`is_instance_valid(instance)` / `Godot.Object.IsInstanceValid(Object)`
- **用途**：检测对象实例是否仍未释放。
- **误用**：把它当类型检查；在多线程中把单次结果缓存为长期真相。
- **判据（源码特征）**
  - GDScript：`is_instance_valid\s*\(`
  - C#：`Object\.IsInstanceValid\s*\(`
- **确认**
  1. 检查调用后是否仍可能在下一行发生释放；必要时拷贝引用到局部变量并重新校验。
  2. 若目标是 Node，补充 `is_inside_tree()` 或 `is_node_ready()`。
- **置信度：官方明确；异步窗口属于审查判断**
```

### 1.2 Resource 元数据、变更通知与路径控制

**`set_meta`/`get_meta` 是黑盒附着层，不应承载主类型协议。** 官方文档列出的资源成员包括 `set_meta(name, value)` 和 `get_meta(name, default)`。扫描时重点不是禁用元数据，而是防止业务通过字符串键替代类型化属性、跨系统共享可变对象，或在热路径中频繁存取。另一个风险是元数据保存/复制语义与预期不同：保存、复制、编辑器重新打开、资源格式转换是否保留所有元数据的细节，不能由普通项目代码可靠假定；判据应要求对关键数据使用显式字段和测试。

```text
### Resource.set_meta / Resource.get_meta
- **签名**：`set_meta(name, value)` / `set_meta(const StringName &name, const Variant &value)`；`get_meta(name, default=null)` / `get_meta(const StringName &name, const Variant &default)`
- **用途**：为对象附加不进入主数据契约的额外信息。
- **误用**：用魔法字符串跨模块通信；把可变 Resource/Array/Dictionary 放进元数据后跨实例共享；把存档必需字段藏进元数据。
- **判据（源码特征）**
  - GDScript：`set_meta\s*\(|get_meta\s*\(`
  - 风险组合：`get_meta\([^)]*\)\.(?!\b(to_|is_))` 后的链式状态修改
- **确认**
  1. 搜索全部键名，确认没有同名键承担跨系统契约。
  2. 检查 `default` 缺失导致的 `null` 传播。
  3. 检查值是否为 `Resource`、`Array` 或 `Dictionary` 并追踪共享写入。
- **置信度：官方明确存在该 API；具体共享风险为审查判断**
```

**自定义 Resource 的 `changed` 信号不会因属性写入自动触发。** 官方文档说明 `changed` 在资源变化时通常因属性修改而发射，但自定义资源的属性不会自动发射，必要时由 setter 发射 [1]。这意味着依赖 `changed` 做自动保存、Undo/Redo、UI 刷新或跨节点同步的代码，可能因“明明改了字段却不通知”而出现数据陈旧。

```text
### Resource.changed / Resource.emit_changed
- **签名**：`emit_signal("changed")` / `EmitSignal("changed")`；信号连接 `changed`
- **用途**：通知资源使用者数据可能发生变化。
- **误用**：假设 `resource.x = 1` 自动触发 `changed`；在并发线程中发射信号；同一个 setter 递归触发自身。
- **判据（源码特征）**
  - GDScript：`emit_signal\s*\(\s*["']changed["']|signal\s+changed|\.changed\.connect\s*\(`
  - C#：`EmitSignal\s*\(\s*"changed"|public\s+event|SignalName\.Changed`
  - 自定义资源：`set\s*\([A-Za-z_0-9.]+\s*\)`
- **确认**
  1. 对每个自定义资源属性 setter，检查 `_changed`/`emit_signal("changed")` 的存在和守卫条件。
  2. 对批量写入，确认不会因每次 set 触发昂贵 UI/IO。
  3. 在测试中分别覆盖“同名实例修改”与“共享 Resource 修改”。
- **置信度：官方明确**
```

**`get_property_list()` 与编辑/复制语义相关，不能用来建立持久外部索引。** Resource 提供 `get_property_list()`，返回可用 `PropertyInfo` 描述的一组属性；审查重点是不要缓存其结果作为长期字段映射，也不要依赖它枚举私有脚本状态。对于序列化，优先依靠 `@export`、显式 save/load 转换层或确定的资源格式，而非遍历属性字典。

```text
### Resource.get_property_list
- **签名**：`get_property_list()` / `Godot.Collections.Array<Godot.Dictionary> GetPropertyList()`
- **用途**：取得对象属性元数据，常用于编辑器、调试和通用工具。
- **误用**：保存属性顺序、字典键或类型假设；将内部实现细节用于存档格式。
- **判据（源码特征）**
  - GDScript：`get_property_list\s*\(`
  - C#：`GetPropertyList\s*\(`
- **确认**
  1. 读取处若持久化输出，要求固定 schema、版本号和迁移函数。
  2. 检查是否存在对 `class_name`、类型、hint 的字符串耦合。
- **置信度：官方明确；版本兼容风险为审查判断**
```

**`resource_local_to_scene` 是共享可变资源问题的正确开关，但会改变内存与实例关系。** 官方说明当其为 `true` 时，资源会为使用该资源的每个场景实例复制一份；运行时可在一个场景中修改副本而不影响其他实例 [1]。它只适合确实需要“每实例资源状态”的情形，例如材质参数、随机生成种子或可编辑的关卡数据。对只读纹理、共享音效或大型静态数据开启，会增加实例化和内存开销。

```text
### Resource.resource_local_to_scene
- **签名**：`@export var resource_local_to_scene: bool` / `public bool ResourceLocalToScene { get; set; }`
- **用途**：使每个场景实例拥有独立资源副本。
- **误用**：所有共享资源一律开启；在编辑器动态生成资源后又假定没有复制；跨实例共享状态却未开启。
- **判据（源码特征）**
  - GDScript：`resource_local_to_scene\s*=\s*true|@export\s+var\s+resource_local_to_scene`
  - C#：`ResourceLocalToScene\s*=\s*true|public\s+bool\s+ResourceLocalToScene`
- **确认**
  1. 测试至少两个同时运行的场景实例，修改一个后验证另一个未变。
  2. 若仅偶尔需要隔离，比较“启用 local_to_scene”与“按需 duplicate()”的内存/性能。
- **置信度：官方明确**
```

**`duplicate()` 的浅拷贝会保留子资源的同一引用，深拷贝才是完整隔离。** 官方定义 `duplicate(deep: bool = false)`：默认返回浅拷贝，只有 `deep=true` 时才递归复制导出或 `PROPERTY_USAGE_STORAGE` 属性 [1]。因此“调用过 duplicate 就安全”是错误结论。静态判据应标记 `duplicate()`，再要求代码注释或测试证明所需的拷贝深度。

```text
### Resource.duplicate
- **签名**：`duplicate(deep: bool = false)` / `Resource Duplicate(bool deep = false)`
- **用途**：复制资源属性。
- **误用**：浅拷贝后修改嵌套 Resource 影响原对象；深拷贝大型资源树造成卡顿或意外 Object 复制。
- **判据（源码特征）**
  - GDScript：`\.duplicate\s*\(`
  - C#：`\.Duplicate\s*\(`
  - 风险：`.duplicate\s*\(\s*\)`（参数缺失，需审阅）
- **确认**
  1. 画出属性引用图，检查子 Resource 是否应共享。
  2. 对存档/实例状态覆盖写路径做快照对比。
  3. 测量深拷贝耗时，尤其不要在 `_process` 中无条件调用。
- **置信度：官方明确**
```

**`take_over_path()` 不是普通“设置路径”，而是资源缓存覆盖器。** 官方文档说明它会设置 `resource_path` 并可能覆盖已有缓存条目，之后按路径加载会返回该对象 [1]。它适合编辑器工具、运行时热重载或测试替身，却极易造成生产资源被长期单例覆盖。规则应禁止在游戏运行期业务代码中无条件使用；若测试代码使用，必须配对回滚。

```text
### Resource.take_over_path
- **签名**：`take_over_path(path: String)` / `void TakeOverPath(string path)`
- **用途**：让指定路径加载时返回当前资源，覆盖缓存条目。
- **误用**：运行时用它替换正式资源；忘记恢复，导致后续 load 永久拿到覆盖对象；路径注入。
- **判据（源码特征）**
  - GDScript：`take_over_path\s*\(`
  - C#：`TakeOverPath\s*\(`
- **确认**
  1. 搜索调用上下文，确认是否处于 `tool`/编辑器插件/测试替身。
  2. 对替换路径做白名单和规范化检查。
  3. 在退出或测试 tearDown 时恢复/清除受影响缓存。
- **置信度：官方明确；何时回滚为审查判断**
```

**`resource_name` 与 `resource_path` 的语义不同，不能互相替代。** 官方文档列出 `resource_name` 和 `resource_path`。前者通常对应资源的人类可读名称/文件标题，后者是资源系统路径。保存后的路径可能因 `ResourceSaver.FLAG_CHANGE_PATH` 等策略变化；不要在业务逻辑里通过字符串截取 `resource_path` 来生成存档名或网络标识。

```text
### Resource.resource_name / Resource.resource_path
- **签名**：`@export var resource_name: String` / `@export var resource_path: String`
- **用途**：分别取得资源的显示名和资源路径。
- **误用**：把 `resource_path` 当存档目录；把 `resource_name` 当唯一 ID；未归一化比较路径。
- **判据（源码特征）**
  - GDScript：`resource_path|resource_name`
  - C#：`ResourcePath|ResourceName`
  - 反模式：`user://\s*\+\s*resource_path|ProjectSettings\.globalize_path\s*\(\s*resource_path\s*\)` 后再拼接用户输入
- **确认**
  1. 使用 `ProjectSettings.globalize_path()` 做诊断，不要把结果当作可写保证。
  2. 对用户可见名称与唯一 ID 使用两个独立字段。
- **置信度：官方明确**
```

## 2. PackedScene 与 SceneState：instantiate 只产生节点，必须显式加入场景树

### 2.1 4.x 的 instantiate 签名与实例归属

**`PackedScene.instantiate()` 替代 3.x 的 `instance()`，但返回的 Node 仍未在树中。** 官方签名是 `Node instantiate(edit_state: GenEditState = 0)`；它实例化节点层级并触发子场景实例化，根节点收到 `NOTIFICATION_SCENE_INSTANTIATED` [3]。它不负责设置父节点、所有者、组、输入处理顺序或场景树事件。因此“调用 instantiate 后立刻收到 `_ready`”是错误的；根节点进入树前后还需完成 `add_child` 及必要的 `owner`/`set_multiplayer_authority` 配置。

```text
### PackedScene.instantiate
- **签名**：`packed_scene.instantiate(edit_state=0)` / `PackedScene.Instantiate(PackedScene.GenEditState editState = 0)`
- **用途**：把 PackedScene 还原为节点层级。
- **误用**：未判空；返回 Node 后不 add_child；忘了 configure spawn；直接修改共享资源。
- **判据（源码特征）**
  - GDScript：`\.instantiate\s*\(`
  - C#：`\.Instantiate\s*\(`
  - 风险组合：`instantiate\s*\(\)\s*\n(?!\s*(var\s|await|add_child|set_multiplayer_authority|_setup))`
- **确认**
  1. 检查返回值是否为 `null`/未赋值即访问。
  2. 检查同一作用域或紧接着的初始化函数中是否有 `add_child`、owner 设置与权限设置。
  3. 测试生成的对象是否接收 `_enter_tree`/`_ready`。
- **置信度：官方明确**
```

**`can_instantiate()` 只检查场景文件是否包含节点，不是通用资源合法性证明。** 官方将其描述为场景文件有节点时返回 `true` [3]。静态资源可能解析成功，却因脚本缺失、节点类型未注册、资源依赖丢失或权限问题而在 instantiate 时失败；运行时仍应判空并记录错误。

```text
### PackedScene.can_instantiate
- **签名**：`can_instantiate() const` / `bool CanInstantiate()`
- **用途**：预先检查 PackedScene 是否有可实例化的节点。
- **误用**：把它当作“资源存在”“脚本完整”或“实例化一定成功”的证明。
- **判据（源码特征）**
  - GDScript：`can_instantiate\s*\(`
  - C#：`CanInstantiate\s*\(`
- **确认**
  1. 检查调用后是否仍对 `instantiate()` 结果判空。
  2. 检查失败分支是否暴露可用诊断，而不是静默返回空场景。
- **置信度：官方明确；过度断言为审查判断**
```

**`pack()` 只打包 node 与其 owned 子节点，因此 owner 设置直接决定保存范围。** 官方签名 `Error pack(path: Node)` 会清空现有数据，并将指定 node 及所有 owned 子节点打包 [3]。常见误用是动态生成节点后只 `add_child`，没有设置 `owner`，导致 `pack()` 没有纳入预期子树。此 API 的主要风险在编辑器/工具场景；纯运行时生成关卡若不需要回写 `.tscn`，通常无需调用。

```text
### PackedScene.pack
- **签名**：`pack(path: Node)` / `Error Pack(Node path)`
- **用途**：把节点及其 owned 子节点序列化回 PackedScene。
- **误用**：依赖完整 add_child 子树而忽略 owner；重复 pack 时未意识到现有数据被清空；在游戏运行期无条件写 res://。
- **判据（源码特征）**
  - GDScript：`\.pack\s*\(`
  - C#：`\.Pack\s*\(`
  - 反模式：`add_child\s*\([^)]*\)(?!.*owner\s*=)`
- **确认**
  1. 对预期保存集合执行 `get_children()`、owner 递归检查。
  2. 保存目标必须位于 `user://` 或明确的编辑器可写位置，而非生产资源目录。
- **置信度：官方明确签名；owned 集合语义为官方继承/节点语义推断，置信度“官方明确”**
```

**`get_state()` 返回不可变场景描述，适合审计而不是日常业务调用。** 官方说明 `get_state()` 返回表示场景文件内容的 `SceneState` [3]。它适合资源管线、依赖审计和调试；不应在每帧调用，也不应假定返回结构可被运行时稳定修改。

```text
### PackedScene.get_state
- **签名**：`get_state() const` / `SceneState GetState()`
- **用途**：取得场景文件内容的状态表示。
- **误用**：在热路径调用；把 SceneState 当作可写场景对象。
- **判据（源码特征）**
  - GDScript：`get_state\s*\(`
  - C#：`GetState\s*\(`
- **确认**
  1. 检查调用频次和是否只在编辑器/导入期执行。
  2. 确认返回值仅用于只读分析。
- **置信度：官方明确**
```

**`GenEditState` 是编辑器编辑语义参数，运行期常设应标为可疑。** 官方枚举包括 `GEN_EDIT_STATE_DISABLED=0`、`INSTANCE=1`、`MAIN=2` 与 `MAIN_INHERITED=3`；后者与前两者用于本地场景资源和主场景/继承实例化 [3]。普通运行时 `instantiate()` 通常不需要传参。若出现非 0 值，审查器应要求注释说明是否属于工具、编辑器插件或场景继承生成逻辑。

```text
### PackedScene.GenEditState / instantiate_gen_edit_state
- **签名**：`instantiate(edit_state: GenEditState)` / `PackedScene.Instantiate(PackedScene.GenEditState)`
- **用途**：在编辑/实例化场景中生成本地编辑状态。
- **误用**：在发布版游戏运行时误用 MAIN/MAIN_INHERITED；将编辑态对象持久化。
- **判据（源码特征）**
  - GDScript：`instantiate\s*\([^)]*(GEN_EDIT_STATE_(?:MAIN|INSTANCE|MAIN_INHERITED)|[123])\s*\)`
  - C#：`Instantiate\s*\([^)]*(GenEditState\.[A-Za-z]+|[123])\s*\)`
- **确认**
  1. 检查是否仅位于 `tool` 脚本、编辑器插件或明确的场景构建工具。
  2. 运行发布导出版本，验证不会生成可写资源或依赖编辑器状态。
- **置信度：官方明确**
```

### 2.2 SceneState 的只读审计接口

**SceneState 成员适合静态审计，不适合作为运行时节点访问 API。** 官方列出 `get_node_count()`、`get_node_path(idx)`、`get_node_type(idx)`、`get_node_name(idx)`、`get_node_instance_placeholder(idx)` 等；它们按节点索引描述场景内容 [4]。索引 API 的稳定性只适用于给定 SceneState，扫描工具应把“遍历整个节点索引空间”与“访问一个固定索引”区分开。

```text
### SceneState.get_node_count / get_node_path / get_node_type / get_node_name
- **签名**：`get_node_count()` / `get_node_path(idx)` 等 / `int GetNodeCount()`、`NodePath GetNodePath(int idx)`
- **用途**：从 SceneState 读取节点数量、路径、类型或名称。
- **误用**：假定索引跨版本/跨资源稳定；把类型名字符串拼接成可执行代码；越界。
- **判据（源码特征）**
  - GDScript：`get_node_count\s*\(|get_node_path\s*\(|get_node_type\s*\(|get_node_name\s*\(`
  - C#：`GetNodeCount\s*\(|GetNodePath\s*\(|GetNodeType\s*\(|GetNodeName\s*\(`
- **确认**
  1. 遍历前检查 `i < get_node_count()`。
  2. 对返回的类型字符串只做白名单比较，不 `call()`/`new()`。
- **置信度：官方明确**
```

**实例占位符节点意味着依赖可能尚未解析成真正场景。** `get_node_instance_placeholder(idx)` 返回占位符信息；它不是已实例化的场景根。若审查目标是检测“引用了不存在/不安全场景”，需要结合 `ResourceLoader.exists()`、`get_dependencies()` 和打包依赖分析，而不是只检查 PackedScene 非空。

```text
### SceneState.get_node_instance_placeholder
- **签名**：`get_node_instance_placeholder(idx)` / `NodePath GetNodeInstancePlaceholder(int idx)`
- **用途**：读取实例占位符的目标。
- **误用**：把占位符目标当作已加载场景；未验证目标资源存在/可信任。
- **判据（源码特征）**
  - GDScript：`get_node_instance_placeholder\s*\(`
  - C#：`GetNodeInstancePlaceholder\s*\(`
- **确认**
  1. 解析返回的占位符路径并调用 `ResourceLoader.exists()`。
  2. 在资源导入后验证依赖完整性，而非只在运行时检测。
- **置信度：官方明确**
```

## 3. ResourceLoader 与 ResourceSaver：缓存、线程与路径共同决定加载结果

### 3.1 同步/异步加载及缓存模式

**`ResourceLoader.load()` 会缓存结果，写代码前必须先确认“是否要同一份资源”。** 官方签名 `load(path, type_hint="", cache_mode=1)` 明确说明它会缓存资源以供后续访问 [5]。对相同路径后续加载可能返回同一 Resource，而 `preload("res://...")` 在脚本解析期解析，运行时 `load()` 也进入同一资源体系。因此纹理、音效和只读数据适合共享；玩家存档状态、程序生成配置和每实例资源不能靠反复 load 获得隔离。

```text
### ResourceLoader.load
- **签名**：`ResourceLoader.load(path, type_hint="", cache_mode=1)` / `ResourceLoader.Load(path, typeHint, cacheMode)`
- **用途**：同步加载并缓存资源。
- **误用**：同一路径反复 load 却假定拿到独立副本；未处理返回 null；用 load 打开不可信外部文件。
- **判据（源码特征）**
  - GDScript：`ResourceLoader\.load\s*\(|load\s*\(\s*"res://`
  - C#：`ResourceLoader\.Load\s*\(`
  - 风险：`load\s*\([^)]*\)\s*\.[A-Za-z_]`（结果未判空）
- **确认**
  1. 检查返回值是否可能为 null，并读取 `ResourceLoader.get_open_error()` 或日志。
  2. 对可变资源使用 `CACHE_MODE_IGNORE/REPLACE` 或 `duplicate()`。
  3. 在编辑器中加载项目资源时明确 `type_hint`，避免返回不符合预期的类型。
- **置信度：官方明确**
```

**`preload()` 在解析期解析，`load()` 在运行期调用，但两者仍落入同一资源系统。** Godot 官方教程称 `preload()` 是“在脚本解析时加载资源”的快捷方式；普通 `load()` 是在运行时调用的 ResourceLoader 方法。两者并不因执行时机不同而产生两个独立的资源生命周期：相同资源路径仍受缓存影响。代码审查应要求对“动态路径”用 `load()`，对固定编辑器资源可用 `preload()`，但绝不能用字符串拼接后的 `preload()`。

```text
### preload
- **签名**：`preload(path)` / `GD.Load<T>(string path)`（C# 通常直接运行期加载）
- **用途**：在脚本解析期加载固定资源。
- **误用**：拼接路径；从用户/网络数据构造 preload；假定 preload 返回独立实例。
- **判据（源码特征）**
  - GDScript：`preload\s*\(`
  - 风险：`preload\s*\(\s*(?:"[^"]*"\s*\+|[A-Za-z_]+)`（参数为拼接/变量）
- **确认**
  1. 参数必须是常量资源路径。
  2. 对动态路径改用 `load()`/`load_threaded_request()`。
  3. 测试热重载与导出包，确认资源未丢失。
- **置信度：官方明确**
```

**线程化加载不是“fire-and-forget”，必须持续轮询状态并最终取出资源。** 官方签名包括 `load_threaded_request()`、`load_threaded_get_status(path, progress=[])` 和 `load_threaded_get(path)` [5]。状态包括未请求、轮询队列、加载中、完成、失败、已取消等枚举；仅在请求后立刻 `get()` 会得到尚未完成的资源。应使用进度数组更新 UI，达到完成态后再 `get()`，并在失败/取消分支重置状态机。

```text
### ResourceLoader.load_threaded_request / load_threaded_get_status / load_threaded_get
- **签名**：`load_threaded_request(path, type_hint="", use_sub_threads=false, cache_mode=1)` / `load_threaded_get_status(path, progress=[])` / `load_threaded_get(path)`
- **用途**：在线程中加载资源并查询状态。
- **误用**：请求后立即 get；只判断“成功/失败”二元状态；在回调中修改场景树前不检查主线程；忘记取消。
- **判据（源码特征）**
  - GDScript：`load_threaded_request\s*\(|load_threaded_get_status\s*\(|load_threaded_get\s*\(`
  - C#：`LoadThreadedRequest\s*\(|LoadThreadedGetStatus\s*\(|LoadThreadedGet\s*\(`
  - 反模式：`load_threaded_request\s*\([^)]*\)\s*\n\s*var\s+\w+\s*=\s*ResourceLoader\.load_threaded_get`
- **确认**
  1. 状态机至少处理 IN_PROGRESS、DONE、FAILED、CANCELED。
  2. 用 `progress[0]` 驱动 UI，避免假死的 0/1 跳变。
  3. 切换场景时取消未完成任务并丢弃回调结果。
- **置信度：官方明确**
```

**`CacheMode` 五态并非“写时复制”或“立即卸载”的同义词。** 官方 4.x 文档列出 `CACHE_MODE_IGNORE=0`、`REUSE=1`、`REPLACE=2`、`IGNORE_DEEP=3`、`REPLACE_DEEP=4` [5]。具体深/浅语义与实现版本有关，审查规则不应自行断言内存效果，而应强制要求注释“为什么选这个模式”并配套测试。无特殊理由的业务代码默认 `REUSE`，对热重载或外部修改检测使用 `IGNORE/REPLACE` 时，要明确谁拥有缓存、何时失效。

```text
### ResourceLoader.CacheMode
- **签名**：`ResourceLoader.CACHE_MODE_IGNORE/REUSE/REPLACE/IGNORE_DEEP/REPLACE_DEEP`
- **用途**：控制资源加载如何复用或替换缓存。
- **误用**：把 IGNORE 理解为“立即卸载旧资源”；把 REPLACE 当作安全热重载；任意切换导致共享 Resource 状态不一致。
- **判据（源码特征）**
  - GDScript：`CACHE_MODE_(?:IGNORE|REUSE|REPLACE|IGNORE_DEEP|REPLACE_DEEP)`
  - C#：`CacheMode\.(?:Ignore|Reuse|Replace|IgnoreDeep|ReplaceDeep)`
- **确认**
  1. 检查调用处注释与资源所有权。
  2. 用两个独立引用测试缓存替换前后的对象身份。
- **置信度：官方明确存在五值；精确内存影响须以版本实测为准**
```

**`exists()` 只能验证“已识别资源”，不能保证实例化或运行期可用。** 官方签名 `exists(path, type_hint="")` 返回指定路径是否存在可识别资源 [5]。它不验证脚本编译、依赖完整、平台可用性或内容合法。正确流程应是 exists → 加载 → 判空 → 检查类型/关键字段 → 进入业务逻辑。

```text
### ResourceLoader.exists
- **签名**：`exists(path, type_hint="")` / `bool Exists(string path, string typeHint = "")`
- **用途**：检查路径是否有可识别资源。
- **误用**：用 exists 替代 load 判空；检查后未防止资源被并发替换/卸载。
- **判据（源码特征）**
  - GDScript：`ResourceLoader\.exists\s*\(`
  - C#：`ResourceLoader\.Exists\s*\(`
- **确认**
  1. 验证调用后立即加载的结果仍非 null。
  2. 对外部来源资源同时检查扩展名白名单和 load 返回类型。
- **置信度：官方明确**
```

**`get_dependencies()` 适合构建依赖图，不能证明依赖可加载。** 官方签名 `get_dependencies(path)` 返回指定资源路径的依赖 [5]。可用于构建打包允许列表、检测循环引用或分析存档依赖。风险在于依赖字符串通常是资源路径，必须经过允许列表、规范化及存在性检查，不能直接拼接成 `load()` 参数。

```text
### ResourceLoader.get_dependencies
- **签名**：`get_dependencies(path)` / `string[] GetDependencies(string path)`
- **用途**：取得资源依赖列表。
- **误用**：直接 load 返回的依赖字符串；未处理相对/绝对路径和平台差异。
- **判据（源码特征）**
  - GDScript：`get_dependencies\s*\(`
  - C#：`GetDependencies\s*\(`
- **确认**
  1. 对依赖路径应用 `ResourceLoader.exists()` 与资源类型白名单。
  2. 将依赖结果用于只读分析或明确授权的导入管线。
- **置信度：官方明确**
```

**`has_cached()`/`get_cached_ref()` 读取缓存身份，不能替代资源有效性。** 官方文档分别提供“是否存在缓存资源”和“取得缓存资源引用”的查询 [5]。判空后仍要检查它是否符合当前预期版本；若代码同时调用 `take_over_path()`，需要验证是否读取到测试替身或热重载对象。

```text
### ResourceLoader.has_cached / get_cached_ref
- **签名**：`has_cached(path)` / `get_cached_ref(path)`
- **用途**：查询资源缓存状态与引用。
- **误用**：假定缓存对象是最新资源；修改缓存对象并影响所有持有者。
- **判据（源码特征）**
  - GDScript：`has_cached\s*\(|get_cached_ref\s*\(`
  - C#：`HasCached\s*\(|GetCachedRef\s*\(`
- **确认**
  1. 检查资源身份、修改路径和是否需要 duplicate。
  2. 若缓存结果用于断言，测试在 hot-reload/REPLACE 后仍然正确。
- **置信度：官方明确**
```

**`list_directory()` 返回资源与子目录名称，不是通用文件系统递归遍历。** 官方签名 `list_directory(directory_path)` 返回资源及子目录 [5]。与 `DirAccess.get_directories_at()`/`get_files_at()` 的语义可能不同；审查器必须区分资源数据库目录和真实文件系统目录，不能把结果直接拼接为任意 `user://` 路径。

```text
### ResourceLoader.list_directory
- **签名**：`list_directory(directory_path)` / `string[] ListDirectory(string directoryPath)`
- **用途**：列出资源目录中的资源与子目录。
- **误用**：递归拼接任意用户路径；将目录名当文件绝对路径；未处理权限/不存在情况。
- **判据（源码特征）**
  - GDScript：`list_directory\s*\(`
  - C#：`ListDirectory\s*\(`
- **确认**
  1. 把返回项规范化为子路径并重新检查存在性。
  2. 不把遍历结果作为可执行程序列表。
- **置信度：官方明确**
```

**`ResourceFormatLoader` 属于资源导入/加载扩展点，不应在普通游戏中重复注册。** 官方文档同时给出 `add_resource_format_loader()`/`remove_resource_format_loader()` [5]。审查重点是自定义模块/GDExtension 是否在初始化时注册、在卸载/热重载时移除，以及是否影响全局资源解析。

```text
### ResourceLoader.add_resource_format_loader / remove_resource_format_loader
- **签名**：`add_resource_format_loader(format_loader, at_front=false)` / `remove_resource_format_loader(format_loader)`
- **用途**：注册/注销资源格式加载器。
- **误用**：重复注册；插件关闭时未移除；通过 at_front 改变既有资源解析顺序。
- **判据（源码特征）**
  - GDScript：`add_resource_format_loader\s*\(|remove_resource_format_loader\s*\(`
  - C#：`AddResourceFormatLoader\s*\(|RemoveResourceFormatLoader\s*\(`
- **确认**
  1. 检查插件的 `_enable()`/`_disable()` 生命周期。
  2. 测试在注册顺序变化后仍能加载核心资源。
- **置信度：官方明确**
```

### 3.2 ResourceSaver 与导出路径注解

**4.x 的 `ResourceSaver.save()` 参数顺序是“资源优先、路径其次”。** 官方签名 `save(resource, path="", flags=0)` 与旧文档中的参数顺序不同；迁移指南特别指出 `ResourceSaver.save()` 的 resource/path 顺序已交换 [6]。因此 3.x 迁移项目若出现旧顺序或位置参数，应列为 BLOCKER 或至少要求显式命名参数。

```text
### ResourceSaver.save
- **签名**：`ResourceSaver.save(resource, path="", flags=0)` / `ResourceSaver.Save(resource, path, flags)`
- **用途**：把资源持久化到磁盘。
- **误用**：沿用 3.x 参数顺序；写入 res://；path 为空却依赖 resource_path；忽略 Error 返回值。
- **判据（源码特征）**
  - GDScript：`ResourceSaver\.save\s*\(`
  - C#：`ResourceSaver\.Save\s*\(`
  - 反模式：`save\s*\(\s*"res://|save\s*\(\s*[A-Za-z_0-9_.]+\s*,\s*[A-Za-z_0-9_.]+\s*\)`（未命名、顺序难辨）
- **确认**
  1. 对 3.x 项目检查所有 save 调用参数顺序。
  2. 保存结果写入 `user://` 或已授权可写路径，并处理返回值。
  3. 写后校验文件可读，再删除旧备份。
- **置信度：官方明确**
```

**`get_recognized_extensions()` 是格式选择辅助，不验证资源内容可保存。** 官方签名 `get_recognized_extensions(type)` 返回资源类型对应的扩展名 [6]。它适合在保存对话框中选择格式，不能保证该资源实际可序列化，也不能保证结果跨引擎版本稳定。

```text
### ResourceSaver.get_recognized_extensions
- **签名**：`get_recognized_extensions(type)` / `string[] GetRecognizedExtensions(Resource type)`
- **用途**：取得资源类型的可识别保存扩展名。
- **误用**：凭扩展名判定资源类型；把返回的扩展名硬编码成唯一存档格式。
- **判据（源码特征）**
  - GDScript：`get_recognized_extensions\s*\(`
  - C#：`GetRecognizedExtensions\s*\(`
- **确认**
  1. 用返回数组判断 UI 选项，而不是推断资源是否可保存。
  2. 对存档格式显式固定版本号与扩展名。
- **置信度：官方明确**
```

**`FLAG_RELATIVE_PATHS`、`FLAG_BUNDLE_RESOURCES`、`FLAG_CHANGE_PATH` 会改变引用与资源路径语义。** 官方说明分别用于相对路径、捆绑外部资源和把保存资源的 `resource_path` 改成新位置 [6]。三者组合错误可能造成存档目录里的资源指向编辑器资源、导出后相对路径失效，或保存后的 Resource 通过 `take_over_path()` 覆盖其他加载。规则应要求对存档保存显式枚举 flags，禁止从配置/网络读取 flag 位。

```text
### ResourceSaver.SaverFlags
- **签名**：`FLAG_NONE=0|FLAG_RELATIVE_PATHS=1|FLAG_BUNDLE_RESOURCES=2|FLAG_CHANGE_PATH=4`
- **用途**：控制资源保存路径和依赖处理方式。
- **误用**：把 FLAG_CHANGE_PATH 用于外部文件；使用 FLAG_BUNDLE_RESOURCES 后不验证依赖；flags 来自外部输入。
- **判据（源码特征）**
  - GDScript：`FLAG_(?:RELATIVE_PATHS|BUNDLE_RESOURCES|CHANGE_PATH)`
  - C#：`SaverFlags\.(?:RelativePaths|BundleResources|ChangePath)`
- **确认**
  1. 保存后立即 reload 并比较关键字段。
  2. 检查保存资源的 `resource_path` 是否为预期的 `user://` 路径。
- **置信度：官方明确**
```

**`load()`/`save()` 之外的资源选择注解主要用于编辑器/工具选择，不提供运行期路径安全。** `@export_file`/`@export_dir` 输出相对于项目文件系统的路径，`@export_global_file`/`@export_global_dir` 输出全局文件系统路径 [11]。官方说明全局路径通常只在 tool 模式脚本中可用。因此运行期接收这些值后仍需归一化、允许列表和存在性检查；它们不能阻止高级用户或外部工具写入恶意路径。

```text
### @export_file / @export_dir / @export_global_file / @export_global_dir
- **签名**：`@export_file @export_file(".txt") @export_dir @export_global_file(".png") @export_global_dir`
- **用途**：在检查器中提供路径选择。
- **误用**：在运行期把任意 export 路径拼接为读/写目标；把 filter 当内容验证；将 global 路径用于发布游戏运行期。
- **判据（源码特征）**
  - GDScript：`@export_file\s*\(|@export_dir|@export_global_file\s*\(|@export_global_dir`
- **确认**
  1. 检查使用处是否在 `tool` 脚本或编辑器插件中。
  2. 路径使用前调用 `ProjectSettings.globalize_path()` 并再次校验前缀与存在性。
  3. 对存档选择 UI 使用显式文件对话框，而非无约束文本输入。
- **置信度：官方明确（注解与 tool 限制）；运行期安全处理为审查判断**
```

## 4. FileAccess：返回值、错误状态与关闭语义必须同时检查

### 4.1 打开、读取与写入

**4.x 中 `FileAccess.open()` 返回 null 表示失败，不再存在 `File.new()` 模式。** 官方签名 `FileAccess.open(path, flags)` 创建对象并依 flags 打开文件；`get_open_error()` 返回当前线程上一次 `open()` 的结果 [7]。若仍写 `var f = File.new(); f.open(...)`，属于 3.x 残留，必须阻断。

```text
### FileAccess.open
- **签名**：`FileAccess.open(path, flags)` / `FileAccess.Open(path, flags)`
- **用途**：打开文件并返回 FileAccess 对象。
- **误用**：沿用 3.x `File.new()`；不检查 null；打开失败后使用对象；多线程共享单线程 open 错误状态。
- **判据（源码特征）**
  - GDScript：`FileAccess\.open\s*\(|File\.new\s*\(`
  - C#：`FileAccess\.Open\s*\(`
- **确认**
  1. 判空并检查 `FileAccess.get_open_error()`。
  2. 对 3.x 项目执行全局 `File\.new\s*\(|File\(` 检查。
  3. 用不存在路径、只读目录和占用文件做失败注入测试。
- **置信度：官方明确**
```

**写入模式不只是“打开”，`WRITE` 会截断已有文件，`READ_WRITE` 不会。** 官方说明 `READ=1`、`WRITE=2`（存在则清空，否则创建）、`READ_WRITE=3`（不清空）、`WRITE_READ=7`（存在则清空，否则创建）[7]。这是典型的数据破坏风险：想追加却用 `WRITE`，会清空存档；想就地覆盖又用 `READ_WRITE`，可能在未截断的前提下写入较短内容，残留旧尾部数据。

```text
### FileAccess ModeFlags：READ/WRITE/READ_WRITE/WRITE_READ
- **签名**：`FileAccess.READ/WRITE/READ_WRITE/WRITE_READ`
- **用途**：选择文件打开语义。
- **误用**：把 WRITE 当追加；把 READ_WRITE 当安全覆盖；忽略平台换行与编码。
- **判据（源码特征）**
  - GDScript：`FileAccess\.(READ|WRITE|READ_WRITE|WRITE_READ)`
  - C#：`FileAccess\.ModeFlags\.(Read|Write|ReadWrite|WriteRead)`
- **确认**
  1. 对存档写盘采用“写临时文件→fsync/关闭→原子替换”模式。
  2. 用截断/非空旧文件测试三种写入模式的实际结果。
- **置信度：官方明确**
```

**`get_as_text()` 按 UTF-8 解释，且忽略光标；逐行读取则推进光标。** 官方文档说明 `get_as_text()` 返回完整文本、按 UTF-8 解释、不影响光标；`get_line()` 返回下一行并前进到换行后，且去掉 `\n`/`\r` [7]。因此两者不可混用并假定光标位置一致；解析完 `get_as_text()` 后再 `get_var()` 往往不是从文件开头开始。

```text
### FileAccess.get_as_text / get_line
- **签名**：`get_as_text()` / `get_line()`
- **用途**：分别读取完整 UTF-8 文本和下一行。
- **误用**：混用全量文本与行光标；把去换行结果当原始行；假定编码总是 UTF-8。
- **判据（源码特征）**
  - GDScript：`get_as_text\s*\(|get_line\s*\(`
  - C#：`GetAsText\s*\(|GetLine\s*\(`
- **确认**
  1. 明确解码策略；解析 JSON/INI 前读取全量文本。
  2. 在测试中放入 BOM、CRLF、非 UTF-8 字节并记录处理策略。
- **置信度：官方明确**
```

**`store_string()` 不写换行，`store_line()` 写换行；二者不可互换。** 官方说明 `store_string()` 以 UTF-8 存储且不附加 `\n`，`store_line()` 存储后附加 `\n` [7]。存档程序若假定“每次 store 都是一行”，后续 `get_line()` 解析可能合并/错位。审查规则可要求：所有“行协议”使用 `store_line`，所有“定长/二进制块”使用 `store_string`/`store_buffer`。

```text
### FileAccess.store_string / store_line
- **签名**：`store_string(string)` / `store_line(line)`
- **用途**：分别写入无换行 UTF-8 字符串和带换行字符串。
- **误用**：用 store_string 写行协议；把 store_line 用于二进制或固定宽度数据。
- **判据（源码特征）**
  - GDScript：`store_string\s*\(|store_line\s*\(`
  - C#：`StoreString\s*\(|StoreLine\s*\(`
- **确认**
  1. 对保存文件做十六进制尾部检查，确认是否存在预期换行。
  2. 读取解析器必须与写入器位于同一协议模块。
- **置信度：官方明确**
```

**`store_var()`/`get_var()` 的可变对象选项不应面向外部数据。** 官方文档明确把 `store_var(value, full_objects=false)` 与 `get_var(allow_objects=false)` 中的对象选项标为风险来源；打开时可能执行反序列化代码，来自不可信来源时可导致远程代码执行 [7][10]。因此存档格式应优先使用 JSON/ConfigFile/显式字段，而不是把任意脚本对象序列化。

```text
### FileAccess.store_var / get_var
- **签名**：`store_var(value, full_objects=false)` / `get_var(allow_objects=false)`
- **用途**：以 Godot 的 Variant 二进制格式存取数据。
- **误用**：用 allow_objects/full_objects 读取用户或网络数据；跨引擎版本长期依赖私有格式；忽略返回值。
- **判据（源码特征）**
  - GDScript：`store_var\s*\(|get_var\s*\(`
  - C#：`StoreVar\s*\(|GetVar\s*\(`
  - BLOCKER：`get_var\s*\(\s*true\s*\)|store_var\s*\([^)]*true\s*\)` 且数据来源包含网络/外部文件
- **确认**
  1. 数据来自 `user://` 存档时仍不得打开对象反序列化，除非使用签名/完整性校验并由受保护目录写入。
  2. 比较强类型自定义格式与 Variant 二进制的版本迁移成本。
- **置信度：官方明确**
```

**`file_exists()` 有竞态窗口，不能单独保证随后打开成功。** 官方提供静态 `file_exists(path)` [7]。迁移文档还提示，资源可能在导出时打包进 `.pck`，不能直接把项目目录的存在性套到导出环境。正确写法是：先确保目标目录存在，再尝试打开，检查 open 错误，必要时处理“已被占用/权限不足”。

```text
### FileAccess.file_exists
- **签名**：`FileAccess.file_exists(path)` / `FileAccess.FileExists(string path)`
- **用途**：检查文件是否存在。
- **误用**：用“存在”推断“可读/可写/未损坏”；把编辑器中的 res:// 存在性当作导出后存在性。
- **判据（源码特征）**
  - GDScript：`FileAccess\.file_exists\s*\(`
  - C#：`FileAccess\.FileExists\s*\(`
- **确认**
  1. 实际打开并读取校验值/魔术字段/版本号。
  2. 对 res:// 使用 ResourceLoader，对 user:// 使用 FileAccess。
- **置信度：官方明确**
```

**`close()` 不是唯一释放路径，但应作为显式所有权边界。** 官方文档说明 FileAccess 会随对象释放、离开作用域或被赋 `null` 自动关闭 [7]。不过显式 `close()` 能减少对象生命周期误判、及早暴露文件占用，并使异常/提前返回逻辑更清晰。审查器应标记超过约 50 行仍不关闭、跨函数保存 FileAccess 引用，或在 `_process` 中打开而不关闭的模式。

```text
### FileAccess.close
- **签名**：`close()` / `void Close()`
- **用途**：显式关闭文件并阻止后续读写。
- **误用**：打开后不关闭；提前 return 时未关闭；在多线程中并发读写同一句柄。
- **判据（源码特征）**
  - GDScript：`\.open\s*\((?:(?!close\s*\(|return\b)[\s\S]){0,1500}`（启发式：长作用域未见 close）
  - 更稳妥：`FileAccess\.open\s*\(` 后同作用域缺少 `finally|close\s*\(|return\s*` 等控制流
- **确认**
  1. 构造文件句柄泄漏测试：连续打开 1000 次并立即回收，检查平台句柄/临时文件占用。
  2. 对提前返回路径验证局部 FileAccess 被设为 null 或离开作用域。
- **置信度：官方明确有自动关闭；何时要求显式 close 为工程审查判断**
```

**`get_open_error()` 是线程局部状态，`get_error()` 是对象操作状态。** 官方分别定义静态 `get_open_error()` 与对象方法 `get_error()` [7]。把后者当 open 失败码、或在多线程中依赖全局单例保存上一次错误，都会误判。审查器应要求紧接 `open()` 调用 `get_open_error()`，且在多线程代码中将错误值保存在局部变量。

```text
### FileAccess.get_open_error / get_error
- **签名**：`get_open_error()` / `get_error()`
- **用途**：分别取得最近一次 open 结果与最近一次操作错误。
- **误用**：混用二者；跨函数/跨线程读取；忽略结果。
- **判据（源码特征）**
  - GDScript：`get_open_error\s*\(|get_error\s*\(`
  - C#：`GetOpenError\s*\(|GetError\s*\(`
- **确认**
  1. 紧邻 open 后读取并打印错误码。
  2. 写/读后检查 `get_error()`，避免静默截断或编码失败。
- **置信度：官方明确**
```

### 4.2 路径系统与 DirAccess

**`res://` 在编辑器中通常可编辑，在导出后一般只读，不应写入存档。** 官方文档指出项目中的文件使用 `res://`，导出后的数据/用户文件使用 `user://`；资源会打包到 `.pck` 或可执行文件中，运行期访问机制因导出模板不同而异 [8]。因此写入 `res://saves/save.json` 在编辑器可能“正常”，导出后失败。规则库应将“`user://` 以外的运行时写入目标”设为 BLOCKER。

```text
### res:// 与 user://
- **签名**：路径字面量 `res://...`、`user://...`
- **用途**：分别访问项目资源与持久化用户数据。
- **误用**：在发布版本写入 res://；把 user:// 绝对位置当跨平台稳定常量；将存档目录暴露给不受控路径拼接。
- **判据（源码特征）**
  - GDScript：`"res://(?!(?:icon|assets|.*\.(?:png|wav|tscn|tres|res)))[\w./-]+\.(?:json|cfg|save|dat)`
  - 一般：`(FileAccess|DirAccess|ResourceSaver)\.(?:open|save|remove|make_dir_recursive)\s*\([^)]*"res://`
- **确认**
  1. 在 Windows/macOS/Linux/iOS/Android 导出目标上实际写入并重启读取。
  2. 用 `ProjectSettings.globalize_path("user://")` 记录实际目录，但不把它当安全保证。
- **置信度：官方明确**
```

**`ProjectSettings.globalize_path()` 是诊断/工具 API，不是运行期“任意路径转安全路径”的转换器。** 官方说明它把 `res://`/`user://` 等虚拟路径转为真实路径 [8]。它可能暴露内部目录，因此不应回显给玩家、写入日志服务器，更不能用它把用户提供的相对路径变成绝对路径。

```text
### ProjectSettings.globalize_path
- **签名**：`ProjectSettings.globalize_path(path)` / `ProjectSettings.GlobalizePath(string path)`
- **用途**：把 Godot 虚拟路径转换为平台真实路径。
- **误用**：转换不受控字符串；把返回值拼接成新可写路径；泄露真实路径到日志。
- **判据（源码特征）**
  - GDScript：`globalize_path\s*\(`
  - C#：`GlobalizePath\s*\(`
- **确认**
  1. 调用前只允许 `user://`/内部常量前缀。
  2. 调用后对结果重新校验位于允许目录内。
- **置信度：官方明确；路径白名单策略为审查判断**
```

**`OS.get_user_data_dir()` 与应用/系统策略相关，不能假定等于 `user://`。** 官方说明 Godot 使用 `user://` 作为持久化数据路径；具体目录受 `OS.get_user_data_dir()`、项目名、导出名及平台规则影响 [8]。规则不应硬编码 `C:/Users/...`、`~/Library/...` 或 Android 内部路径。跨平台保存测试应检查真实绝对路径，而不是依赖正则预测。

```text
### OS.get_user_data_dir
- **签名**：`OS.get_user_data_dir()` / `OS.GetUserDataDir()`
- **用途**：取得平台用户数据目录。
- **误用**：硬编码平台目录；假定它与 user:// 完全一致；跨用户/沙箱访问。
- **判据（源码特征）**
  - GDScript：`OS\.get_user_data_dir\s*\(`
  - C#：`OS\.GetUserDataDir\s*\(`
- **确认**
  1. 在目标平台运行诊断场景，输出 `ProjectSettings.globalize_path("user://")`。
  2. 检查应用卸载/重装/权限策略下的数据保留要求。
- **置信度：官方明确**
```

**`DirAccess` 不能 `new()`，必须 `open()`；目录遍历需要 begin/next/end 的生命周期匹配。** 官方说明 DirAccess 不能直接实例化，必须通过静态 `open()`；`list_dir_begin()` 初始化目录流，`list_dir_next()` 逐条读取，`list_dir_end()` 结束 [9]。常见错误是 begin 后发生提前返回，却没有 end；或 next 返回的 `.`/`..` 被当作普通条目。

```text
### DirAccess.open / list_dir_begin / list_dir_next / list_dir_end
- **签名**：`DirAccess.open(path)` / `list_dir_begin(skip_navigation=true, skip_hidden=true)` / `list_dir_next()` / `list_dir_end()`
- **用途**：打开目录并遍历其内容。
- **误用**：DirAccess.new()；遍历期间提前返回未 end；把 . 和 .. 当文件；目录不存在未处理。
- **判据（源码特征）**
  - GDScript：`DirAccess\.open\s*\(|list_dir_begin\s*\(|list_dir_next\s*\(|list_dir_end\s*\(`
  - C#：`DirAccess\.Open\s*\(|ListDirBegin\s*\(|ListDirNext\s*\(|ListDirEnd\s*\(`
- **确认**
  1. 使用 `try/finally` 或显式控制流确保 `list_dir_end()`。
  2. 跳过 `.` 和 `..`，并根据 `current_is_dir()` 分类。
- **置信度：官方明确**
```

**`make_dir_recursive()` 只创建目录，不赋予游戏额外文件权限。** 官方将其描述为静态方法，创建目标及其所有中间目录 [9]。它不等价于“确认可写”，也不验证磁盘空间。存档初始化应在创建目录后真正打开一次文件或检查目标路径的写入结果。

```text
### DirAccess.make_dir_recursive
- **签名**：`DirAccess.make_dir_recursive(path)` / `static Error MakeDirRecursive(string path)`
- **用途**：递归创建目录。
- **误用**：目录已存在就假定可写；路径来自用户输入且未规范化；把“创建成功”当“保存成功”。
- **判据（源码特征）**
  - GDScript：`DirAccess\.make_dir_recursive\s*\(`
  - C#：`DirAccess\.MakeDirRecursive\s*\(`
- **确认**
  1. 对父目录存在/不存在、权限不足、同名文件占位三种场景测试。
  2. 创建后尝试写入并关闭一个临时文件。
- **置信度：官方明确**
```

**`DirAccess.remove()` 不是递归删除工具，尤其不能把玩家目录当单个文件删除。** 官方说明它删除文件或空目录；目录非空时会失败 [9]。如果需求是递归清理，必须由白名单遍历实现，并对每个条目确认位于允许目录内。直接对 `user://` 或其父目录执行递归删除属于 BLOCKER。

```text
### DirAccess.remove
- **签名**：`remove(path)` / `Error Remove(string path)`
- **用途**：删除文件或空目录。
- **误用**：删除非空目录；把相对路径当规范化绝对路径；未检查返回值；递归删除用户目录。
- **判据（源码特征）**
  - GDScript：`DirAccess\.remove\s*\(|dir_access\.remove\s*\(`
  - C#：`DirAccess\.Remove\s*\(`
- **确认**
  1. 检查路径必须位于 `user://saves` 等明确子目录。
  2. 验证返回值；非空目录删除失败需显式递归策略。
- **置信度：官方明确**
```

**`copy_absolute()` 会覆盖目标文件，必须防止目标逃逸出允许目录。** 官方签名 `copy_absolute(from, to, chmod_flags=-1)` 在目标存在时覆盖，并可设置 Unix 权限 [9]。风险不仅是覆盖存档，还包括把任意来源复制到可执行目录或用户配置目录。规则应同时校验源存在性、目标前缀、覆盖确认和权限默认值。

```text
### DirAccess.copy_absolute
- **签名**：`copy_absolute(from, to, chmod_flags=-1)` / `Error CopyAbsolute(string from, string to, int chmodFlags = -1)`
- **用途**：复制文件并可选地设置权限。
- **误用**：覆盖目标不确认；源/目标路径未规范化；从下载目录复制可执行文件；赋予 0777 权限。
- **判据（源码特征）**
  - GDScript：`copy_absolute\s*\(`
  - C#：`CopyAbsolute\s*\(`
- **确认**
  1. 目标位于明确允许目录，并进行 realpath/前缀比较。
  2. 除非必要，不传非零 `chmod_flags`。
  3. 测试源不存在、目标存在、跨卷复制失败。
- **置信度：官方明确**
```

## 5. JSON、ConfigFile 与 Variant 序列化：格式选择决定兼容性与攻击面

### 5.1 JSON 的两种解析接口

**`JSON.parse()` 与 `JSON.parse_string()` 的错误能力不同，不能互换。** 官方说明 `parse(json_text, keep_text=false)` 返回 `Error`，成功时为 `OK` 且可通过 `data` 获取结果，失败时可用 `get_error_line()`/`get_error_message()`；`parse_string(json)` 是静态方法，失败时返回 `null` [12]。审查器应优先在存档/网络入口使用 `parse()`，以便定位错误；只有调用者明确能接受“失败即 null”的简单场景，才允许 `parse_string()`。

```text
### JSON.parse / JSON.parse_string
- **签名**：`var json = JSON.new(); json.parse(text)` / `JSON.ParseString(string json)`
- **用途**：把 JSON 文本解析为 Variant。
- **误用**：用 parse_string 解析网络数据却无法区分 null 数据与失败；未检查 OK；解析巨量文本导致卡顿。
- **判据（源码特征）**
  - GDScript：`JSON\.parse\s*\(|JSON\.parse_string\s*\(|\.parse\s*\(json`
  - C#：`JSON\.ParseString\s*\(|json\.Parse\s*\(`
- **确认**
  1. 用格式错误、UTF-8 截断、超大输入、嵌套过深数据测试。
  2. 错误路径记录 `get_error_line()`/`get_error_message()`，而非只打印“解析失败”。
- **置信度：官方明确**
```

**`JSON.stringify()` 是 Variant 到 JSON 的静态转换，输出不能直接假定包含自定义对象全部语义。** 官方签名 `stringify(data, indent="", sort_keys=true, full_precision=false)` [12]。自定义 Resource、函数、Object 引用、循环结构不一定能无损表达。判据应要求存档对象先经 DTO/字典转换，明确字段、类型、版本与缺省值，避免“`to_json(my_resource)`”的错觉。

```text
### JSON.stringify
- **签名**：`JSON.stringify(data, indent="", sort_keys=true, full_precision=false)` / `JSON.Stringify(Variant data, ...)`
- **用途**：把 Variant 转换为 JSON 文本。
- **误用**：直接序列化 Resource/Node；依赖键顺序；忽略浮点精度；把字典当稳定 schema。
- **判据（源码特征）**
  - GDScript：`JSON\.stringify\s*\(`
  - C#：`JSON\.Stringify\s*\(`
- **确认**
  1. 对存档模型使用显式 `to_dict()`/`from_dict()`。
  2. 测试 `Vector2`/`Color`/`Rect2`/自定义类型在读写后的精度与字段完整性。
- **置信度：官方明确**
```

**`JSON.ParseResult` 的存在不能被当作成功结果。** 官方教程中的 `JSON.parse()` 流程先检查返回 Error，再从解析器取得 `data` [12]。若代码直接读取 `ParseResult.data` 而不检查状态，或在 parse 失败后继续业务处理，应列为 MAJOR。

```text
### JSON.ParseResult
- **签名**：`JSON.parse()` 后访问 `result.error`、`result.error_string`、`result.error_line`、`result.data`
- **用途**：携带 JSON 解析状态与结果。
- **误用**：只读取 result.data；把 error_string 暴露给玩家；使用行号却不检查 error 枚举。
- **判据（源码特征）**
  - GDScript：`result\.data|get_error_line|get_error_message`
- **确认**
  1. 检查解析器状态后再访问 data。
  2. 日志记录与玩家提示分离，避免泄露内部路径。
- **置信度：官方明确**
```

### 5.2 ConfigFile 的字段安全与事务语义

**ConfigFile 适合简单键值配置，不适合保存未迁移的任意对象图。** 官方 API 包括 `set_value(section, key, value)`、`get_value(section, key, default)`、`load(path)`、`save(path)`、`has_section(section)` [13]。其 INI 风格适合设置、按键映射和小型元数据；存档若含数组、嵌套对象、版本迁移和二进制数据，应使用 JSON+FileAccess 或 Resource+ResourceSaver。

```text
### ConfigFile
- **签名**：`var cfg = ConfigFile.new(); cfg.set_value(sec,key,val); cfg.save(path)` / `ConfigFile cfg = new ConfigFile(); cfg.SetValue(...); cfg.Save(path)`
- **用途**：以分节键值结构持久化简单配置。
- **误用**：把所有存档塞进 INI；键名由外部输入拼接；保存失败后未回滚；同一 ConfigFile 在多个系统间共享可变状态。
- **判据（源码特征）**
  - GDScript：`ConfigFile\.new\s*\(|set_value\s*\(|get_value\s*\(`
  - C#：`new ConfigFile\s*\(|SetValue\s*\(|GetValue\s*\(`
- **确认**
  1. 定义允许的 section/key 白名单。
  2. 测试加载损坏/缺少 section 的配置文件，并正确返回默认值。
- **置信度：官方明确**
```

**`get_value()` 的默认值不只是“便利参数”，而是 schema 兼容机制。** 官方签名允许 `get_value(section, key, default=null)` [13]。若调用者省略默认值并把 `null` 直接用于算术或 UI，会导致后续崩溃；若类型与预期不同，也会在运行期才暴露。审查规则应要求保存和读取使用同一类型集合，并在新增键时显式提供默认值。

```text
### ConfigFile.get_value
- **签名**：`get_value(section, key, default=null)` / `Variant GetValue(string section, string key, Variant defaultValue)`
- **用途**：读取配置值，缺失时返回默认值。
- **误用**：忽略 default；把 null 直接转为 int/float；跨版本读取旧键不迁移。
- **判据（源码特征）**
  - GDScript：`get_value\s*\([^,]+,[^,]+\)`（无第三个参数）
  - C#：`GetValue\s*\([^,]+,\s*[^,]+\)`
- **确认**
  1. 对必需键提供 default，并检查类型后使用。
  2. 配置升级代码先复制旧值，再写入新 schema 版本号。
- **置信度：官方明确**
```

**`ConfigFile.load()`/`save()` 是完整读写的 IO 事务，不是字段级原子操作。** 官方将两者定义为完整加载/保存路径 [13]。保存中途失败会留下旧文件或部分文件，因此必须采用临时文件加替换，或在确认目录可写后写新文件。规则不应把 `save()` 的 `OK` 当作“磁盘已持久化”的充分条件；对强一致需求还需平台特定 fsync/文件替换策略。

```text
### ConfigFile.load / save
- **签名**：`load(path)` / `save(path)`
- **用途**：从 INI 文件加载/保存全部配置。
- **误用**：同步加载未处理 Error；保存覆盖原文件；路径为 res://；忽略相对路径。
- **判据（源码特征）**
  - GDScript：`config\.load\s*\(|config\.save\s*\(|ConfigFile\.load\s*\(`
  - C#：`\.Load\s*\(|\.Save\s*\(`
- **确认**
  1. 保存流程：临时文件 → close/flush → 替换原文件。
  2. 测试磁盘满、目录只读、文件被占用三种失败路径。
- **置信度：官方明确**
```

**`has_section()` 只证明节存在，不能证明所需键存在。** 官方签名 `has_section(section)` [13]。配置迁移应依次验证 section、key、类型与范围，而不是只判断节名。反模式是 `if cfg.has_section("Graphics")` 后直接读取 `fullscreen`，缺少键时可能拿到 `null`。

```text
### ConfigFile.has_section
- **签名**：`has_section(section)` / `bool HasSection(string section)`
- **用途**：检查配置节是否存在。
- **误用**：用节存在推断全部键存在；检查后不处理并发文件替换。
- **判据（源码特征）**
  - GDScript：`has_section\s*\(`
  - C#：`HasSection\s*\(`
- **确认**
  1. 对每个关键键提供默认值和类型检查。
  2. 迁移测试使用缺 key、缺 section、未知 section 三种样例。
- **置信度：官方明确**
```

### 5.3 Variant 二进制的对象反序列化红线

**Variant 二进制格式的最大风险不是体积，而是对象可执行语义。** 官方文档明确警告：反序列化对象可能包含会被执行的代码，不可信来源的 `allow_objects/full_objects` 选项可造成远程代码执行 [10]。因此 BLOCKER 应绑定“数据来源 × 标志位”：网络响应、玩家导入文件、模组包、下载缓存、任意文本输入中的任一组合打开对象反序列化，均不得放行。

```text
### @GlobalScope.var_to_bytes / bytes_to_var / var_to_str / str_to_var
- **签名**：`var_to_bytes(variant, full_objects=false)` / `bytes_to_var(bytes, allow_objects=false)` / `var_to_str(variant, full_objects=false)` / `str_to_var(string, allow_objects=false)`
- **用途**：把 Variant 与字节/文本互相转换。
- **误用**：从网络/外部文件读取对象；用对象标志做“深拷贝”或插件通信；跨版本长期保存私有格式；忽略返回值。
- **判据（源码特征）**
  - GDScript：`bytes_to_var\s*\(|var_to_bytes\s*\(|str_to_var\s*\(|var_to_str\s*\(`
  - C#：`BytesToVar\s*\(|VarToBytes\s*\(|StrToVar\s*\(|VarToStr\s*\(`
  - BLOCKER：`bytes_to_var\s*\(\s*[^,)]*\s*,\s*true|str_to_var\s*\(\s*[^,)]*\s*,\s*true`
- **确认**
  1. 所有外部来源统一使用 JSON/ConfigFile/显式二进制协议。
  2. 检查加载器是否验证 magic number、版本、长度上限和字段类型。
  3. 对受保护内部缓存，评估即使为 true 是否仍能被外部内容影响。
- **置信度：官方明确**
```

## 6. HTTP 与 HTTPClient：节点生命周期、线程和 TLS 共同决定请求可靠性

### 6.1 HTTPRequest 的高层 API

**HTTPRequest 必须由场景树驱动，光创建不 `add_child()` 不会正常处理。** 官方教程示例将 `HTTPRequest` 节点添加到场景树，并通过 `request_completed` 信号接收结果 [14]。它不是纯数据对象；离开树、父节点被释放或脚本在请求中途退出场景，都会中断请求。规则应标记创建后未 `add_child()`，以及 `add_child()` 后又没有移除/取消请求的资源生命周期。

```text
### HTTPRequest（节点生命周期）
- **签名**：`add_child(http_request)` / `AddChild(httpRequest)`
- **用途**：把 HTTPRequest 节点放入场景树，使其能处理请求生命周期。
- **误用**：`HTTPRequest.new()` 后直接 request；add_child 到短生命周期节点；请求未结束就 queue_free 父节点。
- **判据（源码特征）**
  - GDScript：`HTTPRequest\.new\s*\(|add_child\s*\([^)]*request`
  - C#：`new HttpRequest\s*\(|AddChild\s*\([^)]*request`
- **确认**
  1. 测试创建、发送、切换场景、返回响应四个时序。
  2. 在退出场景前调用 `cancel_request()`，并断开旧回调以防悬空处理。
- **置信度：官方明确**
```

**`request()` 返回 Error，信号参数也不是 HTTP 状态码的同义词。** 官方签名 `request(url, custom_headers=PackedStringArray(), method=0, request_body="")`；`request_completed(result, response_code, headers, body)` 中的 `result` 是连接/传输结果枚举，`response_code` 才是 HTTP 状态码 [14]。常见错误是只判断 `result == OK` 就认定业务成功，或把 `response_code != 0` 当成错误。

```text
### HTTPRequest.request
- **签名**：`request(url, custom_headers=[], method=0, request_body="")` / `Error Request(string url, ...)`
- **用途**：发起 HTTP 请求。
- **误用**：忽略返回 Error；url 来自不可信输入；body 未编码；请求前未取消旧请求。
- **判据（源码特征）**
  - GDScript：`\.request\s*\(`
  - C#：`\.Request\s*\(`
  - 风险：`request\s*\([^)]*url` 中 url 为外部拼接字符串
- **确认**
  1. 对 URL 使用固定 scheme/host 白名单与明确路径拼接。
  2. 检查返回 Error；并发请求采用独立节点或请求队列。
- **置信度：官方明确**
```

**`request_completed` 的四参数顺序不可重排，body 是 PackedByteArray 不是 String。** 官方信号为 `result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray` [14]。GDScript 连接处理中若写成 `func _on_completed(body, code, headers, result)` 会静默错配；C# 事件参数包也要检查顺序。进一步应根据 `Content-Type`/`Content-Encoding` 将 body 转 UTF-8 或 JSON，而非无条件 `get_string_from_utf8()`。

```text
### HTTPRequest.request_completed
- **签名**：`request_completed(result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray)`
- **用途**：通知 HTTP 请求完成并传递结果。
- **误用**：参数顺序错误；只判断 result 不判断 response_code；把 body 直接当 UTF-8 文本。
- **判据（源码特征）**
  - GDScript：`func\s+_on_[A-Za-z0-9_]*request_completed\s*\([^)]*\)`
  - C#：`RequestCompleted\s*\(object sender, SignalArgs e\)|void.*RequestCompleted`
- **确认**
  1. 对 handler 签名做 AST 参数顺序检查。
  2. 检查 HTTP 2xx、4xx、5xx、超时、DNS 失败各分支。
- **置信度：官方明确**
```

**`download_file` 只接受真实文件路径，不处理 JSON 响应解析。** 官方将 `download_file` 定义为下载目标路径，默认空字符串；`download_chunk_size` 默认 65536 [14]。若下载到 `user://`，必须先确保目录存在；若文件已存在，写入策略依赖底层打开语义。规则还应标记把 URL 路径段直接用作 `download_file` 的目录穿越问题。

```text
### HTTPRequest.download_file / download_chunk_size
- **签名**：`@export var download_file: String` / `@export var download_chunk_size: int = 65536`
- **用途**：指定请求结果下载到真实文件及分块大小。
- **误用**：把任意 URL 文件名拼成 download_file；目录不存在；分块过小导致频繁回调；下载文件未校验哈希。
- **判据（源码特征）**
  - GDScript：`download_file\s*=|download_chunk_size\s*=`
  - C#：`DownloadFile\s*=|DownloadChunkSize\s*=`
- **确认**
  1. 目标目录创建后检查返回值，再开始请求。
  2. 下载完成后比较大小、SHA-256/签名或期望 Content-Type。
- **置信度：官方明确**
```

**`use_threads=true` 把处理移入独立线程，回调并发和退出清理成为必须审查项。** 官方说明启用线程时请求在工作线程中处理，完成信号在主线程发射；退出游戏时未完成请求仍需清理 [14]。判据应标记“未取消请求就切换场景/退出”“回调访问已释放节点”和“共享可变状态无同步”。注意官方并未宣称所有 FileAccess/IO 操作都可在任意线程使用，因此下载后的解析逻辑仍应在主线程或明确支持的线程路径执行。

```text
### HTTPRequest.use_threads / timeout / cancel_request
- **签名**：`use_threads: bool` / `timeout: float` / `cancel_request()`
- **用途**：控制线程模式、超时和取消。
- **误用**：假定线程回调天然安全；未取消导致悬空回调；把 timeout=0 当“无限等待”；超时后仍访问旧响应。
- **判据（源码特征）**
  - GDScript：`use_threads\s*=|timeout\s*=|cancel_request\s*\(`
  - C#：`UseThreads\s*=|Timeout\s*=`
- **确认**
  1. 强制退出/场景切换时取消请求。
  2. 使用固定短超时与重试上限，避免永久挂起。
  3. 在回调开头检查 owner 是否仍有效。
- **置信度：官方明确**
```

**代理设置不是安全边界，TLS 证书验证与主机名校验才是。** `set_http_proxy(host, port)` 只是配置代理 [14]。审查 HTTPS 请求时重点包括：是否允许不安全/自签名证书、证书链是否有效、主机名是否匹配、是否被代理降级、响应是否来自预期 host。Godot 的 TLS 选项、平台证书存储和 Web 导出限制随版本/平台变化，因此不能只凭 `https://` 前缀判定安全。

```text
### HTTPRequest.set_http_proxy / get_body_size
- **签名**：`set_http_proxy(host, port)` / `get_body_size()`
- **用途**：设置 HTTP 代理并查询响应体大小。
- **误用**：把代理配置当加密；下载前未检查 body size 导致内存暴涨；代理凭据硬编码。
- **判据（源码特征）**
  - GDScript：`set_http_proxy\s*\(|get_body_size\s*\(`
  - C#：`SetHttpProxy\s*\(|GetBodySize\s*\(`
- **确认**
  1. 限制最大响应体并流式处理大文件。
  2. 代理地址/凭据不得写死在源码，必要时走受保护配置。
  3. 在目标平台验证 HTTPS 证书链。
- **置信度：官方明确**
```

### 6.2 HTTPClient 状态机

**HTTPClient 不替你运行主循环，`poll()` 是推进状态机的必要条件。** 官方状态枚举包含 `DISCONNECTED=0`、`CONNECTING=1`、`CONNECTED=5`、`REQUESTING=6`、`BODY=7` 等；状态机会从连接过程逐步推进 [15]。轮询不足会永远停留在连接或请求状态；而 `poll()` 只能在支持线程安全的场景中使用，长连接状态也不应跨线程随意修改。

```text
### HTTPClient.connect_to_host / poll / request / get_response_body
- **签名**：`connect_to_host(host, port=-1, tls_options=null)` / `poll()` / `request(method, url, headers, body="")` / `get_response_body_chunk()`
- **用途**：手动驱动 HTTP 连接、请求与响应。
- **误用**：不 poll；阻塞主线程等待；连接后没有处理 TLS 握手；把 get_response_body_chunk 当完整 body。
- **判据（源码特征）**
  - GDScript：`HTTPClient\.new\s*\(|connect_to_host\s*\(|poll\s*\(|request\s*\(|get_response_body`
  - C#：`new HttpClient\s*\(|ConnectToHost\s*\(|Poll\s*\(|Request\s*\(`
- **确认**
  1. 在 `_process`/`_physics_process` 中按状态机 poll，不写死空转循环。
  2. 状态迁移测试覆盖 DNS 失败、TLS 失败、重定向、断开、分块完成。
- **置信度：官方明确**
```

**连接主机后 URL 参数应是路径，不应重复完整 URL。** 官方明确说明：客户端只需连接一次主机；已连接后，方法中的 URL 通常只取主机之后的路径部分 [15]。因此常见错误是每次 `request()` 都传入 `https://host/path`，或在 `connect_to_host()` 时把完整 URL 当主机名。

```text
### HTTPClient 的 URL 参数
- **签名**：`connect_to_host(host, port=-1, tls_options=null)` / `request(method, url, headers, body="")`
- **用途**：连接主机并发送相对路径请求。
- **误用**：connect 时传完整 URL；request 时重复 host；同一 client 跨多个 host 复用。
- **判据（源码特征）**
  - GDScript：`connect_to_host\s*\(\s*"https?://`
  - C#：`ConnectToHost\s*\([^)]*"https?://`
- **确认**
  1. 拆分 URL 为 scheme/host/port/path，并在连接状态校验主机。
  2. 切换 host 前 close 并重建 client。
- **置信度：官方明确**
```

## 7. 4.x 多人 API：权限、RPC 参数验证与复制范围必须同时受控

### 7.1 MultiplayerAPI 与 @rpc

**`MultiplayerAPI` 是多人 RPC/复制的总线，不直接等同于某个 Peer 的实现。** 官方文档列出 `is_server()`、`rpc(peer, object, method, arguments)`、`object_configuration_add/remove`、`peer_connected/disconnected` 等 [16]。审查重点不是禁止底层 API，而是任何对象配置、RPC 目标与连接状态变更都要经过明确的网络层封装，避免把 peer id 0、已断开 id 或无效 multiplayer_peer 当作有效目标。

```text
### MultiplayerAPI.is_server / rpc / object_configuration_add / remove
- **签名**：`is_server()` / `rpc(peer, object, method, arguments)` / `object_configuration_add(object, configuration)` / `object_configuration_remove(object, configuration)`
- **用途**：判断服务端身份、向目标发送 RPC、管理对象复制配置。
- **误用**：用 RPC id 比较代替权威判断；向无效 peer 发送；add/remove 配置不配对；未验证 sender。
- **判据（源码特征）**
  - GDScript：`multiplayer\.is_server\s*\(|multiplayer\.rpc\s*\(|object_configuration_add\s*\(|object_configuration_remove\s*\(`
  - C#：`Multiplayer\.IsServer\s*\(|Multiplayer\.Rpc\s*\(`
- **确认**
  1. 服务端关键路径检查 `multiplayer.is_server()` 或 `is_multiplayer_authority()`。
  2. 在 RPC 内用 `get_multiplayer_authority()`/`get_remote_sender_id()` 验证来源。
- **置信度：官方明确**
```

**`@rpc` 的默认配置不是“开放远程入口”，而是权威端可调用、远程执行、可靠传输、通道 0。** 官方等价形式为 `@rpc("authority","call_remote","reliable",0)`；`mode` 可为 `authority`/`any_peer`，`sync` 可为 `call_remote`/`call_local`，传输可为 `unreliable`/`unreliable_ordered`/`reliable` [17]。`any_peer` 会扩大攻击面，必须逐函数验证发送者、参数范围、频率、状态机阶段和副作用。

```text
### @rpc / C# [Rpc]
- **签名**：`@rpc(mode="authority|any_peer", sync="call_remote|call_local", transfer_mode="reliable|unreliable|unreliable_ordered", channel=0)`
- **用途**：声明远程可调用函数。
- **误用**：默认模式理解错误；把状态修改放在 call_local 分支以外却未校验权威；高频率状态用 reliable；RPC 参数不受限。
- **判据（源码特征）**
  - GDScript：`@rpc\s*\(|rpc\s*\(|rpc_id\s*\(|rpc_unreliable\s*\(`
  - C#：`\[Rpc\(|\[Godot\.Rpc\(`
  - BLOCKER：`@rpc\s*\(\s*"any_peer"`
- **确认**
  1. 每个 any_peer RPC 提供 sender id、参数范围、速率限制和权限校验。
  2. 对位置/冷却/资源变化采用服务端权威并回放/校正。
- **置信度：官方明确**
```

**RPC 的双方签名必须一致，`any_peer` 必须验证发送者。** 官方说明客户端和服务端脚本必须声明同一 RPC，并使用方法签名校验 [17]。更重要的是，官方多人教程明确建议服务端作为关键游戏状态的真相源，RPC 参数在应用前必须验证，不能信任客户端报告的位置、计时器、冷却或资源值 [17]。这意味着即使签名匹配，也不足以证明安全。

```text
### rpc / rpc_id / get_remote_sender_id
- **签名**：`object.rpc(method, args)` / `object.rpc_id(peer_id, method, args)` / `get_remote_sender_id()`
- **用途**：触发远程函数并取得调用者 id。
- **误用**：把 rpc 当本地函数直接调用而绕过验证；信任 caller 报的位置/货币；peer_id 来自用户输入。
- **判据（源码特征）**
  - GDScript：`rpc\s*\(|rpc_id\s*\(|get_remote_sender_id\s*\(`
  - C#：`Rpc\s*\(|RpcId\s*\(|GetRemoteSenderId\s*\(`
- **确认**
  1. 检查 RPC 开头是否取得 sender id 并查询权威 peer 映射。
  2. 服务端重新计算移动、冷却、资源交易，不执行客户端原始值。
- **置信度：官方明确**
```

**`multiplayer_authority` 决定谁拥有节点，不等于请求调用者的身份自动可信。** 官方将 `multiplayer_authority` 作为控制 RPC/复制权限的核心属性。规则应要求 Spawner、Synchronizer 和可 RPC 的 Node 显式设置 authority，并在转移权限前校验转移发起者；不要默认场景树父节点自动拥有正确 authority。

```text
### Node.multiplayer_authority / set_multiplayer_authority
- **签名**：`set_multiplayer_authority(id)` / `@export var multiplayer_authority: int`
- **用途**：设置节点的多人权限所有者。
- **误用**：动态生成节点未设置 authority；把任意客户端报告的 authority 当合法；权限转移后复制状态不一致。
- **判据（源码特征）**
  - GDScript：`set_multiplayer_authority\s*\(|multiplayer_authority\s*=`
  - C#：`SetMultiplayerAuthority\s*\(|MultiplayerAuthority\s*=`
- **确认**
  1. 在服务端生成节点后立即设置 authority。
  2. 权限转移只由当前 authority 发起，并通知相关 peer。
- **置信度：官方明确；转移协议为工程审查判断**
```

### 7.2 Spawner/Synchronizer 的复制边界

**`MultiplayerSpawner` 的自动复制只覆盖已注册场景与明确 spawn 调用。** 官方签名包括 `spawn_path: NodePath`、`spawn_function: Callable`、`add_spawnable_scene(path)`、`spawn(data)` 以及 `spawned`/`despawned` 信号 [18]。仅把节点 `add_child()` 不会自动让所有 peer 复制；未注册场景、未配置 spawn_path、authority 不匹配都会导致复制失败。

```text
### MultiplayerSpawner.spawn_path / add_spawnable_scene / spawn
- **签名**：`spawn_path: NodePath` / `add_spawnable_scene(path)` / `spawn(data=null)`
- **用途**：定义复制生成目标并触发跨 peer 生成。
- **误用**：未设置 spawn_path；动态场景未注册；客户端 spawn 后假定服务端 authority；未处理 despawn。
- **判据（源码特征）**
  - GDScript：`add_spawnable_scene\s*\(|\.spawn\s*\(|spawn_path\s*=`
  - C#：`AddSpawnableScene\s*\(|\.Spawn\s*\(|SpawnPath\s*=`
- **确认**
  1. 在服务端/authority 生成后确认 remote peer 收到 spawned。
  2. 检查 spawnable 场景路径白名单；不要从网络动态加载未授权场景。
- **置信度：官方明确**
```

**`spawn_function` 必须返回尚未进入树的 Node，不能替调用者完成父子关系。** 官方把 `spawn_function` 描述为处理自定义 spawn 请求并返回未加入场景树节点的可调用对象 [18]。如果 spawn 函数立即 `add_child()`，可能绕过 Spawner 的复制语义；如果返回非 Node 或已入树节点，也会导致复制错误。

```text
### MultiplayerSpawner.spawn_function
- **签名**：`@export var spawn_function: Callable`
- **用途**：自定义生成节点的创建逻辑。
- **误用**：返回 null/非 Node；返回已入树节点；函数内部依赖未同步状态；客户端覆盖服务端 spawn 决策。
- **判据（源码特征）**
  - GDScript：`spawn_function\s*=|\.spawn_function`
  - C#：`SpawnFunction\s*=`
- **确认**
  1. 单元测试 spawn_function 返回类型与父子关系。
  2. 服务端日志验证每次 spawn 的 authority 和场景路径。
- **置信度：官方明确**
```

**`MultiplayerSynchronizer` 默认对所有 peer 同步配置属性，可见性是额外约束。** 官方说明其将配置属性从多人 authority 同步到远程 peer，默认同步到所有 peer；`public_visibility=true` 是默认状态，可进一步用 `set_visibility_for()`、`add_visibility_filter()`、`update_visibility()` 控制 [19]。因此“客户端没配置 filter 就看不到”是错误假设；规则应要求为敏感属性明确配置 public/private 可见性。

```text
### MultiplayerSynchronizer.root_path / replication_config / visibility
- **签名**：`root_path: NodePath` / `replication_config: SceneReplicationConfig` / `public_visibility: bool`
- **用途**：定义同步根、复制属性及可见性。
- **误用**：root_path 指向错误节点；同步包含密码、授权令牌、服务端内部状态；默认可见性被误解为私有。
- **判据（源码特征）**
  - GDScript：`root_path\s*=|replication_config\s*=|public_visibility\s*=`
  - C#：`RootPath\s*=|ReplicationConfig\s*=|IsVisibilityPublic\s*\(`
- **确认**
  1. 列出所有同步字段，审核信息分级。
  2. 非公共属性使用 visibility filter 并在服务端校验。
- **置信度：官方明确**
```

**复制配置是带宽与信息泄露的统一攻击面。** `SceneReplicationConfig` 控制哪些属性被复制；即便数据不可由客户端直接 RPC 修改，同步属性仍会周期性发送到 peer。审查器应结合 `replication_config` 查找坐标、库存、AI 状态、调试开关等敏感字段，并要求注释数据可见性。C# 端名称通常是 `SceneReplicationConfig`，但字段/方法绑定应针对具体 Godot .NET 版本做编译验证。

```text
### SceneReplicationConfig
- **签名**：`replication_config: SceneReplicationConfig` / `Godot.SceneReplicationConfig`
- **用途**：声明需要同步的属性集合。
- **误用**：复制不必要的大对象/字符串；在运行时无版本地修改配置；跨语言调用假定相同 API 名称。
- **判据（源码特征）**
  - GDScript：`SceneReplicationConfig|replication_config`
  - C#：`SceneReplicationConfig`
- **确认**
  1. 统计同步字段数、更新频率和估算带宽。
  2. 对运行时修改配置的路径做单测和权限检查。
- **置信度：官方明确；具体 C# 绑定名称按 Godot .NET 版本确认**
```

## 8. 存档选型与反直觉坑：安全路径、原子写盘与版本迁移必须进入规则

### 8.1 三种存档方案的正反选择

**Resource + ResourceSaver 最接近 Godot 数据模型，但序列化细节和引用策略不是存档兼容性的稳定保证。** 它适合工具、编辑器资源、关卡模板和简单内部状态；对跨版本存档建议只保存领域字段，不用完整对象图。必须写入 `user://`，保存后 reload 验证，且避免 `FLAG_CHANGE_PATH` 在运行时误改 `resource_path`。

```text
### 方案 A：Resource + ResourceSaver
- **推荐场景**：Godot 原生资源、工具数据、类型化配置、需要资源引用的内部格式。
- **判据**
  - 目标路径必须以 `user://` 开头：`^"user://`.
  - `save()` 返回值必须检查。
  - 禁止 `FLAG_CHANGE_PATH` 把运行时缓存资源的 resource_path 改成存档路径。
- **验证**
  1. 保存后立即 `ResourceLoader.load()` 并比较关键字段。
  2. 在导出项目而非编辑器运行。
- **置信度：官方明确**
```

**ConfigFile 的兼容性优势是可读，代价是 schema 能力有限。** 它适合设置、按键、小型元数据和人类可编辑存档；不适合复杂对象图、二进制数据或需要严格版本迁移的数据。关键字段必须有默认值，损坏文件必须能进入修复/重置分支。

```text
### 方案 B：ConfigFile
- **推荐场景**：简单键值、游戏设置、小型元数据。
- **判据**
  - 所有 `get_value()` 有默认值。
  - 定义 section/key 白名单。
  - 禁止将玩家输入作为 section/key 或拼接成路径。
- **验证**
  1. 使用空文件、缺 key、多余 key、格式错误文件测试。
  2. 保存前后校验类型和范围。
- **置信度：官方明确**
```

**JSON + FileAccess 是最适合跨版本和跨语言迁移的存档格式，但必须自行定义 schema。** 官方提供 `JSON.parse()`/`stringify()` 与 `FileAccess` 的读写能力 [7][12]。推荐将业务对象转换为普通 Dictionary/Array，写入 schema 版本和字段，再以 UTF-8 保存；加载时先验证 magic/版本、长度、字段存在性和类型，再映射到强类型存档模型。

```text
### 方案 C：JSON + FileAccess
- **推荐场景**：跨平台存档、模组可编辑存档、需要显式版本迁移的玩家数据。
- **判据**
  - JSON 文本统一 UTF-8；保存使用 `store_string()`，不依赖 `store_line()`。
  - 文件头包含 `schema_version`/类似字段。
  - 从 FileAccess 读取后使用 `JSON.parse()` 并判 Error，再校验类型。
- **验证**
  1. 制作 v1→v2 迁移测试与未知版本拒绝测试。
  2. 测试大整数、浮点精度、Unicode、数组长度上限。
- **置信度：官方明确**
```

**无论哪种格式，写入都应是“临时文件—关闭—原子替换”，而不是原地覆盖。** `FileAccess.WRITE` 会截断现有文件 [7]；进程在写入中途退出会留下空文件。规则应要求：创建唯一临时文件名 → 打开并写入 → 检查 store 错误 → 关闭 → 将临时文件移动到最终名称。Godot 的 `DirAccess` 是否支持真正原子 rename 受平台/文件系统影响，因此也应进行应用级“写入完成标记文件”或“双备份”验证。

```text
### 通用原子保存流程
- **判据（源码特征）**
  - 写入前出现 `make_dir_recursive()` 或已存在目录检查。
  - 使用独立临时文件名，而非直接写入最终存档名。
  - 保存后 `close()` 或 FileAccess 离开作用域。
  - 使用替换/重命名或明确的完成标记。
- **确认**
  1. 模拟崩溃：写入 50% 时终止进程，重启后旧存档仍可用。
  2. 验证备份不会无限制增长。
- **置信度：官方明确 FileAccess 语义；原子替换策略为工程审查判断**
```

**存档迁移是显式状态机，不能依赖“缺字段就用 null”。** 每个存档至少保存 `schema_version`；加载器根据当前版本执行严格递增迁移。新字段应有默认值，旧字段应有映射；未知未来版本应拒绝加载并提示修复，而不是盲目忽略。Resource 方案还应测试 `duplicate()` 深度、外部子资源和缓存对迁移结果的影响。

```text
### 存档版本迁移
- **判据（源码特征）**
  - GDScript：`schema_version|"version"\s*:|migrate\s*\(`
  - C#：`SchemaVersion|Version\s*=|Migrate\s*\(`
- **确认**
  1. 为每一代格式建立样本文件，执行正向迁移与回滚测试。
  2. 检查迁移后旧路径不会残留可加载但格式错误文件。
- **置信度：工程审查判断；版本字段与校验为官方可验证实践**
```

### 8.2 反直觉坑清单

**“Resource 需要 `queue_free()`”是错误直觉，真实规则是 RefCounted 自动回收。** 它不进场景树、没有节点销毁队列，手动 `free()` 会破坏引用计数；循环引用也不会自动消失。正确做法通常是清除最后一个引用、从容器移除，必要时使用 `WeakRef`。

```text
### 反直觉坑：Resource 不是 Node
- **错误假设**：“Instantiate 出来的资源用完后像 Node 一样 queue_free。”
- **实际情况**：Resource 继承 RefCounted，引用计数归零后自动释放；Node 的 queue_free/free 不适用。
- **静态判据**：Resource 子类变量/字段参与 `queue_free()`/`free()` 调用图。
- **置信度：官方明确**
```

**“同一路径 load 两次会得到两个独立资源”是错误直觉，真实规则是缓存可能返回同一引用。** `load()` 会缓存结果 [5]。修改一个 load 结果前必须判断共享语义；需要隔离时使用 `resource_local_to_scene` 或 `duplicate(deep=true)`。

```text
### 反直觉坑：资源加载存在共享缓存
- **错误假设**：“load 每次都从磁盘创建新资源。”
- **实际情况**：load 会缓存；preload 与 load 的目标也可能共享资源身份。
- **静态判据**：对 load 结果执行状态修改，却无 duplicate/local_to_scene 注释或测试。
- **置信度：官方明确**
```

**“`res://` 是普通工程目录”是编辑器直觉，真实规则是导出后它可能只读且位于打包资源中。** 存档、下载缓存、玩家配置和临时文件应使用 `user://`，并先创建目录、校验真实路径。

```text
### 反直觉坑：res:// 不是运行时存档盘
- **错误假设**：“游戏目录里的 res:// 可以随便写文件。”
- **实际情况**：导出后资源通常打包，res:// 多为只读；写入应使用 user://。
- **静态判据**：`res://` 出现在 ResourceSaver.save/FileAccess.open/DirAccess.remove 的目标参数。
- **置信度：官方明确**
```

**“4.x 的 File 与 3.x 一样”是迁移错觉，真实规则是 `FileAccess.open()` 返回对象，失败时返回 null。** `File.new()`、`File.open()` 均为旧 API；打开后必须检查 null 和 `get_open_error()`。

```text
### 反直觉坑：FileAccess.open 失败返回 null
- **错误假设**：“像 3.x 一样 new File，然后检查 open 的 Error 就行。”
- **实际情况**：4.x 使用 FileAccess.open()，失败返回 null。
- **静态判据**：`File\.new\s*\(|File\(\)|open\s*\([^)]*\)\s*==\s*OK` 但对象未判空。
- **置信度：官方明确**
```

**“打开文件后总要在 finally 里 close”的通用直觉在 Godot 中部分成立：自动释放会关闭，但显式所有权更可靠。** 审查器不应只靠“是否写了 close”判定泄漏，还应检查对象是否长期存活、是否被容器持有、是否跨函数传递。

```text
### 反直觉坑：FileAccess 会随对象释放自动关闭
- **错误假设**：“忘记 close 一定立刻泄漏句柄。”
- **实际情况**：赋 null、离开作用域或释放时会自动关闭；但长生命周期引用仍可能占用文件。
- **静态判据**：FileAccess 引用跨函数、跨帧存活，或打开/写入路径没有关闭/回收策略。
- **置信度：官方明确有自动关闭；泄漏风险为审查判断**
```

**“WRITE 就是打开文件”是错误直觉，真实规则是 WRITE 会截断现有内容。** `READ_WRITE` 不清空，因此“打开、读、再覆盖”可能残留旧数据；追加需要项目明确的文件追加策略。

```text
### 反直觉坑：FileAccess.WRITE 会截断
- **错误假设**：“用 WRITE 打开旧存档，读旧数据再写回。”
- **实际情况**：WRITE 会清空已有内容；READ_WRITE 不清空。
- **静态判据**：同一 FileAccess 先用 READ/READ_WRITE 语义读旧存档，再以 WRITE 打开并最终 replace。
- **置信度：官方明确**
```

**“下载文件就是安全文本”是错误直觉，真实规则是 body 是 PackedByteArray，对象反序列化可远程执行。** 来自 HTTP、模组、导入文件的数据应先做 schema/长度/哈希校验；禁止 `bytes_to_var(..., true)`/`str_to_var(..., true)`。

```text
### 反直觉坑：反序列化对象可以执行代码
- **错误假设**：“把下载的 JSON/Variant 直接反序列化只是数据转换。”
- **实际情况**：打开 allow_objects/full_objects 的对象反序列化存在远程代码执行风险。
- **静态判据**：外部来源与 `bytes_to_var(..., true)`/`str_to_var(..., true)`/`get_var(true)` 的组合。
- **置信度：官方明确**
```

**“HTTPRequest 是网络工具对象”是错误直觉，真实规则是它依赖场景树处理并需要取消旧请求。** `add_child()` 后还必须处理 `request_completed` 的四参数顺序、线程模式、超时和节点释放。

```text
### 反直觉坑：HTTPRequest 需要入树且需要取消
- **错误假设**：“new HTTPRequest 后直接 request，完成时读取 result 就行。”
- **实际情况**：它需 add_child；退出/切换场景需取消；回调接收 result、response_code、headers、body。
- **静态判据**：`HTTPRequest.new()` 后无 add_child，或场景退出前无 cancel_request。
- **置信度：官方明确**
```

**“RPC 只是远程函数调用”是错误直觉，真实规则是 any_peer 等于开放网络入口。** 默认 `authority` 也不意味着业务状态自动可信；服务端必须重算坐标、冷却、资源和权限。

```text
### 反直觉坑：@rpc 默认不是无条件的服务端命令
- **错误假设**：“客户端调用 RPC，服务端照做即可。”
- **实际情况**：authority 配置控制调用权限，any_peer 要求逐项校验；关键状态必须服务端权威。
- **静态判据**：`any_peer` RPC 缺少 sender、参数范围或权限校验。
- **置信度：官方明确**
```

## 9. 从静态判据到可执行规则：正则只是线索，必须结合类型流和控制流

### 9.1 正则与 AST 的适用边界

**正则适合发现 API 使用面，不能单独证明资源生命周期错误。** 例如 `queue_free()` 的正则可以找到调用，却不能证明接收者是 Resource；`@rpc("any_peer")` 能找到高风险函数，却不能证明内部缺少校验。生产规则库应把报告分成三档：直接 API 违规（如 `File.new()`、`res://` 保存、`any_peer` RPC）、需要上下文确认（如 Resource 释放、FileAccess 关闭、load 共享、线程回调）和架构建议（如存档版本、可见性、目录结构）。

| 规则 ID | 标题 | 默认级别 | 证据类型 | 自动化要求 |
|---|---|---:|---|---|
| IO-001 | 4.x 残留 `File.new()` | BLOCKER | 官方签名迁移 | 正则 + 文件扩展名 |
| IO-002 | `FileAccess.open()` 未判空 | BLOCKER | 官方失败语义 | AST/数据流 |
| IO-003 | 存档写入 `res://` | BLOCKER | 官方路径语义 | 字符串/调用参数 |
| IO-004 | `FileAccess.WRITE` 覆写旧存档 | MAJOR | 官方截断语义 | 字符串 + 控制流 |
| IO-005 | 长时间持有未关闭 FileAccess | MAJOR | 官方自动关闭 | 作用域分析 |
| RES-001 | Resource 调用 Node 释放 API | BLOCKER | 官方 RefCounted 语义 | 类型流 |
| RES-002 | 修改 load 结果却无隔离 | MAJOR | 官方缓存语义 | 数据流 |
| RES-003 | 自定义资源 setter 无 `changed` 通知 | MINOR | 官方文档 | AST |
| SER-001 | `get_var`/`bytes_to_var` 打开对象反序列化 | BLOCKER | 官方安全警告 | 调用参数 |
| NET-001 | `any_peer` RPC 无发送者/参数校验 | BLOCKER | 官方教程 | AST + 函数体检查 |
| NET-002 | HTTPRequest 未 `add_child()` | MAJOR | 官方示例/语义 | AST |
| NET-003 | `download_file` 来自未净化 URL | BLOCKER | 官方字段语义 | 污点流 |
| SAVE-001 | 存档无版本字段或迁移测试 | MAJOR | 工程规则 | 结构检查 |
| SAVE-002 | 保存不是原子/备份流程 | MAJOR | FileAccess 截断语义 | 控制流 |

**污点规则的最小集合应包括四个来源和一个 sink。** 污点来源为网络响应、下载文件、玩家导入文件、命令行/路径输入框；中间传播包括 JSON 解析、`bytes_to_var`、`get_var`、路径拼接和配置读取；敏感 sink 包括 `load()`、`bytes_to_var(...,true)`、`request()`、任意进程执行、`download_file` 和 `user://` 之外写入。只标记 sink 会产生噪声，只标记来源又无法定位修复点；两者之间的传播路径才是有效结果。

**类型流比正则更适合 Resource 规则。** 规则引擎应读取 GDScript/C# 的类型注释、`@export`、函数签名、赋值和容器元素类型。对 `var player_data = load("res://player.tres")` 可暂定类型为 `Resource`；随后若出现 `player_data.queue_free()`，触发 RES-001；若出现 `player_data.gold += 10` 且同一路径被另一个 load 引用，触发 RES-002。对无法判定类型的动态变量，报告为“需人工确认”，不应自动 BLOCKER。

**调用图适合检测“打开—使用—回收”，但阈值规则不能过度。** FileAccess 的开销是：确认 open 后是否在后续异常/提前返回路径上赋 null、离开作用域或被关闭。一个跨 10 行的函数不关闭，不一定泄漏；一个全局变量持有 FileAccess 跨多个场景才更危险。规则引擎应把“显式 close”“赋 null”“局部作用域结束”列为三种有效回收事件，再对长期容器字段和静态变量提高优先级。

### 9.2 推荐的审查流程与测试矩阵

**审查应按“API 表面 → 数据来源 → 所有权/状态机 → 实际运行验证”推进。** 先静态扫描找出调用点，再追踪路径、资源引用、网络数据、线程上下文和场景树生命周期；最后在编辑器和至少 Windows、macOS/Linux、一个移动平台上运行文件、网络与多人测试。官方文档不能替代目标平台导出验证，因为 `user://`、TLS、线程和文件锁行为都受平台与导出模板影响。

| 测试场景 | 必须观察结果 | 对应判据 |
|---|---|---|
| 编辑器与导出版均写入存档 | 导出版不出现 `res://` 只读失败 | IO-003 |
| 存档写入时杀进程 | 旧存档仍可用，完成标记/临时文件被清理 | SAVE-002 |
| 两个场景实例修改共享 Resource | 只有预期实例变化，或明确共享 | RES-002 |
| 加载损坏/未知版本存档 | 有明确错误、迁移或重置路径 | SAVE-001 |
| HTTPS 下载后读取 body | 编码、大小、TLS、完整性分别处理 | NET-003 |
| 服务端处理客户端 RPC | sender、参数范围、状态机和权限都被校验 | NET-001 |
| 客户端切换场景中途请求完成 | 无悬空回调，无已释放节点访问 | NET-002 |
| 两个引用 load 同一路径 | 对象身份测试与 local_to_scene/duplicate 测试 | RES-002 |

**文档版本以 Godot 官方稳定文档为准，本报告的 API 事实指向 4.x 稳定版。** 本次联网抓取可读取到的最新稳定文档年份为 2026 年；其中 `CacheMode` 已包含 `IGNORE_DEEP`/`REPLACE_DEEP` 等扩展枚举。由于 Godot 的 C# 绑定、编辑器导出和底层网络 TLS 行为会跨小版本变化，CI 规则库应在 PR 中同时记录 Godot 引擎版本、.NET Godot 版本与目标平台，不能只写“Godot 4.x”。

## 引用来源

[1] https://docs.godotengine.org/en/stable/classes/class_resource.html
> "Since they inherit from RefCounted, resources are reference-counted and freed when no longer in use."

[2] https://docs.godotengine.org/en/stable/classes/class_refcounted.html
> "RefCounted's therefore do not need to be freed manually with Object.free()."

[3] https://docs.godotengine.org/en/stable/classes/class_packedscene.html
> "Instantiates the scene's node hierarchy. Triggers child scene instantiation(s)."

[4] https://docs.godotengine.org/en/stable/classes/class_scenestate.html
> "SceneState represents the node tree structure of a scene file."

[5] https://docs.godotengine.org/en/stable/classes/class_resourceloader.html
> "Loads a resource at the given path, caching the result for further access."

[6] https://docs.godotengine.org/en/stable/classes/class_resourcesaver.html
> "Error save(resource: Resource, path: String = '', flags: BitField[SaverFlags] = 0)"

[7] https://docs.godotengine.org/en/stable/classes/class_fileaccess.html
> "Creates a new FileAccess object and opens the file for writing or reading, depending on the flags."

[8] https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html
> "On desktop platforms, the path to the `user://` directory can be obtained by `OS.get_user_data_dir()`."

[9] https://docs.godotengine.org/en/stable/classes/class_diraccess.html
> "static Error make_dir_recursive(path: String)"

[10] https://docs.godotengine.org/en/stable/classes/class_marshalls.html
> "Deserialized objects can contain code which gets executed. Do not use this option if the serialized object comes from untrusted sources."

[11] https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/gdscript_exports.html
> "@export_global_file and @export_global_dir only work in tool mode scripts."

[12] https://docs.godotengine.org/en/stable/classes/class_json.html
> "String stringify(data: Variant, indent: String = '', sort_keys: bool = true, full_precision: bool = false) static"

[13] https://docs.godotengine.org/en/stable/classes/class_configfile.html
> "Variant get_value(section: String, key: String, default: Variant = null) const"

[14] https://docs.godotengine.org/en/stable/classes/class_httprequest.html
> "request_completed(result: int, response_code: int, headers: PackedStringArray, body: PackedByteArray)"

[15] https://docs.godotengine.org/en/stable/classes/class_httpclient.html
> "This client only needs to connect to a host once (see connect_to_host()) to send multiple requests."

[16] https://docs.godotengine.org/en/stable/classes/class_multiplayerapi.html
> "Returns true if this MultiplayerAPI's multiplayer_peer is valid and in server mode."

[17] https://docs.godotengine.org/en/stable/tutorials/networking/high_level_multiplayer.html
> "Use server-authoritative logic for gameplay-critical decisions. Validate RPC arguments before applying them to the game state."

[18] https://docs.godotengine.org/en/stable/classes/class_multiplayerspawner.html
> "void add_spawnable_scene(path: String)"

[19] https://docs.godotengine.org/en/stable/classes/class_multiplayersynchronizer.html
> "Synchronizes properties from the multiplayer authority to the remote peers."

[20] https://docs.godotengine.org/en/stable/tutorials/migrating/upgrading_to_godot_4.html
> "ResourceSaver's save() method now has its arguments swapped around (resource: Resource, path: String)."
