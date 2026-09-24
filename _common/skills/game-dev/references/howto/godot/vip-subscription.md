# Godot 4.x VIP / 订阅 / 累充

> **适用**：VIP 等级与权益、月卡/订阅、累充额度、礼包资格。
> **不适用**：单次内购与掉单（`monetization.md`）、货币与商店（`economy.md`）。
> ⚠ 本域的核心不是"能不能扣款成功"，而是 **"到期与等级算得对不对"**。

## 0. 先定性：这是时间问题，不是商店问题

⚠ **VIP 体系最容易错的地方不在支付，在时间。**

⛔ 常见起点错误：把 VIP 当成"买了一个商品"，
把到期判断写成"看本地时钟现在几点"——
ⓘ 于是玩家**改系统时间就能无限续期**，而服务端若也信了客户端时间，
就是可以直接提现的漏洞。

✅ 三条定性：

| 维度 | 定性 |
|---|---|
| 等级 | 由**累充额度**决定的**派生值**，不单独存 |
| 订阅 | 有**到期时刻**的持续状态，不是一次性标记 |
| 权益 | **一处定义、多处读取**的只读表，不散落在业务里 |

⚠ 与 `monetization.md` 的分工：
那篇讲**扣款与掉单**（钱有没有收到），
本篇讲**到账之后状态怎么算**（权益对不对）。

## 1. ⛔ 不能用本地系统时间算到期

⚠ **官方 `Time` 类 Important 原话：**

> *"The `_from_system` methods use the system clock that the user can manually
> set. **Never use** this method for precise time calculation since its results
> are subject to automatic adjustments by the user or the operating system.
> **Always use** `get_ticks_usec` or `get_ticks_msec` for precise time
> calculation instead, since they are guaranteed to be monotonic
> (i.e. never decrease)."*

⛔ 所以 `Time.get_unix_time_from_system()` **不能**作为到期的唯一判据——
它是**用户可改的系统时钟**。

✅ 三种时间源的分工（完整版见 `time-progression.md#1. 三种时间源，用错层级是万恶之源`）：

| 用途 | 用哪个 |
|---|---|
| **到期判定** | ⚠ **服务器时间**，本地只做展示 |
| 展示倒计时 | 服务器下发的时间戳 + `get_ticks_msec()` 推进 |
| 精确的本地计时 | `get_ticks_msec()`（单调递增） |

ⓘ `get_ticks_msec()` 是**引擎启动以来的毫秒数**，
⛔ 它不能告诉你"现在是几号"——所以**不能**用来存到期时刻。

⚠ 两者必须配合：存**服务器给的绝对时间戳**，本地用 `get_ticks_msec()` 插值推进显示，
⛔ 不要每帧去问系统时间。

## 2. ⚠ 时区与夏令时不会自动转换

⚠ **官方原话：*"Conversion methods assume 'the same timezone', and do not
handle timezone conversions or DST automatically."***

⛔ 后果：

- `get_datetime_dict_from_system()` **默认 `utc=false`**（本地时区）
- 而 `get_unix_time_from_datetime_dict()` 的官方 Note 写得很清楚：
  *"This method does not do any timezone conversion, so the timestamp will be
  in the same timezone as the given datetime dictionary."*

⚠ 所以"本地字典 → unix 时间戳 → 再转回字典"这个来回**本身是自洽的**，
但一旦**服务端用的是 UTC**，两边就差一个时区偏移——
表现为"玩家这里显示还剩 3 小时，服务器说已过期"。

✅ 判据：**所有跨端比较的时间戳统一用 UTC**，只在展示层转本地。

ⓘ 还有一个更隐蔽的点：`get_datetime_dict_from_unix_time()` 官方注明
**夏令时无法从纪元推断**（*"as it cannot be determined from the epoch"*），
⛔ 别指望从时间戳反推 DST。

## 3. ⛔ 空字典/缺键会静默落到 1970

⚠ **官方 `get_datetime_string_from_datetime_dict()` 说明：**

> *"If the dictionary is empty, 0 is returned. If some keys are omitted, they
> default to the equivalent values for the Unix epoch timestamp 0
> (1970-01-01 at 00:00:00)."*

⛔ 所以"构造一个时间字典再转时间戳"时，
少填一个字段**不会报错**，而是悄悄用 1970 年的默认值。

⚠ 症状：VIP 到期时间变成 `0` 或 1970 → **判定为早已过期**，
表现为"刚充完值，VIP 立刻没了"。

✅ 判据：转换后**必须校验时间戳落在合理区间**（比如 > 2020），
⛔ 不要信任转换结果。

ⓘ 同一家族的另一条：`get_datetime_dict_from_datetime_string()` 官方注明
*"Any decimal fraction in the time string will be ignored silently."* ——
带小数的字符串**静默丢掉小数部分**。

## 4. ⚠ `get_unix_time_from_system()` 返回的是 float

⚠ **官方 Note：*"Unlike other methods that use integer timestamps, this
method returns the timestamp as a float for sub-second precision."***

⛔ 与其他 `get_unix_time_from_*` 方法**返回类型不一致**：

| 方法 | 返回 |
|---|---|
| `get_unix_time_from_system()` | **float** |
| `get_unix_time_from_datetime_dict()` | int |
| `get_unix_time_from_datetime_string()` | int |

⛔ 存进 `int` 字段会**静默截断**亚秒；
而混用时若按 int 比较，边界上会出现"差 0.9 秒导致状态不同"。

ⓘ 官方同时注明：*"the `get_unix_time_from_system` method always returns the
time in UTC"*（2024 年专门提交澄清过这一点）。

## 5. 等级是派生值，⛔ 不单独存

⚠ **VIP 等级 = `f(累充额度)`，是派生的。**

⛔ 单独存等级 = 两份真相。
表现为"累充够了但等级没涨"，或"退款了等级还在"——
⛔ 而这类不一致**不会报错**，只在玩家投诉时暴露。

✅ 做法：只存 `total_recharge`，等级由阈值表算出。

⚠ **退款/扣回必须走同一条链**：
⛔ 只减 `total_recharge` 不重算等级 → 等级不变；
⛔ 只降等级不减额度 → 下次重算又升回去。

## 6. ⓘ 权益表要一处定义

⚠ **权益最常见的腐化方式是散落。**

⛔ `if vip_level >= 3: ...` 写在十几个地方 →
改一次权益要改十几处，⛔ 且必然漏。

✅ 做法：一张权益表（配置），业务只读。

⚠ 权益**取值而非判断**：
⛔ `is_vip()` 这种布尔判断会让"不同等级不同值"退化成一堆 if，
✅ 应该是 `get_benefit(key) -> value`。

## 7. ⚠ 到期的三种处理，选错就是事故

| 处理 | 后果 |
|---|---|
| 到期时**清掉权益** | 若数据是临时的，玩家**永久损失**已解锁内容 |
| 到期时**什么都不做** | 权益继续生效 = 白嫖 |
| ⛔ **到期时删除数据** | 续期后**历史等级丢失**，最严重 |

✅ 判据：到期只**改变生效状态**，⛔ 不删除任何累积数据。

ⓘ 与 `time-progression.md#8. 周期重置：硬边界，不是定时任务` 同源：
到期是**硬边界判定**，不是"到点执行的定时任务"。
⛔ 用定时任务实现 → 服务器重启/玩家离线就会漏执行。

## 8. ⚠ 订阅续期要处理"叠加"与"补时"

⚠ 玩家在**未到期时再次购买**，两种设计：

| 设计 | 语义 |
|---|---|
| 叠加 | `end = max(end, now) + duration` |
| 覆盖 | `end = now + duration` |

⛔ 不做 `max(end, now)` 直接加 → 续期反而**缩短**了剩余时间，
表现为"我续费了，剩余天数反而变少了"。

⚠ 还要处理**到期后补买**：此时 `now > end`，
⛔ 若用 `end + duration` 会把已过期的那段也算进去，
玩家得到"倒欠"的时间。

## 9. 待核对项（运行时验证）

> ⚠ 以下为本域**尚无统一法定数值/口径**的项，落地时必须实测确认。
> ⛔ 不要凭印象填数值——这些恰恰是各项目差异最大的地方。

- ⚠ 待核对：等级阈值与权益内容 · 验证：由策划给出配置表并进配置系统，**不硬编码**
- ⚠ 待核对：到期时刻用谁的时间 · 验证：确认服务端是唯一权威；本地改系统时间后**权益不应变化**
- ⚠ 待核对：跨时区玩家的到期展示 · 验证：改设备时区后，**剩余时间的秒数应一致**（只有显示格式变）
- ⚠ 待核对：续期是叠加还是覆盖 · 验证：按产品定，⛔ 未定就用 `max(end, now) + duration`
- ⚠ 待核对：退款是否扣回累充 · 验证：与支付渠道的退款回调对齐，⛔ 两侧口径必须一致
- ⚠ 待核对：本地缓存的权益多久刷新 · 验证：确认有失效路径；⛔ 缓存无失效 = 权益永久停在旧值

## 10. 相关文档

- 支付/掉单/抽卡 → `monetization.md`
- 货币与商店 → `economy.md`
- 三种时间源与周期重置 → `time-progression.md`
- 离线期间的状态变化 → `time-progression.md#4. 分段：离线期间的速率不能按"回来那一刻"倒推`
- 存档必须存什么 → `systems.md`
- 配置表（等级阈值应进配置）→ `datatable.md`
- 存档迁移与版本 → `save-migration.md`

## 11. 审核清单

> **反模式清单（不能怎么做，审核用）** → `audit/godot/vip-subscription.md`

## 全局块（跨功能通用）

> ⚠ 以下是**多个功能域共用**的全局内容，不在本域重复展开。
> 多对多索引见 `common/index.md`。

【读】 `common/howto/principles.md#GC-03`　数据与逻辑分离（等级阈值进配置，不硬编码）
【读】 `common/howto/principles.md#GC-05`　缓存必须有失效路径（本地缓存的权益要能刷新）
