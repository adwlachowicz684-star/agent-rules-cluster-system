<!-- oversize-exempt: 反模式清单，审核用 -->
# platform-export — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/platform-export.md`

## 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | Web 也能用 Forward+ | **只有 Compatibility**，GPUParticles 会静默失效 |
| 2 | 多线程随便开 | 需 COOP+COEP+HTTPS，三者缺一 |
| 3 | itch.io 上传后黑屏是 bug | 忘了勾 SharedArrayBuffer 开关 |
| 4 | GitHub Pages 能跑多线程 | 默认不能设自定义头 |
| 5 | NDK 用最新就行 | **必须 r28b**，否则 Gradle 失败 |
| 6 | APK 能传 Google Play | 2021 起**强制 AAB** |
| 7 | keystore 丢了能找回 | 不能，包名永久报废 |
| 8 | 权限全勾省事 | 多报会被下架 |
| 9 | macOS 不签名也能分发 | Gatekeeper **硬拦**，ad-hoc 不够 |
| 10 | 公证完就完了 | 还要 **staple 钉票**，否则离线打不开 |
| 11 | Windows 上能出 iOS 包 | 不行，必须 macOS + Xcode |
| 12 | 免费 Apple 账号能上架 | 不能，要 99 美元/年 |
| 13 | 隐私描述可省 | 缺了直接崩且无提示 |
| 14 | Web 存档很可靠 | IndexedDB 受 Cookie/无痕影响，要检测 |
| 15 | res:// 也能写存档 | 导出后**只读**，静默失败 |
| 16 | arm64+armv7 都要 | 包体翻倍，只 arm64 就够 |
| 17 | Linux 用发行版 SDK | 普遍过时，用官方命令行工具 |
| 18 | 导出模板版本差不多就行 | 必须匹配 |
| 19 | CLI 导出的相对路径按当前目录算 | ⛔ 基准是 `project.godot` 所在目录 |
| 20 | 预设名差不多就行 | 必须**精确匹配**，含空格要引号，否则直接失败 |
| 21 | 非资源文件会自动进包 | `.json`/`.txt` 要在 `Resources > Filters` 显式加，否则静默缺失 |
| 22 | Android 装了导出模板就够 | Gradle 构建还要 `Install Android Build Template`（每项目一次） |
| 23 | iOS 导出目录随便选 | 必须是**空文件夹** |
| 24 | iOS 工程名与项目目录同名没事 | ⛔ 同名导致 Xcode **签名问题** |
| 25 | iOS 工程名带空格没事 | ⛔ 会**损坏 Xcode 工程文件** |
| 26 | Team ID 填错只报签名错 | ⛔ 会报 `JSON text did not start with array or object` |
| 27 | iOS 能用模拟器测 | 官方不支持（GH-102149） |
| 28 | 任意平台都能打 DMG | ⛔ 仅 macOS 主机支持 |
| 29 | `--export-debug` 只是多个调试符号 | 还开远程调试与调试检查；Android 上 debug 签名与正式版冲突 |
| 30 | 存档检测通过就安全 | ⛔ `OS.is_userfs_persistent()` 官方明示会**误报** |
| 31 | itch.io 丢存档只在无痕模式 | ⛔ iframe 内还需**第三方 cookie** |
| 32 | PWA 勾了就永远有隔离头 | 由 Service Worker 模拟，**可取消勾选禁用** |
| 33 | Bundle identifier 随便填 | 官方要求 **valid and unique**（有效且唯一） |
| 34 | 纹理压缩随便配 | 项目设置与导出预设的 `For Mobile` 必须一致，否则导出校验失败 |
| 35 | Web 首屏就能出声 | ⛔ 无用户手势前 AudioContext suspended，要做启动屏解锁 |
