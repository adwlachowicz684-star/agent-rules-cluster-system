# 01 身份主键与 Godot 侧边界（账号安全域）

> **本步交付**：四对象唯一键 + 授权表 + 凭据存放与传输口径
> **对应**：流程 `howto/godot/account-security.md` · 审核 `audit/godot/account-security.md`

## 0. 交付物定义

1. 身份 / 凭证 / 会话 / 角色 四层都有**唯一键与授权表**
2. 账号主键**内部生成**，第三方登录存 `issuer + subject`
3. 业务请求只信**服务端从会话查出**的 ID
4. 凭据不进 `user://`，只进平台安全存储
5. "记住密码"实现为**不存密码**，只存可撤销的 refresh
6. TLS 校验在生产构建中**仍生效**，无 `client_unsafe()` 残留

## 1. 前置检查清单

- [ ] 四层模型已写出，每层有唯一键
- [ ] 账号主键不是手机号 / 邮箱 / 可枚举昵称
- [ ] 没有任何业务接口直接信任客户端传的 ID 或权限字段
- [ ] token 只存在内存与平台安全存储
- [ ] 生产构建里 `is_unsafe_client()` 为 false
- [ ] 崩溃上报与日志已脱敏

## 2. 工序

### Step 1　先设计四对象的唯一键，⛔ 不是先设计登录界面　`[account-security/01#S1]`

【读】`howto/godot/account-security.md#0. 先分清四个对象`

【做】
把**身份 / 凭证 / 会话 / 角色**四层各自的主键与授权关系写成一张表，
再动手做登录界面。
⛔ 先做界面 —— 界面会倒推出"账号就是手机号""登录态就是个 bool"这类隐含模型，
表现为"改绑手机后资产丢了""换设备后角色对不上"，
⛔ 而排查时每个界面单看都是对的。

ⓘ 这一层缺失，后面加再多加密和风控都只是**把越权入口包起来**——
入口还在，只是包得好看。

【产出】四层模型表（每层主键、可变更性、授权关系）

【判据】任一层被替换（换手机、换第三方、换端）时，其余层不受影响。

【审】`audit/godot/account-security.md#1`

### Step 2　账号主键内部生成，第三方存 `issuer + subject`　`[account-security/01#S2]`

【读】`howto/godot/account-security.md#0. 先分清四个对象`

【做】
账号主键由**服务端内部生成**，不可枚举、不可变更。
第三方登录只存 `issuer + subject`，⛔ 不存第三方返回的可变用户 ID。
⛔ 用手机号 / 邮箱当**主键** —— 它们是可变更的**登录名**，
表现为"用户换了手机号，历史订单与角色全部对不上"，
⛔ 而换号流程本身一切正常，排查被引向换号功能。

ⓘ 第三方的可变 ID 尤其隐蔽：它在同一平台上长期不变，
⛔ 只在用户解绑重绑、平台改口径时才变，届时账号直接串号。

【产出】主键生成规则 + 第三方绑定表（issuer / subject / 绑定时间）

【判据】换登录名、换第三方绑定后，账号 ID 与资产不变。

【审】`audit/godot/account-security.md#3`、`audit/godot/account-security.md#4`

### Step 3　业务只信服务端从会话查出的 ID　`[account-security/01#S3]`

【读】`howto/godot/account-security.md#0. 先分清四个对象`

【做】
所有业务接口从**服务端会话**反查账号 ID 与角色 ID，
⛔ 不接受客户端传来的 `account_id` / `role_id` / `is_admin`。
⛔ 信任客户端传的 ID —— 改包即可越权查看与操作他人资产，
表现为"排行榜第一名的背包能被别人打开"，
⛔ 而服务端日志里每一次都记录为"该账号的正常请求"。

ⓘ 这条只在有人改包时才暴露，⛔ 测试环境下永远测不出来，
所以判据必须是**改包实测**（见 07）。

【产出】服务端会话反查函数 + 接口入参白名单（不含任何身份字段）

【判据】改包伪造 ID 后服务端一律拒绝或使用会话 ID。

【审】`audit/godot/account-security.md#2`

### Step 4　凭据不进 `user://`，⛔ 它不是凭据库　`[account-security/01#S4]`

【读】`howto/godot/account-security.md#凭据存放`

【做】
access token 只存**内存**；需要持久化的 refresh token 放进**平台安全存储**
（iOS Keychain / Android Keystore），⛔ 不写 `user://` 的任何文件。
⛔ 把 `user://` 当安全目录 —— 官方只对**移动端**声明该路径项目独享、
其他应用不可访问；桌面端实际是 `%APPDATA%\Godot\app_userdata\[项目名]` 等
**普通用户目录**，HTML5 导出则是 IndexedDB 虚拟文件系统。
表现为"桌面端 token 被同机其他进程读走"，⛔ 而游戏自身一切正常。

ⓘ 桌面端若没有统一凭据库，正确做法是**降低离线续期能力**
（冷启动重新认证），⛔ 而不是"加密一下继续存文件"。

【产出】凭据存放位置表（内存 / 平台安全存储 / 绝不落盘清单）

【判据】`user://` 下不存在任何 token、TOTP 密钥、密码或工单凭据。

【审】`audit/godot/account-security.md#30`、`audit/godot/account-security.md#37`

### Step 5　"记住密码"实现为不存密码　`[account-security/01#S5]`

【读】`howto/godot/account-security.md#7. Godot 侧的正确位置`

【做】
"记住密码"只保存**可撤销的 refresh token**，⛔ 绝不保存密码本身。
⛔ 把密码加密后存文件 —— 密钥仍可被同一进程、导出 PCK 或同设备其他应用间接取得，
表现为"本机被入侵后全部账号失守"，⛔ 而加密本身没有出任何错。

ⓘ 判据很直接：**能不能只靠服务端撤销就让这个"记住"失效**。
能撤销的是 refresh，不能撤销的是密码。

【产出】"记住我"的落地形态（refresh token + 可撤销）与撤销入口

【判据】服务端撤销后，客户端不再自动登录，且不保存任何密码材料。

【审】`audit/godot/account-security.md#31`

### Step 6　传输层不能留 `client_unsafe()`　`[account-security/01#S6]`

【读】`howto/godot/account-security.md#TLS 传输`

【做】
生产构建使用默认证书校验，⛔ 不残留 `TLSOptions.client_unsafe()`。
该配置下**证书校验变可选、common name 永不检查**，
中间人可换证书截获 access / refresh token，⛔ 而客户端**不会有任何提示**。
ⓘ 官方 `is_unsafe_client()` 可反查，适合做成发布门禁。

⚠ 两个方向相反的坑要一起记：
Web 平台 TLS 校验**始终强制**（官方称 security feature），无法用 `client_unsafe()` 绕过；
而把自签证书加进证书包**并不等于放行任意域名**——官方仍按 CN 与 SAN 做**域名校验**。

⛔ 表现为"桌面版连得上内网、Web 版握手失败"或"证书配了还是握手失败"，
⛔ 两种都会被误判成网络库或平台问题。

【产出】TLS 配置清单（生产 / 内网 / Web 三套）+ 发布门禁检查项

【判据】生产构建 `is_unsafe_client()` 为 false；换证书后连接失败。

【审】`audit/godot/account-security.md#34`、`audit/godot/account-security.md#35`、`audit/godot/account-security.md#36`

## 3. 参考实现

```gdscript
# ⓘ 承接本步产出：四层模型 + 服务端反查 + 凭据不落 user://
# ⛔ 常量均为占位，实际取值见 00 参数登记，待实测

enum CredentialStore { MEMORY, PLATFORM_SECURE }

# 业务请求的用户身份只能来自服务端会话，⛔ 不接受客户端传入
# SESSION_LOOKUP_ENDPOINT 见 00 参数登记
func current_account_id(session_token: String) -> String:
    # ⛔ 不实现为 fun(account_id) —— 那是信任客户端
    return _auth.session_account_id(session_token)

# 凭据存放：access 只进内存，refresh 只进平台安全存储
# ⛔ 不写 user:// —— 桌面上那是普通用户目录
func persist_refresh(token: String) -> void:
    if OS.has_feature("iOS") or OS.has_feature("Android"):
        _secure_store.write("refresh", token)
    else:
        # ⓘ 桌面无统一凭据库 → 降低离线续期能力，冷启动重新认证
        pass

# 发布门禁：⛔ 生产构建不得残留不安全客户端配置
func assert_tls_safe(opts: TLSOptions) -> void:
    assert(not opts.is_unsafe_client(), "生产构建不得使用 client_unsafe()")
```

## 4. 验收清单

- [ ] 四层都有唯一键，换登录名不影响资产
- [ ] 第三方绑定存的是 `issuer + subject`
- [ ] 改包伪造 ID 被服务端拒绝
- [ ] `user://` 下无任何凭据
- [ ] "记住我"可被服务端撤销
- [ ] 生产构建 `is_unsafe_client()` 为 false

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 改个 ID 能看别人背包 | 信任客户端传的 ID | S3 |
| 换手机号后资产对不上 | 手机号当了主键 | S2 |
| 桌面端凭据被读走 | 写进了 user:// | S4 |
| 本机失守全部账号 | 存了密码 | S5 |
| Web 版连不上内网 | 依赖 client_unsafe | S6 |
| 配了证书仍握手失败 | 忽略了 CN/SAN 域名校验 | S6 |

## 6. 下一步

→ 02 口令存储与强度校验

## 7　整体审核（功能点级收尾）

【审】`audit/godot/account-security.md#1`、`audit/godot/account-security.md#3`、`audit/godot/account-security.md#4`、`audit/godot/account-security.md#2`、`audit/godot/account-security.md#30`、`audit/godot/account-security.md#37`、`audit/godot/account-security.md#31`、`audit/godot/account-security.md#34`、`audit/godot/account-security.md#35`、`audit/godot/account-security.md#36`
