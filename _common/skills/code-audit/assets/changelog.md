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
| 2026-09-14 | report-template-split.md | 新增 | **分文件报告模板（默认）**。整机审查产出目录：主窗口按子系统拆 + 插件各一份 + 00-索引。四条硬约束：只写问题不写过程、每条必须有位置+后果、误报段必写、同类合并。单模块审查才用旧的七节单文件版 |
| 2026-09-14 | R11 | 新增 | **文件读取无路径约束（可越权读取）**。填补模式库缺口：R01 只管"整文件读入的内存上限"，管不到"能不能读"。来源：nexus-panel `fpx_read_file` → `content::read_preview` 直接 `fs::read_to_string(p)`，能读任意文本文件。实测命中 5 处，其中 3 处真（`content.rs:202` / `mod.rs:679` / `store.rs:313`），2 处为私有工具函数属误报 |
| 2026-09-14 | R12 | **已移除** | 尝试实现"安全校验函数定义后零调用"，真问题（`safe_url` 零调用）确实存在且已人工确认，但规则实现未达标：PROJECT_CHECKS 拿到的 `all_text` 与收集到的定义不在同一上下文，10 个函数里 8 个误报。**不为凑数留半成品，已彻底删除**，待重做 |
| 2026-09-14 | J09 | **修正（重要）** | 原判据"文件里有 add 无 remove 就报"太粗；改为**接收者感知 + 一次性上下文**：① 接收者是本作用域 createElement 的局部变量 ② 确有清空操作 ③ 未被 push 外部持有 —— 三条同时满足才降级。反例：有清空却注册在 window / 容器自身 / 被缓存持有的节点上，仍是真泄漏。另：`init`/`boot`/顶层 IIFE 里的一次性 window 监听是正常用法，按**缩进**找外层函数（不能只找最近的，会被平级的 `const x = () =>` 误导），命中一次性名单则不报 |
| 2026-09-14 | s-backend | 新增 H-01/H-02 | 人工检查项（正则扫不出）：H-01 防护函数定义后零调用（safe_url 案例，同族函数有的接了有的没接，不对称即线索）；H-02 同族命令授权模型不一致（fs_op 有 resolve_within，fpx_read_file 没有） |
| 2026-09-14 | s-contracts | 新增 H-03 | 人工检查项：安全增强把回归测试打挂的静默失效（handshake-test 因新增 source 校验导致行为层 3 项失效，源码层仍绿）；附"断言依赖源码文本距离"的脆弱性 |
| 2026-09-14 | fixtures | 新增 APP-J09 | tp=renderPanel 里注册 window（真泄漏）· fp=renderList 里注册新建 btn+清空（不泄漏） |
| 2026-09-14 | K-30 | 新增 | 元数据推断依赖 os.access X_OK：容器与挂载文件系统上权限常为 0777 或 core.fileMode=false，导致恒真，把所有改动文件一律写成可执行 100755。来源：push_api.py 审查 P1-1，实测 |
| 2026-09-14 | K-31 | 新增 | 子进程返回码被丢弃：包装函数只取 stdout，git add 部分失败退出码 1 仍被视为成功。来源：push_api.py 审查 P2-1，实测 |
| 2026-09-14 | K-07 | 修正 | 原判据只说是否允许穿越，未区分 normpath 与 canonicalize。补充：只做字符串规整等于没校验，符号链接可绕过，须 realpath 后比较。实测 etcdir/passwd 读到 /etc/passwd |
| 2026-09-14 | T-11 | 新增 | 基线快照维度不全：只存内容哈希不存 mode，导致只改元数据不改内容的变更被判为一致而静默跳过。来源：push_api.py 审查 P1-3，实测 |
| 2026-09-14 | T-12 | 新增 | 自污染输入：程序回读自身上一次产出作默认值形成闭环，第一轮正常、从第二轮起值被固化。典型 git log -1 取提交信息而脚本自己会补同信息 commit。来源：push_api.py 前次审查 P0 |
| 2026-09-14 | A-11 | 新增 | 可选降级被赋予业务语义：x.get(k,[]) 在失败路径返回空容器，被下游解释成业务结论，把网络故障伪装成疑似他人改动。来源：push_api.py 前次审查 P1 |
| 2026-09-14 | A-12 | 新增 | 批量操作作用范围未显式限定：git commit 不带 pathspec 捎带调用前已暂存的文件。来源：push_api.py 前次审查 P1 |
| 2026-09-14 | B-10 | 新增 | 响应成功判定不靠状态码：按字段存在性判成功或 curl -s 吞错误，422 被当正常响应解析。附带重试幂等性判据。来源：push_api.py 前次审查 P1 |
| 2026-09-14 | C-14 | 新增 | 预览所见不等于实际所执行：预览基准与执行基准不是同一对象，用户据此做不可逆决定。典型预览 git diff HEAD 而执行以远端最新为 base_tree。来源：push_api.py 前次审查 P1 |
| 2026-09-14 | route.md | 补充 | 新增扫描器语言覆盖边界：scan-ts/scan-app 模式按 TS/JS 语法编写，对 Python 等输出 0 文件 0 候选，不是已修好。自检 62/62 与 28/28 全通过仍扫不出，实测该脚本人工精审仍有 4 个 P1 |
| 2026-09-14 | note.py | 修正 | 依赖 self-evolving 技能包的 domain.py，未设 PYTHONPATH 时直接 ModuleNotFoundError。改为自动向上查找并给出可执行指引 |
| 2026-09-14 | 审查产物/push-api | 新增 | push_api.py 审查报告与可重跑探针：4 个 P1/P2 实测确认，含前次 8 项修复的回归复验 |
| 2026-09-14 | SKILL.md | 拆分 | 已 216 行超 200 预算：四个新机制的命令与缘由下沉为 references/mechanisms.md，只留最常用三条命令。拆后 191 行 |
| 2026-09-14 | A-13 | 新增 | 防覆盖校验的前提假设失效：只比远端sha==基线证明不了本地是基于最新版改的。本地副本过期（CDN缓存tarball/离线包/旧clone）时，过期全文被当作自己的改动整文件覆盖，静默回退远端。实测同一仓库隔数分钟两次下载tarball的blob sha不同 |
| 2026-09-14 | A-14 | 新增 | 安全校验过度 fail-closed 导致 bypass 成为肌肉记忆：无风险场景也拦，逼用户每次加 --force，真有风险时同样被放过。判据要精确到具体场景而非能否确认所有事。来源：push_api.py 修复时发现新增文件被无谓拦截 |
| 2026-09-14 | K-07 | 补充 | 修法易踩点：用 realpath 校验、normpath 返回。直接用 realpath 结果会把仓库内合法符号链接改写成目标路径 |
| 2026-09-14 | 审查产物/push-api | 补充 | 8 条问题全部修复并实测：mock GitHub API 跑端到端回归，另修掉新增文件无谓拦截（升级为 A-14） |
| 2026-09-14 | p-python.md | 新增 | Python 语言包（PY-01~12）：可变默认参数、宽泛异常吞没、资源未 with、assert 守大门、模块级可变全局、naive datetime。来源：开源调研（Google Python Style Guide）+ 实测——scan-ts/scan-app 对 Python 输出 0 文件 0 候选 |
| 2026-09-14 | s-concurrency.md | 新增 | 并发与生命周期独立成域（R-01~10）：共享状态无同步、取消不传播、任务泄漏、锁序死锁、TOCTOU、超时不回滚、重试不幂等、退出不收敛。填补 A-/B-/L- 各自只覆盖片段的缺口 |
| 2026-09-14 | scan-py.py | 新增 | AST 驱动的 Python 扫描器（12 规则 + 20 组自检 + 12 组 fixture）。实测：自检 20/20，fixture 24 条断言全通过。解决「Python 压根没被扫」 |
| 2026-09-14 | route.py | 修正 | walk_files 已含 .py 但无语言包信号；新增 ext 信号类型与 p-python / s-concurrency 场景。纯 Python 项目现已能命中 |
| 2026-09-14 | rule-registry.py | 补充 | extract() 只认 scan-ts/scan-app，新扫描器规则进不了注册表。接入 scan-py.py + PY2SCENE 映射，规则数 89 → 101 |
| 2026-09-14 | K-32 | 新增 | 不安全反序列化（pickle/yaml.load/ObjectInputStream）= 任意代码执行。易漏点：代码看起来只是读个配置，没有 eval/exec 显眼 |
| 2026-09-14 | S-10 | 新增 | 敏感数据进日志：落盘即长期泄露，比内存泄露更难消除。易漏点：logger.info(x, password=pw) 的敏感信息在关键字名上 |
| 2026-09-14 | S-11 | 新增 | 行级/对象级授权缺失（水平越权）：入口鉴权存在、测试也通过，没人想到换 id |
| 2026-09-14 | G-11 | 新增 | 依赖供应链四问：锁定文件/SBOM/漏洞扫描/原生依赖审计。供应链攻击不经过代码审查 |
| 2026-09-14 | PY-08 | 修正 | 初版误报率 98%（68 条里 67 条）：只读常量被当成可变全局。加降级「无 mutate 即跳过」→ 1 条。且不得按全大写降级——名为常量实际被改的更危险 |
| 2026-09-14 | p-go.md | 新增 | Go 语言包（GO-01~10）：goroutine 泄漏、context 未传播、channel 死锁/重复关闭、map 并发写、mutex 值拷贝、err 被丢、WaitGroup 计数、循环 defer、select 无退出、无 recover |
| 2026-09-14 | p-java.md | 新增 | Java 语言包（JAVA-01~10）：资源未 try-with-resources、线程池不关、InterruptedException 被吞、并发集合误用、ThreadLocal 串扰、synchronized 锁共享对象、equals/hashCode 不配对、static 可变、异常吞没、共享 SimpleDateFormat |
| 2026-09-14 | p-cpp.md | 新增 | C/C++ 语言包（CPP-01~10）：裸资源所有权、不安全内存函数、循环边界、数据竞争、条件变量用 if、析构危险操作、悬垂引用、无符号回绕、未初始化、违反运行时策略 |
| 2026-09-14 | scan-go.py | 新增 | Go 扫描器（10 规则 + 15 组自检 + 10 组 fixture）。修复 GO-05 判据过窄（[^)]* 跨不过双括号）与 GO-08 未识别 IIFE 修法 |
| 2026-09-14 | scan-java.py | 新增 | Java 扫描器（10 规则 + 16 组自检 + 10 组 fixture）。修复 JAVA-07 Match 对象直接比较恒不等、JAVA-09 空块判断未截断到块尾 |
| 2026-09-14 | scan-cpp.py | 新增 | C/C++ 扫描器（10 规则 + 17 组自检 + 10 组 fixture）。修复 CPP-05 正则 [^)]* 跨不过 q.empty() 的双括号导致永远 0 命中 |
| 2026-09-14 | 正则判据 | 修正 | 三个语言包均踩到同一类问题：为防误报加的收紧条件反而把真阳性排掉（GO-05）、或正则语法缺陷导致永远 0 命中（CPP-05）。写正则判据必须配自检用例，否则 0 命中与无问题无法区分 |
| 2026-09-15 | 扫描器 --exclude | 新增 | 四个语言包扫描器支持 --exclude（可重复/逗号分隔）。fixture 的 tp.* 故意写成有缺陷，扫它必然命中；抑制必须显式写在命令行上——藏在隐藏配置里的抑制等于没有抑制，没人看得见也就没人复核。实测：55 → 41 条 |
| 2026-09-15 | review 退出标准 | 新增 | 三类清单（已验证/未验证/需人工确认）+ blocking 判定表，写入 common-reporting.md 与 report-template.md。没有这三张表审查不算完成：读者无法区分「查过没问题」和「没查」 |
| 2026-09-15 | finding 四要素 | 补充 | 位置·原因·后果之外补「复现/验证建议」。不写怎么验证，读者只能选择全信或全不信 |
| 2026-09-15 | rule-registry.py | 修正 | 两处统计失真：① 规则总数写死只报 scan-ts/scan-app，新增语言包后 131 条只显示 89，掩盖新规则是否入表；② fixture 覆盖率恒报 0/131——extract 只从源码提取，不知道 fixtures 目录，导致测试全通过却显示零覆盖 |
| 2026-09-15 | cwe-map.json | 新增 | 131 条规则的 CWE 映射 + fix 建议（39 种 CWE）。104 条有 CWE，27 条显式写 [] 表示非安全类 |
| 2026-09-15 | cwe 语义 | 修正 | cwe:[] 与 null 必须区分：空数组=明确非安全漏洞（死契约/性能/孤儿文件），null=没映射。硬塞相近 CWE 会让下游把它当漏洞统计，污染安全视图 |
| 2026-09-15 | 多 CWE 分组 | 修正 | _group_defaults 里一个组写多个 CWE 会让每条成员继承全部编号（TS-O01 移位溢出被标成 CWE-369 除零）。这类必须逐条写进 _rules |
| 2026-09-15 | sarif.py | 修正 | _rule_id 前缀推断写死 else 'TS-'，导致新语言包被误加前缀（PY-01→TS-PY-01），SARIF 里查不到元数据。改已知前缀直接返回 |
| 2026-09-15 | sarif.py | 新增 | 导出带 properties.cwe / properties.fix，供 GitHub Code Scanning / DefectDojo 等消费者读取 |
| 2026-09-15 | rule-registry.py | 补充 | --check 增加 CWE 映射与 fix 完整性校验。已实测：故意删两条映射后正确告警 |
| 2026-09-15 | item-index.py | 新增 | 判据条目结构化索引：加载粒度从「文件」降到「条目」，实测省 67%~91%。169 条判据 + 77 分节入索引 |
| 2026-09-15 | 条目级加载 | 新增 | 自动附带三类上下文：常见误报段（总是带）、标题引用了该 ID 的章节（如「双实现比对（C-02 的展开）」）、标「必读」的前置段（如「NaN 的三副面孔」）。只取条目会丢这些，误报率会上升 |
| 2026-09-15 | 指针条目 | 新增 | 正文<60 tokens 的条目（如 G-07 全文就一句「与 S-04 同源」）自动带上指向的目标。阈值实测：短条目 21~59、正常条目最短 71，无重叠 |
| 2026-09-15 | G-10 | 修正 | s-build.md 的 G-10 是空条目（标题在、正文全无），由 item-index --self-test 查出并补齐：sourcemap/minify 未按 profile 区分 |
| 2026-09-15 | 条目级加载边界 | 补充 | 两种情况仍要整文件读：① 确认扫描候选时（语言包标了 oversize-exempt，理由就是需整体对照本包全部判据）② 首次接触某场景未建心智模型时 |
| 2026-09-15 | route.py --items | 新增 | 路由输出建议加载的条目 ID + 可执行命令。两条路径：--scan（精准，扫描器报哪条取哪条）与 route --items（起步，按命中特征名收窄到 P0） |
| 2026-09-15 | 条目建议收窄 | 修正 | 两处静默失效：① 特征名带 ×N 计数后缀（clamp×3）未剥离 → 一条都对不上、静默回退全 P0 ② 匹配范围含 keywords（全是 loop/size 等通用词）→ 一个场景命中 13 条等于没筛。改为只认判据/特征/典型/正确四字段并剥离后缀，自检有覆盖 |
| 2026-09-15 | ID 归一化 | 修正 | 同一判据有 C01 / TS-C01 / C-01 三种写法，--scan 只做字符串相等判断导致一条也取不到。加归一化匹配，自检有覆盖 |
| 2026-09-15 | item-index --scan | 修正 | 只支持 scan-py/go 的 [{'id':..}] 格式，遇 scan-ts 的 {'items':..,'by_pattern':..} 直接 AttributeError 崩栈。改为三种形态都适配 |
| 2026-09-15 | audit.py --items | 新增 | 编排器跑完扫描自动按场景落盘判据到 <根>/.audit-items/。实测四语言项目 8 场景/7 候选 → 5 文件/9 条/1508 tokens |
| 2026-09-15 | 无候选不落判据 | 新增 | 扫描零命中且特征不匹配 → 默认跳过（判据服务于候选核对）。--items-all 可强制落 P0 起步集。加闸门前后：4854 → 1508 tokens |
| 2026-09-15 | 语言包候选丢失 | 修正 | registry 把 PY-05 标 s-backend、PY-06 标 s-sandbox，按 registry 分组导致这两条被分到路由未命中的场景、候选静默丢失。改为按 ID 前缀归语言包（判据就写在 p-python.md，审 Python 该在 p-python 看到） |
| 2026-09-15 | audit 不跑语言扫描器 | 修正 | 主循环只跑 scan-ts/scan-app，四语言项目里 p-python/p-go/p-java/p-cpp 永远 0 候选。改为按命中场景挑扫描器 |
| 2026-09-15 | s-backend 判据缺失 | 修正 | s-backend.md 用表格格式（| **K-01** … |），条目式解析器覆盖不到，32 条判据一条都没进索引。解析器加表格支持；另补 K-25~K-29 缺失的级别列 |
| 2026-09-15 | audit.py gitignore | 新增 | 审查产物落在被审查项目里会弄脏对方 git status。检测 git 仓库自动追加两行 .gitignore（幂等、带来源注释、可删），--no-gitignore 可关 |
| 2026-09-15 | gitignore 路径锚定 | 修正 | SRC 是仓库子目录时必须写 sub/.audit-items/。gitignore 含 / 时锚定到文件所在目录，不写前缀会完全失效 |
| 2026-09-15 | audit 自检 | 补充 | gitignore 四种情形全覆盖：仓库根 / 子目录 / 非 git 目录 / --no-gitignore。初版 _mkgit 把 git init 放在 sub 里，子目录场景等于没测到，已修 |
| 2026-09-15 | rule-registry --eval | 新增 | 跑 fixture 并把结论回填 eval 字段（recall 看 TP 命中、precision 看 FP 拒绝）。原 131 条全 unverified，字段形同虚设；回填后 55 条实测通过、76 条仍 unverified，哪条敢信有据可查 |
| 2026-09-15 | rule-registry 三态 | 修正 | _run_scanner 失败与「真的 0 命中」原来都返回 None，被上层当「无有效输出」跳过 → 规则失效/扫描器跑挂/没写 fixture 混成一个数。改为 (ok, hits, err) 三态，执行失败单独计数并在 --test 里报出 |
| 2026-09-15 | rule-registry eval 继承 | 新增 | --sync 按规则签名（native_id+level+title）继承上次实测结论，判据变了才重置为 unverified。不带 sig 的历史 eval 一律不继承 |
| 2026-09-15 | check-skill 阈值对齐 | 修正 | SKILL.md 上限自检用 500、config.yaml 用 200，两边不统一 → 238 行却报「警告 0」。改为 200 报 warn、500 报 error，阈值注明依据 |
| 2026-09-15 | fixture 补录 P0 | 新增 | 30 组 TP/FP（27 条 TS + 3 条 APP）。已验证规则 55 → 85 条，未覆盖 72 → 42 |
| 2026-09-15 | --test 按 id 过滤 | 修正 | 六个扫描器里只有 scan-ts 认 --pattern=，其余当未知 flag 忽略 → 实际跑全量，只要**任何**规则命中就算通过。「TP 已验证」里混着从未被自己规则命中的假通过。改为跑全量后按规则 id 自行过滤 |
| 2026-09-15 | _run_scanner 三态 | 修正 | 扫描器执行失败与「真的 0 命中」原来都返回 None → 合并成同一个数。改 (ok, hits, err)，失败单独报出。上线当天就抓到一次 scan-ts 崩溃（此前会被算作通过） |
| 2026-09-15 | 扫描器精度：typeof | 修正 | 只认 `typeof x === 'number'`，而 `!==` 早返回是最常见写法 → 正确守卫过的收口函数被判缺校验（误报）。改 `!?==?` |
| 2026-09-15 | 扫描器精度：清理 API | 修正 | x04 的 CLEAN 只认 `stop(`，引擎里标准的 `stopAllActions()` 匹配不到 → 已正确清理的代码被判泄漏。改 `(?:stop|clear|pause|cancel)\w*\(` |
| 2026-09-15 | 扫描器默认排除 | 新增 | 测试与 fixture 样本默认跳过（扫描**缺陷示范代码**只会污染结果：扫本仓库时候选 100% 来自 rules/fixtures/*/tp.*）。--include-tests 可放开，且同时解除目录级排除 |
| 2026-09-15 | CI self-audit | 新增 | 本仓库提供 SARIF 与「P0 退出码 1 可接 CI」却自己没用。新流水线跑 fixture 实测 + 六扫描器自检 + 配置解析自检，并上传 SARIF 到 Code Scanning |
| 2026-09-15 | README | 新增 | 仓库此前无 README，用法只能进代码看 |
| 2026-09-15 | fixture 批量补齐 | 新增 | 新增 38 组 tp/fp（scan-ts 25 条 + scan-app 13 条）。TP fixture 覆盖率 56/131 → 124/131；fixture 实测 114 通过 → 250 通过 0 失败 |
| 2026-09-15 | fixture 生成即验证 | 新增 | 新增的 tp/fp 全部实跑扫描器确认「tp 命中且 fp 不命中」再入库，不靠看起来对。TS-Q02 首版 remove(x: any) 带类型标注匹配不到判据，当场修正 |
| 2026-09-15 | eval 刷新 | 更新 | 全部 fixture 跑完后重跑 --eval：123 条 recall/precision 双 pass（原 131 条全 unverified），仅 7 条项目级规则仍未覆盖 |
| 2026-09-15 | fixture 批量补齐 | 新增 | 新增 38 组 tp/fp（scan-ts 25 条 + scan-app 13 条）。TP fixture 覆盖率 56/131 → 124/131；fixture 实测 114 通过 → 250 通过 0 失败 |
| 2026-09-15 | fixture 生成即验证 | 新增 | 新增的 tp/fp 全部实跑扫描器确认「tp 命中且 fp 不命中」再入库，不靠看起来对。TS-Q02 首版 remove(x: any) 带类型标注匹配不到判据，当场修正 |
| 2026-09-15 | eval 刷新 | 更新 | 全部 fixture 跑完后重跑 --eval：123 条 recall/precision 双 pass（原 131 条全 unverified），仅 7 条项目级规则仍未覆盖 |
