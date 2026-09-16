# K-42 分类优先级倒置（细粒度分支被粗粒度判定吞掉）

- **TP 必须命中**：① 权威粗粒度字段（`mergeable_state`）的判定写在 ② 细粒度命中表之前，
  且 ① 的取值集合覆盖了 ② 想表达的成因
- **FP 必须不命中**：① 只判语义唯一的取值，其余下落给 ②

实测来源：某推送工具 `merge_pr()` 先按 `mstate` 判，`blocked/unstable` 一律归 `need_update`；
而 CI 未跑完时 GitHub 返回的正是 `blocked` → 为 CI 写的 `ci_pending` 分支与
`_CI_PENDING_HINTS` 从不执行，用户拿到「去点 Update branch」的无效指引。
与 K-36 的分界：K-36 是命中词语义模糊（表达力）；本条是判定顺序（控制流）。
