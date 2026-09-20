<!-- oversize-exempt: 反模式清单，审核用 -->
# project — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/project.md`

## 常见漏写

| 漏写 | 后果 |
|---|---|
| `.godot/` 没进 gitignore | 仓库爆炸、冲突 |
| Web 用 forward_plus | 浏览器跑不起来 |
| `assert` 做运行时校验 | release 校验消失 |
| `print()` 残留 | I/O 开销 + 信息泄露 |
| Autoload 信号未断开 | 节点永远不释放 |
| release 未实测 | debug 能跑 release 崩 |
| 层不起名 | 三个月后没人记得哪层是什么 |
| 改了物理 tick 未调参数 | 手感全变 |
