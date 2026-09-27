# 06 Web 导出与托管（多平台导出与发布域）

> **本步交付**：渲染器覆盖 + 线程与隔离头 + 持久化降级
> **对应**：流程 `howto/godot/platform-export.md` · 审核 `audit/godot/platform-export.md`

## 0. 交付物定义

1. 渲染器已按平台覆盖到 Compatibility，不维护两套工程
2. 线程开关与跨域隔离三件套的结论已定，且与托管方能力匹配
3. 存档持久性已检测，未持久化时玩家看得见提示
4. 托管方的头能力已确认（能配 / 开关 / 不能配）
5. 音频解锁点已做，首屏不会静默

## 1. 前置检查清单

- [ ] Web 走 Compatibility，桌面仍走 Forward+
- [ ] 线程结论与托管方是否支持自定义头一致
- [ ] 启动时调用了持久化检测
- [ ] 托管方隔离头方案已确定（自建 / `_headers` / 开关 / PWA）
- [ ] ⚠ 首屏存在一次用户手势用于解锁音频

## 2. 工序

### Step 1　Web 只有 Compatibility，这是硬限制不是取舍　`[platform-export/06#S1]`

【读】`howto/godot/platform-export.md#三重硬限制`

【做】
用按平台覆盖让 Web 走 Compatibility。
⛔ 想"先在桌面调好再移植" —— Compatibility 与 Forward+ / Mobile
依赖的后端**不同**（Web 是 WebGL 2.0 / OpenGL ES 3.0，
而后者依赖 Vulkan / D3D12 / Metal，Web 上全部用不上）。

⛔ 最致命的表现是静默失效：`GPUParticles2D/3D` 在 Compatibility 下
**粒子不出现、无报错**。这是"Web 端特效消失"的第一怀疑点，
⛔ 而排查必然被引向资源打包或粒子参数。

ⓘ 用 `rendering/renderer/rendering_method.mobile` 之类的按平台覆盖机制，
让 Web 与桌面各走各的，⛔ 不维护两套工程。

【产出】按平台覆盖的渲染器配置

【判据】同一份工程导出 Web 后，粒子等特效已知是"能跑"还是"会失效"。

【审】`audit/godot/platform-export.md#1`

### Step 2　线程开关与跨域隔离三件套要一起定　`[platform-export/06#S2]`

【读】`howto/godot/platform-export.md#三重硬限制`

【做】
定下线程开关，并把跨域隔离三件套配齐。
⛔ 只勾线程开关 —— `SharedArrayBuffer` **只在跨域隔离的文档里存在**，
需要 `Cross-Origin-Opener-Policy: same-origin` +
`Cross-Origin-Embedder-Policy: require-corp` + 安全上下文（HTTPS 或 localhost），
⛔ **三者缺一不可**。

⛔ 还有个反向副作用：COEP 会让**不带正确跨域标记的外部资源加载失败** ——
第三方脚本 / CDN 字体 / 广告 SDK 要么支持 CORP、要么配 `crossorigin`，
⛔ 否则页面白屏，**看起来像 Godot 的 bug，其实是资源策略问题**。

ⓘ PWA 的 Service Worker 会**始终**模拟跨域隔离头（即使服务器没配），
这让启用线程的导出能托管在任意站点；
⛔ 该行为可在 `渐进式 Web 应用` 部分取消勾选「启用跨域隔离标头」来禁用 ——
⛔ 不知道这条就会出现"我明明没配头，它却跑起来了"的困惑。

【产出】线程结论 + 隔离头方案 + 外部资源的 CORP 兼容性确认

【判据】能说出隔离头的三个来源（服务器 / `_headers` / PWA 模拟）用了哪一个。

【审】`audit/godot/platform-export.md#2`、`audit/godot/platform-export.md#32`

### Step 3　存档持久性要检测，且检测通过不等于安全　`[platform-export/06#S3]`

【读】`howto/godot/platform-export.md#10. macOS 与 Web 的两处边界`

【做】
启动时调用 `OS.is_userfs_persistent()`，未持久化时给玩家可见提示。
⛔ 以为检测通过就安全 —— 官方明示该方法**在某些情况下会误报**，
⛔ 所以它只是个提示，不是保证。

⛔ 还有一条仅在 iframe 场景出现：官方要求
**游玩用 iframe 呈现的游戏时必须启用第三方 cookie**。
⛔ itch.io 正是 iframe 嵌入 —— 于是"itch.io 上进度丢失"的排查
会被引向 Godot 存档代码，⛔ 而根因在浏览器 cookie 策略。

ⓘ 存档统一走 `user://`：导出后 `res://` 只读，
⛔ 往那里写**静默失败**，连报错都没有。
ⓘ 存档前先 `DirAccess.make_dir_recursive_absolute("user://saves")`。

【产出】启动检测 + 未持久化时的可见提示 + 目录已预建

【判据】在无痕模式下启动，玩家能看到"进度可能不会保存"的提示。

【审】`audit/godot/platform-export.md#30`、`audit/godot/platform-export.md#31`、`audit/godot/platform-export.md#15`

### Step 4　托管方的头能力先确认，再定线程方案　`[platform-export/06#S4]`

【读】`howto/godot/platform-export.md#其他限制`

【做】
先确认托管方能不能设自定义响应头，再定线程结论。
⛔ 先做完再找托管 —— 这是**平台级差异**，不是配置细节：

- 能自己配 Nginx/Caddy → 随便用多线程
- Netlify → 根目录 `_headers`；Vercel → `vercel.json`
- **itch.io → 勾 "SharedArrayBuffer support" 开关**（⛔ 忘勾＝本地正常、上传后黑屏）
- **GitHub Pages → 默认不能设自定义头，只能单线程**
- PWA → 勾 `Progressive Web App > Enable`，由 Service Worker 模拟隔离头

⛔ 表现为"本地一切正常、上传后黑屏或报错"，
⛔ 排查被引向构建产物或浏览器兼容，不会想到是托管方能力。

ⓘ 另外 Web 必须经 HTTP(S) 提供，
⛔ 直接 `file://` 打开不行 —— 这是另一类"本地双击打不开"。

【产出】托管方清单 + 每方的头方案 + 据此定的线程结论

【判据】能按托管方逐字说出用哪种方案，而不是"到时候再试"。

【审】`audit/godot/platform-export.md#3`、`audit/godot/platform-export.md#4`

### Step 5　音频要有解锁点，首屏不能静默　`[platform-export/06#S5]`

【读】`howto/godot/platform-export.md#音频与加载`

【做】
做一个"点击开始"启动屏，把首次交互当音频解锁点。
⛔ 指望首屏直接出声 —— 浏览器自动播放策略下，
⛔ **没有用户手势前 AudioContext 处于 suspended**，首屏静音。

⛔ 表现为"游戏没声音"，而排查被引向音频总线或音量设置，
⛔ 不会想到是缺少一次用户手势 —— 因为在桌面端从来不需要。

ⓘ Web 音频走 Sample 模式（4.3 起，即使不开线程也低延迟），
⛔ 代价是 AudioEffect 不支持、混响/多普勒不支持、程序化音频不支持 ——
⛔ 这些是能力裁剪，不是 bug，不要去"修"它。

ⓘ 顺带：加载慢最伤转化。用 Brotli/Gzip、开 `application/wasm` 流式编译、
内容哈希化长期缓存、减小首包 PCK（非首关资源拆成 PCK 补丁按需下载）。

【产出】启动屏（含一次用户手势）+ Web 端音频能力裁剪说明

【判据】首次点击后音频正常，且未去"修"被裁剪的 AudioEffect。

【审】`audit/godot/platform-export.md#35`

## 3. 参考实现

```gdscript
# ⓘ 承接本步产出：持久化与音频解锁都在启动期一次性处理
extends Node

func _ready() -> void:
    if not OS.has_feature("web"):
        $UI/StartScreen.visible = false
        return
    # S3：⛔ is_userfs_persistent() 官方明示会误报，只当提示
    if not OS.is_userfs_persistent():
        $UI/WarnPersistent.visible = true
    DirAccess.make_dir_recursive_absolute("user://saves")
    # S5：启动屏的点击即音频解锁点
    $UI/StartScreen.visible = true

func _on_start_pressed() -> void:
    # ⛔ 首次用户手势前 AudioContext 处于 suspended
    $UI/StartScreen.visible = false
    AudioServer.set_bus_mute(0, false)
```

## 4. 验收清单

- [ ] Web 走 Compatibility，桌面仍走 Forward+，同一份工程
- [ ] 线程结论与托管方头能力一致；外部资源 CORP 兼容性已确认
- [ ] 启动时检测持久化，无痕模式下玩家看得见提示
- [ ] 托管方头方案已确定并实测（不是"到时候再试"）
- [ ] 启动屏存在一次用户手势，点击后音频正常

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| Web 端特效全没了 | Compatibility 下 GPUParticles 静默失效 | S1 |
| 本地正常、上传后黑屏 | 隔离头没配齐 / 忘勾开关 | S2、S4 |
| 玩家反馈进度没了 | 持久化误报或 iframe 第三方 cookie | S3 |
| 页面白屏（外部资源） | COEP 拦截未标 CORP 的资源 | S2 |
| 游戏没声音 | 缺一次用户手势解锁音频 | S5 |

## 6. 下一步

→ 07 发布验收

## 7　整体审核（功能点级收尾）

【审】`audit/godot/platform-export.md#1`、`audit/godot/platform-export.md#2`、`audit/godot/platform-export.md#32`、`audit/godot/platform-export.md#30`、`audit/godot/platform-export.md#31`、`audit/godot/platform-export.md#15`、`audit/godot/platform-export.md#3`、`audit/godot/platform-export.md#4`、`audit/godot/platform-export.md#35`
