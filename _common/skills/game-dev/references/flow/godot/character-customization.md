# 角色自定义：捏脸 / 换装 / 染色（Godot 4.7.2）

"捏脸""角色自定义" 此前 **0 命中**。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/character-customization.md`


## 1. Blend Shape（官方支持完整）

Godot 4.x 把行业的 morph target / shape key 统一叫 **Blend Shape**。

运行时控制链：

```
get_blend_shape_count() → find_blend_shape_by_name(name) → set_blend_shape_value(idx, value)
```

⚠ `set_blend_shape_value` 在 mesh 为 null 或索引无效时**会报错**
→ 调用前必须判空与判索引有效性。

⚠ **导入侧**：Blender 导出要启用 `Export Deformation Bones Only`，否则**法线着色错误**。

## 2. ⚠ 没有官方"合并网格"API

⚠ **Godot 4.7.2 没有 `Mesh.combine()` / `Mesh.merge()`**。
`SurfaceTool.append_from()` 只能把一个 Mesh 的**单个 surface** 追加到正在构建的 mesh 上。

真正的多部件合并要自己**按材质分桶、拼顶点/索引/权重数组**。

⚠ **资产库的 Static Mesh Merger 插件明确声明**：不支持运行时合并、不支持动态对象、不支持 LOD
—— 它是编辑器侧静态批次工具，**不能用于运行时换装**。

### 合并后动画怎么保持

⚠ 前提是**共用同一个 `Skeleton3D` 的 Skin**（通过 `Skeleton3D.register_skin()`），
**不是"顶点数量相同"**。

### ⚠ 合并网格与 Blend Shape 不能混用

`add_surface_from_arrays` 的 `blend_shapes` 参数需要**每个 shape 一份完整顶点 delta**。
合并时每个 shape 的 delta 要按合并后的顶点布局重新编排 —— **Godot 不会自动做**。

→ **带 Blend Shape 的捏脸身体网格，建议永远不参与装备合并**，只合并刚性/蒙皮装备部件。

### ⚠ 合并网格没有自动 LOD

LOD 是**导入期产物**，运行时 `ArrayMesh` 必须自己用 `add_surface_from_arrays` 的
`lods` 参数（键为 float 距离、值为 `PackedInt32Array` 索引数组）手动提供。

⚠ **这是合并网格路线的隐性成本**，选型时要算进去。


## 3. ⚠ 4.6 起 skeleton 默认路径变了

`MeshInstance3D.skeleton` 默认路径从 `".."` 改为 `NodePath("")`
→ **旧工程必须打开兼容开关**，或显式指定路径。

## 4. 性能

- ⚠ 同屏多角色时**部件数直接决定 DrawCall**
- 合并时机与缓存策略
- ⚠ `append_from` **跨线程更慢**且会 stall 主线程


## 4.5 ⚠ 换网格：骨骼名相同 ≠ 可以换

⚠ 官方换装文档指出：3D 骨架动画用 Transform 轨道，依据 NodePath 指向具体骨骼；
**即使骨骼名称相同，只要父子层级或 Bone Rest 不同，动画也可能无法共用**。
（不同 DCC 导出的骨架，Bone Rest 也可能不同。）

⚠ `SkeletonProfile` / `BoneMap` 能识别未映射、重复映射或父子异常，
但**这些提示不会阻止资源导入**，只表示动画可能不能共用。
✅ 项目侧必须再建一层**资产验证器**，在 CI 或导入监听里生成骨架兼容指纹，
⛔ 指纹不匹配的资源不得进构建包。

| 检查层级 | 校验内容 | ⛔ 失败时不能做什么 |
|---|---|---|
| 结构层 | 骨骼名集合、父子层级、根骨骼 | 不能直接换网格并假定动画正常 |
| 绑定层 | 蒙皮权重、Skin 骨骼顺序、绑定姿势 | 不能复用另一网格的 `Skin` |
| 资产层 | 表面数量、材质槽、缩放约定、挂点 | 不能假定材质索引一一对应 |
| 运行层 | 是否 T-pose、缩放异常、局部反向 | 不能静默保留错误外观 |

⚠ `MeshInstance3D` 的 `mesh`、`skeleton`、`skin` 是**三个独立属性** ——
换装应视为"网格 + 骨骼绑定 + 表面材质"的组合替换，⛔ 不是简单替换一个预制体。
⚠ `skin` 特别容易误用：共享或错误设置会让部分顶点漂移到错误骨骼，
且不立即崩溃，而表现为手指、披风或裙摆轻微漂移。

```
换网格原子流程：
1. 取当前动画状态（状态名、时间、循环、混合目标）
2. 卸载旧网格引用，停止旧网格上的动态材质写入
3. 校验新 mesh 与兼容骨骼 profile 的指纹
4. 设置 mesh；若 Skin 属于该部件，设置独立 Skin
5. 设置 Skeleton3D 路径
6. 为可写表面建立实例材质
7. 重建 BoneAttachment 与可见附件
8. 恢复动画状态；校验骨骼 Track 覆盖
9. ⚠ 任一关键步骤失败 → 停止切换，回退上一组已验证外观
```

## 4.6 ⚠ 染色必须建立在实例材质上

⚠ **`Resource.duplicate` 默认浅拷贝**，嵌套材质、纹理、着色器参数仍可能共享。
⛔ 运行时直接写共享 `Material` 或 `ShaderMaterial` 参数 →
**一个玩家的染色会污染所有同材质对象**；写进共享纹理后果更持久。

✅ 统一通过 `make_instance_material()` + `set_surface_override_material()` 建实例材质，
只有 `Shader` 和只读纹理共享；颜色只写**实例参数**（也可用 `resource_local_to_scene`）。
⛔ CI 应禁止运行时直接写 `base_material` 或共享纹理。

> 时装 / 称号 / 头像框 / 表情动作 / 坐骑皮肤等**外观资产系统层**见 `cosmetic.md`
> （本篇只到"怎么换上去"，那篇讲"能不能拥有、何时过期、谁说了算"）

## 5. 待核对项（运行时验证）

⚠ 待核对：`register_skin` 对内嵌 skin 的确切行为 · 验证：实测内嵌 skin 与共享 skin 的动画表现

⚠ 待核对：合并网格在 Compatibility 渲染器下的 4 权重表现 · 验证：目标渲染器实测

⚠ 待核对：`bake_mesh_from_current_blend_shape_mix` 对多 surface 合并网格的输出 · 验证：实际调用比对

## 6. 相关文档

- 骨骼动画与 IK → `animation-skeletal.md`
- 材质与着色器 → `shaders.md` / `3d.md`
- 共享 Resource 与 duplicate → `datatable.md`
- LOD 与渲染进阶 → `rendering-advanced.md`
- 存档与序列化 → `io-network.md`
- 性能剖析 → `perf-profiling.md`
