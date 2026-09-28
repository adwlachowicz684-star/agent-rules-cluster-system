<!-- oversize-exempt: 反模式清单，审核用 -->
# animation-advanced — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/animation-advanced.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 配置了状态机就能播 | `active = true` 忘了设，全无输出 |
| 2 | `travel` 能到任何状态 | 走状态图路径，**没连接就静默不动** |
| 3 | `start` 和 `travel` 一样 | `start` 直接设，不走路径 |
| 4 | switch_mode 是淡入算法 | 是**过渡时机** |
| 5 | AtEnd 适合受击 | 玩家感觉操作延迟 |
| 6 | 条件能写表达式 | 只能布尔真，复杂条件用 Advance Expression |
| 7 | 转移顺序决定优先级 | 要显式设 `priority` |
| 8 | 过渡期 get_current_node 是当前状态 | 淡化开始后就变成目标状态 |
| 9 | 根运动后还能用代码移动 | 会**双倍位移** |
| 10 | IK 很便宜 | 每帧求解，远处角色要关 |
| 11 | 分层不用过滤 | 全身混合，上半身被稀释 |
| 12 | Sync 总是更好 | 长度差异大时导致变形 |
| 13 | 状态机 vs 混合空间二选一 | 嵌套使用才是常态 |

| 14 | 4.x 里"没输出"是 active 没设 | ⛔ `AnimationMixer.active` 默认 **true**；官方教程要求的是**调 `start()` 或连 Start 节点** |
| 15 | travel 到未连接节点会不动 | 官方口径是 **teleport**（无过渡跳变），表现为"突然跳变"而非"没反应" |
| 16 | Discrete 轨道就是离散的 | ⛔ AnimationTree 覆盖 `callback_mode_discrete=2`，Discrete **被强制当连续值插值** |
| 17 | 表情/开关滑动是动画资源问题 | ⛔ 是 `callback_mode_discrete`，应设 `DISCRETE_DOMINANT` |
| 18 | Add2/Add3 的 amount 就是叠加量 | ⛔ `deterministic=true` 下总权重被归一化，Add2 两个 1.0 **等于 Blend2 取 0.5** |
| 19 | deterministic 关掉更好 | ⛔ 关掉后总权重恒为 1.0 且缺轨道不补初值，失去 RESET 兜底 |
| 20 | 改动画节点只影响自己 | ⛔ 节点是**共享资源**，影响所有使用该树的实例 |
| 21 | playback 也是共享的 | ⓘ 相反：`playback` 的 `resource_local_to_scene` 默认 **true**，每实例独立 |
| 22 | `SkeletonIK3D` 是标准做法 | ⛔ 官方标注 **Deprecated**，可能被移除 |
| 23 | 用 `interpolation` 调 IK 强度 | ⛔ 已 deprecated，官方指向 `SkeletonModifier3D.influence` |
| 24 | `start()` 立刻生效 | ⛔ 官方：**下一帧**才生效；`start(true)` 立即但下一帧重置 |
| 25 | `stop()` 只停自己这条链 | ⛔ 会 `clear_bones_global_pose_override()`，清掉**所有骨骼**的 override |
| 26 | reparent 后 IK 会重新找骨架 | ⛔ `get_parent_skeleton()` 绑定的是**进树时**的父节点，之后不重绑 |
| 27 | 根运动取的是局部位移 | ⛔ `root_motion_local` 默认 **false**，取的是混合**后**的值 |
| 28 | Advance Expression 写了就能用 | ⛔ `advance_expression_base_node` 默认 `"."`，**必须在 Inspector 指向脚本节点** |
| 29 | 转移条件只能布尔 | 补充：`advance_mode` 可设 `DISABLED` / `AUTO`，自动转移不靠 travel |
| 30 | 分层只要连 Blend2 就够 | ⛔ 不做轨道过滤 = 全身混合，上半身被下半身稀释 |
| 31 | IK 关掉只要不 start | ⛔ `influence <= 0.01` 才等价清 override，且会连带清别处 |
| 32 | 根运动能直接叠在代码位移上 | ⛔ 会**双倍位移**；且要与物理插值、网络同步分开验 |
| 33 | `xfade_time` 有默认值 | ⛔ 默认 **0.0**，不设就是硬切；且当前状态在淡化**开始时就切换** |
| 34 | 循环动画转移会等播完 | ⛔ 需显式 `break_loop_at_end = true` |
| 35 | 混合时缺轨道的动画不影响结果 | ⛔ `deterministic` 下缺轨道按初值参与，非确定性下直接跳过 |
| 36 | RESET 动画只是编辑器用的 | ⛔ `deterministic=true` 且总权重为 0 时，结果**等于 RESET 动画** |
| 37 | 大量角色 IK 靠降低频率 | ⛔ IK 每帧求解，远处 LOD 应关；只降频率仍占用解算 |
| 38 | 同屏角色各持一份动画资源 | ⛔ 应复用；但改参数要确认改的是实例不是共享树 |
| 39 | 混合位置可以直接塞原始速度 | ⛔ 基准值未归一，改移动速度后混合全错；基准值必须进参数表 |
