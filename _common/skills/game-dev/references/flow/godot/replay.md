# 回放 / 录像与确定性系统（Godot 4.7.2）

"录像" 此前 0 命中；"回放"只在网络回滚预测里顺带提过，没有独立体系。
大型项目用它做三类事：**调试复现、精彩回放、防作弊校验**。

## 0. 先回答"录什么"，不是先找保存函数

⚠ **Godot 4.7.2 没有内置一站式 Demo 系统** ——
它提供的是固定时间步、物理、输入映射、MovieMaker 等**底层原语**，回放体系要自己组装。

| 路线 | 录什么 | 体积 | 确定性要求 | 适合 |
|---|---|---|---|---|
| **输入 + 确定性重放** | 每固定 tick 的动作状态、种子、版本 | **极小** | **极高** | 调试复现、校验、输入回滚 |
| **状态快照** | 关键实体位置/旋转/动画时间 | 中到大 | 不需要 | 幽灵车、精彩回放、观战 |
| **MovieMaker 离线渲染** | 画面帧和音频 | 视频体积 | 仅本次渲染可重复 | 预告片、过场、画质对比 |

## 1. ⚠ 最关键的一条：Godot 物理不保证确定性

**官方结论：Godot 物理无论使用哪种物理引擎，都不保证确定性。**

因此严格意义的输入重放，在涉及刚体时必须把模拟限定在：
同一 Godot 版本 · 同一精度构建 · 同一物理后端 · 受控数据

⚠ **要把"单机固定步可复现"与"跨平台逐比特一致"分开承诺** ——
它们是两个不同的保证级别，别说成同一个。

## 2. 破坏确定性的常见来源

- ⚠ **浮点**在不同平台/编译器下可能不一致
- ⚠ **遍历顺序**（Dictionary 顺序、节点顺序）
- ⚠ **`rand()` 未用固定种子**
- ⚠ **依赖真实时间** —— `delta` 必须来自固定步长，不能用墙钟
- ⚠ **物理引擎的确定性边界**（见上）

**固定时间步（fixed timestep）是确定性的前提。**

⚠ **要有验证确定性的自检方法** —— 跑两遍比对结果哈希，
而不是"看起来一样"就认为确定性成立。

## 3. 输入录制：记录的是动作状态，不是按键流

⚠ **输入录制记录的是固定物理 tick 的动作状态，不是原始按键事件流。**
⚠ **回放必须在同一 tick 率下按固定步推进** —— 帧率不同会直接跑偏。

## 3.1 固定时间步：tick 是输入的横坐标

⚠ 官方明确区分物理 tick 与渲染帧：`_process()` 频率随硬件和优化变化，
同一物理逻辑在不同 tick 率下也会改变响应、碰撞与轨迹。
⛔ 逻辑层不能把 `delta` 当输入时间、把 `_process` 调用次数当帧数。

```gdscript
const STEP_MS := 1000 / 60.0
var accumulator_ms := 0.0
var sim_tick := 0

func _physics_process(delta: float) -> void:
    accumulator_ms += delta * 1000.0
    while accumulator_ms >= STEP_MS:
        accumulator_ms -= STEP_MS
        sim_tick += 1
        input_port.begin_tick(sim_tick)
        simulation.step(STEP_MS)
        event_sink.flush(sim_tick)
```

⚠ 录制键按 `(sim_tick, actor, intent)` 存储；回放时即使某帧晚到，
也把输入**安排到目标 tick**，⛔ 不能"现在读到就立即生效"。
⚠ 回放要把真实时间**放大**，⛔ 不能改变模拟步长。

## 3.2 ⚠ 五个确定性杀手（必须逐项关掉）

**① 浮点不保证位一致** —— 跨编译器、优化、CPU 扩展精度、数学库、线程调度都会改变结果。
核心规则用整数或定点；⛔ 禁止 fast math / FMA 等破坏承诺的优化。

**② 所有参与结果的随机必须来自独立 seeded RNG。**
⚠ 官方明确 `RandomNumberGenerator` 底层算法是**实现细节**，不能依赖跨 Godot 版本复现；
需要长期稳定时自实现已知算法或锁死算法与版本。

```gdscript
class_name RngBank
var combat: RandomNumberGenerator
var spawn: RandomNumberGenerator
var cosmetic: RandomNumberGenerator   # 表现层可本地实时随机，不参与结果

func snapshot() -> Dictionary: return {"combat": combat.state, "spawn": spawn.state}
func restore(state: Dictionary) -> void:
    combat.state = state["combat"]
    spawn.state = state["spawn"]
```

**③ 遍历顺序必须显式。** ⚠ 官方警告：**迭代字典时删除元素会产生不可预测行为**。
行动顺序要用 actor ID + 阵营优先级 + 稳定副键构成**全序**，
⛔ 不能依赖 `Dictionary`、节点创建顺序、内存地址或场景树顺序。

```gdscript
# ⛔ 错误：顺序依赖字典迭代，删除期间还修改
for key in buffs:
    if buffs[key].expired: buffs.erase(key)

# ✅ 正确：稳定顺序 + 安全删除
var expired := []
for key in buffs.keys():
    if buffs[key].expired: expired.append(key)
for key in expired: buffs.erase(key)
```

**④ 时间源必须统一** —— 只能从 `sim_tick` 和固定 STEP 推出，
⛔ 不用 `OS.get_ticks_msec()`、`Time.get_unix_time_from_system()`、`_process(delta)`、
动画完成时间或音频时钟决定命中、Buff 结束、技能释放。

**⑤ 外部输入必须队列化** —— 网络包、服务端命令、文件加载完成、信号回调、线程结果、UI 事件
⛔ 不得直接改写模拟状态，要转换成**带目标 tick 的命令**。
（网络抖动会让同一命令在不同机器不同 tick 到达，从而破坏回放。）

## 3.3 跳转、校验和与存储分层

⚠ **跳转要从最近检查点快照恢复**，⛔ 不能把当前渲染节点位置写回模拟器：
先定位快照 → 恢复 seed/state 与已确认输入前缀 → 从该 tick 重新推进。

⚠ **输入录制的校验和是反作弊与调试双重工具：**
对每个 tick 或检查点算 `HMAC-SHA256(master_key, tick || sorted_entity_state || sorted_event_state)`。
⚠ 不匹配**不必然证明作弊**，但证明确定性已破坏或文件被改动 → 拒绝竞技提交并记录证据。

⚠ 存储分层：默认只存 `version + seed + compressed intents`；
每 K tick 存一份轻量快照；每 N tick 存一次结构化事件供拖拽。
⚠ 若允许分享，要提供"匿名化"模式，移除账号、好友、精确输入时间。

## 3.4 ⚠ 跨版本不兼容是产品约束，不是实现偷懒

《英雄联盟》官网明确写"录像只能在当前版本下播放"，建议剪辑成视频保存高光。
原因**不是文件格式**，而是地图、单位、技能、平衡、碰撞、随机和配置均可能改变。

✅ 必须保存 `app_version, content_version, rules_hash, stage/map_version, seed, config_digest`，
**默认同版本才允许重演**。

## 4. MovieMaker 不是实时录屏

⚠ **`--write-movie` 是逐帧模拟 + 离线渲染**，帧节奏完美但很慢。
实时录制应交给 OBS 等外部工具。

## 5. 应用场景

| 场景 | 用哪种 |
|---|---|
| bug 报告附带复现序列 | 输入录制 |
| 服务端重放防作弊 | 输入录制（配合 `multiplayer.md`） |
| 竞速游戏幽灵车 | 状态快照 |
| 精彩回放 / 击杀回放 | 状态快照 |
| 宣传片 | MovieMaker |

> **反模式清单（不能怎么做，审核用）** → `audit/godot/replay.md`


## 6. 待核对项（运行时验证）

⚠ 待核对：目标物理后端在固定步下的可复现程度 · 验证：同一输入序列跑两遍比对状态哈希

⚠ 待核对：双精度构建对确定性的实际改善 · 验证：用双精度模板跑同一序列比对结果

## 7. 相关文档

- 网络同步与回滚 → `netsync-advanced.md` / `multiplayer.md`
- 防作弊 → `security.md`
- 存档 → `io-network.md`
- 调试 → `debugging.md`
- 固定步长与帧预算 → `perf-profiling.md`
