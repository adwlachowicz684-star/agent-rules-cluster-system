# 角色自定义：捏脸 / 换装 / 染色（Godot 4.7.2）

"捏脸""角色自定义" 此前 **0 命中**。

## 0. ⚠ 最致命的坑不是技术难度

是**把捏脸、换装、染色三件事当成同一件事来设计**：

| | 改什么 | 数据生命周期 |
|---|---|---|
| **捏脸** | 共享网格的顶点/形变权重 | 与身体网格绑定 |
| **换装** | 部件组合与骨骼绑定 | 随装备增删 |
| **染色** | 材质实例 | 随实例私有化 |

⚠ 三者生命周期完全不同，**混在一个 Resource 里必然在第一版之后无法扩展**。

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

## 3. 染色的共享材质陷阱

⚠ 换装场景的具体表现：**一件装备染成红色，所有引用同一 `BaseMaterial3D.tres` 的装备全变红**。

必须用 `material.duplicate()` 做实例私有化。
⚠ 且 `duplicate(true)` **仍是浅拷贝**（见 `datatable.md`）。

## 4. ⚠ 4.6 起 skeleton 默认路径变了

`MeshInstance3D.skeleton` 默认路径从 `".."` 改为 `NodePath("")`
→ **旧工程必须打开兼容开关**，或显式指定路径。

## 5. 性能

- ⚠ 同屏多角色时**部件数直接决定 DrawCall**
- 合并时机与缓存策略
- ⚠ `append_from` **跨线程更慢**且会 stall 主线程

## 6. 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 捏脸换装染色是一件事 | **三套生命周期**，混设计必死 |
| 2 | Godot 没有 blendshape | **官方支持完整** |
| 3 | `set_blend_shape_value` 不会错 | mesh 空或索引无效**会报错** |
| 4 | Blender 导出不用管 | 不开 Export Deformation Bones Only 会**法线错误** |
| 5 | 有官方合并网格函数 | **没有**，要自己拼数组 |
| 6 | 静态合并插件能做运行时换装 | **明确不支持** |
| 7 | 顶点数相同动画就能保持 | 要共用 **Skin + register_skin** |
| 8 | 合并网格还能捏脸 | **不能混用**，身体网格别参与合并 |
| 9 | 合并后自动有 LOD | **没有**，要手动提供 lods |
| 10 | 改材质只影响自己 | 共享材质**全变**，要 duplicate |
| 11 | `duplicate(true)` 是深拷贝 | **仍是浅拷贝** |
| 12 | 4.6 后 skeleton 路径不变 | 默认改成 **`""`**，旧工程要兼容开关 |
| 13 | 部件随便加 | 每个部件**一个 DrawCall** |
| 14 | 合并放线程更快 | `append_from` 跨线程**更慢**且 stall 主线程 |
| 15 | 捏脸参数存就行 | 要**可序列化**且装备要跟着变（否则穿模） |

## 7. 待核对项（运行时验证）

⚠ 待核对：`register_skin` 对内嵌 skin 的确切行为 · 验证：实测内嵌 skin 与共享 skin 的动画表现

⚠ 待核对：合并网格在 Compatibility 渲染器下的 4 权重表现 · 验证：目标渲染器实测

⚠ 待核对：`bake_mesh_from_current_blend_shape_mix` 对多 surface 合并网格的输出 · 验证：实际调用比对

## 8. 相关文档

- 骨骼动画与 IK → `animation-skeletal.md`
- 材质与着色器 → `shaders.md` / `3d.md`
- 共享 Resource 与 duplicate → `datatable.md`
- LOD 与渲染进阶 → `rendering-advanced.md`
- 存档与序列化 → `io-network.md`
- 性能剖析 → `perf-profiling.md`
