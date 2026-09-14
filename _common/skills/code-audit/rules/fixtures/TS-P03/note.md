# TS-P03

Math.max/min 当收口守卫；**前置已有 NaN 收口则不算问题**。

- `tp.ts` —— **必须命中**：直接 `Math.max(-180, Math.min(180, n))`，n 为 NaN 时穿透
- `fp.ts` —— **必须不命中**：`isNaN(n) ? 0 : Math.max(...)` 已挡住 NaN

**来源**：2026-09-14 第二轮 nexus-panel 审查。原规则命中 2 处，
全部是 `isNaN(n) ? 0 : Math.max(...)` 形态 → 100% 误报。
