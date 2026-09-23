# 全局层索引（多对多）

> 本文件是**全局块 ↔ 功能域**的多对多映射。
> ⚠ 一张表解决两件事：
> - **正向**：这块内容被哪些域用（改这块时知道要回归哪些域）
> - **反向**：这个域要用哪些全局块（做这个域时知道要先读什么）
>
> ⛔ **不是一对一、也不是一对多** —— 一个块可被多个域引用，
> 一个域也可引用多个块。例：`GC-05 缓存` 同时被配置表、UI、存档、
> 经济四个域引用，而"埋点"这类内容还会被更多系统共用。

## 做法块（howto）

| ID | 主题 | 引用它的域 |
|---|---|---|
| GC-01 | 状态机优于 if 嵌套 | `howto/godot/character.md` `howto/godot/combat.md` `howto/godot/ai-behavior.md` `howto/godot/survival.md` `howto/godot/ui.md`  `howto/godot/class-awaken.md`|
| GC-02 | 频繁生成/销毁要池化 | `howto/godot/projectile.md` `howto/godot/ui.md` `howto/godot/combat.md` |
| GC-03 | 数据与逻辑分离 | `howto/godot/datatable.md` `howto/godot/economy.md` `howto/godot/character.md`  `howto/godot/class-awaken.md` `howto/godot/gem-rune.md`|
| GC-04 | 事件解耦 vs 直接引用 | `howto/godot/combat.md` `howto/godot/ui.md` `howto/godot/survival.md` |
| GC-05 | 缓存必须有失效路径 | `howto/godot/datatable.md` `howto/godot/ui.md` `howto/godot/save-migration.md` `howto/godot/economy.md`  `howto/godot/class-awaken.md` `howto/godot/gem-rune.md`|
| GC-06 | 性能：先定位再优化 | `howto/godot/performance.md` `howto/godot/ui.md` `howto/godot/ai-behavior.md` |
| GC-07 | 手感优先于正确性 | `howto/godot/character.md` `howto/godot/combat.md` `howto/godot/vfx-feel.md` |
| GC-08 | 常见架构模式速查 | `howto/godot/systems.md` `howto/godot/datatable.md` |

## 审查块（audit）

| ID | 主题 | 引用它的域 |
|---|---|---|
| GA-01 | 参数类型不符 | `audit/godot/datatable.md` `audit/godot/netsync-advanced.md` `audit/godot/save-migration.md` `audit/godot/gem-rune.md`|
| GA-02 | 资源没配对 | `audit/godot/character.md` `audit/godot/survival.md` `audit/godot/projectile.md` `audit/godot/ui.md` `audit/godot/input-remap.md` `audit/godot/gem-rune.md`|
| GA-03 | 硬编码易变值 | `audit/godot/datatable.md` `audit/godot/economy.md` `audit/godot/performance.md`  `audit/godot/class-awaken.md` `audit/godot/gem-rune.md`|
| GA-04 | 每帧做本该事件驱动的事 | `audit/godot/ui.md` `audit/godot/character.md` `audit/godot/ai-behavior.md` `audit/godot/accessibility.md` |
| GA-05 | 缓存无失效路径 | `audit/godot/datatable.md` `audit/godot/ui.md` `audit/godot/save-migration.md`  `audit/godot/class-awaken.md` `audit/godot/gem-rune.md`|
| GA-06 | 状态机只写 enter 不写 exit | `audit/godot/character.md` `audit/godot/ai-behavior.md` `audit/godot/survival.md` |
| GA-07 | 错误处理吞掉异常 | `audit/godot/save-migration.md` `audit/godot/netsync-advanced.md` `audit/godot/io-network.md` `audit/godot/gem-rune.md`|

## 双向校验规则

⚠ 索引表与文档**必须对得上**，否则等于没有索引：

| 方向 | 判据 |
|---|---|
| 表 → 文档 | 表说"A 域用 GC-01"，则 A 域文档里**必须真有** `GC-01` 引用 |
| 文档 → 表 | 文档里出现 `GC-01`，则表里**必须登记**了该文件 |

⛔ **单向登记不算索引** —— 表里写了但文档里没有，做的时候照样找不到。

## 全局块 vs 域内块：放哪的判断

| 放全局块 | 放域内 |
|---|---|
| ≥3 个域都会遇到 | 只在本域出现 |
| 改了要回归多个域 | 改了只影响本域 |
| 内容本身与具体玩法无关 | 内容与玩法强绑定 |
| ⛔ 不可能每个功能单独写 | 单独写更清楚 |

ⓘ **拿不准就留域内**，等第二个域出现相同内容时再上提。
⛔ 过早抽象出来的全局块没人用 = 孤儿（自检会报）。
