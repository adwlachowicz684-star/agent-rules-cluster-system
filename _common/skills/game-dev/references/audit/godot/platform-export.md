<!-- oversize-exempt: 反模式清单，审核用 -->
# platform-export — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/platform-export.md`

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
