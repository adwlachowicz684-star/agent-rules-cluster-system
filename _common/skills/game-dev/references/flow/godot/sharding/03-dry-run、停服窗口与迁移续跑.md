# 03 dry-run、停服窗口与迁移续跑（分服合服域）

> **本步交付**：影子库冲突报告 + 冻结清单 + 可重入可续跑的迁移脚本
> **对应**：流程 `howto/godot/sharding-matchmaking.md` · 审核 `audit/godot/sharding-matchmaking.md`

## 0. 交付物定义

1. 合服已在影子库跑过 dry-run，⛔ 不是直接改生产库
2. dry-run 用的是生产备份恢复的副本，且同一一致性快照
3. 冲突报告有八张子表，"无冲突"已被反向核查
4. 冻结清单覆盖 GM / 客服 / 定时任务 / 消费者 / 补偿脚本
5. 迁移脚本可重入、可断点续跑，批次有限流

## 1. 前置检查清单

- [ ] ⛔ 影子库已建，生产库未被直接改写
- [ ] dry-run 数据源是生产备份恢复的副本
- [ ] 冲突报告子表齐全
- [ ] ⛔ 冻结先于迁移，且后台系统也在冻结清单内
- [ ] 迁移脚本有检查点，中断后不从头重跑

## 2. 工序

### Step 1　⛔ 合服必须先跑影子库 dry-run，不是直接改生产库　`[sharding/03#S1]`

【读】`howto/godot/sharding-matchmaking.md#1.2 dry-run：第一产出是冲突报告，不是「迁移成功」`

【做】
直接改生产库的迁移一旦失败，**无法安全回退**——
因为此时新旧数据已经混合，无法区分哪些是迁移写进去的。
⛔ dry-run 的第一产出是**冲突报告**，不是"迁移成功"：
报成功的 dry-run 只证明脚本跑完了，不证明搬对了。

【产出】影子库 + 冲突报告

【判据】存在一份在影子库上产出的冲突报告，且它先于任何生产写入

【审】`audit/godot/sharding-matchmaking.md#6`


### Step 2　⛔ dry-run 必须用生产备份恢复的副本，且同一一致性快照　`[sharding/03#S2]`

【读】`howto/godot/sharding-matchmaking.md#1.2 dry-run：第一产出是冲突报告，不是「迁移成功」`

【做】
用生产只读库跑 dry-run 看似方便，但它是一个**持续变化的源**：
两个服的快照不在同一时刻，于是冲突报告里会出现大量**根本不存在的冲突**，
也会漏掉真实存在的冲突。
⛔ 必须两服都从**同一一致性快照**恢复，否则报告不可信。

【产出】快照时间戳记录（两服一致）

【判据】两服快照时间差为 0，且有记录可查

【审】`audit/godot/sharding-matchmaking.md#7`


### Step 3　⚠ dry-run 报"无冲突"要反过来查选择器是否漏表　`[sharding/03#S3]`

【读】`howto/godot/sharding-matchmaking.md#冲突报告至少八张子表`

【做】
"无冲突"不是好消息，⚠ 它最常意味着**选择器漏了表**。
正确的第一反应是加一张肯定有冲突的验证表（如两边都有的同名公会），
确认报告能把它报出来——报不出来说明枚举器有问题。
⛔ 庆祝"无冲突"再往下走，等于带着一个失效的检测器开服。

【产出】冲突报告八张子表 + 一条反向验证记录

【判据】报告里有一张人为植入的已知冲突，且它被正确报出

【审】`audit/godot/sharding-matchmaking.md#8`


### Step 4　⛔ 冻结先于迁移：先冻结写入，再追增量，最后切流　`[sharding/03#S4]`

【读】`howto/godot/sharding-matchmaking.md#1.3 停服窗口：先冻结写入，再追增量，最后切流`

【做】
顺序必须是**冻结 → 追增量 → 切流**。
⛔ 先迁移再冻结是反的：迁移期间产生的新写入会被漏掉，
而这些写入恰恰来自还活着的系统。
⚠ 冻结清单要逐项写明冻结方式与验证方法，不能只写"已停服"。

【产出】冻结清单（系统 / 冻结方式 / 验证方法 / 责任人）

【判据】每一条都能说出怎么证明它确实不再写入

【审】`audit/godot/sharding-matchmaking.md#12`


### Step 5　⛔ 停客户端入口不够：后台系统仍在写库　`[sharding/03#S5]`

【读】`howto/godot/sharding-matchmaking.md#1.3 停服窗口：先冻结写入，再追增量，最后切流`

【做】
停掉客户端入口后，GM 工具、客服后台、定时任务、消息队列消费者、
补偿脚本**仍在写库**。
⛔ 只停客户端，会得到"停服了但数据在变"的现象，
而排查会被引向迁移脚本本身的 bug。

【产出】写入方全量清单（客户端外的一切写入方）

【判据】清单里不含"应该没有了"这种无法验证的条目

【审】`audit/godot/sharding-matchmaking.md#13`


### Step 6　⛔ 迁移要小批次 + 限流，不能大事务一次 INSERT　`[sharding/03#S6]`

【读】`howto/godot/sharding-matchmaking.md#1.3 停服窗口：先冻结写入，再追增量，最后切流`

【做】
大事务一次 INSERT 看似更快，实际会**打爆目标库**：
锁等待、binlog 暴涨、主从延迟一起出现，
⛔ 而表现为"迁移很慢"而不是"要炸了"，于是继续加大批次。
⚠ 限流要按**目标库的写压力**调，不是按源库读速度。

【产出】批次与限流配置（含目标库压力观测项）

【判据】迁移期间目标库主从延迟在阈值内

【审】`audit/godot/sharding-matchmaking.md#14`


### Step 7　⛔ 迁移脚本必须可重入、可中断续跑　`[sharding/03#S7]`

【读】`howto/godot/sharding-matchmaking.md#迁移脚本必须可重入、可中断续跑`

【做】
中断后从头重跑，会把已完成的部分**再做一遍**——
如果脚本不是幂等的，就会双写。
⛔ 正解是检查点：批次状态为 `IN_PROGRESS` 时，
重启后先查"已写到哪个源主键"，从那里继续，而不是从头扫。

【产出】批次状态机 + 检查点记录（源主键水位）

【判据】杀掉进程后重启，已完成批次不重复执行

【审】`audit/godot/sharding-matchmaking.md#15`


## 3. 参考实现

```gdscript
# ⓘ 承接本步产出：批次 + 检查点，中断后从水位继续
const MIGRATE_BATCH_SIZE := 500
const MIGRATE_RATE_LIMIT_RPS := 200
const CHECKPOINT_INTERVAL_SEC := 30

# ⛔ 只做水位展示与续跑判定，真正的迁移写入在服务端。
# ⓘ last_src_id 为上一批已写入的最大源主键；为 0 表示从头开始。
func next_batch_start(last_src_id: int, done: bool) -> int:
	if done:
		return -1
	return last_src_id
```

## 4. 验收清单

- [ ] ⛔ 影子库 dry-run 报告存在，且先于任何生产写入
- [ ] 两服快照时间一致
- [ ] "无冲突"已被反向验证
- [ ] 冻结清单含 GM / 客服 / 定时任务 / 消费者 / 补偿脚本
- [ ] 杀进程重启后不重复执行已完成批次
- [ ] 目标库主从延迟在阈值内

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 迁移失败无法回退 | 直接改了生产库 | S1 |
| 报告里大量假冲突 | 快照不同一 | S2 |
| 开服后才发现漏表 | 相信了"无冲突" | S3 |
| 停服了数据还在变 | 只停了客户端 | S4 / S5 |
| 迁移越跑越慢 | 批次过大打爆库 | S6 |
| 重跑后数据双写 | 脚本不可重入 | S7 |

## 6. 下一步

→ 04 校验、开服与回滚语义

## 7　整体审核（功能点级收尾）

【审】`audit/godot/sharding-matchmaking.md#6`、`audit/godot/sharding-matchmaking.md#7`、`audit/godot/sharding-matchmaking.md#8`、`audit/godot/sharding-matchmaking.md#12`、`audit/godot/sharding-matchmaking.md#13`、`audit/godot/sharding-matchmaking.md#14`、`audit/godot/sharding-matchmaking.md#15`
