<!-- oversize-exempt: 反模式清单，审核用 -->
# occlusion-instancing — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/occlusion-instancing.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | AABB 部分遮挡就剔除 | 必须完全遮挡才剔除，小物体才易受益 |
| 2 | 4.7 还有 Room/Portal 系统 | 已移除，改用 OccluderInstance3D 烘焙 |
| 3 | 自动烘焙含 MultiMesh/粒子 | 只考虑 MeshInstance3D |
| 4 | 开阔空地也开遮挡剔除 | 要维护烘焙 + 每帧查询，未必有收益 |
| 5 | 角色/动态道具也做遮挡物 | 要排除，否则是无效遮挡物 |
| 6 | 自动实例化 = 引擎自动合并 | MultiMesh 仍需显式配置 |
| 7 | MultiMesh 能逐实例剔除 | 共享同一 AABB，分散过大要拆多个节点 |
| 8 | 运行时改 instance_count | 会清空重分配 buffer，要改 visible_instance_count |
| 9 | MultiMesh 免费 | 实例数/阴影/逐实例参数都影响性能 |
| 10 | GPU 粒子能逐粒子回调 | 不是可查询 CPU 数组，逻辑要退 CPUParticles |
| 11 | fixed_fps 保证确定性 | 只降更新频率，不算时间缩放 |
| 12 | visibility_aabb 随便设 | 之外粒子消失且不计算碰撞 |
| 13 | 粒子数大就一定贵 | 少量近距离半透明大覆盖可能更贵 |
| 14 | compute shader 是普通 ShaderMaterial | 走 RenderingDevice |
| 15 | Compatibility 能用 compute | OpenGL 后端无 RenderingDevice |
| 16 | 每帧大量小 dispatch 立即 sync | 立即回读让 CPU 等 GPU，要避免乒乓 |
| 17 | Windows 长计算不会超时 | 可能触发 TDR，要拆 dispatch |

echo "已创建 3 份"
