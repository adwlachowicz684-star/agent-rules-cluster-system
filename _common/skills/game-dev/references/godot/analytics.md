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
        "client_ts": Time.get_datetime_string_from_system(true),
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
    return str(Time.get_unix_time_from_system()) + "_" + str(randi())

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

⚠ **退出时要保存未上报的队列**：
```gdscript
func _notification(what: int) -> void:
    if what == NOTIFICATION_WM_CLOSE_REQUEST:
        _save_cache()
```

⚠ **关键节点立即上报**（付费、通关），其余批量。

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

## 5. 常见坑

| # | 本能以为 | 实际 |
|---|---|---|
| 1 | 事件名随时能改 | 进生产后改 = 历史数据不可比 |
| 2 | 三层命名更清晰 | 会变成同义事件泛滥 |
| 3 | 用设备 ID 做玩家 ID | **合规风险**，必须可重置可匿名 |
| 4 | 每条事件发一个 HTTP | 要批量，否则卡顿又费电 |
| 5 | 断网就丢数据 | 要**本地缓存 + 重试** |
| 6 | 退出时不用管 | 未上报队列要持久化 |
| 7 | `HTTPRequest` 创建就能用 | 必须 `add_child` 进树 |
| 8 | 在 `_process` 里随手上报 | 高频事件会拖垮帧率，要节流 |
| 9 | 枚举用数字省空间 | 后续无法解读，用稳定字符串 |
| 10 | 记录中文显示名方便 | ID 改了就断，用数据表主键 |
| 11 | 通关率低就是太难 | 也可能是迷路/无聊，要结合时长 |
| 12 | 分析是上线前才做 | 事件模型要早期定，否则无法回溯 |

## 6. 相关文档

- 调试日志（另一回事）→ `debugging.md`
- 存档 → `security.md`
- 关卡设计 → `tilemap.md`
- CI/发布 → `cicd-publish.md`
