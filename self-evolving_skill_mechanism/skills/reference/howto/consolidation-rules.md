# 整合规则库（索引）

> **本区性质：howto / 怎么做（索引）。**
> 本文件是**索引**，不是内容。整合流程的判定标准按类型拆成了三份。

ⓘ **为什么拆**：原 `consolidation-rules.md` 251 行、19 个章节，
超过「单文件章节 >12」上限。更实际的问题是——
**查一个判据时不必读另外两类**。

| 文件 | 判什么 | 什么时候查 |
|---|---|---|
| [`consolidation-gate.md`](consolidation-gate.md) | **能不能入**（第零道闸 / 四道门槛 / 强度分级 / 三件套 / 查重抽样） | 拿到一条草稿，判断留还是丢 |
| [`consolidation-place.md`](consolidation-place.md) | **放哪、叫什么**（归位决策 / 归属判定 / ID 规范 / 冷热分层） | 决定留下了，判断写进哪 |
| [`consolidation-practice.md`](consolidation-practice.md) | **工作怎么组织**（量分档 / 长会话分段 / 改完重跑 / 回看建设册） | 安排一次整合任务 |

**判据一句话**：
- 这条**该不该留** → `gate`
- 留下后**放哪里** → `place`
- 这次整合**怎么安排** → `practice`

流程本身（按什么顺序做）见 [`../flow/consolidation.md`](../flow/consolidation.md)（`FL-01`）。

---

## 变更溯源

| 日期 | 改动 | 原因 |
|---|---|---|
| 2026-09-24 | 从流程文件 `flow/consolidation.md` 移出 | 判定标准是「查的东西」不是「走的东西」，混在流程里会让流程文件越来越长 |
| 2026-09-24 | 拆成 gate / place / practice 三份，本文件改为索引 | 251 行 19 章节超上限；且查一个判据时不必读另外两类 |
