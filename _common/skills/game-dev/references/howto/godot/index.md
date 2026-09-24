# Godot 4.x 开发索引

**版本**：Godot 4.x。3.x 大量不兼容，模板不可直接套用。

## 按功能域入口

| 我要做… | 看哪个文件 | 关键 API |
|---|---|---|
| **角色移动 / 跳跃 / 手感** | `character.md` | `CharacterBody2D/3D` · `velocity` · `move_and_slide()` · 土狼时间 · 跳跃缓冲 |
| **转职 / 觉醒 / 职业进阶** | `class-awaken.md` | `ClassTemplate/ClassState` 分离 · 转职事务（试算→扣费→提交→回滚） · 装备兼容判定 · 技能映射表 |
| **UI / 菜单 / HUD / 背包 / 对话** | `ui.md` | `Control` 锚点 · `CanvasLayer` · `GridContainer` · `RichTextLabel` |
| **存档 / 设置 / 场景切换 / 事件总线 / 对象池** | `systems.md` | `ResourceSaver` · `user://` · `change_scene_to_file` · Autoload signal |
| **动画 / 状态机 / Tween** | `animation.md` | `AnimationPlayer` · `AnimationTree` 状态机 · `Tween` 链式 · `kill()` |
| **输入绑定 / 音效 / BGM** | `input-audio.md` | Input Map 动作 · 四回调顺序 · `AudioServer` 总线 · 音效池 |
| **碰撞 / 射线 / 触发区 / 施力 / 移动平台** | `physics.md` | 碰撞层位掩码 · `intersect_ray` 参数对象 · `Area2D` · `AnimatableBody` |
| **3D 场景 / 相机 / 材质 / 光照 / 粒子** | `3d.md` | 坐标系 · 第三人称相机 · 共享材质陷阱 · `Environment` |
| **敌人 AI / 寻路 / 状态机** | `ai-navigation.md` | NavigationAgent2D 模板 · 巡逻追击攻击 FSM · AStarGrid2D · 视线检测 |
| **TileMap 关卡 / 地形 / 程序生成** | `tilemap.md` | 4.3+ vs 4.2 两套 API · 坐标转换 · 地形拼接 · FastNoiseLite |
| **移动端触控 / 虚拟摇杆 / 适配** | `mobile.md` | ScreenTouch/Drag · 浮动摇杆 · 手势识别 · 安全区 · 返回键 · 移动端性能 |
| **性能诊断 / 优化** | `performance.md` | 先测量再优化 · Monitors 排查泄漏 · 屏幕外停处理 · 线程池 · 性能预算 |
| **GDScript 热路径 / 生命周期** | `gdscript-advanced.md` | 类型系统 · 热路径禁止清单 · await 三坑 · 回调时机 · @tool 隔离 |
| **架构 / 规范** | `architecture.md` | 17 步成员顺序 · call down signal up · 组件组合 · Resource 数据驱动 |
| **测试 / CI** | `testing.md` | GUT · 无框架最小方案 · 静态检查进 CI · 存档回归测试 |
| **多人 / 服务器权威** | `multiplayer.md` | @rpc 参数 · 输入上报+序号 · 客户端预测回滚 · 快照插值 · authority 迁移 · 专用服务器 |
| **对话 / 任务 / 库存** | `game-systems.md` | 命令解释器白名单 · 对话图 + Runner · 任务定义与进度分离 · 库存四层 · 奖励幂等 |
| **生成 / 编辑器 / 管线 / XR** | `advanced-topics.md` | 确定性生成 · BSP + 连通性校验 · EditorPlugin 生命周期 · 资源三层隔离 · XR 性能预算 |
| **渲染进阶** | `rendering-advanced.md` | XR 手部/抓握/传送 · LOD 四层 · visibility_range · 着色器管线预热 · 大世界分块 |
| **AI 决策** | `ai-behavior.md` | FSM/BT/GOAP/效用选型 · 最小行为树 · 黑板 · RUNNING 语义 · LimboAI/Beehave |
| **高级测试** | `testing-advanced.md` | 属性/不变量 · 存档模糊 · 截图 diff · p99 帧时间基准 · 确定性回放 |
| **调试 / 排错** | `debugging.md` | 断点两种区别 · 多线程断点失效 · release 日志差异 · CPU/GPU 瓶颈判定 · 故障定位流程 |
| **CI / 发布** | `cicd-publish.md` | 无头导入 · 完整 Actions 配置 · 产物非空校验 · 模板版本匹配 · 各平台签名 · 凭据走 Secret |
| **C# / .NET** | `csharp.md` | C#/GDScript 选型 · .NET 版本政策 · PascalCase 生命周期 · Signal 委托命名 · await 守卫 |
| **版本 / 迁移** | `version-migration.md` | 4.x 结构变化 · TileMap 三重迁移 · 3→4 改名对照 · 锁 commit · 升级检查清单 |
| **插件生态** | `plugins.md` | 决策口诀 · 按环节取舍表 · 绝不引入的 8 种情况 · 引入检查清单 |
| **动画高级** | `animation-advanced.md` | StateMachine/BlendSpace/BlendTree 分工 · travel vs start · switch_mode 是过渡时机 · 根运动双倍位移 · IK 开销 |
| **音频高级** | `audio-advanced.md` | 总线架构 · 音量是分贝不是 0-1 · 音效池轮转 · 动态音乐分层 · 暂停 process_mode |
| **开放世界** | `openworld.md` | chunk 三半径滞回 · 分帧预算 · 节点池 · Terrain3D · 大世界坐标精度 · 原点重置 |
| **XR/VR** | `xr.md` | 内置节点四件套 · 不能接管相机 · 无速度 API · 抓取速度传递 · 晕动症规避 |
| **4.7/4.8 版本专项** | `version-47-48.md` | **目标版本** · 4.7.2 稳定 / 4.8 仍 dev · AreaLight3D · HDR · offset_transform · 内置 VirtualJoystick · breaking changes |
| **网络同步进阶** | `netsync-advanced.md` | 同步模型选型 · 客户端预测+输入历史 · 服务器回滚(固定dt+阈值) · 远端插值 · rpc 默认 reliable · 传输层取舍 |
| **GDExtension/插件** | `gdext-plugin.md` | 先 profile 再换语言 · 版本+浮点精度是 ABI · 4.0→4.1 硬断裂 · 热重载仅编辑器 · @tool + 对称注销 |
| **战斗系统** | `combat.md` | 四层分离 · AttackContext 去重 · 判定放物理帧 · hitbox 默认关 · 帧数据三段 · hitstop  · **对抗层**：硬直/霸体/破防/招架/处决/部位破坏（争夺行动权不是数值增减）· 硬直两来源分开且按真实时间衰减 · 霸体是**延迟硬直不是减伤** · 招架先于伤害结算且不能概率 · 处决期间攻击方无敌目标不可打断 · 部位是独立实体 |
| **数据分析/埋点** | `analytics.md` | object_verb 命名 · 离线优先缓存 · 批量上报 · 不用设备 ID · 引导每步埋点 |
| **渲染管线** | `render-pipeline.md` | 三渲染器能力矩阵 · Web 只能 Compatibility · 性能曲线反直觉 · 后处理开销排序 |
| **光照** | `lighting.md` | 三种 GI 选型 · 烘焙六步与失败码 · bias 权衡 · 体积雾仅 Forward+ |
| **美术资产** | `art-assets.md` | Filter/Repeat/Mipmap · 像素糊的五个原因 · 压缩按用途分层 · 中文子集化 |
| **相机/过场** | `camera-cutscene.md` | 相机分层 · 帧率无关 lerp · trauma 平方衰减 · 过场三要素同状态机 · **视角切换要继承朝向**（否则切完朝天/朝地）· ⛔ 第一人称本体分层+near 更小 · **多相机用优先级栈**（过场>死亡>载具>正常），⛔ push/pop 必须配对否则永久卡住 |
| **引导/成就** | `onboarding-meta.md` | 引导超时兜底 · 九宫格挖洞 · 成就定义与状态分离 · Mod 是任意代码 |
| **平台导出/发布** | `platform-export.md` | 六平台速查表 · Web 仅 Compatibility · 多线程需 COOP+COEP · NDK 必须 r28b · keystore 丢了包名报废 |
| **GDExtension 实战** | `gdextension-deep.md` | pin 到 4.7 同步 commit · entry_symbol 严格匹配 · 只在 SCENE 层注册 · RefCounted 必须 Ref<T> |
| **编辑器插件开发** | `editor-plugin.md` | enter/exit_tree 对称注销 · is_editor_hint≠跑游戏 · get_undo_redo 按对象选历史 · 4.7 统一 EditorDock |
| **性能剖析/平台差异** | `perf-profiling.md` | 编辑器 FPS 不代表目标设备 · P99 才是卡顿指标 · Profiler 不覆盖 C# · 移动端要测 10 分钟 |
| **XR 深入/手部交互** | `xr-deep.md` | XRCamera3D 会滞后几毫秒 · 抓取不能 reparent 刚体 · 控制器无速度 API 需自己差分 · 优先传送 |
| **程序化生成** | `procedural-generation.md` | 没 seed 无法维护 · 全局 randi 是全局状态 · 元胞自动机最易不可达 · 分帧要先纯数据算完 · ±10⁷ 是精度问题 |
| **AI 感知** | `ai-perception.md` | 感知≠寻路 · 输出不是 bool 要有置信度 · 遮挡必须射线 · 4.x 要 PhysicsRayQueryParameters3D · 检测 10Hz 够 |
| **骨骼动画/IK** | `animation-skeletal.md` | 骨骼是有序数组非节点 · 4.7 无 PoleModifier3D/SplineIK3D · modifier 顺序由子节点列表定 · 每帧回滚 |
| **数据驱动/配表** | `datatable.md` | 数值写代码=程序员成瓶颈 · duplicate() 默认浅拷贝共享子资源 · 外键存 ID 不存引用 · 导入期要校验 · load_threaded 才是异步 |
| **VFX/游戏感** | `vfx-feel.md` | GPU 粒子不是默认答案（Web/兼容渲染器选 CPU）· 震动要 trauma+噪声不是随机偏移 · time_scale=0 时定时器也停需 ignore_time_scale |
| **经济/长线系统** | `economy.md` | 货币不能只一个 int · 保底计数必须持久化且绑定卡池 · 洗点要同一事务 · 三种叠加结果不同 · 时间源用 UTC · **装备四层分离（模板/实例/词条快照/绑定）· 失败回退让期望次数从 31 涨到 2557 · 词条存 roll 不存最终值 · 分解按当前状态折算** |
| **遗物/局内构筑** | `relic-build.md` | 遗物/词条/局外解锁按失效时机分 · 先 seed 后 state · RNG 无雪崩效应 · `rand_weighted` 空数组返回 -1 |
| **植被/大规模散布** | `vegetation.md` | MultiMesh 共享一个 AABB · 分块 + `custom_aabb.grow()` · MSAA 对 alpha scissor 无效需配 alpha AA · 砍伐要交换不能缩放 |
| **VIP/订阅/累充** | `vip-subscription.md` | 系统时钟用户可改 ⛔ 禁用精确计时 · 跨端统一 UTC · 缺键默认 1970 静默 · 等级是派生值 · 续期 `max(end,now)+d` · 回调去重 |
| **宝石/符文** | `gem-rune.md` | 宝石是 Resource 不是 Node · 插槽类型来自配表 · 镶嵌是事务（先删后插=资产消失）· 拆卸损耗必须明示 · 合成防套利环 · 套装按槽位去重 |
| **输入重绑定** | `input-remap.md` | 4.x 用 action_get_events 非 get_action_list · 键位以 physical_keycode 为主键 · 振动不会自己停需显式 stop |
| **无障碍/字幕** | `accessibility.md` | 无障碍≠难度选项 · 颜色即信息时滤镜无效要形状冗余 · 字幕要含非语音线索 · 闪烁每秒≤3 次且面积≤1/4 |
| **回放/录像** | `replay.md` | Godot 物理官方不保证确定性 · 录的是每 tick 动作状态非按键流 · MovieMaker 是离线逐帧非实时录屏 |
| **关卡设计** | `level-design.md` | 白盒直接上美术更贵 · CSG 官方定位是原型非资产 · tscn 是文本≠可安全合并 · 关卡不硬编码逻辑 · 跳关入口决定迭代速度 |
| **云存档/跨端** | `cloud-save.md` | 核心是冲突不是传输 · 不能用文件修改时间判冲突 · Godot 无内置云存档要平台 SDK · iOS Caches 不备份 · HTML5 用 IndexedDB |
| **调试工具/GM** | `devtools.md` | 自定义参数要放 `--` 后用 get_cmdline_user_args · Performance 部分监控 release 恒为 0 · 作弊要视觉标识+审计日志 · 无内置 DebugDraw3D |
| **玩家 Mod** | `modding.md` | Mod≠编辑器插件 · 后来加载的覆盖先加载的 · replace_files=false 是不覆盖非沙箱 · Mod 脚本无法沙箱隔离 · 手动解压要防 zip-slip |
| **存档迁移** | `save-migration.md` | 格式版本≠游戏版本≠构建号 · VERSION 要第一天写 · 迁移前必须备份 · 后要重算 HMAC · 降级 get_value 静默返回默认值 |
| **热更新/DLC** | `hotupdate.md` | 资源热更≠代码热更差一个量级 · 已缓存资源不会自动换血 · iOS 审核 2.5.2 禁止动态代码 · 配置热更也要版本校验 · DLC 未购买要占位 |
| **平台服务** | `platform-services.md` | Godot 无内置成就/排行榜/内购 · 要统一异步接口+离线桩 · 发布包不要带 steam_appid.txt · 无 Steam 客户端要降级不崩 · token 秘密留服务端 |
| **画质/超分** | `upscaling.md` | stretch 与 3D 缩放是两套机制 · 内置只有 FSR2.2 无 FSR3/DLSS · TAA 仅 Forward+ · 2D MSAA 在 Compatibility 不可用 · HDR 只在部分 tonemap 下响应 |
| **载具/物理进阶** | `vehicle-physics.md` | VehicleBody 是街机求解器非高保真 · 翻车多是质心非碰撞形状 · SoftBody3D 官方存在建议 Jolt · 摩擦默认取最低 · 卡帧物理最多追 8 步 |
| **角色自定义** | `character-customization.md` | 捏脸/换装/染色三套生命周期别混设计 · 无官方合并网格 API · 合并与 BlendShape 不能混用 · 合并网格无自动 LOD · 4.6 起 skeleton 默认路径变 |
| **环境系统** | `environment-systems.md` | 无官方 Water 节点但 apply_force 能做浮力 · Gerstner 采样 CPU/GPU 必须一致否则船漂错高度 · 天空/雾/环境光/GI 联动 · Static 烘焙完全锁定不能做昼夜 · 雨要跟随相机 |
| **UI 进阶** | `ui-advanced.md` | 无内置虚拟列表且 Tree 也不虚拟化（70k 项 1.21 GiB） · BBCode 有注入风险要 escape · 拖拽预览不能自己 free · 鼠标能点≠手柄能选 · 4.7 AccessibilityServer 独立成单例 |
| **诊断与稳定性** | `diagnostics.md` | GDScript 无 try/catch · print 崩溃时可能没刷盘要用 stderr · assert 在 release 不求值且副作用会丢 · 原生崩溃进程没机会上报 · MovieMaker 不是玩家录像器 |
| **商业化/变现** | `monetization.md` | Godot 4.x 全系列无内置 IAP/支付/广告 API · 客户端只是发起支付的遥控器 · 合规优先于体验 · 中国抽卡是四件套（含替代获取途径）· 概率公示必须与实现同源 · 保底存服务器防清档 · 掉单幂等 |
| **投射物/弹道** | `projectile.md` | 无专门子弹节点 · CCD 官方称「有时有效」不替代射线扫描 · 预测线必须复用真实弹道函数否则显示与落点不一致 · 网络应同步开火事件而非逐帧 transform · 一帧多次命中要去重 |
| **进阶移动** | `movement-advanced.md` | 特殊移动不能堆 if 要状态机 · 抓边要两条射线且分吸附/悬停/攀爬三阶段 · 不要直接赋坐标会穿薄墙 · 改 up_direction 不必然失效（真正原因是那 5 个）· 改重力要 up/相机/移动平面一起变 |
| **多人社交** | `social.md` | Godot 不内置任何社交服务 · ENet 只是 UDP 传输层不是 P2P 平台 · 房主是临时协调者要能迁移 · 聊天必须服务器过滤并留存 · 举报要存证据快照 · 分控制面与数据面  · **阵营/声望/战力/战报**：关系是非对称**有向图**不能镜像 · 切换要时间+关系+经济三重代价防身份套利 · 战力只展示**不能当匹配依据** · 战报存最小事件集且跨版本要隔离 · 战绩默认最小展示（未满14岁属敏感个人信息） |
| **生存/角色状态** | `survival.md` | 引擎没有 HealthComponent 要自己定义 · 数值四层必须分开且**存输入不存计算结果** · 死亡是四阶段状态机不是 bool · 重生要清 Tween/Timer/信号/飞行投射物 · 检查点只覆盖重生事实不覆盖手动存档 · 死亡播放期间禁止保存 |
| **叙事/进程** | `narrative.md` | flag 必须集中在 StoryState 否则后期无法重构 · 三段式命名防撞车 · 结局要判定表不是 if elif · 优先级显式配置且要查可达性 · 隐形前置要可查询否则卡关 · 周目继承策略各不同 |
| **谜题/机关** | `puzzle.md` | Godot 没有谜题系统要自己定协议 · 交互要抽象成**意图**而非绑按键 · 状态与运行时分开（读档 seek 到终点）· 组合逻辑数据驱动 · 反射必须硬上限 8 次且**用 bounce 不是 reflect** · 推箱子用网格才能校验与 undo · 防卡关是生死线 |
| **时间操控** | `timescale.md` | 时间至少五层不是单一旋钮 · **音频不受 time_scale 影响**要单独处理 · 暂停与慢放是两件事 · process_mode 与 Tween 忽略缩放**正交** · `Tween.set_ignore_time_scale` 是 4.7 新增 · 倒带是快照+冻结不是物理倒流 |
| **着色器** | `shaders.md` | GDShader 方言 · uniform 提示清单 · 2D/3D 九个配方 · 坐标空间 · 变体与预热 · 调试颜色 mask |
| **存档加密 / 防作弊** | `security.md` | 客户端加密的边界 · AES+HMAC 存档 · 随机 IV · 内存值混淆 · 时间作弊 · 服务端权威 |
| **本地化技术实现** | `i18n.md` | `tr()`/`tr_n()` · CSV 工作流 · 语言切换 · 字体回退 · RTL |
| **2D 渲染 / 着色器 / 屏幕特效** | `2d-rendering.md` | Y-Sort 结构 · Parallax2D · shader 配方 · trauma 抖动 · hitstop |
| **资源加载 / HTTP / 多人联机** | `io-network.md` | `load`/`preload` · 线程加载 · `HTTPRequest` · ENet · `@rpc` |
| **项目设置 / 导出 / 调试 / 性能** | `project.md` | 项目设置关键项 · Autoload · `Performance` · 导出清单 |

## 本地化：本目录只放技术

`i18n.md` 只讲引擎侧实现（`tr()`、CSV、切语言、字体回退）。
**翻译流程、文案管理、术语表、翻译 QA 属于独立 skill `localization`**，
那边目前是占位壳子，内容待真实项目需求驱动填充。

两边不重复写 —— 重复必然只改一处，另一处过期。

## 项目结构约定

推荐的目录组织（不强制，但这样最不容易乱）：

```
my_game/
├── project.godot
├── scenes/              # .tscn 场景文件
│   ├── main.tscn
│   └── levels/
├── scripts/             # .gd 脚本
│   ├── player/
│   ├── enemies/
│   └── ui/
├── autoload/            # 全局单例（Events / SaveManager / SceneManager）
├── assets/              # 美术音频原始资源
│   ├── sprites/
│   ├── audio/
│   └── fonts/
└── ui/                  # UI 场景（.tscn）
```

**Autoload 配置**：项目设置 → Autoload，加载顺序有讲究
（被依赖的先加载，如 Events 要在其他之前）。

## Godot 特有的心智模型

从 Unity/Unreal 转过来最容易踩的：

| 你以为 | 实际 |
|---|---|
| 场景 = 关卡 | 场景是**可复用的节点树**，任何子树都能存成场景再实例化 |
| 预制体（Prefab） | 就是场景（`.tscn`）+ `instantiate()` |
| 组件挂载 | 节点组合 + 脚本 `extends`，一个节点只能挂一个脚本 |
| 烘焙光照进场景 | 需要 `LightmapGI` / `VoxelGI` 节点显式烘焙 |
| GameObject.Find | `get_node()` 路径查找，或 `@onready` 缓存 |
| **塔防 / 波次 / 索敌** | `genres-tower-defense.md` | Wave Resource · 路径缓存 · map_force_update · 降频 shape query |
| **RTS / 框选 / 编队 / 战争迷雾** | `genres-rts.md` | 命令模式 · Rect2.has_point · 编队偏移位 · 迷雾脏区批量提交 |
| **卡牌 / 效果栈 / 连锁** | `genres-card.md` | CardData Resource · 显式效果栈 · rng 洗牌 · .tres 存档 |
| **Roguelike / 元进度** | `genres-roguelike.md` | 四阶段 RNG 分支 · 纯数据中间表示 · AStar2D 房间图 · 原子写盘 |
| **自走棋 / 战棋 / 六边形** | `genres-tactics.md` | 轴向坐标 · 离散朝向枚举 · 事件队列结算 · 棋盘双表示 |
| **模拟经营 / 放置 / 离线收益** | `genres-idle-sim.md` | 固定步长累加器 · 离线跑完整 tick · Unix 时间 · 数组格子校验 |
| **平台跳跃手感** | `platformer-feel.md` | get_real_velocity · _input 捕获缓冲 · CUT_SPEED 截断 · was_on_floor |
| **弹幕射击 / SHMUP** | `genres-bullet-hell.md` | MultiMesh 定容量 · 只查判定点 · 固定逻辑步长 · 图案数据化 |
| **破坏 / 布料 / 软体** | `destruction-cloth.md` | 预切分凸碎片 · 碎片池与预算 · SoftBody3D 边界 · Jolt |
| **遮挡剔除 / 实例化 / GPU 粒子** | `occlusion-instancing.md` | OccluderInstance3D 烘焙 · visible_instance_count · RenderingDevice |
| **版本控制 / 资源组织** | `vcs-collab.md` | .uid 必须入库 · 移动带侧车 · 可 diff ≠ 可合并 · LFS 白名单 |
| **性能预算 / CI / 评审 / 技术债** | `project-governance.md` | P95/P99 · Profiler 有开销 · 符号一一对应 · 高影响重构分 PR |
| **观战 / 断线重连 / 主机迁移 / 延迟补偿** | `spectate-reconnect.md` | 观战者是纯接收端 · Peer ID 是会话 ID · close() 不发射断开 · 重连以连续权威快照为准 · 角色保留+AI托管 · 仲裁要 quorum |
| **群集行为（boids）与避障** | `boids-swarm.md` | 三规则加权 · 网格裁剪邻居 · avoidance_enabled 默认 false · velocity_computed 要自己移动 · 静态障碍不能每帧移动 |
| **分区分服 / 跨服 / 合服 / 匹配** | `sharding-matchmaking.md` | 全局账号+逻辑服角色 · 各服自增 ID 会撞车 · 合服快照 dry-run 幂等 · 邮件附件幂等会满 · 匹配判定服务端 |
| **合规/法务/版号（上线门槛）** | `compliance.md` | **Godot 无任何合规 API** · 版号 80 工作日是受理后不含补正 · 防沉迷现行是周五六日及法定节假日 20–21 时 1 小时（2019 口径已作废）· 实名是登录前置含游客模式 · 未满 8 岁禁付、8–16 岁 50/200、16–18 岁 100/400 · 注销是状态机不是 DELETE · 数据出境按当年累计人数 |
| **宠物 / 坐骑 / 召唤物 / 孵化合成** | `companion.md` | 没有 Pet/Mount/Summon 节点 · 宠物不是"会动的装备"要三层分离 · 共享 SpeciesResource 改一只影响所有同类 · 骑乘**只有一个** CharacterBody 驱动 · reparent 要 call_deferred 且保留全局变换 · 孵化/合成结果必须**开始时** roll · 召唤物要对象池 + 服务端强制上限 |
| **时间推进：离线结算 / 生产队列 / 体力 / 重置** | `time-progression.md` | 内核只有 `elapsed = now - last_settled_at` · 存档存**绝对锚点**不存剩余秒数 · 余数必须写回锚点、float 累加器禁止 · 离线速率按**事件日志分段**不能按回来那一刻倒推 · 封顶是留存节奏 · 重置是**硬边界**要能补算 · PAUSED 只做持久化（iOS 约 5 秒） |
| **账号安全 / 生命周期 / 风控** | `account-security.md` | **Godot 不是安全边界**、`user://` 不是凭据库 · 密码要 Argon2id（快速摘要加盐不算密码哈希）· access 短命、refresh 要**轮换且重用撤销整个 family** · TOTP 30 秒窗口最多 1 步 · 短信是 **RESTRICTED** 不能当唯一强验证 · 找回不能靠客服跳过第二因素 · 风控信号**只增信**不能当认证因子 · 注销不能只删角色 · 转服要同一幂等键 |
| **服务端稳定性 / 容量 / 事故响应** | `backend-stability.md` | **无超时 + 无限流 + 无熔断 + 无界重试**会把抖动放大成雪崩 · 限流按"允许突发/允许排队"选算法 · 熔断**必须统计超时** · 重试要退避+抖动+幂等键且 jitter 覆盖首次重连 · 分片键要**贴合访问路径** · 压测要测**受控失败** · 告警必须可执行且要降噪 · **先恢复再查根因** · 备份副本数**不能证明能恢复**，要演练 · 数据回滚常不可行，主路径是向前修 |
| **构筑（Deckbuilding）与词条/词缀系统** | `build-affix.md` | 构筑与词条是**两条独立规则** · 词条存最终值会失去重算能力（要 `affix_id + roll + 双 version`）· `generation_version` 与 `balance_version` **要分开** · 减伤两条 75% 相乘得 **93.75%** 逼近无敌 → 组内求和组间相乘再 clamp · 互斥要在**四个入口**检查 · 协同分数值与触发两种 · 构筑要**组卡/保存/开局**三层校验且服务端重跑并签名 |
| **自动战斗 / 扫荡 / 离线挂机** | `auto-battle.md` | 同一战斗模拟器在四种输入源下的复用**不是四套实现** · 扫荡是不带位置碰撞动画的结算函数**不是加速战斗** · 预告与发放必须同一笔事务 · 自动AI只见玩家可见信息否则托管客观强于手动 · 离线一次性分段推导⛔不能按真实时间跑循环 · 回放与观战见 `replay.md`/`spectate-reconnect.md` |
| **外观与个性化** | `cosmetic.md` | 客户端只持可展示缓存**服务端保存拥有权有效期优先级授权** · 显示用A属性用B是第一道隔离 · 外观与装备实例必须分离 · 称号可伪造会冒充GM · 坐骑皮肤⛔不能改移速碰撞 · 默认外观要零外部依赖 · 增量丢包不自愈要全量校正 · 限时时装到期两种承诺须购买前明确 · 换装与染色技术层见 `character-customization.md` |
| **玩家交易 / 拍卖行 / C2C 流通** | `player-trading.md` | 客户端请求交易**服务端决定一切** · 资产离开一个位置前必须先建立另一个位置的权威暂存 · 流转的是**实例**不是模板 · 绑定是迁移函数的输入每次重新求值 · 上架即托管否则双卖 · 一口价服务端重读价格 · 竞价本质是冻结领先者资金 · 价格显示是缓存成交必须实时 · 税三种模式不可混用且**销毁**比进系统钱包可控 · 延迟到账是盗号止损唯一窗口 · 撤销全有或全无 · 风控看**关系链** · 日志要写请求前快照+意图+结果 |
| **潜行 / 侦察 AI 玩法层** | `stealth-ai.md` | 潜行不是「发现/未发现」布尔，是**连续怀疑度 → 离散警戒等级 → 可观察行为**三层 · 警戒拆 `EvidenceTier`（知道多少）+ `ActionState`（在做什么），⛔ `HOSTILE` 不能直跳 `UNSEEN` · 单源怀疑度**必须有软上限**（否则一次落地直接进战斗）· 搜查是**覆盖区域**不是访问噪声点，且要能被玩家利用 · 可见度是连续值采样头/躯干/脚 · 视野锥**必须让玩家看得见** · 暗杀是六项状态条件不是处决换皮 · 尸体是持久证据且要进对象预算 |
| **枪械 / 射击系统** | `firearms.md` | 枪械是**射击状态与规则层**不是动画层 · 后坐力拆**视觉/模式/扩散**三个独立变量（⛔ 不是镜头抖动）· 扩散必须可读，准星显示命中半径但**不参与命中** · 预测线必须与真实弹道**共用同一积分器** · 换弹的**逻辑装填门限早于动画结束**（战术换弹枪膛留一发，统一扣会白丢一发）· 切换是 `disable` 不是销毁 · 命中射线归一到**统一 socket** · ⛔ 命中判定绝不能客户端定 |
| **生活职业 / 采集生产 / 家园建造** | `lifeskill-housing.md` | 采集/加工/家园是**同一材料闭环的三个闸门** · 采集点是**模板+世界实例**不是一个节点 · 刷新要绝对锚点不能相对倒计时 · 配方是**多级 DAG** 要查循环依赖否则无限增值 · 入队≠消耗要开始时原子扣 · 家园用**整数占格表**不能用物理碰撞校验 · 要 `home.version` 防多人摆放冲突 |
| **载具 / 驾驶** | `vehicle.md` | 轮式走 `VehicleBody3D` 其余走 `RigidBody3D` · 车轮是**直接子节点**且**无碰撞体**（自带射线）· ⛔ `mass` 必须显式设 · ⛔ `suspension_travel=0` 像滑板 / `damping=0` 无限弹跳（最像引擎 bug）· `engine_force`/`steering` 是**持续属性**要显式归零、物理帧施加 · 转向用弧度且随速衰减 · 乘员用 `Area3D` 且状态存外部 · 上下车先定位再切控制且有冷却 |
| **成就系统** | `achievement.md` | 定义与状态**必须分离**否则改 `target_progress` 炸存档 · ⛔ `id` 用显示名/索引则改名即进度全丢 · 进度是**跨会话累计**不是会话计数（否则永远解锁不了）· 事件驱动⛔不轮询 · 复合型子条件各存 `sub_progress` 且判定**不短路** · 解锁事务顺序固定：判达成→标记→发奖→通知 · 发奖**幂等**（重放可刷）· 标记与发奖一起落盘 · 隐藏成就**必须**展示标题/进度/是否已解锁 · ⛔ Godot 核心无成就能力需插件 · 平台同步失败**必须可重试** · 新增累计型成就要 backfill 否则老号永远拿不到 |

**节点树即架构** —— Godot 里"父子关系"既是层级也是生命周期。
子节点会随父节点一起释放，这是设计上的便利，也是泄漏的来源
（父节点不释放，子节点就永远在）。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/index.md`


## 验证方式

写完代码后：

```bash
# 审查侧：跑规则
python3 ../../code-audit/scripts/godot-audit.py --src=<项目根>

# 运行时：对象计数是否单调增长（切场景前后对比）
print(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT))
```
