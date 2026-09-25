# 性能剖析与平台差异（Godot 4.7.2）

通用优化看 `performance.md`，本文讲**怎么量**和**各平台差多少**。

## 0. 测量纪律：不可比较的 FPS 只是运行痕迹

⚠ **任何基准记录至少要包含**：Godot 精确版本、项目提交、导出模板、
release/debug、渲染方法、图形 API、内部分辨率、显示分辨率、MSAA、
阴影、后处理、质量预设、场景种子、**运行分钟数与环境温度**。

⚠ **编辑器的 FPS 不能替代目标设备** ——
编辑器跑在桌面 GPU 上，还有 gizmo、热重载、远程调试器。
**只优化编辑器里的尖峰，等于把问题推迟到发布前。**

⚠ **平均帧率掩盖尖峰** ——
1000 帧中 990 帧 14ms、10 帧 120ms，均值仍接近 60FPS，但用户明显感到停顿。
**要记 P50/P95/P99，掉帧次数定义为超过目标帧间隔 120% 的帧数。**

⚠ **"测一次"和"测 10 分钟"回答不同问题** ——
桌面短时测峰值算力，移动/XR 长时测**可持续性能**。
每次先预热 30–60 秒让着色器、缓存、调度稳定再记录。

## 1. Profiler：四条曲线回答四件事

⚠ **帧时间 ≠ process 时间，也 ≠ GPU 时间** ——
它覆盖从物理到渲染完成的全部逻辑。

**Inclusive vs Self**：
- `Inclusive` 高、`Self` 低 → 它自己便宜，只是调了贵函数 → **找子函数**
- `Self` 高 → 值得直接审算法、缓存、分配

⚠ **百分比视图找相对热点，毫秒视图判断用户体验**。
只盯百分比会形成错误安全感：新增更贵的系统会让原热点"看起来变小"。

⚠ **Profiler 当前不覆盖 C#**（版本事实，不是配置问题）——
C#/GDExtension 项目必须辅以原生工具（dotTrace 等）。

## 2. Monitors：单位与更新频率决定能否解读

- `MONITOR_MAX = 59`（4.7.2）
- ⚠ **部分监视器只在 debug 可用，发布版返回 0**；
  部分因性能原因**延迟最多 1 秒**更新

| 监视器 | 用途 |
|---|---|
| `TIME_PROCESS` | 一帧耗时 |
| `TIME_PHYSICS_PROCESS` | 一物理帧耗时 |
| `TIME_NAVIGATION_PROCESS` | 导航地图更新 + 代理避障 |
| `OBJECT_COUNT` / `OBJECT_NODE_COUNT` | 对象数 / 场景树节点数 |
| `OBJECT_ORPHAN_NODE_COUNT` | 未挂树的节点（debug 模式） |
| `RENDER_TOTAL_DRAW_CALLS_IN_FRAME` | 未被剔除的 draw call |
| `RENDER_TOTAL_PRIMITIVES_IN_FRAME` | 因 prepass/shadow 通常约为实际 2–3 倍 |

⚠ **对象数比节点数更能发现泄漏**：
进入关卡→退出→再进入，检查是否回到基线。
- 对象数涨、节点数不涨 → **Resource/Image/Shape 残留**
- 节点数涨 → 场景树没真正释放

⚠ **primitive 数不能直接和建模工具的三角形数比** ——
会因 depth prepass、shadow pass 翻倍。

⚠ **VRAM 看 Video RAM 面板**（按资源列路径/类型/格式/用量），
总量上涨时按大小排序。注意总量可能含杂项，不等于系统报告的 VRAM。

## 3. 帧预算

| 目标 | 帧预算 | P99 参考门槛 |
|---|---|---|
| 60 FPS | 16.67 ms | 24 ms |
| 90 FPS | 11.11 ms | — |
| 120 FPS | 8.33 ms | — |

⚠ 以上是**工程量级，不是官方承诺**。

⚠ **物理步长默认 60Hz，与渲染帧率不匹配会 jitter** ——
需要开物理插值。

## 4. 各平台特有差异

### 桌面

⚠ **Forward+ 的灯光优势是摊销，不是无限免费** ——
200 个不可见灯与 20 个覆盖全屏的灯完全不同。
**不存在跨硬件统一的"X 盏灯后变慢"阈值**，要自己在目标 GPU 上测。

**判定 CPU / GPU bound 的方法**（不是猜）：
1. 关 V-Sync，比 720p 与 1080p
2. 分辨率降、帧时间大幅降 → **fillrate/bandwidth**
3. 分辨率不变、减灯光/材质/后处理有效 → **shader/状态**
4. 两者都不动且 CPU 占满 → **逻辑瓶颈**

⚠ **首帧 shader 编译常被误认为 GPU 卡顿** ——
用 `Time.get_ticks_usec()` 包住 `load()` / `instantiate()` 测。
预热一个代表场景比让用户首屏承担所有变体可控。

### 移动端（Android / iOS）

⚠ **tile GPU 的核心优势是片上处理，读屏会破坏它** ——
凡是需要读取现有 framebuffer 的全屏效果（SSR/折射/glow/DOF/多次 bloom），
都要先做"关掉后 GPU 时间是否显著下降"的实验。

⚠ **没有统一低端机内存边界，只有设备分档** ——
iOS 内存由 apps/OS/kernel 共享，超限被终止；Android 也不暴露全部 RAM。
正确做法是按真实机型测峰值 RSS，建**低端/中端/旗舰**三档。
**把"512MiB"写成所有手机的上限会同时过早失败和浪费内存。**

⚠ **纹理压缩减的是带宽，不只是包体** ——
运行时 VRAM 还含 mipmap、对齐、RenderTarget、驱动私有内存，
**不能把磁盘上的压缩纹理大小直接相加**。

⚠ **draw call 只能给区间**：
轻量 2D 数十至数百；中等 3D 数百至一两千；复杂 3D 数千以上风险较高。
（量级参考，非官方硬上限。）

⚠ **热节流必须画长期曲线** ——
前 60 秒高帧不代表 10 分钟稳定。

**Android**：`PowerManager.getCurrentThermalStatus()`
（NONE/MODERATE/SEVERE/…）、`getThermalHeadroom()`。
⚠ Godot 4.7.2 **没有承诺直接暴露**这些字段，需 GDExtension/插件桥接。

**iOS**：四级（nominal / fair / serious / critical），
serious 要降网络、定位、屏幕更新与动画；critical 要停计算与相机/蓝牙/定位。

⚠ **动态质量必须带迟滞** ——
单次热状态变化就降档会在边界反复跳。
建议"进入低档需连续数秒，回升需更长时间"的状态机。

### Web

⚠ **只能用 Compatibility**（WebGL 2.0，无 Forward+/Mobile）。
⚠ **默认单线程**：physics / process / 音频 / GC / JS 事件**共享主线程**，
任一阶段超预算都会挤压下一阶段。

⚠ WASM 的 CPU/GPU 预算要**分别建立**：
解析/实例化、WASM 编译、引擎初始化、资源下载解码、场景创建、稳态逻辑、稳态 GPU。
**不能只测首屏 FPS。**

⚠ Safari 对 WebGL 2 存在其他浏览器没有的问题 ——
官方建议优先 Chromium 或 Firefox。

### XR

⚠ **XR 双眼不是把单眼 draw call 乘 2** ——
每只眼都要视图变换、剔除、阴影/光照、后处理、呈现。
正确指标是**双眼总 draw call、双眼总像素、GPU 时间、掉帧**。

⚠ **刷新率由 runtime 决定，不能硬编码** ——
读 `get_display_refresh_rate()` 与 `get_available_display_refresh_rates()`，
选设备支持且能稳定维持的，再让物理节拍匹配。
OpenXR 默认物理 60Hz，头显最低常为 72Hz，现代设备可达 144Hz。

⚠ **降双眼负载的顺序**：动态分辨率 → LOD/遮挡/远处阴影 → 才减对象与材质。
降内部分辨率立刻恢复帧率 → fillrate/bandwidth 为主；
GPU 时间几乎不变 → 查双眼命令提交、CPU 遍历、同步。

## 5. 瓶颈定位速查

| 现象 | 先查 | 确认方法 |
|---|---|---|
| 帧时间高但 CPU 低 | GPU bound | 关 V-Sync 比 720p/1080p |
| draw call 爆炸 | 材质/图集/实例化 | `RENDER_TOTAL_DRAW_CALLS_IN_FRAME` |
| 物理开销高 | 碰撞体数量/形状复杂度/步长 | `TIME_PHYSICS_PROCESS` |
| 加载卡顿 | 主线程 `load()` | `get_ticks_usec()` 包住测 |
| 内存持续涨 | 对象数 vs 节点数 | 进出关卡比对基线 |
| 过热降频 | 平台热状态 | 画 10 分钟曲线 |
| 首帧卡 | shader 编译 | 预热代表场景 |
| 透明/粒子卡 | overdraw | 降分辨率看是否恢复 |

## 6. 平台必测清单

| 平台 | 必测场景 | 特有信号 |
|---|---|---|
| Windows | 高刷、高鼠标轮询、全屏切换 | 4.7.2 修了高轮询率鼠标 |
| Linux | 全屏/窗口、高刷 | Wayland 输入与合成 |
| macOS | 全屏合成、低功耗模式 | Instruments 热/电量 |
| Android | 冷启动、**10 分钟持续负载** | ThermalStatus API |
| iOS | 10 分钟持续负载、内存峰值 | thermalStateDidChange |
| Web | 下载/解析/首帧、后台恢复 | SharedArrayBuffer |
| XR | 快速转头、持续运动、再投影 | OpenXR 刷新率 |

> **反模式清单（不能怎么做，审核用）** → `audit/godot/perf-profiling.md`


## 7. 待核对项（运行时验证）

⚠ 待核对：Tracy 在 4.7.2 官方导出模板中是否内置 · 验证：查目标平台发布模板是否含 Tracy 符号，无则需模块/插桩

⚠ 待核对：Windows 高轮询率鼠标修复的实际收益 · 验证：同一鼠标与刷新率下对比 4.7.1 与 4.7.2 的 `_process`/`_input` P99

⚠ 待核对：目标机型的热节流曲线拐点 · 验证：真机连续跑 10 分钟，每 30 秒记录帧时间与热状态

## 9. 自定义监视器：把项目指标放进 Monitors 面板

⚠ 官方支持注册**自定义监视器**，显示在 Debugger → Monitors 面板里：

```gdscript
Performance.add_custom_monitor("game/enemies", get_enemy_count)
```

- ⚠ **斜杠决定分类**：`"game/enemies"` → Game 分类下的 Enemies。
  ⛔ 不含斜杠（或含多个斜杠）→ 落到通用的 `Custom` 分类，监视器一多就找不到。
- ⛔ **只能注册一次**，重复注册同名监视器**会报错**。
  注册前用 `Performance.has_custom_monitor()` 判断。
- ⛔ **取值函数必须返回 ≥ 0 的数**（int 或 float），负数**会被钳到 0**。
  ⛔ 表现为"指标一直是 0"，极易被误判成统计函数写错，
  而去查一个根本没问题的统计函数。
- ⓘ 取值函数在编辑器里**每秒被查询一次**（手动调用则更频繁）。
- ⓘ `Performance.get_custom_monitor()` 在**导出项目**里也能用
  （debug 与 release 均可），可用来在游戏内画自己的调试面板。
- ⓘ 注册代码不必放在业务节点上。**放 autoload 更稳** ——
  ⛔ 挂在会销毁的节点上，节点没了监视器也没了。

## 10. 预热与稳态：什么时候才准

⚠ **首次运行包含着色器编译、资源首次加载、文件系统缓存冷启动** ——
这些都不是稳态性能。

- ⛔ 每次测量前先**预热 30–60 秒**再开始记录。
- ⚠ 桌面短时测的是**峰值算力**，移动 / XR 长时测的是**可持续性能** ——
  两者回答不同的问题，⛔ 不能拿同一个数字互相比较。
- ⓘ 回归对比必须**同一套预热流程**，否则差异里混着冷启动成本，
  表现为"这次比上次慢"但其实只是这次没预热。

## 11. 首帧编译：pipeline cache 不是万能

⚠ **Godot 惰性编译着色器** —— 材质第一次出现时才编译，主线程停顿。

- ⓘ 4.1 起 Vulkan 渲染器有 **pipeline cache**，**默认开启**，
  缓存写在 `user://vulkan/pipelines.cache`。
- ⛔ 但官方 4.1 发布说明明确写着：pipeline 编译卡顿问题
  **"far from solved"（远未解决）**，这个缓存只是
  "朝正确方向迈出的一步"。
  ⛔ 所以**开了缓存不等于首帧不卡** —— 表现为"我明明开了缓存怎么还顿"，
  进而怀疑配置没生效，去查一个本来就是开启状态的开关。
- ⚠ 缓存头里带 **vendor_id / device_id / driver_version / UUID** ——
  换显卡或升级驱动后缓存**失效**，又要重新编译一遍。
- ⛔ 真正有效的办法是**在加载屏预编译**：把每种材质先在屏幕外
  实例化、渲染几帧再释放，把编译成本挪到玩家本来就在等待的时刻。
- ⓘ 排查首帧卡顿时注意：资源加载与着色器编译**会互相掩盖** ——
  修掉一个，停顿**缩小但没有消失**，容易误判成"没修好"，
  于是把已经生效的修复又回滚掉。

## 12. 相关文档

- 通用优化 → `performance.md`
- 渲染器能力 → `render-pipeline.md`
- 移动端 → `mobile.md`
- Web 限制 → `platform-export.md`
- XR → `xr-deep.md`
- 调试工具 → `debugging.md`
- 高级测试 → `testing-advanced.md`
