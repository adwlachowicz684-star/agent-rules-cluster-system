<!-- oversize-exempt: 反模式清单，审核用 -->
# character — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/character.md`

## 常见漏写

写完对照看一遍，这些是审查会抓的：

| # | 漏写 | 后果 | 审查规则 |
|---|---|---|---|
| 1 | `move_and_slide(velocity, Vector2.UP)` | 4.x 无参，带参是 3.x 残留 | GD09 |
| 2 | `velocity *= delta` | 二次积分，移动速度不对 | GD21 |
| 3 | 物理逻辑放 `_process` | 低帧率时步长变化，抖动/穿模 | GD14 |
| 4 | 没设 `up_direction` | `is_on_floor()` 永远 false，跳不起来 | 人工 |
| 5 | 没加 `CollisionShape2D` | 不碰任何东西，直接穿墙 | 人工 |
| 6 | 每帧 `_anim.play()` | 动画卡在第一帧 | GD54 |

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【审】 `common/audit/global.md#GA-02`　资源没配对
【审】 `common/audit/global.md#GA-04`　每帧做本该事件驱动的事
【审】 `common/audit/global.md#GA-06`　状态机只写 enter 不写 exit
