<!-- oversize-exempt: 反模式清单，审核用 -->
# tilemap — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/tilemap.md`

## 常见漏写

| 漏写 | 后果 | 审查规则 |
|---|---|---|
| 4.3 用 4.2 的 `set_cell` 签名 | 图块不出现，不报错 | GD33 |
| `local_to_map` 传全局坐标 | 图块位置全错 | 人工 |
| TileSet 没加物理层就画碰撞 | 碰撞无效，角色穿过 | 人工 |
| `get_cell_tile_data()` 不判空 | 空格子崩溃 | 人工 |
| 破坏地形未重烘焙导航 | 敌人往坑里走 | 人工 |
| `set_cells_terrain_connect` 传单个 cell | 报错 | 人工 |
| 未设 terrain peering bit | 什么都不画，不报错 | 人工 |
| `y_sort_enabled` 开在 TileMap 而非父节点 | 不排序 | 人工 |
| 用 `event.position` 当世界坐标 | 相机移动后错位 | 人工 |
