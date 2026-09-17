# APP-G10 · 缺口补齐

对应判据条目：**G-10**（sourcemap / minify 未按 profile）

**tp**：`sourcemap: true` 是常量 → 生产也产出 .map（源码随产物分发）。
**fp**：随 profile 变化。

---

> 以下来自并行工作线（合并时保留）
# APP-G10 CI 引用不存在的 npm script

- **TP 必须命中**：`.github/**/*.yml` 里 `npm run X`，而任一 package.json 的 scripts 都没有 X
- **FP 必须不命中**：script 存在（CI 命令不变，只补 package.json）

为什么致命：该 step 退出码 1 → fail-fast → 后续所有 step 一次都没跑过。
**CI 存在 ≠ CI 在起作用**——成本极低的验证是把 CI 里的 run: 命令在本地原样跑一遍。
实测来源：某项目 `.github/workflows/ci.yml` 第一步 `npm run config:check` 不存在，
后续 5 个 step（跨端契约、构建、3 个冒烟）从未执行。
