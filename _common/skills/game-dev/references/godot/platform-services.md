# 平台服务与后端集成（Godot 4.7.2）

"steam""云函数" 此前 **0 命中**。

## 0. Godot 不提供这些

⚠ 引擎**没有**成就、排行榜、账号、内购、统计、云函数、云存档的任何内置能力
—— 只有通用 HTTP / TCP / UDP / WebSocket 原语。

**全部要靠平台 SDK 或自建后端。**

⚠ 因此架构上必须**抽象一层**，不能把平台 API 散落在游戏代码里。

## 1. 抽象层：统一异步接口 + 多适配器 + 离线桩

```
PlatformService（异步接口）
├── Steam 适配器（GodotSteam）
├── EOS 适配器（EOSG）
├── Play Games / Game Center 适配器
├── 自建 HTTP 适配器
└── 离线桩（开发主路径）
```

⚠ **接口要异步** —— 平台调用都是异步的，同步写法会卡。
⚠ **绝不能把平台 ID 直接写死在游戏逻辑里。**

### ⚠ 离线桩不是玩具，是开发主路径

它必须支持：编辑器运行、断网、CI、手动测试、演示。
**不能只打印 `print("TODO")`。**

应把账户/统计/成就/排行榜存到 `user://platform_stub.json`，
待提交任务存 `user://platform_pending.json`，
**可手动注入失败与延迟** —— 用来验证游戏 UI 不卡死。

## 2. Steam（GodotSteam）

**已有针对 4.7.2 的构建**，但与 Steam 客户端、Steamworks SDK、导出模板**强耦合**。

### ⚠ `steam_appid.txt` 的三态

| 阶段 | 做法 |
|---|---|
| 开发期 | 用 `steam_appid.txt` 或 `SteamAppId` 环境变量 |
| 发布 | ⚠ **不要包含** `steam_appid.txt`（正式发行由客户端与 DRM 配置决定） |

⚠ 把调试 App ID 留在发布包里**不是"兼容保险"**，是泄露测试与配置错误来源。

⚠ **DRM 包装 ≠ `steam_appid.txt`**，也不是反作弊。

### ⚠ 没有 Steam 客户端时要降级，不能崩溃

已知问题：
- Windows 隐藏扩展名会生成 **`steam_appid.txt.txt`**
- `ConnectToGlobalUser failed` → 客户端未启动或账号无权限
- 错误 79 → depot/package 配置问题

这些是**发布前必须走完的检查项**，不是可忽略的日志。

## 3. 移动端

| 平台 | 插件 | 声明 |
|---|---|---|
| iOS Game Center | GameCenterKit | 覆盖 **4.5–4.7** |
| Android Play Games | 官方主仓 | 只声明 **4.3+** |

⚠ **不能因为写"4.x"就认定 4.7.2 无需改代码** —— 要逐项验收。

⚠ **Game Center 身份 ≠ 你的玩家账号** ——
要跨平台统一存档，需用平台 identity token 向自建后端换稳定 player ID 并做账户绑定。

## 4. EOS（EOSG 2.3.x）

声称 Godot 4.2+ 覆盖五平台，但**发布页没有 4.7.2 专项验证** → 标为**待核对**。

好处是**跨平台统一**，代价是接入复杂。

## 5. 自建后端

⚠ **平台 token 只能作为登录凭证，业务 token 由服务端签发。**
⚠ **秘密必须留在服务端，客户端不能硬编码管理密钥。**

协议：JSON 简单；二进制（protobuf）在 Godot 里的现状**待核对**。

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/platform-services.md`


## 6. 待核对项（运行时验证）

⚠ 待核对：EOSG 在 4.7.2 的实际可用性 · 验证：按 4.7.2 导出并跑通成就与统计

⚠ 待核对：protobuf 在 Godot 4.7.2 的可用方案 · 验证：实际导入并序列化测试

⚠ 待核对：目标平台插件的版本匹配 · 验证：按目标平台导出后跑通登录与成就

## 7. 相关文档

- 云存档 → `cloud-save.md`
- 多人/网络 → `multiplayer.md`
- 埋点与统计 → `analytics.md`
- 平台导出 → `platform-export.md`
- 热更新与 DLC → `hotupdate.md`
- 防作弊 → `security.md`
