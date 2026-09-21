# 热更新、资源分包与 DLC（Godot 4.7.2）

"资源热更""资源分包" 此前 **0 命中**。

## 0. 先分清两种"热更"

⚠ **资源热更**（更新贴图/配置/关卡）与 **代码热更**（更新脚本逻辑）是**两件事**，难度差一个量级。

| 内容 | 方式 | 可行性 |
|---|---|---|
| 贴图/模型/音频/动画/场景 | PCK/DLC 覆盖，按路径覆盖 | ✅ 原生稳定 |
| 配置/数值 | 远程下发 | ✅ 但要版本校验 |
| GDScript 逻辑 | 覆盖 `.gd` 资源 | ⚠ 接口原生但生命周期不自持 |
| C# / GDExtension | 原生程序集/动态库 | ⚠ 非常困难，ABI 冲突 |

## 1. 资源热更：PCK 覆盖

核心是 `ProjectSettings.load_resource_pack()`（详见 `modding.md`，用途不同）。

**后加载的覆盖先加载的** —— 打补丁时靠这个语义。

⚠ **对已缓存资源、已 `preload()` 的场景、旧脚本实例，加载新包并不会自动"换血"**
—— 需要重新加载资源、切换场景或重建状态。

这是最容易踩的坑：补丁下载成功了，但屏幕上还是旧的。

**补丁包生成**：导出 PCK 与完整导出不同（只导资源不导引擎）。

⚠ **增量补丁 vs 全量替换**的取舍要按实际体量定。

## 2. ⚠ 代码热更是红线，不是技术问题

**Apple App Store 审核指南 2.5.2** 明确禁止：下载、安装或执行会**改变应用功能特性的代码**。
Google Play 也禁止从 Play 更新机制以外下载可执行代码。
Xbox 公开认证同样警告不要下载远程脚本用于改变功能。

⚠ 所以"下载服务器上的 `.gd` 后 `load()`/`new()`"作为常规热修主路径，**风险高于收益** —— 后果是**下架**，不是 bug。

⚠ **GDScript 资源可以通过 PCK 覆盖，但已实例化的脚本逻辑、继承结构、信号连接、已加载类状态不会原子切换。**

### 推荐的三层设计

```
1. 版本化的基础包 + 可选 DLC 包
2. 非代码配置/资源补丁
3. 客户端中已编译的状态机/脚本解释器
```

原则：**只有数据、资源和受限内容指令变化，不远程注入新执行能力。**

⚠ Nintendo / PlayStation 具体条款受 NDA 约束 —— 需向平台代表核对。

## 3. DLC

DLC 作为独立 pack 加载。

⚠ **DLC 未购买时游戏不能崩** —— 引用了 DLC 资源要有占位策略。

## 4. 配置/数值热更

- 为什么配置要和代码分离（见 `datatable.md`）
- ⚠ **配置热更也要版本校验** —— 否则旧客户端读到新配置会崩

## 5. ⚠ 第一硬限制：PCK 无法卸载

⚠ **Godot 没有 `unload_resource_pack()`，官方确认不存在，只能重启进程。**

- 2021 年官方论坛答复：*"There is currently no method to unload a resource pack once it has been loaded"*
- 2025 年仍有 issue #12047 请求该功能，也只能靠 `OS.create_process` + `quit` 重启间接实现
- issue #2689 同样以"目前无法卸载"起笔，提议的是**禁用（disabled）而非卸载**

✅ 工程对策：

1. **把包设计为进程生命周期级** —— 启动时按玩家已购清单一次性加载，运行期间只做**数据层**热更
2. 需要切换 DLC 的场合用**子目录隔离 + `replace_files=false` 加载**，或接受重启
3. ⚠ **内存层"卸载"只能靠 `ResourceLoader` 缓存管理，不是卸载 pack** ——
   `ResourceLoader.clear_path_cache(path)` + 解除所有 `Ref` 引用，等引用计数归零；
   但 PCK 这个"虚拟文件系统层"本身仍挂着

⛔ **别花时间写一个根本不存在的 `unload_resource_pack`** —— 这条要在代码评审里反复强调。

## 6. ⚠ 第二硬限制：补丁必须在 autoload 的 `_init()` 里加载

⚠ **这是发生率最高的错误，症状就是"补丁下载成功、文件在磁盘上、游戏还是旧的"。**

⛔ `load_resource_pack` 不能写在 `_ready()` 或 `_enter_tree()` ——
那时 `Main` 场景里的 `preload("res://enemy.tscn")` **已经把旧版本钉进 `ResourceLoader` 缓存**，补丁永远没机会。

✅ 正确做法：更新系统做成**顺序为 0 的 autoload**，在 `_init()` 里调用 `load_resource_pack`，
返回 true 后立即 `change_scene_to_packed()` 跳到真正的主场景。

⚠ **`_init()` 与场景切换之间⛔ 不能插任何可能引用旧资源的逻辑。**

## 7. 四个版本号：混用是唯一会让你半年后救不回来的错误

| 版本号 | 例 | 标识什么 | 生命周期 |
|---|---|---|---|
| `client_version` | `1.4.2` | 编译产物，决定能否被强更 | 随商店审核走 |
| `asset_version` | `20260921-r1287` | 当前已安装的全部资源集合 | 随补丁走 |
| `config_version` | `17` | 数值表结构，判断"我能否读懂" | 随运营走 |
| `min_supported_client` | `1.4.0` | **服务端下发**，低于此版本不许连 | 随事故走 |

⛔ **合并成一个 `GAME_VERSION` 常量的项目，最终都会在"只改了数值表却要逼玩家下载商店包"这步崩盘。**

### 强更判定：唯一可信来源是服务端

```gdscript
min = parse(server.min_supported_client)   # 服务端下发
cur = parse(client_version)                # 本机编译时写死
if   cur <  min:  state = FORCE_UPDATE    # 必须去商店，游戏不可继续
elif cur == min:  state = SOFT_FORCE       # 强烈建议更，可延迟一次
else:             state = OPTIONAL         # 有补丁就下，没有也能玩
```

⚠ **`min_supported_client` 必须放服务端，⛔ 不能写客户端常量** ——
线上发现严重经济漏洞时你要**立刻把全量老客户端踢下线**，这不可能重新发包。

客户端只保存 `build_id`（编译期固化、不可变）与 `min_supported_client_cache`（离线兜底）。
⚠ 离线时缓存不存在或高于当前 → 拒绝进对局但允许单机（这个分支要写死进评审清单）。

### 兼容性矩阵：判定顺序不能反

| 配置版本 \ 客户端 | 1.3.x | 1.4.x | 1.5.x |
|---|---|---|---|
| 配置 v15 | 拒绝 | 可运行 | 可运行 |
| 配置 v16 | 拒绝 | 拒绝 | 可运行 |
| 配置 v17 | 拒绝 | 拒绝 | 可运行（需 asset r1287） |

⚠ **判定顺序必须是"先客户端版本 → 再配置版本 → 最后资源版本"** ——
顺序反了会出现"客户端读得懂配置但资源里缺贴图"的崩溃。
⛔ 把校验责任推给客户端是灾难（客户端校验逻辑有 bug 你无法修复）。

### 版本清单要签名 + 带有效期

```json
{
  "generated_at": "2026-09-21T10:00:00Z", "ttl_seconds": 300,
  "client": { "min_supported_client": "1.4.0", "latest_client": "1.5.1",
              "store_urls": { "ios": "...", "android": "..." } },
  "patches": [{ "patch_id": "p_20260921_r1287", "from_sequence": 1280,
                "to_sequence": 1287, "size_bytes": 8421376,
                "sha256": "a3f5...", "url": "...", "is_critical": true }],
  "config": { "config_version": 17, "min_client": "1.4.0", "url": "...", "sha256": "..." },
  "active_patches": ["p_20260921_r1287"],
  "revoked_patches": ["p_20260910_bad01"],
  "rollout": { "config_bucket": "c_17", "percent": 5, "hash_salt": "..." }
}
```

⚠ **`active_patches` 与 `revoked_patches` 是"一键回滚"的关键** ——
客户端维护 `enabled_patches` 集合，服务端把某 `patch_id` 从 active 移到 revoked，下次启动直接跳过。
✅ **补丁永远是可禁用的开关，⛔ 不是删除**。

⚠ **资源版本用单调整数 + 补丁链锚点**：`asset_sequence: int`，每次成功安装 +1。
⛔ 不要用语义版本号描述资源（资源没有"主版本不兼容"语义，只有对不对得上）。

## 8. 补丁生成：基线、差分、签名

⚠ **4.4 起官方已把"补丁 PCK"做成编辑器一等公民** —— 导出菜单 Patching 页签，
把首发全量 PCK 加入 Base Packs，勾选 Export as Patch，再次导出只含改动过的资源。
ⓘ 之后 `patch2.pck` 可以把 `patch.pck` 也加进 Base Packs，避免重复包含。

⚠ **4.4+ 的 delta encoding 用的是 zstd `--patch-from`，不是 bsdiff**（PR #112011）。

⚠ **delta 有真实累积成本，这是选型第一约束：**

- 被更新资源的**加载时间会变长**，且**同一个资源的每个补丁会累积叠加**
- 压缩级别默认 19，⛔ 不建议超过（内存暴涨而收益显著降低）
- 最小体积缩减率默认 10%，达不到就不启用 delta
- ⚠ **导出 delta 补丁时 Base Packs 列表必须与运行时加载的包完全一致、顺序也一致** ——
  Godot 导出存在非确定性，重新导出旧版本可能得到不同字节导致 patching 失败
  （ⓘ 这条只针对 delta，普通 patch PCK 不受影响）

✅ **双层结构而不是二选一**：

| 补丁 | 用哪种 | 理由 |
|---|---|---|
| 小补丁（< 5MB 或改动文件少） | 普通 patch PCK 全量替换 | 零累积开销、简单可靠 |
| 大补丁（> 20MB 且改动文件少） | delta + **定期出合并基线** | 每 4–8 个增量后发一份基于最新全量的普通 patch，截断 delta 链 |

⛔ **绝不对 GDScript 字节码、`.import` 元数据开 delta** —— 它们每次构建都变，delta 几乎无效只增开销。

⚠ **bsdiff 类思路在 Godot 资源上收益有限且风险高** —— 适用于自研整块二进制 blob；
⛔ 不适用于 `.import`、`.godot/imported/`、uid 缓存（引擎版本或导出参数稍变就面目全非，delta 体积超过原文件）。

### 补丁元数据必须声明 from / to

`patch_manifest.json`（可嵌进 PCK 或随包下发）至少含：
`patch_id`、`from_sequence`、`to_sequence`、`from_client`、`to_client`、
`asset_version`、`min_client_to_apply`、`base_pack_sha256`、`patch_sha256`、`generated_at`

```gdscript
if state.asset_sequence != manifest.from_sequence:
    push_warning("sequence mismatch, expecting %d" % state.asset_sequence)
    download_full = true          # ⛔ 不要删除已下载包，转全量
if client_version < manifest.min_client_to_apply:
    abort("client too old, need store update")
```

### ⚠ 签名与校验三层，顺序不能反

1. **manifest 签名**（Ed25519，客户端内置公钥验签）—— 防中间人投毒
2. **包体哈希**（SHA-256）—— 完整性
3. **结构校验**（把 PCK 当 pack 打开、读几个关键路径、确认 manifest 可解析）

⚠ **先验签再哈希**，⛔ 顺序反了等于给攻击者一个免费哈希 oracle。
⛔ 只做哈希的项目曾在"CDN 返回 200 但 body 是 HTML 错误页"上集体中招 —— 哈希过了，内容是错的。

ⓘ PCK 自带的 256-bit AES 加密是给资源防扒用的，**不提供来源认证**，两者不可替代。

### CI 流水线

`git tag` 触发 → 检出基线 tag 用 `--export-pack` 生成基线 PCK → 检出新版本用**同一份 preset** 导出新 PCK
→ 资源清单差集 → headless 导出 patch PCK（Base Packs 指向基线）→ 可选 delta
→ 生成 manifest → 私钥签名 → 上传 CDN 写版本清单 → **干净环境冒烟**（下载→校验→加载→加载旧场景→对比字节）

⚠ **基线 PCK 必须是从同一次构建产物归档取回的，⛔ 不能重新导出**，否则 delta 会失败。

## 9. 客户端更新状态机

```
IDLE → CHECKING → DETERMINED → DOWNLOADING → VERIFYING
     → INSTALLING → LOADING → ACTIVATED
失败统一进 FAILED，按错误类型分流：
     ROLLBACK / RETRY_DOWNLOAD / PROMPT_FORCE_UPDATE
```

⚠ **必须是显式状态机，⛔ 不能用回调嵌套**；每个状态一个入口一个出口，转换写进单元测试。

### 下载：用 HTTP Range，⛔ 不要用 HTTPRequest 拉整包

⚠ **`HTTPRequest` 会把整个响应体攒在内存里** —— 几十 MB 补丁在低端 Android 上直接 OOM。

✅ 用 `TCP_Socket` 手写分段：`Range: bytes=<downloaded>-`，服务端回 `206 Partial Content`，
追加写 `user://update/<patch_id>.part`；**每 64KB 或每 1 秒持久化 `bytes_downloaded`**，否则崩溃后进度归零。
⚠ 服务器必须支持 Range 并透传 `Accept-Ranges: bytes`（CDN 配了却未透传是常见踩坑）。

⚠ **重试：指数退避 + 抖动** —— 初始 1s、每次 ×2、最大 30s、最多 8 次；抖动 ±20% 避免雪崩。
⚠ **403/404 立即放弃并告警** —— 签名 URL 过期是"这个包不该再被下载"的信号，死循环重试会烧玩家流量。

### 磁盘空间：留 2 倍余量

```gdscript
required = patch.size_bytes * 2   # .part + 校验/解压临时空间
if FileAccess.get_space_left() < required: state = DISK_FULL
```

⚠ **不要只留 1.2 倍** —— delta 合并、临时文件、文件系统预留会一起吃掉剩余空间。
⚠ **下载中每 5% 复检**，跌破 `size × 1.5` 立即暂停并保留已下载片段，
⛔ 绝不在空间不足时继续写（会产生不可恢复的部分文件）。

### 安装：三段式原子切换

```
user://update/
├── staging/              下载中的 .part
├── ready/<id>.pck        校验通过待安装
├── installed/<id>/       当前生效（保留两份）
├── prev/<id>/            上一份，回滚用
└── state.json
```

流程：`mkdir installed_new` → 复制/移动（**同文件系统内 rename 是原子的**）→ 逐个校验 SHA-256 与内部结构
→ 全部通过后 `installed` 改名 `prev`、`installed_new` 改名 `installed` → 更新 `state.json`

⚠ **顺序绝不能反**：⛔ 先更新状态再移动文件 —— 断电后状态指向不存在的目录，
你就制造了一个"启动即崩溃"的死局。

### 回滚：触发条件要预先枚举，⛔ 不能靠人判断

触发源：校验失败（哈希/签名/结构任一）· 安装期 I/O 错误 · `load_resource_pack` 返回 false ·
加载后关键资源 `load()` 返回 null · **启动后 30 秒内第二次崩溃**（`crash_count` 持久化）·
主城加载超时 · 关键漏斗失败率超阈值

流程：保留 `prev/` ⛔ 不删 → `asset_sequence` 回退 → `applied_patches` 移除该 patch
→ manifest 的 `revoked_patches` 追加该 id → 记录 `last_failed_patch` → 下次启动从 `prev` 加载

⚠ 若连续两次回滚同一 patch → 进**安全模式**：清空全部 installed，只加载基础资源，提示重下。

⚠ **回滚测试是上线前必跑项** —— 模拟三种故障：下载到 70% 杀进程、PCK 内容改成全零、
`load_resource_pack` 之后抛异常。三种都必须能启动且状态一致。
⛔ 95% 的项目写了回滚代码但从未在故障路径上跑过，出事时发现回滚本身有 bug。

## 10. 加载新包后的"换血"：最容易崩的一步

⚠ **`load_resource_pack` 只影响后续的 `load()` / `preload()` 解析。**
已拿到 `RefCounted` 的资源、已在场景树里的节点、正在播放的 `AnimationPlayer` 引用的动画，**全部仍是旧实例**。

✅ 正确做法：
- 让 `load_resource_pack` 在所有业务场景加载前完成（即 `_init()`）
- 可热更的资源改用**路径字符串 + 延迟 `load()`**，⛔ 不用 `preload` 常量
- 缓存 `String` 路径而非 `Texture2D` 引用

### 已实例化对象分三档处理

| 档 | 内容 | 做法 |
|---|---|---|
| 一 | 纯数据（数值表、本地化字符串） | 卸载旧表 → 加载新表 → 通知监听者刷新 UI，**无需重建场景** |
| 二 | 可重建场景（主菜单、商店、背包） | `queue_free()` 整个子树后重新 `load()` 再 `instantiate()`（⚠ 先解除所有外部引用否则泄漏） |
| 三 | 不可中断的运行时状态（战斗进行中） | ⛔ **绝不热换** —— 标记"下次进入该场景时生效"，后台 `load_threaded_request` 预加载，场景退出时切换 |

⚠ **场景树切换必须停住输入与计时** —— `set_process(false)`、禁 UI 输入、暂停 `AnimationPlayer`、
`Time` 相关逻辑切暂停态。⛔ 否则旧节点的 `_process` 会在新场景树里继续跑，产生幽灵回调。
切换期间显示非交互式进度层（最高 `CanvasLayer`），⛔ 禁止玩家点击。

⚠ **重启是最可靠也最重的切换手段** —— 适合 GDScript 字节码、`project.godot` 覆盖、autoload 脚本、core 场景变更。
用 `OS.create_process(OS.get_executable_path(), args)` 拉起新进程后 `get_tree().quit()`，
⚠ 通过命令行参数传"跳过本次更新检查"防重启循环（`restart_count` 超过 2 次放弃补丁进安全模式）。

### 生效时机要显式声明

`apply_at: boot`（下次启动，默认最安全）· `next_scene`（离开当前场景时，资源类）
· `immediate`（立即，仅数据，风险最高）

⚠ manifest 里声明、客户端按声明执行，⛔ 不允许业务代码自行决定。

## 11. 资源分包与 DLC

⚠ **分包粒度由"玩家进入时机"决定，⛔ 不由目录结构决定。**

| 层 | 内容 | 分发 |
|---|---|---|
| L0 | 启动必需（引导、UI、首场景、核心系统、**占位资源**） | 商店包 |
| L1 | 首屏（主城 + 第一关 + 通用音效） | 商店包或预下载 |
| L2 | 章节/关卡包 | **过场动画时后台下载** |
| L3 | 角色包 | 按需 |
| L4 | 高清材质包 | 按需 |
| L5 | 语言包 | 按需 |

⛔ **不要把高频共用资源（通用 shader、基础 UI 图集、共享音效）放进章节包** —— 这是依赖地狱的起点。

⚠ **分包依赖要显式声明成图，CI 做环路检测** —— 每个分包 manifest 含 `depends_on`，客户端拓扑排序，检测到环构建失败。

重复资源三条规则：出现两次以上 → **提到 common 包**；只有两处引用且包体小 → 各打一份并标 `duplicated: true`；
**出现三处以上还不提公共包 → CI 报错**。
⛔ 禁止隐式依赖 —— "刚好另一个包先加载所以能读到"是迟早会断的线。

⚠ **按需下载的代价是"第一次进关卡必然卡顿"** —— 此时才下载等于把"关卡加载条"伪装成"网络等待条"。
✅ 下载窗口选玩家无可中断操作的时段：章节结算页、装备界面打开时、设置页停留超 3 秒。

⚠ **磁盘配额主动管理** —— `user://dlc/quota.json`：`max_cache_bytes`（默认可用空间 30%）、
按 `last_used_at` 排序 LRU 淘汰。⛔ **永不淘汰基础包与已购买但未验证的包**；
淘汰前检查该包是否正被场景引用（有就延后到场景退出）。

### DLC 占位：三种策略不能混用

| 策略 | 表现 | 适用 |
|---|---|---|
| `LOCKED_PLACEHOLDER` | 入口显示锁与价格，点击跳商店；预置 1×1 占位贴图与静音 wav | 常规 |
| `SILENT_HIDDEN` | 未购入口整条不出现 | 章节制叙事（避免"第 3 章灰着"破坏预期） |
| `GREYED_OUT` | 灰态显示 + 锁定原因 | 角色/外观 |

⚠ 选择规则写进设计文档**全游戏统一**。
⚠ **所有占位资源随基础包分发，⛔ 绝不从网络拉取** —— "玩家离线打开背包看到崩溃"是真实高频事故。

⚠ **所有权校验要有超时兜底**：启动时拉一次存 `user://entitlements.json`，之后读缓存；
每次打开 DLC 入口再校验，**网络失败时信任缓存而非锁死入口**。
⛔ 把网络错误当成"未购买"会让玩家在地铁里看到自己花钱买的关卡变灰。

ⓘ Godot 4.7 的 Android 导出已支持以 APK/AAB 为 base pack 做 PCK patching（PR #116553）。

## 12. 配置热更：纯数据的边界要守住

✅ 数据只走 `ResourceLoader.load()` 或 JSON 解析，**Apple 与 Google 对纯数据下载无限制**。

⚠ 但边界要守住：配置里出现 **URL 跳板、决定功能开关的字段、可执行表达式**，
就跨过了数据/逻辑的线 → 被判定为**变相代码热更**。

⚠ **配置版本校验要在解析之前，⛔ 不在崩溃之后：**
拉取 → 验签 → `if version < CONFIG_COMPAT_MIN: reject` → `if version > CONFIG_COMPAT_MAX: prompt_store_update`
→ **JSON Schema 校验**字段类型与必填项 → 加载

### ⚠ 与存档兼容的真正难点是"语义变了"

| 故障 | 后果 |
|---|---|
| 字段改名（`atk` → `attack`） | 旧存档读不到默认 0，玩家战力凭空消失 |
| 枚举插入值（`Sword=2` 中间插入 `Axe`） | 旧存档的 2 从剑变成盾 |
| 数值单位变更（暴击率 0–100 → 0–1） | 旧存档 35 变成 3500% |

✅ 对策：存档文件头固定 `save_version: int`，每个版本升档写独立的 `migrate_vN_to_vNp1()`，
**迁移链式执行（v1→v2→v3），⛔ 不能跳过中间步骤**；每个迁移函数只做一件事并单测；
迁移前写 `save.bak`，`load` 失败先回退备份。
⚠ **存档版本与配置版本独立演化，⛔ 不允许互相耦合。**

⚠ **数值变更要带生效策略** —— `data_effective_at`：`immediate`（仅无状态数据）、
`next_battle`（平衡性调整，战斗进行中不生效）、`next_login`（商店价格）、
`never`（不可逆字段：已购买货币、永久属性点）。

⚠ **回滚要区分"配置错误"与"数值不合理"** —— 前者崩溃级走 revoked；后者是运营判断，
改回数值重新下发即可。⛔ 把"玩家觉得太弱"当"配置损坏"回滚，会让玩家看到角色属性来回跳。

## 13. 灰度与应急

✅ 灰度维度顺序：账号 ID 哈希（最稳定）→ 设备/机型 → 地区 → 客户端版本。
桶边界 `hash(account_id + rollout.salt) % 100 < rollout.percent`，服务端旋转 `salt` 即可重来。

⛔ **绝不能用随机数或 `rand()` 分桶** —— 玩家每次启动都换桶，A/B 数据作废且可能反复触发新功能闪现。

### 灰度期监控六类指标

崩溃率（按 `client_version × patch_id × device_model` 三维切片）· 启动成功率 ·
补丁下载成功率与中位数耗时 · `load_resource_pack` 返回 false 占比 ·
关键漏斗（登录→主城→首战）· DLC 下载完成率与空间不足报错率

⚠ 硬阈值：崩溃率较上一版 +0.5pp 即暂停 · 启动成功率 < 98% 即回滚 · 下载成功率 < 95% 检查 CDN/签名 URL
（ⓘ 具体数值**待核实**，须按项目稳定期基线回填）

⚠ **回滚必须一键且客户端无需更新** —— 服务端把 `percent` 置 0、`active_patches` 移到 `revoked_patches`、
`config_bucket` 指回上一版。✅ **永远保留最近两份全量资源包**，否则回滚意味着所有玩家重下几百 MB。

### ⚠ 强制更新不能灰度（结构性矛盾）

强更的本质是"低于某版本服务端拒绝服务"，⛔ 你无法让同一服务端"对 1% 人说不、对 99% 说可以"还保持状态一致 ——
老客户端读到的数据格式、协议字段、资源路径都不同。

⛔ 误把强更配灰度开关 → 同一账号在两台设备上一个能进一个不能进、存档同步错乱。
✅ 需要强更就**全量强更**；想灰度就只灰度非破坏性内容（资源、数值、可选包），破坏性变更放进下一次商店版本。

### 应急四级响应

| 级别 | 场景 | 动作 | 目标 |
|---|---|---|---|
| P0 | 全量不可用 / 数据损坏 | 上调 `min_supported_client`、吊销问题包、切回上一配置、全平台公告 | 15 分钟止血 |
| P1 | 崩溃率显著上升 / 加载大面积失败 | 暂停灰度、撤销 patch、通知客服话术 | — |
| P2 | 单地区 / 单机型 | 缩窄灰度、收集日志、排期修复 | — |
| P3 | 体验类 | 记录进 backlog | — |

⚠ **止血动作必须幂等** —— 同一指令重复执行⛔ 不能把已恢复的版本再次撤销。
⚠ **应急剧本要预演，⛔ 不是文档**。

## 14. 平台差异

⚠ **Apple 2.5.2 是红线，没有任何"热修复例外"** —— 审核关注**行为是否改变**，不是你用什么技术。
Lua/JS 解释器本身不违规，但**解释器加载下载来的脚本并改变功能就违规**；
远程配置驱动原生行为、跨过"数据变逻辑"的线同样违规。
ⓘ 教育类例外极窄：代码必须完全可被用户查看与编辑，只能用于教学。

⚠ **Google Play 表述更具体但结论一致** —— 唯一例外是"运行于 VM/解释器内、且该 VM 间接访问 Android API 的代码（如 WebView 中的 JS）"，
⛔ 但前提是这类代码不允许违反 Play 政策。带 `addJavascriptInterface` 的 WebView 加载不可信 URL 是明确违规示例。

⚠ **Steam 的 depot/branch 与自建热更是并存，⛔ 不是替代** ——
depot 是内容容器，build 是快照，manifest 记录每个文件 SHA-1；branch 是 build 指针，`Default` 一旦 set live
**所有已拥有玩家立即收到更新**（官方强调 "make sure you're ready to release"），且需 Steam Mobile Authenticator 二次授权。

⚠ **Steam 版要小心双重更新** —— 玩家先被 Steam 更新到新资源，再被你的系统下载旧补丁覆盖回去。
✅ Steam 版以 depot 版本为准并跳过自建流程。

⚠ **主机没有自建热更的合规空间，且每次提交都要重过认证** ——
Xbox SLA：数字内容更新 2 工作日、Fastlane 24 小时；光盘提交 5 工作日。
PlayStation 与 Nintendo 首提普遍 2–6 周。
→ 主机的"热修复"本质上不可能，应急通道只能是**服务端配置、协议兼容、提前埋好但默认关闭的功能开关**。

⚠ **主机包要按平台规则命名** —— 用稳定 GUID 而非路径做引用；每平台单独 export preset，CI 分别归档基线 PCK；
`min_supported_client` 按平台独立下发（各平台审核不同步，同一时刻可能差两个大版本）。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/hotupdate.md`


## 15. 待核对项（运行时验证）

⚠ 待核对：目标平台对资源包覆盖式更新的实际接受度 · 验证：按目标平台提交审核前与平台方确认

⚠ 待核对：PCK 补丁的加载顺序对已缓存资源的影响 · 验证：实测加载补丁后旧实例是否更新

## 16. 相关文档

- 玩家 Mod（同样的覆盖机制）→ `modding.md`
- 资源加载 → `io-network.md`
- 配表与数据驱动 → `datatable.md`
- 平台导出 → `platform-export.md`
- 存档迁移 → `save-migration.md`
- 云存档 → `cloud-save.md`
