# 骨骼动画、蒙皮与 IK（Godot 4.7.2）

`animation.md` 讲 AnimationPlayer，本文讲**骨骼体系**——此前完全空白。

## 0. 骨骼的本质

⚠ **骨骼是带局部变换的有序数组，不是场景树节点。**
`Skeleton3D` 内部存 `(name, parent, rest, pose)` 记录：

```gdscript
skeleton.get_bone_count()
skeleton.get_bone_name(i)
skeleton.get_bone_parent(i)
skeleton.find_bone("LeftUpLeg")   # 按名查索引
```

⚠ **父子关系由索引顺序保证** —— 父骨索引永远小于子骨索引。
⚠ **编辑器里的彩色骨棒只是调试绘制，运行时不存在这些 Node。**
⚠ 导入模型时 `Skeleton3D` / `MeshInstance3D` / 动画轨道由导入器一并生成，
**不应手动重建这套层级**。

## 1. IK 体系：以 `SkeletonModifier3D` 为根

| 节点 | 用途 |
|---|---|
| `SkeletonIK3D` | 通用链 IK（旧，最简单） |
| `ChainIK3D` | 任意长度骨链基类（尾巴、触手） |
| `IterateIK3D` | `ChainIK3D` 的迭代实现（多骨柔性链） |
| **`TwoBoneIK3D`** | **两骨确定性 IK**（手臂抓握、腿部落地） |
| `LookAtModifier3D` | 单骨朝向（头部看玩家、炮塔） |
| `BoneConstraint3D` → Aim/CopyTransform/ConvertTransform | 两骨约束映射 |
| `BoneTwistDisperser3D` | 把父骨扭转分散到子骨链（前臂拧转） |
| `LimitAngularVelocityModifier3D` | 限制角速度（抑制抖动、防甩鞭） |
| `SpringBoneSimulator3D` | 弹簧骨骼（马尾、披风） |
| `RetargetModifier3D` | 运行期跨骨架重定向 |
| `PhysicalBoneSimulator3D` | 布娃娃 |
| `XRBodyModifier3D` / `XRHandModifier3D` | XR 全身/手部追踪 |

⚠ **纠正一个常见错误说法**：
**4.7 没有 `PoleModifier3D`，也没有 `SplineIK3D`。**

- **Pole 是 `TwoBoneIK3D` 的参数**（`pole_node` 构建关节共面 + `pole_direction` 控制扭转方向），不是独立节点
- **Spline IK 不是内置节点** —— 长链沿曲线分布要自己用 `IterateIK3D` 加多个目标，或找插件

**待核对**：`SkinReference`、`BoneTwistDisperser3D`、`ModifierBoneTarget3D`
及 `BoneConstraint3D` 三派生类的参数——4.7 文档未补全。

### 执行顺序

⚠ **Modifier 结果每帧回滚，不污染骨骼 pose。**
⚠ **执行顺序由 `Skeleton3D` 的子节点列表决定** —— IK 要开在骨骼修改之后。
⚠ **自定义 modifier 内不得自行乘 influence**（父类统一混合）。

## 2. 重定向是两层

| 层 | 机制 |
|---|---|
| 导入期 | BoneMap / SkeletonProfile |
| 运行期 | `RetargetModifier3D` |

⚠ 不是"导入时勾一下就完事"。

## 3. 程序化骨骼控制

- 代码里直接 `set_bone_pose`
- 头部朝向、上半身转向瞄准
- 与 AnimationPlayer 的混合：**动画播完再叠加程序化修正**
- ⚠ **覆盖顺序：谁最后写谁生效**

## 4. 布娃娃

`PhysicalBone3D` / `PhysicalBoneSimulator3D`：
`start_simulation()` / `stop_simulation()`，死亡时切换。

⚠ 激活时机与切换是难点，不是调个函数就完。

## 5. 导入后骨骼动画不播（排查清单）

1. 轨道 NodePath 断了 —— **改名/挪层级后**，其他轨道正常、只有骨骼不动
2. 骨骼层级被手动改过
3. 动画库未绑定
4. 导入设置问题

⚠ **第 1 条最常见且最难发现** —— 症状是"部分动画正常"。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/animation-skeletal.md`


## 6. 待核对项（运行时验证）

⚠ 待核对：`SkinReference` 与 `BoneTwistDisperser3D` 的 4.7 参数 · 验证：4.7.2 编辑器查类参考与 Inspector

⚠ 待核对：`BoneConstraint3D` 三个派生类的参数 · 验证：编辑器逐个查看 Inspector 字段

⚠ 待核对：`ModifierBoneTarget3D` 的用法 · 验证：配合约束/重定向实测

## 7. 相关文档

- AnimationPlayer / 状态机 → `animation.md`
- 动画进阶 → `animation-advanced.md`
- 3D 与渲染 → `3d.md`
- 角色控制器 → `character.md`
- XR 手部 → `xr-deep.md`
- 导入管线 → `advanced-topics.md`
