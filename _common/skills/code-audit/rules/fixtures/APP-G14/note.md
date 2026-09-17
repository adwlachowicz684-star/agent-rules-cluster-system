# APP-G14

对应判据条目：**G-11**（CI 引用不存在的 npm script）的机扫版。

**tp**：workflow 里 `npm run lint`，而 package.json 的 scripts 只有 `build`
→ 该 step 退出码非 0，fail-fast 下后续 step 全部跳过，CI 红灯却看不出根因。

**fp**：`npm run build`，scripts 里有 `build` → 正常，不报。

## 为什么编号是 G14 不是 G10

G-10 在 `s-build.md` 里是 **sourcemap / minify 未按 profile 区分**，已被
APP-G10（sourcemap 常量）占用。另一侧曾把「CI 引用不存在的 npm script」
也编成 G10，两条规则撞同一个判据号 —— 这正是本仓库反复出现的
**ID 命名空间冲突**。故此处另起 G14，判据侧待补 G-14 条目。
