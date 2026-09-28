# 03 HTTP 客户端与失败语义（资源与网络域）

> **本步交付**：timeout/header/限流口径 + 三类结果判据 + 单请求约束
> **对应**：流程 `howto/godot/io-network.md` · 审核 `audit/godot/io-network.md`

## 0. 交付物定义

1. `timeout` **显式**设置，不留默认
2. 自定义 header 里**不含** `Accept-Encoding`
3. `body_size_limit` 已设，⛔ 不留 `-1`
4. 一个 `HTTPRequest` 同时只处理一个请求
5. 结果分三类判：`result` / `response_code` / 解析

## 1. 前置检查清单

- [ ] 每个 `HTTPRequest` 都设了 `timeout`
- [ ] header 数组里没有 `Accept-Encoding`
- [ ] `body_size_limit` 有值
- [ ] 有 `get_http_client_status()` 的忙判断
- [ ] 回调里三层判据都在

## 2. 工序

### Step 1　timeout 必须显式设，默认的 0.0 是"永不超时"　`[io-network/03#S1]`

【读】`howto/godot/io-network.md#6. HTTP`

【做】
按用途设 `timeout`：小 REST 请求设 10.0–30.0，⛔ 文件下载留 `0.0`。
⛔ 不设 —— 默认 `0.0` 的含义是**永不超时**，
弱网下表现为"一直转圈"，⛔ 排查被引向服务端没响应。

ⓘ 这不是"设大一点更安全"：设成 0.0 等于关掉保护，
而关掉保护在**网络正常时完全看不出问题**。

【产出】timeout 选型表（接口类别 → 秒数 → 理由）

【判据】断网后请求在预期时间内失败，而不是永久挂起。

【审】`audit/godot/io-network.md#22`

### Step 2　自定义 header 里不能带 Accept-Encoding　`[io-network/03#S2]`

【读】`howto/godot/io-network.md#6. HTTP`

【做】
自定义 header 只放业务头（鉴权、版本），⛔ **不要**写 `Accept-Encoding`。
官方：*"If the user has specified their own `Accept-Encoding` header,
then no header will be added regardless of `accept_gzip`"*。
⛔ 顺手重写整个 header 数组 —— gzip 解压**静默失效**，
`body` 直接是压缩字节，`JSON.parse` 失败。
⛔ 表现为"接口时好时坏"，排查被引向服务端或编码问题。

ⓘ 这条最难查：加的是鉴权头（一件完全正确的事），
坏的是顺带写进去的那一行。

【产出】header 构造规则（⛔ 白名单：只允许业务头）

【判据】开启 gzip 的服务端响应能正常解析。

【审】`audit/godot/io-network.md#23`

### Step 3　响应体要有上限，进度分母不能是 -1　`[io-network/03#S3]`

【读】`howto/godot/io-network.md#6. HTTP`

【做】
设 `body_size_limit`；用 `get_body_size()` 做进度时**先判 -1**。
官方：服务器不发长度或用 chunked 传输时它返回 **-1**。
⛔ 直接拿它当分母 —— 除零或负数进度，⛔ 表现为"进度条乱跳"。

ⓘ 上限这条不是性能优化：**响应体是对方控制的**，
不限流等于把内存交给服务端决定。

【产出】限流值 + 进度计算（含 -1 分支）

【判据】构造一个超大响应，被限流拦下而不是吃满内存。

【审】`audit/godot/io-network.md#24`、`audit/godot/io-network.md#26`

### Step 4　一个 HTTPRequest 只处理一个请求，ERR_BUSY 要单独认　`[io-network/03#S4]`

【读】`howto/godot/io-network.md#3. HTTP 请求`

【做】
发请求前用 `get_http_client_status()` 判忙，或一请求一节点。
`request()` 会返回 `ERR_BUSY`（前一个还在处理）、`ERR_UNCONFIGURED`（不在树里）。
⛔ 统一 `if err != OK: push_error("请求发起失败")` ——
把四种错误压成一句话，于是"连发两次第二次没反应"
看起来跟网络故障**一模一样**，⛔ 排查被引向服务端。

ⓘ 这与"必须 `add_child`"是同一个约束的两面：
不在树里 = `ERR_UNCONFIGURED`，在树里但忙 = `ERR_BUSY`。

【产出】请求封装（判忙 + 错误码分流转译）

【判据】连续发两次请求，第二次明确报"忙"而不是"失败"。

【审】`audit/godot/io-network.md#25`、`audit/godot/io-network.md#1`

### Step 5　结果要分三类看：传输 / 状态码 / 解析　`[io-network/03#S5]`

【读】`howto/godot/io-network.md#3. HTTP 请求`

【做】
回调里依次判：① `result != RESULT_SUCCESS`（传输层）
② `response_code` 不在 2xx（业务层）③ 解析是否成功。
⛔ 只判 `result` —— 500 / 404 被当成成功，
⛔ 于是"服务端报错"在客户端表现为"数据为空"，排查被引向数据处理。

ⓘ `JSON.parse_string` 失败返回 `null`，
⛔ 与"成功解析出 JSON null"无法区分（见 `monetization` 域同一条），
所以解析要用 `JSON.new().parse()` 取错误码，不要用返回值判成功。

【产出】统一回调处理函数（三层判据 + 各自的错误出口）

【判据】构造 500 响应，客户端报"业务失败"而不是"数据为空"。

【审】`audit/godot/io-network.md#27`

## 3. 参考实现

```gdscript
# ⓘ 承接本步产出：显式 timeout + 限流 + 判忙 + 三层结果判据
# ⓘ 常量出处：TIMEOUT_SEC / BODY_LIMIT 由参数表登记（待实测）
# ⓘ BASE_URL 由项目配置注入，本块按已声明使用
const BASE_URL := "https://api.example.com"
const TIMEOUT_SEC := 15.0
const BODY_LIMIT := 4 * 1024 * 1024
const STATUS_DISCONNECTED := HTTPClient.STATUS_DISCONNECTED
# ⓘ ERR_BUSY 为引擎内置全局错误码（@GlobalScope），无需声明

var _http: HTTPRequest

func _ready() -> void:
    _http = HTTPRequest.new()
    add_child(_http)                     # ⛔ 不入树 = ERR_UNCONFIGURED
    _http.timeout = TIMEOUT_SEC          # ⛔ 默认 0.0 = 永不超时
    _http.body_size_limit = BODY_LIMIT   # ⛔ 默认 -1 = 无限制
    _http.request_completed.connect(_on_done)

func get_json(path: String) -> int:
    if _http.get_http_client_status() != STATUS_DISCONNECTED:
        push_warning("上一个请求还在处理")   # ⛔ ERR_BUSY 要单独认
        return ERR_BUSY
    # ⛔ header 只放业务头，不能带 Accept-Encoding（会让 gzip 解压失效）
    var err := _http.request(BASE_URL + path, ["Content-Type: application/json"])
    if err != OK:
        push_error("发起失败: %d" % err)
    return err

func _on_done(result: int, code: int, _h: PackedStringArray, body: PackedByteArray) -> void:
    if result != HTTPRequest.RESULT_SUCCESS: return   # ① 传输层
    if code < 200 or code >= 300: return              # ② 业务层
    var j := JSON.new()
    if j.parse(body.get_string_from_utf8()) != OK: return   # ③ 解析层
    _apply(j.data)
```

## 4. 验收清单

- [ ] 断网后在预期时间内失败
- [ ] gzip 响应能解析
- [ ] 超大响应被限流拦下
- [ ] 并发请求报"忙"而不是"失败"
- [ ] 500 响应报"业务失败"

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 弱网下一直转圈 | `timeout` 没设 | S1 |
| 接口时好时坏，body 是乱码 | header 带了 Accept-Encoding | S2 |
| 进度条乱跳 | `get_body_size()` 是 -1 | S3 |
| 第二次请求没反应，报网络故障 | `ERR_BUSY` 被压成一句话 | S4 |
| 服务端报错却表现为数据为空 | 只判 `result` | S5 |

## 6. 下一步

→ 04 下载、断点与磁盘落盘

## 7　整体审核（功能点级收尾）

【审】`audit/godot/io-network.md#1`、`audit/godot/io-network.md#22`、`audit/godot/io-network.md#23`、`audit/godot/io-network.md#24`、`audit/godot/io-network.md#25`、`audit/godot/io-network.md#26`、`audit/godot/io-network.md#27`
