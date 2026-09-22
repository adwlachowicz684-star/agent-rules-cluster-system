# Godot 4.x 存档加密与防作弊

## 0. 先说清楚边界（最重要的一节）

**客户端加密不能防作弊。**

原因是结构性的，不是实现得不好：

```
密钥必须在客户端（否则游戏解不开自己的存档）
  ↓
玩家拥有客户端的完整访问权
  ↓
密钥一定能被拿到
```

所以唯一诚实的结论是：

| 能防 | 防不住 |
|---|---|
| 用记事本/十六进制编辑器直接改存档 | 会解包 PCK 的人 |
| 随手搜内存改数值（Cheat Engine 基础用法） | 定向逆向的人 |
| 改系统时间 | 速度倍率工具（需额外检测） |

**如果防作弊对你很重要，唯一可靠的方案是服务端权威** —— 见第 6 节。
本章剩下内容的目标是**提高修改成本**，保护那些本来不打算作弊的玩家的体验。

## 请求签名：防篡改与重放，不能证明诚实

⚠ **客户端密钥必然泄露** —— 签名层只提供完整性、绑定和难度，**不提供真实性**。
把"有签名"当成"服务端可以信任数值"是本主题最大的误判。

**规范化串**（前后端共同定义，Godot 不替你定）：

```
method + "\n" + path + "\n" + body_sha256 + "\n" + timestamp + "\n" + nonce + "\n" + app_version
```

```gdscript
const ALGO := HashingContext.HASH_SHA256

func _sign_request(method, path, body, ts_ms, nonce, hmac_key) -> String:
    var ctx := HashingContext.new()
    ctx.start(ALGO); ctx.update(body.to_utf8_buffer())
    var body_digest := ctx.finish()
    var canonical := "%s\n%s\n%s\n%d\n%s\n%s" % [
        method, path, body_digest.hex_encode(), ts_ms, nonce.hex_encode(), _client_version]
    return Crypto.new().hmac_digest(ALGO, hmac_key, canonical.to_utf8_buffer()).hex_encode()
```

⚠ **`hmac_digest()` 当前仅支持 `HASH_SHA1` 和 `HASH_SHA256`**。
⚠ **HMAC 密钥必须是服务端按会话颁发的随机 32 字节密钥** —— 绝不用客户端共享的固定字符串。
⚠ `nonce` 至少 16 字节且不可重复；body 先 SHA-256 再进规范串（避免大 body 与编码歧义）。
⚠ 比较用 `constant_time_compare()`，避免时序泄漏。

**重放窗口要同时校验时钟偏移**：服务端维护 `(client_id, nonce)` 短期集合（TTL 5–10 分钟），且要求 `|now - ts| <= 300s`。

| 反模式 | 症状 |
|---|---|
| nonce 只按时间生成 | 相邻请求**碰撞** |
| 只用内存去重 | 重启后**可重放** |
| 集群无共享状态 | 多副本**重复执行** |

**签名能防**：未装游戏的中间人手动改 JSON、提高脚本批量构造成本、帮助定位重放与异常设备。
**防不了**：自制客户端、内存改值、按键宏、拥有合法账号的玩家作弊。

### TLS 能力边界

`StreamPeerTLS.connect_to_stream(stream, common_name, client_options)`，状态含 `ERROR_HOSTNAME_MISMATCH`。
`PacketPeerDTLS.connect_to_peer()` + `TLSOptions.client(trusted_chain, common_name_override)` / `server(key, certificate)`。

⚠ **官方警告 DTLS 不支持证书吊销与证书钉扎** → 用短期自动管理证书。
⚠ Android 必须开 INTERNET 权限。
⚠ Web 导出走浏览器/WebSocket 安全，**不能套用原生 TCP/TLS**。

## 反外挂分层：客户端是传感器，服务端是唯一裁判

⚠ **ROI 按"作弊经济成本"排序**：
① **服务端权威 + 输入校验**（同时解决加速、瞬移、伤害、资源、冷却、交易）
② 客户端轻量检测与遥测 ③ 登录风控/设备风险/支付反欺诈 ④ 内核/驱动级对抗

⚠ 小团队把预算投"客户端反修改"却不做服务端校验，只把开挂门槛从 5 分钟提到 30 分钟。

### 加速检测必须用单调时钟

⚠ **系统时间能被改表，`Time.get_ticks_msec()` 不能。**

```gdscript
func observe_client_logic_time(reported_logic_ms: int, max_speed: float) -> bool:
    var dt_ms := Time.get_ticks_msec() - _base_ticks_ms
    var allowed := (_base_logic_ms + dt_ms) * max_speed
    return reported_logic_ms > allowed
```

### 客户端检测只是信号

- **内存校验**：`checksum = value ^ position_seed`，每帧或提交前检查
- ⚠ 反模式：客户端发现校验失败后**自己封禁自己** → 攻击者直接 NOP 掉检测函数。
  正确：服务端收集信号、按阈值累积风险分、限制匹配/交易，运营人工封禁
- **多开检测**：锁文件、进程互斥、命名管道 → 可被 sandbox/虚拟机/改名绕过
- **调试器检测**：放独立协程、结果抖动上报；⚠ 别写固定 `if debugger_attached: exit()`（会被搜字符串定位）

⚠ **合法用户开两个窗口不该封号**，只应禁止同账号进同一排位局。

### 服务端有效性来自可证伪规则

每次高价值动作校验：身份与 session 有效 → 角色/物品归属 → 位置可达、速度不超上限 → CD 未结束 →
资源足够 → 频率未超滑动窗口 → 数值变化符合状态机 → **重复请求用业务幂等键**。

⚠ **服务端维护最近 N 秒的权威时间戳，不接受客户端"动作发生时间"作为事实**；客户端时间戳只用于表现层插值。

## 1. 存档加密

### 内置 API

```gdscript
FileAccess.open_encrypted(path, mode_flags, key: PackedByteArray)
FileAccess.open_encrypted_with_pass(path, mode_flags, pass: String)
```

两者都返回 `FileAccess`，之后用法与普通文件一致（`store_var` / `get_var` / `store_string` …）。

⚠ **是 AES-256-CBC 不是 ECB**，但有两个必须知道的坑：

**坑一：不传 IV = 用空 IV。** 相同密钥 + 相同（空）IV 时，
相同明文开头会产生**相同密文开头**。多个存档的前缀会一模一样，
攻击者不用解出密钥就能推断结构。

**坑二：没有认证（authentication）。** CBC 可被比特翻转攻击 ——
翻转密文某一位，解密后明文的对应位也翻转，**而且解密不会报错**。
攻击者不改密钥就能把金币字段的某位从 0 翻成 1。

**结论：加密 ≠ 防篡改。必须再加 HMAC**（第 2 节）。

⚠ `open_encrypted` 和 `open_compressed` **不能链式调用**。
要先 `Compression.compress()` 得到字节数组，再加密写入。
顺序必须是**先压缩后加密** —— 反过来压缩率接近零。

### 密钥放哪

```gdscript
# 反例：明文硬编码 —— PCK 能被解包，等于没加密
const KEY := "my_secret_key_123"
```

⚠ 脚本里的字符串常量在 PCK 解包后是可读的（GDScript 导出的 `.gdc`
能被 `gdsdecomp` 还原成接近源码的形式）。

**务实做法**：主密钥分成几段、藏在不同地方、启动时拼接 ——
提高的是"找到它"的成本，不是"能不能找到"。

```gdscript
# security_keys.gd
# 分散存储，启动时拼接。防的是搜索与随手查看，不是定向逆向。
const _A := "7f3a"
const _B := "c91e"
var _C: String      # 从资源文件读
var _D: String      # 从项目设置的某个不起眼字段读

func _ready() -> void:
    _C = (load("res://data/cfg.tres") as ConfigData).blob
    _D = ProjectSettings.get_setting("application/config/version_suffix", "")

    MASTER_KEY = (_A + _B + _C + _D).sha256_text()
```

**真正要防定向攻击**：核心算法与密钥放 GDExtension（C++）里，
编译成二进制库。这是唯一有意义的提升，代价是要维护原生模块。

### 完整实现：加密 + 压缩 + 每文件随机 IV

```gdscript
# secure_save.gd —— Autoload，名 SecureSave
extends Node

const MAGIC := "GSAVE"
const VERSION := 1
const IV_SIZE := 16
const HMAC_SIZE := 32          # SHA-256

var _key := PackedByteArray()
var _hmac_key := PackedByteArray()

func _ready() -> void:
    var master := _derive_master()
    # 从主密钥派生两个子密钥：一个加密、一个签名，不复用
    _key = _derive(master, "enc")
    _hmac_key = _derive(master, "mac")

func _derive_master() -> PackedByteArray:
    # 见上面"密钥放哪"，返回 32 字节主密钥
    return _load_master_hex().hex_decode()

func _derive(master: PackedByteArray, purpose: String) -> PackedByteArray:
    var ctx := HashingContext.new()
    ctx.start(HashingContext.HASH_SHA256)
    ctx.update(master)
    ctx.update(purpose.to_utf8_buffer())
    return ctx.finish()

## 写入：[magic][version][IV][密文][HMAC]
func save(path: String, data: Dictionary) -> bool:
    var json := JSON.stringify(data).to_utf8_buffer()
    var compressed := Compression.compress(json, Compression.COMPRESSION_ZSTD)

    # 每次存都换 IV —— 不复用是关键
    var iv := _random_bytes(IV_SIZE)
    var cipher := _encrypt(compressed, iv)
    if cipher.is_empty():
        return false
    var payload := iv + cipher

    var mac := _hmac(payload)
    var f := FileAccess.open(path, FileAccess.WRITE)
    if f == null:
        push_error("存档写入失败: %d" % FileAccess.get_open_error())
        return false
    f.store_pascal_string(MAGIC)
    f.store_32(VERSION)
    f.store_buffer(payload)
    f.store_buffer(mac)
    f.close()
    return true

## 读取：先验签，再解密
func load(path: String) -> Dictionary:
    if not FileAccess.file_exists(path):
        return {}
    var f := FileAccess.open(path, FileAccess.READ)
    if f == null:
        return {}
    if f.get_pascal_string() != MAGIC:
        f.close(); return {}
    if f.get_32() != VERSION:
        f.close(); return {}

    var payload := f.get_buffer(f.get_length() - f.get_position() - HMAC_SIZE)
    var mac := f.get_buffer(HMAC_SIZE)
    f.close()

    # 顺序很重要：先验签，签不对就别解密
    if not _verify(payload, mac):
        _on_tampered()
        return {}
    var iv := payload.slice(0, IV_SIZE)
    var cipher := payload.slice(IV_SIZE)
    var plain := _decrypt(cipher, iv)
    if plain.is_empty():
        return {}
    var json := JSON.new()
    if json.parse(Compression.decompress(plain,
            Compression.COMPRESSION_ZSTD).get_string_from_utf8()) != OK:
        return {}
    return json.data as Dictionary

func _random_bytes(n: int) -> PackedByteArray:
    var out := PackedByteArray()
    out.resize(n)
    for i in n:
        out[i] = randi() % 256
    return out

func _hmac(data: PackedByteArray) -> PackedByteArray:
    return Crypto.new().hmac_digest(HashingContext.HASH_SHA256, _hmac_key, data)

func _verify(data: PackedByteArray, mac: PackedByteArray) -> bool:
    return Crypto.new().constant_time_compare(_hmac(data), mac)
    # constant_time_compare 防时序侧信道，别用 ==

func _encrypt(data: PackedByteArray, iv: PackedByteArray) -> PackedByteArray:
    # Godot 4.x 没暴露内存级 AES API，用临时文件中转
    var tmp := "user://.tmp_enc"
    var f := FileAccess.open_encrypted(tmp, FileAccess.WRITE, _key)
    if f == null:
        return PackedByteArray()
    f.store_buffer(data)
    f.close()
    var out := FileAccess.get_file_as_bytes(tmp)
    DirAccess.remove_absolute(ProjectSettings.globalize_path(tmp))
    return out

func _decrypt(data: PackedByteArray, iv: PackedByteArray) -> PackedByteArray:
    var tmp := "user://.tmp_dec"
    var f := FileAccess.open(tmp, FileAccess.WRITE)
    if f == null:
        return PackedByteArray()
    f.store_buffer(data)
    f.close()
    var g := FileAccess.open_encrypted(tmp, FileAccess.READ, _key)
    if g == null:
        DirAccess.remove_absolute(ProjectSettings.globalize_path(tmp))
        return PackedByteArray()
    var out := g.get_buffer(g.get_length())
    g.close()
    DirAccess.remove_absolute(ProjectSettings.globalize_path(tmp))
    return out

func _on_tampered() -> void:
    push_warning("存档校验失败，可能被篡改")
    # 见第 5 节：怎么反应比检测更重要
```

⚠ `_encrypt` / `_decrypt` 用临时文件中转，因为 Godot 4.x 没有
内存级 AES API。生产项目如果需要性能，用 GDExtension 调 mbedtls。

⚠ 验签**必须**在解密之前。顺序反了，等于把攻击者构造的数据喂给解密器。

⚠ 用 `constant_time_compare` 而不是 `==` 比对 HMAC ——
`==` 的提前退出会泄露"前几个字节对了"的信息（时序侧信道）。

## 2. 单纯的轻量方案：只签名不加密

很多游戏其实**不需要加密**，只需要"改了能发现"：

```gdscript
func save_signed(path: String, data: Dictionary) -> bool:
    var json := JSON.stringify(data)
    var mac := _hmac(json.to_utf8_buffer())
    var f := FileAccess.open(path, FileAccess.WRITE)
    if f == null:
        return false
    f.store_pascal_string(json)
    f.store_buffer(mac)
    f.close()
    return true

func load_signed(path: String) -> Dictionary:
    var f := FileAccess.open(path, FileAccess.READ)
    if f == null:
        return {}
    var json := f.get_pascal_string()
    var mac := f.get_buffer(f.get_length() - f.get_position())
    f.close()
    if not _verify(json.to_utf8_buffer(), mac):
        _on_tampered()
        return {}
    var p := JSON.new()
    if p.parse(json) != OK:
        return {}
    return p.data as Dictionary
```

**为什么这个更实用**：存档内容（关卡进度、装备）通常不是机密，
真正需要的是"别让人随手续命/加金币"。签名就够了，还省掉加密的性能开销。

## 3. 内存值保护

Cheat Engine 的基础用法是"搜 100 → 受伤 → 搜 80 → 定位地址 → 改成 9999"。
让它搜不到的方法是**内存里不存明文**。

```gdscript
class_name ProtectedInt

var _mask: int
var _stored: int          # 实际是 value ^ mask

func _init(value: int = 0) -> void:
    _mask = (randi() | 0x100000)      # 确保非零
    _stored = value ^ _mask

func get_value() -> int:
    return _stored ^ _mask

func set_value(v: int) -> void:
    _mask = _rotate(_mask, 13) ^ 0x9E3779B9    # 每次写入都换掩码
    _stored = v ^ _mask

func add(d: int) -> void:
    set_value(get_value() + d)

## 合理性自检：超出范围说明被改了
func is_plausible(min_v: int, max_v: int) -> bool:
    var v := get_value()
    return v >= min_v and v <= max_v

func _rotate(x: int, n: int) -> int:
    return (x << n) | (x >>> (32 - n))
```

**用法**：

```gdscript
var _gold := ProtectedInt.new(0)
var _hp := ProtectedInt.new(100)

func add_gold(n: int) -> void:
    _gold.add(n)

func _process(_delta: float) -> void:
    # 定期自检（不要每帧，隔几秒一次即可）
    if not _gold.is_plausible(0, 9999999):
        Security.on_tampered("gold")
```

⚠ **防不住"重复搜索 + 变化锁定"**，也防不住找到掩码的人。
它挡的是最基础的"搜固定值"用法，这就够挡掉大部分随手作弊。

⚠ 别把所有数值都保护起来 —— 开销和复杂度都会涨。
只保护**有经济意义的**（金币、钻石、体力）。

## 4. 时间作弊

```gdscript
# 反例：读系统时间，玩家改系统时钟就绕过
var now := Time.get_unix_time_from_system()

# 正例：monotonic 计时，基于引擎运行时间，不受系统时钟影响
var elapsed := Time.get_ticks_msec()
```

⚠ `Time.get_ticks_msec()` 只保证**单次引擎运行期间**单调。
跨会话（"每日奖励"）它需要配合：

```gdscript
func is_daily_ready() -> bool:
    var now_mono := Time.get_ticks_msec() / 1000.0
    # 用累计游玩时长判定，而不是墙钟时间
    return now_mono - _last_claim_mono >= 86400.0
```

**真正防每日奖励作弊**只能靠服务端下发的服务器时间。
客户端方案（哪怕用 monotonic）玩家改不了时钟，但可以：
改存档里的 `_last_claim_mono` —— 所以这个字段也要进签名范围。

```gdscript
# 放在签名数据里，改了就验签失败
data["last_claim_mono"] = _last_claim_mono
```

### 倍速作弊

```gdscript
var _last_tick := 0

func _process(_delta: float) -> void:
    var now := Time.get_ticks_msec()
    if _last_tick > 0:
        var real_delta := now - _last_tick
        # 加速工具会让 delta 异常小或异常规律
        if real_delta < 4:            # 快过 250fps，不正常
            _suspicious_count += 1
            if _suspicious_count > 60:
                Security.on_tampered("speed")
    _last_tick = now
```

⚠ 别用这个直接踢玩家 —— 高刷屏（240Hz）也会触发。
只作为"可疑"标记，累计很多次才处理，或者只上报不处理。

## 5. 检测到之后怎么办

**这一步比检测本身更容易做错。**

```gdscript
# security.gd —— Autoload
extends Node

signal tamper_detected(kind: String)

func on_tampered(kind: String) -> void:
    push_warning("检测到异常: %s" % kind)
    tamper_detected.emit(kind)
    # 关键决策：怎么处理
```

| 做法 | 评价 |
|---|---|
| **崩溃 / 直接退出** | ❌ 最糟。等于告诉修改者"你找到了关键检查点"，他会把它 nop 掉 |
| **弹窗警告** | ❌ 同样暴露检查点位置 |
| **静默标记 + 不进排行榜** | ✅ 推荐。修改者不知道自己被发现了 |
| **静默回滚到合法值** | ✅ 推荐。让他白改 |
| **异步上报服务端** | ✅ 联网游戏必备。服务端做风控决策 |
| **进"作弊者匹配池"** | ✅ 联网游戏。只和同类匹配，不破坏正常玩家体验 |

**核心原则**：检测到之后**不要给攻击者反馈**。
任何可观测的反应都是在帮他定位检查代码。

## 6. 联网游戏：唯一可靠的方案

如果游戏有排行榜、交易、竞技匹配 —— **那些逻辑必须在服务端**。

```
客户端：只发"我做了什么"（输入、请求）
服务端：校验合法性 → 计算结果 → 下发
客户端：只负责显示
```

**必须服务端做的**：

| 场景 | 为什么 |
|---|---|
| 排行榜提交 | 客户端提交的是"数字"，服务端不知道它怎么来的 |
| 货币变动 | 客户端说"我扣了100加了装备"—— 凭什么信 |
| 胜负判定 | 客户端说"我赢了" |
| 每日奖励 | 客户端时钟不可信 |

**客户端能帮忙的**（只是帮忙，不是防线）：

- 尽早拦掉明显异常（数值超上限、时间戳倒流）
- 上报异常行为给服务端做风控
- 减少作弊收益（作弊者匹配池）

⚠ **HMAC 不能替代服务端校验**。HMAC 只证明"是同一个客户端发的"，
证明不了"客户端没被篡改"。

⚠ **别信客户端时钟**。服务端用自己的。

## 7. PCK 加密

导出预设 → Encryption → 设置 256-bit 密钥。加密脚本和资源。

**能防**：批量盗取素材、随手查看脚本内容。
**防不住**：下定决心的人 —— 密钥在二进制里，能被提取。

⚠ 官方没有"PCK 加密是安全的"这种说法。它的定位是**提高门槛**。

⚠ 需要真正安全只能自定义编译 Godot（改源码里的密钥常量），
但维护成本很高，一般不建议。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/security.md`

