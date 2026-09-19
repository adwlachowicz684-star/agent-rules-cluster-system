# Godot 4.x 开发索引

**版本**：Godot 4.x。3.x 大量不兼容，模板不可直接套用。

## 按功能域入口

| 我要做… | 看哪个文件 | 关键 API |
|---|---|---|
| **角色移动 / 跳跃 / 手感** | `character.md` | `CharacterBody2D/3D` · `velocity` · `move_and_slide()` · 土狼时间 · 跳跃缓冲 |
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
| **战斗系统** | `combat.md` | 四层分离 · AttackContext 去重 · 判定放物理帧 · hitbox 默认关 · 帧数据三段 · hitstop |
| **数据分析/埋点** | `analytics.md` | object_verb 命名 · 离线优先缓存 · 批量上报 · 不用设备 ID · 引导每步埋点 |
| **渲染管线** | `render-pipeline.md` | 三渲染器能力矩阵 · Web 只能 Compatibility · 性能曲线反直觉 · 后处理开销排序 |
| **光照** | `lighting.md` | 三种 GI 选型 · 烘焙六步与失败码 · bias 权衡 · 体积雾仅 Forward+ |
| **美术资产** | `art-assets.md` | Filter/Repeat/Mipmap · 像素糊的五个原因 · 压缩按用途分层 · 中文子集化 |
| **相机/过场** | `camera-cutscene.md` | 相机分层 · 帧率无关 lerp · trauma 平方衰减 · 过场三要素同状态机 |
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
| **经济/长线系统** | `economy.md` | 货币不能只一个 int · 保底计数必须持久化且绑定卡池 · 洗点要同一事务 · 三种叠加结果不同 · 时间源用 UTC |
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

**节点树即架构** —— Godot 里"父子关系"既是层级也是生命周期。
子节点会随父节点一起释放，这是设计上的便利，也是泄漏的来源
（父节点不释放，子节点就永远在）。

## 常见漏写速查

写完对照一遍：

| 漏写 | 审查规则 |
|---|---|
| Autoload 信号未断开 | GD15 |
| `remove_child` 后没 `queue_free` | GD01 |
| `create_tween()` 未保存引用 | GD02 |
| `FileAccess` 未 `close()` | GD41 |
| 存档写 `res://` | GD43 |
| `instantiate()` 后未 `add_child()` | GD46 |
| 动态 `AudioStreamPlayer` 未 `queue_free()` | GD52 |
| `assert` 做运行时校验 | GD71 |
| `duplicate()` 浅拷贝 | GD73 |
| `print()` 留在正式代码 | GD74 |
| `await` 后未判 `is_instance_valid` | GD75 |
| 每帧赋值 `Label.text` | GD13 |
| `move_and_slide(...)` 带参 | GD09 |
| `velocity *= delta` | GD21 |

完整判据见 `../../code-audit/references/p-godot.md`。

## 验证方式

写完代码后：

```bash
# 审查侧：跑规则
python3 ../../code-audit/scripts/godot-audit.py --src=<项目根>

# 运行时：对象计数是否单调增长（切场景前后对比）
print(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT))
```
