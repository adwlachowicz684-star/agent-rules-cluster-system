<!-- oversize-exempt: 反模式清单，审核用 -->
# version-47-48 — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/version-47-48.md`

ⓘ 本篇针对**版本升级与版本判断**，与 `version-migration.md`（跨大版本结构迁移）分工不同：
那篇管 3→4、4.x 内部结构性变化，本篇管 4.7 / 4.8 的**具体新增与破坏性变更**。

## 常见坑

| # | 坑 | 后果 |
|---|---|---|
| 1 | 生产项目用 4.8 dev 快照 | 特性冻结未完成、API 随时变，升级成本不可控 |
| 2 | 凭检索到的发布列表片段判断版本是否存在 | ⛔ 曾据此得出"4.7.2 不存在"的错误结论；版本类结论只信 godotengine.org 官方发布页 |
| 3 | 认为"4.7 是小版本，升级很安全" | 仅 breaking changes 就有 input 设备 ID、LookAt、stretch 默认、GDScript 两处、Jolt 四处 |
| 4 | 升级后不逐个核对 breaking change 清单 | 每个单看都"没报错"，合起来表现漂移且归因困难 |
| 5 | 仍用 `event.device == 0` 判鼠标键盘 | 4.7 起某些手柄 device 也可能是 0 → 判错设备 |
| 6 | 鼠标键盘设备判断不改用 `DEVICE_ID_MOUSE` / `DEVICE_ID_KEYBOARD` | 本地分屏/多手柄场景行为错乱，且不报错 |
| 7 | 不知道 `LookAtModifier3D.relative` 默认 true → false | 4.6 项目升级后头部朝向直接变 |
| 8 | 只调 `relative` 不管 `use_angle_limitation` | 该选项的**基准角度**也跟着变，限位算错 |
| 9 | 认为 stretch 默认值变了会影响已有项目 | ⛔ 只影响新建项目；误判会导致白白改一套配置 |
| 10 | 4.7 新建项目仍按 `disabled` + `keep` 写分辨率适配 | 默认是 `canvas_items` + `expand`，UI 默认就会缩放 |
| 11 | 继承带类型返回值的方法不显式 return | 4.7 起报错（以前能通过） |
| 12 | 靠 packed array 元素赋值触发整体 setter 做自动保存/脏标记 | ⛔ 4.7 起**静默失效**——不报错，只是不再触发 |
| 13 | 用 Jolt 却不知道 `WorldBoundaryShape3D.plane.d` 符号反转 | 地面/水面边界方向相反，表现像"掉下去"或"被弹回" |
| 14 | 用 Jolt 却沿用旧 `SoftBody3D` 质量语义 | 默认质量 0 → 1 kg，以前按点算总质量巨大 → 手感全变 |
| 15 | 升级后不重调 `SoftBody3D.linear_stiffness` | 换算方式已变，旧参数含义不同 |
| 16 | Jolt 下不屏蔽 `Area3D` 与 `SoftBody3D` 的重叠 | 4.7 起开始上报，触发逻辑被误调用 |
| 17 | 不重测 hitstop | ⛔ 4.7 修了"粒子在 timescale=0 时仍移动"，顿帧期间粒子表现变了 |
| 18 | 认为 `Engine.time_scale = 0` 顿帧写法升级后照旧可用 | 计时器与粒子的组合行为需重新验证 |
| 19 | 4.7 后 AnimationTree 混合"卡住不切"不去查 `sync_mode` | 表现像引擎 bug，实际是 blend space 需要显式设 sync_mode |
| 20 | 开了 HDR 却沿用旧的 2D `source_color` 语义 | 颜色管线变了，2D 与后处理取值范围都要重验 |
| 21 | 在 Android 上开 HDR 输出 | ⛔ 官方明确不支持（仍在开发），Windows/macOS/iOS/visionOS/Linux-Wayland 才支持 |
| 22 | 用 `offset_transform_*` 却忘了 `visual_only` 默认 true | 动画后点击区域不变——多数情况是**对的**，只在需要点击区跟随时才应改 false |
| 23 | 给 `offset_transform_*` 设 false 却没测 hover/点击回归 | 动画期间按钮可能失去响应 |
| 24 | `tween_await()` 接带参数的信号且不用 `set_unbinds()` | ⛔ tweener 不会正确结束，动画链静默停住 |
| 25 | `tween_await()` 等同一个 tween 内回调发出的信号 | 信号可能早于 await 开始发出 → 永不结束；无法保证时序就该用 `parallel()` |
| 26 | 认为 4.8 纹理流送能替代 chunk 流式加载 | ⛔ 互补不是替代：那个管场景节点，这个只管纹理 VRAM |
| 27 | 在 Compatibility 渲染器上开纹理流送 | 只在 Mobile 与 Forward+ 实现，GLES 3.0 读回限制 |
| 28 | 纹理不以 "Texture2D Streamed" 类型导入就指望流送生效 | 导入类型不匹配，设置开了也没效果 |
| 29 | Mobile 渲染器上用 alpha scissor / `discard` 还指望早期剔除 | ⛔ 缺 depth pre-pass 会强制开 early-z，性能可能**更差** |
| 30 | 把 dev 阶段 API（Trail3D 参数、纹理流送设置项名）写进生产代码 | dev → stable 之间可能改名，升级即断 |
| 31 | 4.7 起仍走 Android Google Play OBB 发布流程 | 该支持已移除，旧流程直接不可用 |
| 32 | 升级前不锁 commit / 不备份 | 版本类问题回退成本极高，见 `version-migration.md` |

## 版本判断的三条硬约束

| # | 约束 |
|---|---|
| 33 | ⛔ **生产用 4.7.2，不用 4.8 dev**——4.8 特性冻结未完成，官方策略表为 Q4 2026（估计） |
| 34 | ⛔ **版本存在性只认官方发布页**，检索到的列表片段可能是发布周期中的快照 |
| 35 | ⛔ **`待核对` 项在目标版本实测前不得当结论用**——本篇 howto 第 4 节列出的均为待核对，用 `scripts/verify.py` 追踪 |
