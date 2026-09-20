<!-- oversize-exempt: 反模式清单，审核用 -->
# animation-skeletal — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/animation-skeletal.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 骨骼是场景树节点 | 是**有序数组**，骨棒只是调试绘制 |
| 2 | 能手动重建骨骼层级 | 导入器一起生成，**不要手动建** |
| 3 | 4.7 有 `PoleModifier3D` | **不存在**，Pole 是 TwoBoneIK3D 的参数 |
| 4 | 有 `SplineIK3D` | **不存在**，要自己用 IterateIK3D 或找插件 |
| 5 | modifier 会改骨骼 pose | **每帧回滚**，不污染 |
| 6 | modifier 顺序无所谓 | 由**子节点列表**决定 |
| 7 | 自定义 modifier 要乘 influence | 父类统一混合，**不要自己乘** |
| 8 | 重定向导入时搞定 | 是**两层**（BoneMap + RetargetModifier3D） |
| 9 | 动画不播是设置问题 | 常是 **NodePath 断了** |
| 10 | 程序化控制覆盖动画 | **谁最后写谁生效** |
| 11 | 布娃娃调个函数就行 | 激活时机与切换才是难点 |
| 12 | IK 越复杂越好 | 两骨用 `TwoBoneIK3D` 的解析解更稳 |
