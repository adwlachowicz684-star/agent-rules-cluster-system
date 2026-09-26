# 游戏数据分析与埋点

注意区分：本文是**产品/运营向的数据分析**（玩家行为、留存、漏斗、难度调优），
不是调试日志（`debugging.md` 里那个"自定义埋点"是另一回事）。

## 0. 为什么需要（以及小团队该做到什么程度）

| 用途 | 解决什么 |
|---|---|
| **关卡难度调优** | 哪一关流失、哪一关卡住、死了几次 |
| **漏斗转化** | 新手引导每一步的流失 |
| **经济平衡** | 资源产出与消耗是否失衡 |
| A/B 测试 | 两个数值方案哪个留存高 |
| 崩溃上报 | 线上问题发现 |

⚠ **独立游戏也要吗？** 务实判断：
- 单人买断、无内购 → 至少做**关卡流失 + 崩溃**
- 有内购/长线运营 → 必须做完整漏斗
- 纯粹的个人作品 → 可以只做崩溃上报

⚠ 别一上来就做全套。先做"能回答一个具体问题"的最小集。

## 1. 事件模型：这是接口契约，不是自由文本

⚠ **事件命名一旦进生产，几乎无法无损重命名**。
同一个 `level_complete` 在一个版本表示过关、另一个版本表示通关动画开始，
后续数据就失去可比性。

**建议在仓库里维护一份 `events.yaml`**，与游戏版本一起审查。

### 命名规范（可直接抄）

1. 全部小写，只用 ASCII 字母、数字、下划线
2. 固定为 **`object_verb`**：`game_start`、`level_fail`、`currency_earn`
3. 动词从固定集合选：`start` `end` `complete` `fail` `earn` `spend`
   `acquire` `use` `enter` `exit` `watch` `purchase` `request` `result`
4. 参数用 `snake_case`
5. 枚举用稳定字符串（`reason="hp_zero"`），**不要用 1/2/3**
6. 资源 ID 用数据表主键，不要记中文显示名
7. 布尔事件拆成明确动作：`ad_watched` 比 `ad{status}` 好聚合
8. 废弃字段用 `deprecated_since`，**不要悄悄改含义**
9. 事件名不得包含玩家输入、URL、错误文本
10. 每次新增事件都要写"这个事件回答什么问题"

⚠ **不要用 `category_action_label` 三层命名**——
容易出现 `tutorial_action_step`、`tutorial_click_next`、`tutorial_progress` 并存。
需要第三层就放进参数：`tutorial_step{step_id="move_2"}`。

### 通用载荷（固定结构）

```json
{
  "event": "level_complete",
  "session_id": "01HZX...",
  "player_id": "anon_01HZX...",
  "client_ts": "2026-09-18T03:00:00Z",
  "event_id": "01HZX...",
  "app": { "version": "1.2.3", "engine_version": "4.7.2" },
  "device": { "platform": "Android", "locale": "zh-CN" },
  "params": { "level_id": "2-3", "duration_s": 87, "deaths": 1 }
}
```

- **`event_id` 是幂等键**：网络重试时服务端用它去重
- `client_ts` 必须 UTC，服务端另记 `server_ts`
- `session_id` 是一次连续前台运行，**不是跨设备永久 ID**

⚠ **`player_id` 不要用设备唯一标识**（IMEI/广告 ID）——
合规风险（GDPR / COPPA / 个人信息保护法）。
必须是可重置、可匿名化的自生成 ID 或账号。

### 常用事件清单

| 类别 | 事件 |
|---|---|
| 会话 | `game_start` `game_end` |
| 进度 | `level_start` `level_complete` `level_fail` |
| 经济 | `currency_earn` `currency_spend` `item_acquire` |
| 战斗 | `battle_start` `battle_end` `damage_dealt` |
| 引导 | `tutorial_step` `tutorial_complete` |
| 商业化 | `purchase` `ad_watched` |

### 1.4 ⛔ 事件时间与 ID 不能用系统时钟

⚠ 官方口径：`Time` 的 `_from_system` 系列用的是**用户可手动设置**的时钟，
明确要求"绝不要用于精确时间计算"，应改用单调的 `get_ticks_usec / get_ticks_msec`。

⛔ 用 `Time.get_unix_time_from_system()` 拼事件 ID、
或把 `Time.get_datetime_string_from_system()` 当 `client_ts`，
玩家改系统时间会造成两件事，且**都不报错**：

- **事件 ID 碰撞** → 服务端去重把真实数据**误判为重复而丢弃**
- **时间戳倒流** → 漏斗步骤乱序、留存算错，报表上看不出异常只觉得"数据变了"

⚠ 注意 `get_ticks_msec()` 是**引擎启动以来的毫秒数**，不是日期。
绝对时间仍须由服务端下发后与 ticks 插值对齐（`_wall_clock()` 即为此）。

### 1.5 ⚠ 同意前零采集（合规边界）

"同意"之前必须是**零采集**，不是"先采到本地、同意后再上报"。

⛔ 写成"先入队、同意后再 flush" —— 本地已经存了未同意期间的行为数据，
这本身就是采集，同意开关形同虚设（队列里已有数据，flush 与否只是时机问题）。

采集入口必须**唯一**且经过同意状态判断：
未同意时 `track()` 直接 return，队列长度恒为 0（这也是 07 的验收判据）。

ⓘ 崩溃上报与法律必要项另走策略，不计入"分析"开关。

## 2. 实现：离线优先

⚠ **游戏和 Web 不一样**：玩家会断网、会切后台、会强杀进程。
**没网时必须缓存到本地**，有网再批量上报——否则数据大量丢失。

```gdscript
# analytics.gd（Autoload）
extends Node

const BATCH_SIZE := 20
const FLUSH_INTERVAL := 30.0
const CACHE_PATH := "user://analytics_cache.json"

var _queue: Array = []
var _session_id := ""
var _player_id := ""
var _http: HTTPRequest
var _timer := 0.0

func _ready() -> void:
    _http = HTTPRequest.new()
    add_child(_http)                    # ⚠ 不 add_child 就不能发请求
    # ⛔ timeout 默认 0.0 = 永不超时；服务端不响应会让 flush 永久停摆
    _http.timeout = HTTP_TIMEOUT_SEC
    _http.request_completed.connect(_on_response)
    _session_id = _new_id()
    _player_id = _load_or_create_player_id()
    _load_cache()

func track(event: String, params := {}) -> void:
    _queue.append({
        "event": event,
        "event_id": _new_id(),
        "session_id": _session_id,
        "player_id": _player_id,
        # ⛔ 系统时钟可被玩家设置；绝对时间须由服务端校时后与 ticks 对齐
        "client_ts_monotonic": Time.get_ticks_msec(),
        "client_ts": _wall_clock(),      # 服务端校时后的绝对时间
        "app": { "version": ProjectSettings.get_setting("application/config/version", "") },
        "params": params,
    })
    if _queue.size() >= BATCH_SIZE:
        flush()

func _process(delta: float) -> void:
    _timer += delta
    if _timer >= FLUSH_INTERVAL:
        _timer = 0.0
        flush()

func flush() -> void:
    if _queue.is_empty() or _http.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
        return
    var body := JSON.stringify({"events": _queue})
    var err = _http.request(ENDPOINT, ["Content-Type: application/json"],
                            HTTPClient.METHOD_POST, body)
    if err != OK:
        _save_cache()

func _on_response(_result, response_code, _headers, _body) -> void:
    if response_code == 200:
        _queue.clear()
        _save_cache()
    # 失败就留着队列，下次重试

func _save_cache() -> void:
    var f := FileAccess.open(CACHE_PATH, FileAccess.WRITE)
    if f:
        f.store_string(JSON.stringify(_queue))
        f.close()

func _load_cache() -> void:
    if not FileAccess.file_exists(CACHE_PATH):
        return
    var f := FileAccess.open(CACHE_PATH, FileAccess.READ)
    if f:
        _queue = JSON.parse_string(f.get_as_text()) or []
        f.close()

func _new_id() -> String:
    # ⛔ 不要用 Time.get_unix_time_from_system()：玩家改系统时间会造成 ID 碰撞
    return str(Time.get_ticks_usec()) + "_" + str(randi())

func _load_or_create_player_id() -> String:
    const P := "user://player_id"
    if FileAccess.file_exists(P):
        var f := FileAccess.open(P, FileAccess.READ)
        var v = f.get_as_text(); f.close(); return v
    var id := "anon_" + _new_id()
    var f2 := FileAccess.open(P, FileAccess.WRITE)
    f2.store_string(id); f2.close()
    return id
```

⚠ **退出时要保存未上报的队列** —— ⛔ 但下面这个常见写法是错的，见 `2.1`：
```gdscript
func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_CLOSE_REQUEST:      # ⛔ 只覆盖桌面；安卓收不到
        _save_cache()                              # ⛔ quit() 退出时根本不触发
```

⚠ **关键节点立即上报**（付费、通关），其余批量。

### 2.1 ⛔ 退出通知的三条官方语义（退出保存）

官方"Handling quit requests"明确了三条，⛔ 任何一条不知道都会导致"数据丢了但不报错"：

**① `SceneTree.quit()` 不发送退出通知。**
官方原话：调用 `quit()` **不会**发送 `NOTIFICATION_WM_CLOSE_REQUEST`，
且"不会让自定义动作完成（如保存）"，
⛔ **即使你尝试延迟那行强制退出的代码也不行**。
所以游戏里"退出游戏"按钮调 `get_tree().quit()` 时，
监听 `_notification` 的保存**一次都不会执行**——而这是玩家最常用的退出方式。

**② 安卓发的是 `NOTIFICATION_WM_GO_BACK_REQUEST`。**
桌面与 Web 发 `NOTIFICATION_WM_CLOSE_REQUEST`；⛔ **安卓发的是 GO_BACK**，
且 iOS **不支持**该通知（无物理返回键）。只监听前者，安卓上保存零触发。

**③ 4.x 中通知不会终止程序（与 3.x 不同）。**
要接管完整退出流程必须先 `get_tree().set_auto_accept_quit(false)`，
退出前自己 `get_tree().root.propagate_notification(NOTIFICATION_WM_CLOSE_REQUEST)`，
⛔ 之后**还要再调** `SceneTree.quit()`，否则"点了退出关不掉"。

```gdscript
func _ready() -> void:
    get_tree().set_auto_accept_quit(false)      # ⛔ 不接管则 Godot 直接退出

func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_CLOSE_REQUEST or what == NOTIFICATION_WM_GO_BACK_REQUEST:
        _save_cache()
        get_tree().quit()                       # ⛔ 4.x 必须自己调

func quit_game() -> void:                       # 游戏内"退出游戏"按钮
    get_tree().root.propagate_notification(NOTIFICATION_WM_CLOSE_REQUEST)  # ⛔ quit() 不发
```

### 2.2 ⚠ HTTPRequest 的两条官方语义（超时与并发）

**① `timeout` 默认 `0.0`，含义是"永不超时"。**
官方建议 REST 这类小请求设成与服务端响应匹配的秒数（常见 1.0–10.0）。
⛔ 留 `0.0` 且又用 `get_http_client_status() != STATUS_DISCONNECTED` 作守卫 ——
服务端不响应时状态永远不是 `DISCONNECTED`，flush 永远直接 return，
⛔ **队列无限增长、缓存越写越大，且不报错**（两个"默认值"叠加出的故障）。

**② 必须 `add_child`，且单实例不并发。**
不 `add_child` 发不出请求；⛔ 单个 `HTTPRequest` 发起并发请求时后一个会取消前一个，
表现为"数据丢一半"且不报错。需要并发就为每个请求建独立实例（用完 `queue_free`）。

## 3. 后端方案

**Godot 4 没有内置分析系统**（明确）。选项：

| 类型 | 方案 | 状态 |
|---|---|---|
| 开源自建 | PostHog、Umami、Matomo、Countly | 有 HTTP API，需自己封装 |
| 商业 | GameAnalytics 等 | 需确认插件维护状态 |
| 自建后端 | 自己写接收端 | 可控但要维护 |

⚠ 第三方 SDK/插件的**维护状态和 Godot 版本兼容性必须现查**，
这类插件断更很常见。

⚠ **合规**：隐私政策要写明收集什么、玩家要能关闭非必要分析。
崩溃/法律必要项另走策略。

## 4. 关卡难度调优（怎么把数据用起来）

- **关卡流失曲线**：每一步流失多少，陡降就是卡点
- **死亡点热力图**：哪里死最多
- **区分"太难"和"太无聊"**：
  死亡次数高 + 反复重试 = 太难；
  停留时间长 + 无死亡 = 可能迷路或无聊
- **远程配置**：难度参数放服务器，不用更新包就能调数值

⚠ 光看"通关率"不够 —— 要结合**时长分布**和**重试次数**。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/analytics.md`


### 4.1 远程配置与闭环

可调数值放在服务端，客户端启动时拉取（取不到时用内置默认兜底）。
⛔ 每次调参都要发版 —— 反馈周期长到无法做 A/B，也就谈不上"用数据调优"。

⛔ 只改不留痕 —— 数据变化了却不知道是哪个改动引起的，
下次只能凭印象重试一遍，"调优"退化成反复试。

所以每次变更都要记录：**参数名 / 旧值 / 新值 / 生效时间**，
这样任意一天的数据波动都能查到当天生效的参数变更。

## 5. 相关文档

- 调试日志（另一回事）→ `debugging.md`
- 存档 → `security.md`
- 关卡设计 → `tilemap.md`
- CI/发布 → `cicd-publish.md`

## 6. 流程：按什么顺序做

> ⛔ 本节只给入口，"按什么顺序做"的完整流程在
> `flow/godot/analytics/00-域流程总览.md`（7 个功能点 / 37 个 Step）。

| 要做的事 | 走哪个功能点 |
|---|---|
| 定事件命名与字典 | `flow/godot/analytics/01-埋点契约与事件字典.md` |
| player_id 与同意开关 | `flow/godot/analytics/02-身份会话与合规边界.md` |
| 队列、持久化、退出保存 | `flow/godot/analytics/03-采集与离线缓存.md` |
| 批量、幂等、重试、超时 | `flow/godot/analytics/04-上报通道与失败重试.md` |
| 付费 / 通关等关键事件 | `flow/godot/analytics/05-关键事件与漏斗定义.md` |
| 流失曲线与调参闭环 | `flow/godot/analytics/06-数据消费与反哺调优.md` |
| 敌意环境验收 | `flow/godot/analytics/07-分析验收.md` |
