<!-- oversize-exempt: 反模式清单，审核用 -->
# animation — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/animation.md`

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| `create_tween()` 未保存引用 | 无法 kill，重复触发叠加 | GD02 |
| 重启动画前未 `kill()` | 两个 Tween 抢同一个属性，抖动 | GD02 |
| `get_tree().create_tween()` 未 `bind_node` | 节点释放了 Tween 还在 | GD02 |
| 动画名/参数路径用字面量 | 拼错静默失效 | GD54 / GD53 |
| 该用 `lerp` 的地方用 Tween | 每帧重建，GC 压力 | 人工 |
| `lerp(a,b,0.1)` 固定系数 | 帧率相关，不同机器表现不同 | 人工 |
| 方法轨里的方法改名 | 动画调用失效，不报错 | 人工 |
