<!-- oversize-exempt: 引擎专项骨架 + Cocos↔Godot 对照表，补引擎时整体查阅 -->
# 引擎专项 skill 骨架（补新引擎时照此写）

`p-cocos.md` 是本仓库第一份「引擎专项」文档，结构已跑通。
补 Godot / Unity / Laya 等引擎时**照它的结构写**，不要另起炉灶——
每节的取舍理由记在下面。照抄结构但跳过理由，很容易退化成 API 罗列。

> 本文 Godot 列是**映射方向**，未经本仓库实测。
> 补 `p-godot`（待建） 时每条都要跑真实项目验证，验证不了就标 `unverified`。

## 为什么引擎专项要单独成文件

通用场景文件（`s-lifecycle` / `s-numerics` …）写的是**换个引擎也成立**的东西；
引擎专项只写换了就不成立的部分。所以它必须独立、按需加载——
一个 Godot 项目不该为 Cocos 的 `cc.loader` 规则付上下文。

**判定要不要写进引擎专项**：把规则里的引擎 API 名换成另一个引擎的等价物，
如果判据还成立 → 它是通用规则，该进 `s-*`；
如果不成立 → 才属于引擎专项。

## 骨架（16 节，按此顺序）

| # | 节 | 写什么 | 为什么必须有 |
|---|---|---|---|
| 1 | 适用场景 / **不适用** | 版本范围；明确列出别硬套的情况 | 「不适用」比「适用」更重要——防止把 Creator 规则套到 Cocos2d-x C++ 上 |
| 2 | 前置依赖 | 脚本可用性、Python 版本 | 工具跑不了时要有人工兜底路径 |
| 3 | 第 1 步 静态扫描 | 命令、规则分组、退出码 | 退出码要能接 CI，否则没人用 |
| 4 | **第 2 步 生命周期配对** | 回调顺序表 + 该放什么/常见误用 | 扫不全，必须人工；这是泄漏高发区 |
| 5 | 泄漏源（**按出现频率排序**） | 每类：现象 + 正确写法 + 清理方式表 | 按频率不按类别——用户时间有限，先看最常踩的 |
| 6 | 第 3 步 运行时验证 | 工具 + **判定标准** | 「扫描 0 项」不等于没问题；判定标准要可量化 |
| 7 | 性能项 | DrawCall / 文本 / 物理 / 适配 | 与泄漏分开：泄漏看引用链，性能看帧耗时 |
| 8 | 定位思路 | 先分 CPU/GPU | 搞反了会白优化 |
| 9 | 输出格式 | 分级 + 四项要素 | 与 `common-reporting.md` 对齐 |
| 10 | 迁移对照 | 旧版 → 新版 API 对照 | 引擎大版本升级是常态需求 |
| 11 | 失败处理 | 情况 / 判据 / 动作 | 防止「扫不出就报没问题」 |
| 12 | 关键判断依据 | **为什么**定这个级别 | 没有理由的级别会被随意下调 |
| 13 | 扫描器已知局限 | 漏报/误报清单 | 审查工具自己也要被审查 |
| 14 | 已知坑 | ⚠「本能以为…但…」句式 | 直接对冲错误直觉 |
| 15 | 可复用片段 | 安全组件模板、降频模板 | 给可直接抄的代码，不是描述 |
| 16 | 审核清单 | □ 清单（扫描器不可用时的兜底） | 最后一节，工具挂了也能干活 |

**第 13 节是后补的**（本轮审查 Cocos 时加的）。原 15 节没有它，
结果扫描器的漏报被当成「代码没问题」——工具自身的缺陷会以「结论」的形式出现。

## Cocos ↔ Godot 概念对照

补 `p-godot`（待建） 时按行迁移，每行都要换掉具体的 API 名与验证方式。

### 生命周期

| Cocos Creator | Godot（3.x / 4.x） | 配对的清理点 |
|---|---|---|
| `onLoad` | `_ready`（4.x）；`_ready`（3.x） | 自身初始化 |
| `onEnable` | `_notification(NOTIFICATION_ENTER_TREE)` / `_enter_tree` | 注册全局/输入 |
| `start` | 无直接对应（`_ready` 后手动调 / `call_deferred`） | 依赖他者已就绪 |
| `update` | `_process(delta)` | 每帧逻辑 |
| — | `_physics_process(delta)` | Godot 独有：物理帧，别与 `_process` 混用 |
| `lateUpdate` | `_process` + 手动排序 / `_physics_process` 后 | 依赖他者结果 |
| `onDisable` | `_notification(NOTIFICATION_EXIT_TREE)` / `_exit_tree` | **注销在此** |
| `onDestroy` | `_exit_tree` + `queue_free`；`NOTIFICATION_PREDELETE` | 清理在此 |

⚠ Godot 的清理点比 Cocos 更隐晦：`_exit_tree` 在节点离开场景树时触发，
但节点对象可能还没释放（除非 `queue_free`）。"移出树"和"销毁"是两件事。

### 泄漏源对照

| 泄漏源 | Cocos | Godot |
|---|---|---|
| 循环缓动 | `repeatForever` → `stop()` / `Tween.stopAllByTarget` | `Tween.set_loops()` → `kill()`；Tween 绑节点用 `bind_node()`（节点释放时自动 kill） |
| 事件监听 | `node.on` / `off` / `targetOff` | 信号 `connect` / `disconnect`；`Object.connect` 在 Godot 4 改为 `Callable` 形式 |
| 定时器 | `schedule` / `unschedule`；`setInterval` 是另一套 | `Timer` 节点（`start`/`stop`，不用了要 `queue_free`）；`SceneTreeTimer`（`create_timer`） |
| 动态资源 | `resources.load` + `addRef`/`decRef` | `load()` / `preload()`；Resource 有引用计数，但 **Node 必须手动 `queue_free`** |
| 对象池 | `NodePool`（`get`/`put`） | 无内置 NodePool，需自实现；或 `queue_free` + 复用策略 |
| 闭包/全局引用 | 单例、静态实例 | **Autoload（单例）** 持有节点引用是同类问题 |

**Godot 最需要单列的一条**：`Node` 不手动 `queue_free()` 就不会释放，
这与 Cocos「场景切换自动释放（部分）」的直觉相反。C++ 侧的 Godot
（GDExtension / C#）还要考虑 Dispose 模式。

### 性能项对照

| 项 | Cocos | Godot |
|---|---|---|
| DrawCall | 合批、自动图集、Mask/RichText 打断 | `CanvasItem` 合批、AtlasTexture；`CanvasGroup` 有额外开销 |
| 文本 | Label `cacheMode` NONE/BITMAP/CHAR | 无 cacheMode；动态字体有生成开销，频繁改文本同样掉帧（**需实测**） |
| 物理 | Static / Dynamic 刚体；`allowSleep` | Godot 4：`StaticBody` / `RigidBody` / `CharacterBody`（3.x 的 `KinematicBody` 已改名） |
| 多分辨率 | `FIXED_HEIGHT` / `FIXED_WIDTH` / Widget | `Stretch` 模式（`canvas_items` / `viewport`）+ `Control` 锚点 |
| 包体 | 微信小游戏 4MB、引擎裁剪、Bundle | 导出模板裁剪、PCK 分包；Web 导出体积敏感 |

### 迁移对照（大版本升级）

| Cocos 2.x → 3.x | Godot 3 → 4 |
|---|---|
| `cc.find` → `import { find } from 'cc'` | `KinematicBody` → `CharacterBody2D/3D` |
| `cc.loader.loadRes` → `resources.load` | `export` / `onready` → `@export` / `@onready` |
| `cc.NodePool` → `import { NodePool }` | `yield` / 协程 → `await` |
| 子资源路径 `bg` → `bg/spriteFrame` | 大量 API 由 `snake_case` 改 `PascalCase` |

## 补一个新引擎要改哪些文件

以 Godot 为例，照 Cocos 的接线方式改：

| 文件 | 改什么 |
|---|---|
| `references/p-godot.md` | 新建，按上面 16 节骨架写 |
| `scripts/godot-audit.py` | 新建；**必须带 `--self-test`**（其余扫描器都有，缺了就无法判断改好改坏） |
| `scripts/audit.py` | `SCENE_SCANNERS` 加 `'p-godot': ['godot-audit.py']` |
| `scripts/route.py` | 加场景信号（如 `project.godot` → `p-godot`） |
| `SKILL.md` | 场景表加一行（注意 200 行预算，可能要先下沉别处） |
| `references/route.md` | 信号与场景对照表 |

**路由不接线 = 扫描器永远不被调用。** 这是本仓库反复出现的失效模式：
新增了语言包/引擎包却没加路由信号，输出「0 命中」看起来像「没问题」。

## 写之前先想清楚的两件事

1. **这套规则的证明手段是什么？** Cocos 靠 Profiler / Chrome Memory / 真机 PerfDog。
   Godot 要用什么？内置 Profiler / Monitor（`Performance` 单例）/ 远程调试——
   先确定工具，再写判定标准，否则第 3 步会写空。

2. **哪些东西扫不出来？** 闭包、循环引用、全局单例，任何引擎都扫不出。
   把这条写进第 13 节，别让使用者以为「扫描 0 项 = 通过」。
