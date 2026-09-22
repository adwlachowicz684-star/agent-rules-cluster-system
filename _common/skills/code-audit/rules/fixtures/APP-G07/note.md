# APP-G07

失效相对 import —— **模块整体加载失败**，不是"某个功能不能用"。

- `tp.js` —— **必须命中**：`./preset-icons.js` 不存在
- `fp.js` —— **必须不命中**：非相对导入（包名），本规则只判 `./` 与 `../`
- `fp2.js` —— **必须不命中**：失效路径只出现在注释里（剥注释后再判）

fp 此前缺失，导致 `precision` 一直是 `unverified`（第 4 轮补）。

## 为什么是 P0

ES module 的 import 是**静态**的：解析阶段找不到模块 → 整个模块图加载失败。
不像 `require` 可以延迟到运行到那一行才报错。

## 来源（重要教训）

2026-09-14 nexus-panel。`plugins/mindmap/panels.js:19` import 了 `./preset-icons.js`，
该文件**从未提交**（README 里已写明要新增它，功能规划了、调用方写好了、实现漏了）。
结果：mindmap 插件整体白屏。

**而 CI 全绿**，原因两个：
1. `smoke-test.mjs` 里 `grep -c "mindmap"` = 0 —— 完全没覆盖
2. `mindmap-test.mjs` 虽然 import 它，但自己崩溃退出（MODULE_NOT_FOUND），
   批量跑时只输出堆栈、**不产生 ❌ 计数**

**教训**：测试脚本崩溃 ≠ 测试失败。批量跑测试时要检查退出码，不能只 grep 输出。

## 验证时的注意

判定"文件不存在"必须**三重交叉验证**：GitHub API 列目录 / 本地解压 / 全仓扫描。
此前遇到过 codeload tarball 缓存导致误判的情况。

## 实现注意

扫描前必须**剥注释**：`vite.config.ts:56` 的注释里出现过
`from '../../js/plugin-sdk.js'` 文本，不剥会被误报。
