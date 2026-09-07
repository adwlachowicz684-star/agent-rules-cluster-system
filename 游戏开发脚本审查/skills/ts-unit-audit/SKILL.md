---
name: ts-unit-audit
description: 对 TypeScript/JavaScript 代码库做单元级深度审查：用 53 条缺陷模式先机器扫描缩小范围，再独立验证候选、人工确认、探针实测，产出分级报告与修正代码。Use when the user asks to 精审、逐单元审查、复核、挑毛病、挑隐藏 bug a TS/JS library, or asks whether a codebase with passing tests is safe to ship. 不用于单次代码走查、纯风格检查、PR diff 审查。
---

# TS/JS 代码库单元级精审

对 TypeScript / JavaScript 代码库做**单元级深度审查**：机器扫描缩小范围 →
**独立验证候选** → 人工确认 → 探针实测 → 分级报告 → 修正源码 + 补单测。

模式库来自 240+ 条真实 P0/P1 缺陷（多轮人工审核，覆盖 119 个单元）的聚类。

## 何时使用

- 用户要求「精审」「逐单元审查」「复核」「挑毛病」某个 TS/JS 代码库
- 代码库由多个独立模块组成（插件库、工具库、SDK），需保证单元可独立复用
- 已有历史审核报告，需**修复复核**（确认修了没、有无引入新问题）

不适用：单次走查、纯风格检查、PR diff 审查（那是另一套流程）。

## 核心原则

1. **先扫描再精读** —— 用扫描器把范围缩到具体文件具体行
2. **扫描器只出候选** —— 每条都要验证，它有漏报也有误报
3. **结论必须实测** —— 不靠推理下判断
4. **测试全绿 ≠ 可发布** —— 某库 3,451 项测试全通过，人工精审仍发现 39 个 P0，
   因为用例没覆盖对抗性边界
5. **台账「已修」不等于真修** —— 实测复现一遍再关闭
6. **先读注释再报问题** —— 大量「看起来像 bug」的写法带长注释解释原因，
   这是最高频的误报来源

## Input / Output

**接收**：源码根路径（其下一级子目录即模块）；可选的历史审核报告、已知的排期与台账。

**返回**：

| 产物 | 位置 | 说明 |
|---|---|---|
| 单元报告 | `精审_<单元名>.md` | 按 `assets/report-template.md` 结构 |
| 全库进度 | `审查框架与排期.md` | 单元 × 状态 × P0/P1/P2 计数 |
| 全局议题 | 同上单独章节 | 坐标系、边界语义、平行实现等跨单元问题 |
| 复现脚本 | `audit/repro_findings.js` | 每个缺陷一条可执行复现 |
| 扫描基线 | `扫描结果_全量.txt` / `_P0.txt` | 供后续复核比对 |

## 六步流程

| 步 | 做什么 | 命令 / 读哪个文件 |
|---|---|---|
| 1 | 摸清现状（是否已有历史报告，避免重复功） | `references/workflow.md` |
| 2 | 全库模式扫描（53 条） | `scripts/pattern-scan.py --src=<根>` |
| 3 | 依赖 + 交付物扫描 | `scripts/dep-scan.py` · `scripts/doc-scan.py` |
| 4 | **验证候选**（独立步骤，过滤误报） | `references/pattern-detection.md` |
| 5 | 人工精审 + 探针实测 | `references/manual-review.md` · `assets/adversarial-inputs-card.md` |
| 6 | 分级 + 报告 + 修复 + 补测 | `references/severity.md` · `references/reporting.md` |

详细展开见 `references/workflow.md`。

**第 4 步不可省略**：扫描器产出的是候选（实测 118 模块扫出 2352 条），
必须经一轮独立验证 —— 对每条候选对照实际行为（读上下文、写探针）确认是否为真问题。
这一步是区分「有用审查」与「噪音」的关键。

## 命令速查

源码根 = 其下每个一级子目录视为一个模块。扁平结构（根下直接是文件）加 `--flat`。

```bash
# 模式扫描（53 条）
python3 scripts/pattern-scan.py --src=<根>                      # 全量
python3 scripts/pattern-scan.py --src=<根> --p0                 # 只看致命级
python3 scripts/pattern-scan.py --src=<根> moduleA moduleB      # 只扫指定模块
python3 scripts/pattern-scan.py --src=<根> --pattern=R01        # 只扫某条模式
python3 scripts/pattern-scan.py --src=<根> --json               # 机器可读
python3 scripts/pattern-scan.py --src=<根> --flat               # 扁平结构
python3 scripts/pattern-scan.py --self-test                     # 模式自检

# 依赖合规
python3 scripts/dep-scan.py --src=<根>                          # 全量
python3 scripts/dep-scan.py --src=<根> --infra=_core,ds,utils   # 指定基础设施白名单
python3 scripts/dep-scan.py --src=<根> --violations-only        # 只输出违规

# 交付物完整性（README / 测试 / 示例）
python3 scripts/doc-scan.py --src=<根>                          # 默认：被任何示例引用即算有
python3 scripts/doc-scan.py --src=<根> --strict                 # 要求专属示例文件
python3 scripts/doc-scan.py --src=<根> --missing-only           # 只列缺失

# skill 自检
python3 scripts/check-skill.py

# 探针
cp scripts/probe-template.ts audit/probe_<单元>.ts
npx tsc --outDir build --module commonjs --target ES2019 \
        --skipLibCheck --lib ES2019,DOM audit/probe_<单元>.ts
node build/audit/probe_<单元>.js
```

## 模式族总览（53 条）

| 族 | 范围 | 条数 |
|---|---|---|
| A | 数值收口（守卫、默认值、clamp、累加、位运算） | 5 |
| B | 循环与递归收敛 | 3 |
| C | 原型链安全 | 3 |
| D | 死契约（未实现字段 / 未使用参数） | 2 |
| E | 遍历安全 | 2 |
| F/G/H | 入口校验（反序列化、多订阅者、成对 API 对称） | 3 |
| I/J/K | 资源、原子性、清理 | 6 |
| L/M/N/O | 半成品、fail-open、时间/随机源、其他 | 11 |
| P | 值域与类型收口（typeof、哨兵、Math.max、slice、op 类型） | 5 |
| Q | 内存分配与数据结构（TypedArray、惰性删除、空桶、对象池、spread） | 5 |
| R | 路径与 key 编码（污染、降序删除、可逆协议、key 碰撞） | 4 |
| S | 安全默认值（调试/作弊默认启用） | 1 |
| T | 角度与周期归一化（while 死循环、±Infinity 自增） | 2 |
| U | 展示层掩盖 | 1 |
| W | 交易与批量数量 | 1 |

## 参考文件（按需读取，不要一次性全读）

| 文件 | 何时读 | 行数 |
|---|---|---|
| `references/workflow.md` | **首次执行**：六步展开、批量推进顺序 | ~200 |
| `references/pattern-detection.md` | 第 4 步：53 条判据与确认方法 | ~277 ¹ |
| `references/manual-review.md` | 第 5 步：7 项人工清单 | ~110 |
| `references/adversarial-inputs.md` | 第 5 步写探针：九类必测输入详解 | ~130 |
| `references/global-consistency.md` | 第 5 步：跨单元一致性、地基优先 | ~110 |
| `references/severity.md` | 第 6 步定级：三级定义、升级规则、驳回清单 | ~130 |
| `references/reporting.md` | 第 6 步：报告规则与命名 | ~110 |
| `references/fix-code-core.md` | 第 6 步修 A–H 族 | ~160 |
| `references/fix-code-data.md` | 第 6 步修 I–O 族 | ~75 |
| `references/fix-code-advanced.md` | 第 6 步修 P–W 族 | ~190 |

¹ 查表型文档，已声明体积豁免：确认候选时需整体对照 53 条判据，拆分反而增加往返。

## 输出资产（不读入上下文，用于填充）

| 文件 | 用途 |
|---|---|
| `assets/report-template.md` | 报告骨架，复制后填充 |
| `assets/review-checklist.md` | 执行清单，逐单元打勾 |
| `assets/adversarial-inputs-card.md` | 速查卡，写探针时对照 |
| `assets/eval-cases.md` | 评测集，改 description 后回归 |

## 硬约束

- **每条缺陷必须给三件套**：位置（`文件:起止行`）+ 证据（实测输出或可验证推导链）+ 后果
  （什么场景暴露、什么症状）。「应该」「可能」「似乎」一律不成立。
- **没有实测就标注「未实测（静态分析）」**，不得伪装成已验证。
- **NaN 必须单独测**。只测 0 / 负数 / 正常值测不出 NaN 类缺陷——
  很多守卫对 0 和负数有效，唯独 NaN 绕过。
- **Infinity 必须单独测**。它会让循环挂死、数组分配 OOM，且错误不指向配置字段。
- **先读注释再报问题**。最高频的误报来源就是没读注释。
- **安全 / 经济 / 权限链路的「放行」一律按 P0 处理**。
- **文档把缺陷记为设计意图 → P0**（会阻止下一个人修复）。
- **报告必须写「验证过没问题的部分」**——避免后续重复报已修问题。
- **发现的问题默认先报不改**，等用户批准后再落盘修正源码。

## Troubleshooting

| 症状 | 原因 | 处理 |
|---|---|---|
| 扫描出几百条候选，无从下手 | 计数多的模式（A02/O04/T02/B01）本质是需要批量处理的族 | 先处理**计数少**的模式（L01/M01/R01/S01/W01），它们几乎条条是真问题；计数多的抽样确认后按族批量修，不逐条写报告 |
| 探针得出反直觉结论（如「只执行 1 次」） | 被测单元内部可能 clamp 了 dt；或注册顺序影响回调顺序 | 先修探针再下判断。打印累计时间核对；显式控制注册顺序；每组用 `{}` 独立作用域。见 `references/adversarial-inputs.md` |
| 已修单元再扫，报告的是残留项而非原问题 | 分类器会漂移 | 复核前先确认该单元是否修过，对照历史报告与当前代码 |
| 三件套扫描报「几乎全部缺示例」 | 该仓库用批量综合示例（`batchN-usage.ts` import 十几个模块），而判据要求专属文件 | 先确认仓库的示例组织约定。专属约定 → `--strict`；批量约定 → 默认模式 |
| 有一条模式在全库 0 命中 | 可能已全部修好，也可能模式本身失效 | 跑 `pattern-scan.py --self-test`。自检会注入已知缺陷验证每条模式能否检出 |
| 改了模式逻辑后想确认没弄坏 | — | `pattern-scan.py --self-test`，要求 53/53 通过 |
| 报了问题被指出「这其实是设计意图」 | 没读注释 | 报之前先读该处上方的注释 |
| 想确认 skill 自身结构没问题 | — | `check-skill.py`：断链、孤儿文件、体积预算、frontmatter |

## 交付物

- 每单元一份报告：`精审_<单元名>.md`
- 全库进度 + 全局议题单独维护
- 复现脚本与探针保留在 `audit/` 下以便复现
