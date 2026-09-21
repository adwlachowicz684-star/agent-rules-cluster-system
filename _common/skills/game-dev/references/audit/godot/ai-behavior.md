<!-- oversize-exempt: 反模式清单，审核用 -->
# ai-behavior — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/ai-behavior.md`

## 常见坑

| 坑 | 后果 |
|---|---|
| 简单 AI 也上 BT | 维护成本高于 FSM，没收益 |
| 每个敌人复制整棵树 | 节点膨胀，不如组件复用 |
| 忘记返回 RUNNING | 动画/寻路每帧重头执行 |
| RUNNING 无 abort | 低优先级任务永久阻塞高优先级反应 |
| 把 FAILURE 当错误 | 用 push_error 刷屏，掩盖真问题 |
| 黑板存引擎对象引用 | 存档无法序列化 / 悬空引用 |
| Task 里塞寻路和伤害结算 | 树变成回调壳，无法测试 |
| 插件版本不锁 | 上游改动导致 CI 随机红 |
| 只在编辑器里测过 | 运行时 tick 时机与编辑器不同 |
| AI 与物理帧不同步 | 抖动、判定不稳定（AI 应走 `_physics_process`） |

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【审】 `common/audit/global.md#GA-04`　每帧做本该事件驱动的事
【审】 `common/audit/global.md#GA-06`　状态机只写 enter 不写 exit
