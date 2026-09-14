---
name: code-audit
description: 代码审查矩阵。对任意代码库做分级审查：先跑场景路由确定本仓库存在哪些风险面，再按需加载对应场景的详细判据，产出分级报告与修复任务清单。Use when the user asks to 审查、审一遍、体检、精审、挑毛病、复核、上线前检查 a codebase，或问「这个代码能用吗、有什么坑」。覆盖数值边界、数据结构、生命周期、契约一致性、状态持久化、原子性与安全判定、跨边界通信、沙箱权限、原生后端、构建交付十个风险面。不用于单次走查、纯风格检查、PR diff 审查。
---

# 代码审查矩阵（code-audit）

**分层按需加载**：一个必跑的公共层 + 按仓库实际风险面命中的若干场景层。
不做「一次读完所有判据」——114 条模式全读既读不完也没必要。

```
第 0 步  读 references/common.md（必跑）
第 1 步  scripts/route.py --src=<根>   →  命中场景列表（精确辅助）
第 2 步  人工审核路由结果（可增可减）→  加载对应 s-*.md
第 3 步  逐场景：扫描 → 验证候选 → 精审 → 定级
第 4 步  汇总报告 + 修复清单
```

## 核心原则

1. **路由先行，判据后读** —— 只加载本仓库真的可能有的风险面
2. **脚本是精确辅助，不是结论** —— `route.py` 按确定性信号（目录、文件、正则）判定，
   输出**证据**供你审核。**你可以否决它**——探测到 `src-tauri/` 但只审前端时手动剔除
3. **扫描器只出候选** —— 每条都要验证，它有漏报也有误报
4. **结论必须实测** —— 不靠推理下判断；实测不了就标 `unverified`
5. **测试全绿 ≠ 可发布** —— 某库 3451 项测试全通过，精审仍发现 39 个 P0
6. **先读注释再报问题** —— 最高频的误报来源
7. **静默失败最严重** —— 可选链、空 `catch`、降级返回让缺陷不报错，用户只看到「点了没反应」
8. **发现的问题默认先报不改** —— 等用户批准后再落盘修源码

## 输入 / 输出

**接收**：源码根路径；可选的历史报告、已知台账。

**返回**：分级审查报告 + 修复任务清单（编号 + 级别 + 位置 + 修法 + 批次）。

## 路由与加载

```bash
python3 scripts/route.py --src=<根>            # 出场景命中 + 证据
python3 scripts/route.py --src=<根> --json     # 机器可读
python3 scripts/route.py --src=<根> --all      # 列出全部场景（含未命中的）
```

输出形如：

```
sandbox      命中  证据: plugins/ (8个) · src-tauri/ · README 提及"隔离"
boundary     命中  证据: postMessage ×12 · addEventListener('message') ×5
numerics     命中  证据: clamp( ×34 · 浮点运算密集
contracts    命中  证据: README 存在 · 有对外 API 声明
backend      命中  证据: src-tauri/src/*.rs (23)
structures   跳过  ——  未检出 TypedArray/对象池/分桶
```

**审核要点**（脚本做不到、必须你做的）：

- 脚本按信号猜，可能**漏**（场景相关代码在没扫到的路径）也可能**多**
  （探测到 `src-tauri/` 但用户只审前端）
- **不设命中上限** —— 命中多少审多少，截断会漏检。改为**分批**：
  每批 ≤4（可调 `--batch=N`），一批审完再加载下一批
- **精审中发现新的结构特征 → 回路由层补加载**（增量路由，见 `common.md`）

## 场景表（11 个）

| 场景 | 触发条件 | 主要风险 |
|---|---|---|
| **`s-numerics.md`** | 浮点运算 + 守卫/`clamp`/累加/循环上界 | NaN 穿透、Infinity 死循环、角度归一化挂死 |
| **`s-structures.md`** | TypedArray / 对象池 / 分桶 / 裸对象查表（修法见 `s-structures-fix.md`） | 原型污染、空桶泄漏、尺寸未收口 OOM |
| **`s-lifecycle.md`** | 订阅 / 定时器 / 句柄 / 资源获取 | 成对契约缺一侧、每帧开销、清理不彻底 |
| **`s-contracts.md`** | 对外 API / 接口声明 / README 承诺 | 死契约、文档 vs 实现、孤儿代码、双实现分叉 |
| **`s-state.md`** | store / 序列化 / 配置快照 | 不复位、反序列化无兜底、快照陈旧、降级不重试 |
| **`s-atomicity.md`** | 多步写 / 批处理 / 安全经济判定 | 不回滚、空 catch、fail-open、调试后门默认开 |
| **`s-boundary.md`** | `postMessage` / IPC / 桥接 / iframe | origin 未校验、握手竞态、退订不精确、无超时 |
| **`s-sandbox.md`** | 插件 / 扩展 / 隔离 / CSP / 凭据 | 隔离后静默失效、自授权、路径黑名单、密钥可推导 |
| **`s-backend.md`** | Rust / C++ / Go、fs、进程、本地服务 | 读入无边界、shell 解析、请求体无上限、锁中毒 |
| **`s-build.md`** | 构建 / 打包 / CI / 依赖 | 打包范围过宽、硬编码清单、CI 缺失、占位资源 |
| **`p-cocos.md`** | Cocos Creator 项目 | 引擎生命周期、泄漏源、迁移、包体 |

场景文件内自带「本场景模式清单 + 判据 + 确认方法 + 降级条件 + 修法」，
**每个场景自成一体**，只看这一个文件就能干活。

## 报告产出：默认拆成多文件

整机审查产出**一个目录**：主窗口按子系统拆（Vanilla 外壳 / React 外壳 /
原生后端 / 构建配置），插件一个一份，外加 `00-索引.md`。
≥5 个文件打包 zip 交付。模板见 `assets/report-template-split.md`。

硬约束：**只写问题不写过程**（不写"上轮核对""工具改进""扫描统计"）、
每条必须有位置 + 后果、**误报段必写**、同类问题合并。

## 四个新机制（规则可管理 · 结果可交换 · 过程可续跑 · 项目可定制）

```bash
# ① 规则注册表：88 条规则统一 rule_id，可查、可测、可防漂移
python3 scripts/rule-registry.py --sync     # 从扫描器重建（改扫描器后跑）
python3 scripts/rule-registry.py --check    # 漂移检查 + fixture 覆盖率
python3 scripts/rule-registry.py --test     # 跑 fixture：TP 必须命中 / FP 必须不命中
python3 scripts/rule-registry.py --scene s-numerics

# ② SARIF 2.1.0：接 GitHub Code Scanning / IDE / CI
python3 scan-ts.py  --src=<根> --sarif=ts.sarif
python3 scan-app.py --src=<根> --sarif=app.sarif
python3 sarif.py ts.sarif app.sarif --root=<根> --out=all.sarif
python3 sarif.py --diff old.sarif new.sarif     # 新增 / 消失 / 持续

# ③ 编排器：预算控制 + 断点续跑
python3 audit.py --src=<根> --budget=120000 --batch=4 --sarif=out.sarif
python3 audit.py --src=<根> --resume            # 从断点继续
python3 audit.py --src=<根> --status            # 看进度

# ④ 按路径绑定的项目级规则（通用模式库覆盖不到的项目特化约定）
python3 project-rules.py --src=<根> --init      # 生成 .audit-rules.json
python3 project-rules.py --src=<根> --match=<文件>  # 查该文件适用哪些规则
python3 project-rules.py --src=<根> --check     # 校验 + 报失效规则
```

**为什么需要 ①**：90 条正则散在扫描器里是隐式知识——没有 ID、无法灰度下线、
改一条不知道影响谁。注册表把它们变成可管理资产，`--check` 防注册表与扫描器漂移。

**为什么需要 ②**：扫描器原本只输出人类可读文本，接不进任何 CI/IDE。
SARIF 是通用交换格式，接上就能在 PR 里内联显示。

**为什么需要 ③**：大项目全量扫可能超预算，失败即前功尽弃。
编排器按批推进、每批记账、超预算停下并可续跑。

**为什么需要 ④**：11 个场景都是「换个项目还成立」的抽象模式，
但「改 providers.go 要同步四份语言文档」这类永远抽象不出来，对项目却极其有效。

## 输出资产（不读入上下文，用于填充）

| 文件 | 用途 |
|---|---|
| `assets/report-template.md` | 报告骨架，复制后填充 |
| `assets/review-checklist.md` | 执行清单，逐模块打勾 |
| `assets/adversarial-inputs-card.md` | 数值场景速查卡，写探针时对照 |
| `assets/eval-cases.md` | 评测集，改 description 后回归 |
| `assets/changelog.md` | 变更溯源（为什么改） |

## 公共层（必读）

| 文件 | 内容 |
|---|---|
| `references/common.md` | **必跑**：六步流程、三件套、定级、驳回清单、报告格式、增量路由 |
| `references/common-workflow.md` | 六步展开、模块推进顺序、规模分档 |
| `references/common-severity.md` | 三级定义、8 条升级规则、降级条件、驳回清单 |
| `references/common-reporting.md` | 报告结构、修复清单格式、批次建议、复核 |
| `references/common-manual-review.md` | 人工精审 7 项清单 |
| `references/common-global.md` | 跨单元一致性、地基优先 |
| `references/common-maintenance.md` | **维护本技能**：新缺陷如何入库 |
| `references/route.md` | 场景命中判据（人读版）：信号分级、人工审核清单、增量路由 |

场景配套文件（按需，场景文件内会指明）：
`s-numerics-adversarial.md`（对抗性输入）· `s-numerics-fix.md` / `s-numerics-fix-adv.md`
/ `s-structures-fix.md` / `s-lifecycle-fix.md`（修法）· `s-sandbox-host.md`
（外壳-扩展契约）· `s-sandbox-security.md`（CSP 合并语义、凭据、外链入口）

## 扫描命令

```bash
# 场景路由（先跑这个）
python3 scripts/route.py --src=<根>

# TS/JS 模式扫描（numerics / structures / lifecycle / atomicity / state 用）
python3 scripts/scan-ts.py --src=<根> [--p0] [--json] [--flat]
python3 scripts/scan-ts.py --self-test

# 应用级模式扫描（sandbox / boundary / backend / build 用）
python3 scripts/scan-app.py --src=<根> [--p0] [--json]
python3 scripts/scan-app.py --self-test

# 交付物完整性（单元有无 README/测试/示例）
python3 scripts/doc-deliverable.py --src=<根> [--missing-only] [--strict]
# 文档承诺一致性（README 说的 vs 代码有的）
python3 scripts/doc-promise.py --src=<根> [--commands-only] [--links-only]

# 探针（numerics 实测用）
cp scripts/probe-template.ts audit/probe_<单元>.ts

# 专项
python3 scripts/dep-scan.py --src=<根> [--violations-only]
python3 scripts/cocos-audit.py <路径> [--level P0] [--rule memory]

# 维护
python3 scripts/note.py "<ID>" <类型> "<原因>"
python3 scripts/check-skill.py
```

## 硬约束

- **三件套缺一不可**：位置（`文件:起止行`）+ 证据（实测输出或可验证推导链）+ 后果
  （什么场景暴露、什么症状）。「应该」「可能」「似乎」一律不成立。
- **没实测就标 `unverified`**，不得伪装成已验证。
- **NaN 必须单独测**：只测 0 / 负数 / 正常值测不出 NaN 类缺陷——
  很多守卫对 0 和负数有效，唯独 NaN 绕过。
- **Infinity 必须单独测**：它让循环挂死、数组分配 OOM，且错误不指向配置字段。
- **成对契约缺一侧按 P0**：随运行时长累积，测试期看不出，上线后 OOM。
- **安全 / 经济 / 权限链路的「放行」一律 P0**。
- **文档把缺陷记为设计意图 → P0**（会阻止下一个人修复）。
- **先读注释再报问题**。
- **两条实现要逐项比对**，不能只看其中一条。
- **报告必须写「验证过没问题的部分」**。

## Troubleshooting

| 症状 | 原因 | 处理 |
|---|---|---|
| 路由命中 8、10 个 | 大项目正常 | 分批审（每批 ≤4），不要截断。截断会漏检 |
| 路由一个都没命中 | 信号在没扫到的路径，或仓库太小 | 跑 `--all` 看判据，手工指定；<500 行的小项目直接读 common 即可 |
| 扫描出几百条候选 | 计数多的模式本质是需要批量处理的族 | 先处理**计数少**的模式，它们几乎条条是真问题；计数多的抽样后按族批量报 |
| 候选看着像 bug 但代码上有长注释 | 大概率是设计意图 | 报之前先读注释 |
| 报「孤儿文件」但它是入口 | 静态分析看不到动态引用 | 确认是否出现在入口或构建配置的动态扫描里 |
| 已修模块再扫，报的是残留项 | 分类器会漂移 | 对照历史报告与当前代码 |
| 某模式全库 0 命中 | 已修好，或模式失效 | 跑 `--self-test` 区分 |
| 报告行号指向错误代码 | 注释剥离未保持行数守恒 | 先跑 `--self-test` 看「✓ 行数守恒」 |
