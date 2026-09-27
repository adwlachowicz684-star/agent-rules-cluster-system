# 多平台导出与发布（Godot 4.7.2）

游戏做完之后的事。Web / iOS / Android 此前完全没有文档，而这是上线必经。

## 0. 导出模板

- 导出模板**版本必须与编辑器版本匹配**，不匹配会报各种奇怪错误
- `export_presets.cfg` 建议进版本库（团队共享导出配置）

## 1. 各平台速查表

| 维度 | Windows | Linux | macOS | Android | iOS | Web |
|---|---|---|---|---|---|---|
| 产物 | exe(+pck) | ELF/AppImage | .app bundle | APK / AAB | IPA | HTML+WASM+PCK |
| **渲染器** | 全支持 | 全支持 | 全支持 | Mobile/Compat | Mobile/Compat | **仅 Compatibility** |
| 推荐架构 | x86_64 | x86_64(+arm64) | Universal2 | **arm64-v8a** | arm64 | — |
| 线程 | 原生 | 原生 | 原生 | 原生 | 原生 | **可选，多线程需 COOP/COEP** |
| 文件系统 | 真实 | 真实 | 真实 | 沙盒 | 沙盒 | **虚拟，user:// = IndexedDB** |
| 存档持久性 | 高 | 高 | 高 | 高 | 高 | **中低** |
| 音频 | 完整 | 完整 | 完整 | 完整 | 完整 | **功能裁剪** |
| 代码签名 | 可选 | 不需要 | **必须** | keystore | 证书+Profile | 无 |
| 公证 | 无 | 无 | **需 notarize+staple** | Play 校验 | App Store 审核 | 无 |

**这张表能推出的结论**：
- **Web 是唯一必须围绕限制做设计的平台**，想做 Web 就要从立项起用 Compatibility
- Apple 生态是双重税：签名+公证+钉票（macOS）、证书+App ID+Profile（iOS）
- 存档统一用 `user://`，但 **Web 端必须做持久化检测**
- 线程 API 各原生平台都能用，**只有 Web 是条件开关**，用 `OS.has_feature("web")` 分支

## 2. Windows

- 架构选 x86_64 即可（arm64 只给 Surface Pro X 一类）
- `embed_pck` 可把资源内嵌进 exe，单文件分发
- 发布版关掉 `export_console_wrapper`（否则有黑窗口）
- 4.1 起图标支持直接喂 PNG/WebP/SVG 自动生成 ICO

⚠ **代码签名买不买？** 不签名的结果只是 SmartScreen 弹"未知发布者"，
**是软拦截不是死路**，用户点"仍要运行"即可。
对个人独游来说，不签名 + itch.io/Steam 分发完全可行。

## 3. macOS

⚠ **Universal 2 掩盖不了签名与公证的坑** ——
官方模板输出单个二进制同时含 x86_64 与 arm64，不用维护两个包（这是省心处）。

### Gatekeeper 判定链（理解 macOS 发布的钥匙）

```
应用有开发者签名
  → 公证服务扫描并签发 ticket
    → 首次运行 Gatekeeper 联网验证 ticket
      → 通过
```

**任何一环断掉就弹"无法验证开发者"或"已损坏"。**

⚠ **没有 Apple Developer ID 时**，Godot 的 `Built-in (ad-hoc only)` 签名
**不能过 Gatekeeper**，分发基本不可用。

⚠ **公证完必须钉票（`stapler staple`）** ——
把 ticket 写进 app 本体，否则离线环境首次打开会卡在验证。

### Entitlements 是权限闸门

| 项 | 用途 |
|---|---|
| Allow JIT / Unsigned Executable Memory / DYLD Env | 留给需要 JIT 的 GDExtension 插件 |
| Disable Library Validation | 加载任意 dylib（GDNative add-on） |
| Audio Input / Camera / Location / Photo Library | 系统隐私权限，**还必须填 usage description** |
| Debugging | **生产必须关** —— 带它无法公证 |

⚠ Steamworks 场景下 `Disable Library Validation` + `Allow DYLD Environment Variables`
通常仍需勾选才能让 overlay 正常加载（社区实测，**非官方确认**）。

⚠ **在 Linux/Windows 上跨平台签 macOS** 是官方支持的：用 `rcodesign`（PKCS#12 凭据）。

## 4. Android

### 环境是环环相扣的版本矩阵

```
OpenJDK 17
Android SDK Platform-Tools ≥ 35.0.0
Build-Tools 35.0.1
Android SDK Platform 35
NDK r28b (28.1.13356709)     ← 必须精确到这个版本
CMake 3.10.2.4988404
```

```bash
sdkmanager --sdk_root=<路径> "platform-tools" "build-tools;35.0.1" \
  "platforms;android-35" "cmdline-tools;latest" \
  "cmake;3.10.2.4988404" "ndk;28.1.13356709"
```

⚠ **NDK 版本必须精确到 r28b** —— 4.7 的 Gradle 模板锁死这个版本，
换成更新的 NDK 会构建失败。这是"Gradle 构建失败"最高频的原因。

⚠ **Linux 用户别用发行版仓库里的 Android SDK**（普遍过时）。

### 架构与纹理压缩

⚠ **只选 arm64-v8a 就够了**（覆盖 2015 年后所有主流设备）。
加 armeabi-v7a 只兼容极旧设备，**代价是包体翻倍**。

⚠ **纹理压缩联动**：
项目设置的 `Import ETC2 ASTC` 与导出预设的 `For Mobile` **必须一致**，
不一致会触发导出校验失败。

⚠ ETC2 是 Android 最稳妥默认（通用），ASTC 质量好但需硬件支持。
一张 2048² 贴图从 16MB 压到 ETC2 的 2MB —— **对低端机是否崩溃有决定性影响**。

### APK vs AAB

| | 用途 |
|---|---|
| **APK** | 完整可分发包，能直接装。侧载、测试、第三方市场 |
| **AAB** | **发布格式**，Google Play 用它做动态分发 |

⚠ **Google Play 自 2021 年 8 月起强制新应用上传 AAB**，APK 通道已关闭。
⚠ **AAB 无法直接装到手机** —— 测试要用 `bundletool`。

### Keystore 一旦丢了，包名永久报废

```bash
keytool -v -genkey -keystore mygame.keystore -alias mygame \
        -keyalg RSA -validity 10000
```

⚠ **必须加密存储 + 多人备份 + 密码分开保管**。
丢了无法找回，同名包再也无法更新，只能换包名重新上架、**流失全部评价**。

⚠ **务必取消 `Export With Debug`** —— 否则打出 debug 签名包，
与已装的正式版签名冲突会报"解析包时出现问题"。

⚠ **权限别全勾** —— Google Play 数据安全表单按实际收集申报，多报会被下架。
敏感权限还需运行时申请（`OS.request_permission()`）。

## 5. iOS

⚠ **先说死：Windows 上无法产出可上架的 iOS 包。**
Godot 生成的是 **Xcode 工程**，编译/签名/归档全靠 Xcode。

**现实路径三条**：
1. **远程 CI**（GitHub Actions macOS runner / codemagic / Bitrise）—— 最务实
2. **借/租一台 Mac**（哪怕二手 Mac mini）—— 调试体验最好
3. 虚拟机/黑苹果 —— 违反许可协议，稳定性无保障

⚠ **没有"纯 Windows 直接打出已签名 IPA"的路径**。

### 证书三件套（最易搞晕）

| 组件 | 作用 |
|---|---|
| **证书** | 谁能签 |
| **App ID** | 签哪个应用（= Bundle Identifier，必须**逐字符一致**） |
| **Provisioning Profile** | 把三者绑一起 + 设备 UDID + Capabilities |

⚠ **"签名失败"的本质永远是三选一**：
证书不在钥匙串 / Bundle ID 不符 / Profile 的 App ID 或设备列表不匹配。

⚠ `app_store_team_id` 是 **10 位字母数字组合，不是邮箱**，填错就 `No signing certificate found`。

⚠ **发布构建务必取消 Export with Debug** ——
否则开发证书与预设里的分发证书冲突，报 `conflicting provisioning settings`。

### 隐私描述是硬要求

⚠ `NSMicrophoneUsageDescription` / `NSCameraUsageDescription` 等键
**缺了直接崩在首次调用处，且不提示具体原因**。

⚠ App Store 审核常见拒因：隐私清单 `NSPrivacyAccessedAPITypes`
与实际使用的 API 不符（用了 AdMob/Facebook SDK 必须声明追踪用途）。

## 6. Web

### 三重硬限制

**① 渲染器：只有 Compatibility 一条路。**
Web 用 WebGL 2.0 / OpenGL ES 3.0 后端，Forward+ 和 Mobile 依赖 Vulkan/D3D12/Metal，都用不上。
（Godot 4 尚未支持 WebGPU。）

⚠ **GPUParticles2D/3D 在 Compatibility 下静默失效** ——
粒子不出现、无报错。**这是 Web 端特效消失的第一怀疑点。**

⚠ 用 `rendering/renderer/rendering_method.mobile` 之类的**按平台覆盖**机制，
让 Web 走 Compatibility、桌面走 Forward+，不必维护两套工程。

**② 线程：单线程是 4.3 起的默认。**

| | 单线程 | 多线程 |
|---|---|---|
| 兼容面 | 广（itch.io、Poki 等平台**不支持自定义头**） | 需跨域隔离 |
| 配置 | 零 | 需 COOP + COEP + HTTPS |
| 限制 | **不能用 `Thread`**，CPU 密集掉帧 | 性能接近原生 |

⚠ **SharedArrayBuffer 只在跨域隔离的文档里存在**：

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
+ secure context（HTTPS 或 localhost）
```

**为什么必须是这两个头**（原理）：
COOP 把页面与其他同源页面隔离成独立浏览上下文组（切断 `window.opener`）；
COEP 要求所有子资源显式声明可被跨域嵌入（CORP 头或 `crossorigin`）。
两者叠加才满足跨域隔离，`SharedArrayBuffer` 才被暴露。

⚠ **副作用**：COEP 会让不带正确跨域标记的外部资源加载失败 ——
第三方脚本/CDN 字体/广告 SDK 要么支持 CORP，要么配 `crossorigin`，
否则页面白屏，**看起来像 Godot 的 bug，其实是资源策略问题**。

**托管方案**：
- 能自己配 Nginx/Caddy → 随便用多线程
- Netlify → 根目录放 `_headers`；Vercel → vercel.json
- **itch.io → 勾"SharedArrayBuffer support"开关**（忘勾＝本地正常上传后黑屏）
- **GitHub Pages 默认不能设自定义头** → 只能单线程
- **PWA 兜底**：勾 `Progressive Web App > Enable`，Service Worker 模拟跨域隔离头

**③ 存档：`user://` 是 IndexedDB，不是真文件。**

⚠ **IndexedDB 能否持久化取决于用户设置** ——
禁用 Cookie、无痕模式、配额超限都可能导致拒绝写入或定期清理。

```gdscript
if not OS.is_userfs_persistent():
    # 弹提示告知进度可能不保存
```

⚠ 存档前先 `DirAccess.make_dir_recursive_absolute("user://saves")`。
⚠ **务必存 `user://` 而非 `res://`** —— 导出后 `res://` 只读，往那写静默失败。
⚠ localStorage 只能靠 `JavaScriptBridge.eval()` 桥接，正式存档仍走文件 API。

### 音频与加载

⚠ Web 音频走 **Sample 模式**（4.3 起，即使不开线程也低延迟），
代价是 **AudioEffect 不支持、混响/多普勒不支持、程序化音频不支持**。

⚠ **自动播放策略**：没有用户手势前 AudioContext 处于 suspended，首屏静音。
最稳妥做法是做"点击开始"启动屏，把首次交互当音频解锁点。

⚠ **加载慢最伤转化**。优化：Brotli/Gzip（WASM 高压缩比）、
开 `application/wasm` 流式编译、内容哈希化长期缓存、
减小首包 PCK（非首关资源拆成 PCK 补丁按需下载）。

### 其他限制

⚠ 切后台会暂停（`_process`/`_physics_process` 停止，联网游戏可能掉线）
⚠ 只有 HTTPClient/HTTPRequest/WebSocket/WebRTC，**没有 TCP 服务器**
⚠ 全屏与鼠标捕获需用户手势
⚠ 手柄需用户先按任意键才被识别，映射因浏览器/系统而异
⚠ **网络资源必须 HTTPS**

> **反模式清单（不能怎么做，审核用）** → `audit/godot/platform-export.md`


## 7. 命令行导出与 CI（预设名是硬匹配）

```bash
# ⓘ 预设名必须与 export_presets.cfg 中定义的完全一致，含空格要加引号
godot --headless --export-release "Windows Desktop" build/windows/game.exe
godot --headless --export-release "Web" build/web/index.html
godot --headless --export-pack  "Linux/X11" build/game.pck
```

⛔ **相对路径的基准是 `project.godot` 所在目录，不是当前工作目录。**（官方 Warning）
在 CI 里换个工作目录跑同一条命令，产物会落在完全不同的地方，
⛔ 表现为"命令成功、产物找不到"，排查方向被引向构建脚本而非路径基准。

⛔ **预设名不匹配直接失败** —— `"Windows"` 配不出名为 `"Windows Desktop"` 的预设，
且失败信息不会提示"是不是名字写错了"。

⛔ **非资源文件不会自动进包** —— 外部 `.json` / `.txt` 要在预设的
`Resources > Filters` 里显式加（如 `*.json`）。
表现为"编辑器里读得到、导出后读不到"，而导出过程**完全无警告**。

ⓘ `--export-debug` 不止是"多个调试符号"：它会开启远程调试与调试检查，
Android 上还会用 debug 签名 —— 与已装的正式版冲突，报"解析包时出现问题"。

## 8. Android：Gradle 构建模板要按项目装一次

⛔ **装了编辑器导出模板还不够** —— 预设勾了 `Use Gradle Build` 时，
编辑器要求项目内有 `res://android/build/`，来自：

```
Project > Install Android Build Template     每项目一次，产出目录要提交
```

⛔ 缺它的报错是"路径找不到，指向 templates 文件夹"，
⛔ 看起来像导出模板没装，⛔ 于是反复重装 600MB 的模板包 —— 而根因在项目里。
AAB 输出也依赖它（没装时导出下拉里只有 APK）。

## 9. iOS：Xcode 工程的三个静默坑

| 项 | 官方口径 | 后果 |
|---|---|---|
| 导出目录 | **必须是空文件夹** | 混入旧文件后症状不可预测 |
| Xcode 工程名 | ⛔ **不能带空格** | 会导致 Xcode 工程文件**损坏** |
| 与项目目录同名 | ⛔ `godot_project_to_export` **不得**与 `exported_xcode_project_name` 同名 | Xcode **签名问题** |

⛔ 后两条最难查：症状都是"签名失败"，
排查必然被引向证书 / App ID / Profile 三件套，⛔ 而它们全是对的。

⛔ **`App Store Team ID` 填错会报完全无关的错**：
官方记录的错误信息是
`JSON text did not start with array or object and option to allow fragments not set`
—— 官方明确说这是 Team ID 格式错（要 10 位 `ABCDE12XYZ`，
⛔ 不是 Xcode 在 Signing & Capabilities 里显示的"你的名字"）。
⛔ 这条报错**看起来是 JSON 解析问题**，会把排查引向完全无关的方向。

ⓘ iOS **模拟器导出目前不支持**（GH-102149）；Apple Silicon Mac 可直接跑 iOS app。

## 10. macOS 与 Web 的两处边界

**macOS**：⛔ **导出为 DMG 只在 macOS 主机上支持**（官方原文），
在 Win/Linux 上该选项不可用。

ⓘ 关于 ad-hoc 签名：官方口径是它会"让终端用户运行导出 App 更容易"，
⛔ 具体行为取决于签名 / 公证的组合（官方列了五种情形：
已签名已公证经 App Store / 已签名已公证外部分发 / 已签名含 ad-hoc 但未公证 /
未签名但可执行文件 linker-signed / 两者都未签名）。
⛔ 所以"ad-hoc 到底能不能分发"没有单一答案，要看落在哪一种。

**Web**：

⛔ **`OS.is_userfs_persistent()` 会误报**（官方原文："在某些情况下会误报"）。
所以检测通过**不等于**一定持久化 —— 它只是个提示，不是保证。

⛔ **iframe 内游玩还需启用第三方 cookie**（官方原文）。
⛔ itch.io 正是 iframe 嵌入 —— 于是"itch.io 上进度丢失"的排查
会被引向 Godot 存档代码，而根因在浏览器 cookie 策略。

ⓘ PWA 的 Service Worker 会**始终**模拟跨域隔离头（即使服务器没配），
这让启用线程的导出能托管在任意站点；该行为可在
`渐进式 Web 应用` 部分取消勾选「启用跨域隔离标头」来禁用。

## 11. 流程：按什么顺序做

→ `flow/godot/platform-export/00-域流程总览.md`

## 12. 相关文档

- CI 与自动化发布 → `cicd-publish.md`
- 渲染器能力矩阵 → `render-pipeline.md`
- 存档 → `security.md`
- 移动端触控 → `mobile.md`
- 合规与商店提交 → `compliance.md`
- 项目设置 → `project.md`
