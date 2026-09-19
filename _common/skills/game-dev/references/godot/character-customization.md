# 角色自定义：捏脸 / 换装 / 染色（Godot 4.7.2）

"捏脸""角色自定义" 此前 **0 命中**。

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/character-customization.md`


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
