# 变更溯源

> 记录「为什么改」。`python3 scripts/note.py "<ID>" <类型> "<原因>"`
> 类型：新增 / 补充 / 修正 / 更新 / 参考 / 合并 / 拆分 / 冷藏

| 日期 | ID | 类型 | 原因 |
|---|---|---|---|
| 2026-09-14 | — | 新增 | 创建 `code-audit`：把 ts-unit-audit（62 条 TS 模式）与 tool-audit（52 条工具模式）重组为「公共层 + 11 个场景」的按需加载矩阵 |
| 2026-09-14 | — | 拆分 | 原按「语言/项目类型」分 skill 导致 A01 等 ID 命名空间冲突；改按**结构条件**分场景，每个场景内部独立编号（N-/D-/L-/C-/T-/A-/B-/S-/K-/G-） |
| 2026-09-14 | route.py | 新增 | 场景路由脚本。设计约束：**只做精确辅助**，输出必须带证据，人工可增可减 |
| 2026-09-14 | route.py | 修正 | 初版按特征命中**总数**排序，`\b(?:store\|state\|config)\b` 这类宽泛正则命中 909 次把 s-state 顶到第一。改为：结构信号 >> 特征种类数 >> 命中数（对数压缩） |
| 2026-09-14 | route.py | 修正 | `*.json` / `README.md` 几乎每个项目都有，当结构信号会误导排序 → 降级为弱信号 |
| 2026-09-14 | s-numerics | 新增 | 承接 A/B/P/T/U/W 族，新增「NaN 三副面孔」前置章节（穿透/绕过守卫/静默归零三种失效路径不区分就会误判） |
| 2026-09-14 | s-structures | 新增 | 承接 C/I/Q/R 族。D-12 对象池保留 ⚠：不能用 `has()` 判归属，重复归还拦截也用 `has()` 但方向相反 |
| 2026-09-14 | s-lifecycle | 新增 | 承接 X/Y 族 + K01/K02。L-07 重挂载叠加给出三种期望形态（generation / 先清后加 / 卸载兜底） |
| 2026-09-14 | s-contracts | 新增 | 承接 D/G/H 族 + 工具侧 A 族。C-09 明确降级：不同插件各自定义同名常量是常态，只有**同区域内**取值不同才算分叉 |
| 2026-09-14 | s-sandbox | 新增 | 承接工具侧 D 族。含「静默失败清单」——可选链/空 catch/降级 null 让缺陷只表现为「点了没反应」 |
| 2026-09-14 | s-backend | 新增 | 承接工具侧 E 族。K-18 空口令放行最易忽略：`if expected.is_empty() { return true }` 实为本机任意进程可触发 |
| 2026-09-14 | s-boundary | 新增 | 承接工具侧 B 族。与 s-lifecycle 的重叠点：订阅生命周期归 lifecycle，boundary 只管通道本身 |
| 2026-09-14 | s-state | 新增 | 承接工具侧 C 族 |
| 2026-09-14 | s-atomicity | 新增 | 承接 J/L/M/S 族。核心：放行一律从严 |
| 2026-09-14 | s-build | 新增 | 承接工具侧 G 族。G-09：多份构建配置是**合并（Merge Patch）而非替换**，安全项覆盖关系要推一遍 |
| 2026-09-14 | common.md | 新增 | 公共层只放元规则，一条模式都不放（塞了模式它就会长成新的大 skill，等于没拆）。含**增量路由**条款 |
| 2026-09-14 | ts-unit-audit | 修正 | 原 SKILL.md 模式数有 62/61/53 三种口径打架，实际 62 条。迁入后以场景文件为准 |
| 2026-09-14 | doc-scan | 拆分 | 原两个 skill 都有 `scripts/doc-scan.py` 但语义相反（交付物三件套 vs 文档承诺一致性）。分别改名 `doc-deliverable.py` / `doc-promise.py` |
| 2026-09-14 | route.py | **修正** | 原设计「命中 >4 个时取前 4，其余列候选」**会漏检**——剩余场景降为候选后审着审着就忘了。改为**不设上限、分批加载**：命中多少审多少，每批 ≤4（`--batch=N` 可调），一批审完再加载下一批。分批只影响阅读节奏，不影响覆盖范围 |
| 2026-09-14 | rule-registry.py | 新增 | 规则注册表：88 条规则统一 rule_id（TS-*/APP-*），`--sync` 从扫描器提取、`--check` 防漂移、`--test` 跑 fixture |
| 2026-09-14 | J04 | **修正** | fixture 实测发现规则过宽：`JSON.parse` 在 try/catch 里仍报。加降级：窗口内有 `try{`/`catch`/`\|\| {}` 则忽略 |
| 2026-09-14 | sarif.py | 新增 | SARIF 2.1.0 输出。指纹含行号（初版不含导致 126 条里 35 条撞车）；修重复 relpath 导致的路径嵌套 `../../a/b/a/b/x.js` |
| 2026-09-14 | audit.py | 新增 | 编排器：预算控制（默认 120k token）+ 断点续跑（`.audit-state.json`）+ 统一 SARIF 输出 |
| 2026-09-14 | project-rules.py | 新增 | 按路径绑定的项目级规则（借鉴 open-code-review 的 `rule.json`）。补通用模式库的反面：项目特化、无法抽象的约定 |
| 2026-09-14 | fixtures | 新增 | 12 组 TP/FP fixture（优先「有降级条件」的规则——最易误报）。实测发现 5 个问题：J04 过宽、J08 需 plugins/ 目录、R02 应为 R04、D02 跳过 len<4 参数名 |
| 2026-09-14 | 迁移断链 | **修正** | 重组改名后留下 20 处悬挂引用：`s-*-fix.md` 互链仍指向 `fix-code-core/data/advanced/lifecycle.md`；`common-workflow.md` 指向 `host-plugin/sandbox-security/native-backend/lifecycle-build/severity/reporting.md`；`common-maintenance.md` / `p-cocos.md` 指向已删除的 `pattern-detection.md`。逐个按新名映射修复 |
| 2026-09-14 | K-24 | **修正** | `s-backend.md` 误报区提到 K-29 但表内只到 K-28（悬挂编号）。把「阻塞式固定 sleep 轮询」提回表内编为 K-24，后续编号顺延至 K-29 |
| 2026-09-14 | check-skill.py | 新增 | **PD003 悬挂引用检查**：正文反引号引用的技能内文件必须存在。加上后立刻又查出 5 处（`assets/review-checklist.md` 仍引用旧名），说明这类断链靠人工过目必漏 |
| 2026-09-14 | audit.py | **修正（严重）** | 「每个场景跑一次全量扫描器」导致同一结果计入 6~7 次：nexus-panel 111 条 TS 候选被算成 666 条，总计虚报 1378（真实 200）。改为扫描器各跑一次、按 registry 的 scene 字段分组。token 估算同步失真（82680 → 12000） |
| 2026-09-14 | sarif.py | **修正** | 不认 scan-ts items 的 `pattern` 字段 → 111 条规则 ruleId 全变 `TS-UNKNOWN`。兼容 `id`/`rule_id`/`pattern` 三种 |
| 2026-09-14 | audit.py | **修正** | 分组时未给 item 补 `scanner` → sarif 无法判断前缀，scan-app 的 R06 被标成 `TS-R06` |
| 2026-09-14 | D02 | **修正（3 类误报）** | 实测 13 条 100% 误报：① `.d.ts` 纯类型声明无函数体（9 条）② `_body_of` 截断到 2000 字符，长函数后半段参数看不到（2 条，`mountIframeView` 154 行）③ 正则字面量 `/(^\|\})([^{}@]+)\{/g` 的花括号破坏配平，body 只剩 27 字符（1 条，`scopeCss`）。修法：排除 .d.ts / 不截断 / body<200 时全文计数兜底 |
| 2026-09-14 | P03 | **修正** | 2 条全误报：`isNaN(n) ? 0 : Math.max(...)` 前置已挡 NaN。加降级：同行有 `isNaN`/`isFinite`/`typeof…number` 则跳过 |
| 2026-09-14 | fixtures | 新增 | 4 组（TS-P03 / TS-D02-dts / TS-D02-long / TS-D02-regex），断言 24→29，未覆盖规则 76→72 |
