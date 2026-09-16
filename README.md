# agent-rules-cluster-system

一套 **agents + skills + rules** 的矩阵集群。核心是两个 skill：

| Skill | 位置 | 角色 |
|---|---|---|
| **code-audit** | `_common/skills/code-audit` | 干活的手：代码审查矩阵（11 风险面 × 4 语言包） |
| **skill-evolution** | `self-evolving_skill_mechanism/skills` | 造手的脑：技能库自进化引擎（分类 / 捕获 / 加载 / 冷藏） |

不是"一堆 skill"，而是**一套 skill 的操作系统**：引擎负责让技能库只增不减地长，
code-audit 是已经长成的样板间。

## 快速开始

### 用 code-audit 审一个代码库

```bash
cd _common/skills/code-audit

# ① 路由：看这个仓库命中哪些风险面
python3 scripts/route.py --src=<根>

# ② 扫描：出候选（多语言仓库要跑对应扫描器）
python3 scripts/scan-ts.py  --src=<根> --json > /tmp/ts.json
python3 scripts/scan-py.py  --src=<根> --json > /tmp/py.json   # 有 Python 时必跑

# ③ 取判据：只取命中条目的判据，不整文件读（实测省 67%~91% token）
python3 scripts/item-index.py --scan /tmp/ts.json
```

**`scan-ts.py: 文件 0 / 候选 0` 不代表没问题，是压根没看** —— 它只认 TS/JS。
有 Python / Go / Java / C++ 就跑 `scan-py.go/java/cpp.py`。

### 让 AI 自己跑（全自动）

```bash
python3 scripts/audit.py --src=<根> --items          # 编排 + 按场景落盘判据
python3 scripts/audit.py --src=<根> --resume          # 断点续跑
python3 scripts/sarif.py --diff old.sarif new.sarif   # 新增 / 消失 / 持续
```

## 维护者常用命令

```bash
cd _common/skills/code-audit

python3 scripts/rule-registry.py --check   # 注册表漂移 + fixture 覆盖率 + eval 状态
python3 scripts/rule-registry.py --test    # 跑 fixture（TP 必须命中 / FP 必须不命中）
python3 scripts/rule-registry.py --eval    # 把实测结论回填 eval 字段
python3 scripts/check-skill.py             # 结构 / 体积 / 断链

cd ../../self-evolving_skill_mechanism/skills

python3 scripts/structure.py --self-test   # 大类路由 8 条固定用例
python3 scripts/structure.py --route-check "<描述>"   # 判定归属哪个大类
python3 scripts/lint.py                    # 体积 / frontmatter / ID 唯一性
```

## 目录结构

```
_common/skills/code-audit/
├── SKILL.md              入口（分层按需加载，不一次读完）
├── references/           公共层 common-*.md + 场景 s-*.md + 语言包 p-*.md
├── rules/
│   ├── registry.json    151 条机扫规则（--sync 生成，勿手改）
│   ├── items.json       169 条判据条目索引（Markdown 是源，JSON 是产物）
│   ├── cwe-map.json     CWE 映射与修复建议
│   └── fixtures/        每条规则的 TP（必须命中）/ FP（必须不命中）样本
├── scripts/              7 个扫描器 + 路由 / 编排 / SARIF / 条目索引
└── assets/               报告模板、检查清单、变更溯源

self-evolving_skill_mechanism/skills/
├── SKILL.md              自进化引擎
├── config.yaml           大类注册表 + 体积上限 + 泛词表
├── scripts/              domain / structure / index / consolidate / lint
└── reference/            分层 / 路由 / 加载 / 整合 / 结构演进协议

工具审查/ 游戏开发脚本审查/   已迁入 code-audit，各留一份 MIGRATED.md 说明去向；
                              审查产物作为项目资料原样保留
```

## 几条硬约束

改这个仓库前先知道，不然 PR 会被自己人打回：

- **三件套缺一不可**：报问题必须给 位置 + 证据 + 后果。"应该""可能""似乎"一律不成立
- **没实测就标 `unverified`**，不得伪装成已验证
- **`cwe: []` 与 `cwe: null` 是两回事**：前者明确声明"这条不是安全漏洞"，
  硬给非安全问题塞相近 CWE 会污染安全视图
- **只增不减**：长期不用的技能**冷藏**而非删除；归错类比不归更糟
- **AI 在结构提案这步停住**：`structure.py --propose-new` 只生成提案，执行必须用户确认
- **`-- exclude` 须显式声明**：加排除路径不写理由等于静默降低检出

## 当前状态

| 项 | 状态 |
|---|---|
| 机扫规则 | 151 条（scan-ts 65 / scan-app 33 / py 13 / cpp 10 / go 10 / java 10 / rust 10） |
| 判据条目 | 169 条，覆盖 14 个参考文件 |
| fixture 实测 | 147 条已验证（recall+precision 双 pass）；`rule-registry.py --eval` 可回填 |
| CI | `.github/workflows/self-audit.yml`：fixture 实测 + 扫描器自检 + SARIF 上传 |

`rule-registry.py --check` 会实时报覆盖率与 eval 分布，**以它的输出为准** ——
本表的数字是上次跑 `--sync && --map --apply && --eval` 后的快照，
改扫描器后必须重跑这三个命令再更新，否则就是「文档说谎」。

> **改动扫描器后的三步**（漏任何一步都会让 CI 红）：
> ```bash
> python3 scripts/rule-registry.py --sync          # 提取规则 → registry.json
> python3 scripts/rule-registry.py --map --apply   # 机扫规则 → 判据条目映射
> python3 scripts/rule-registry.py --eval          # 跑 fixture，回填实测结论
> python3 scripts/rule-registry.py --check         # 应为 exit 0
> ```
> 2026-09 前的 registry.json 停在 93 条（只含 scan-ts / scan-app），
> 五个语言扫描器的 58 条规则从未入表 —— 后果是 `--scanners` 只推导出 2 个，
> CI 里其余 5 个扫描器的 `--self-test` **一条都没跑**，流水线照样绿。
> 这正是本仓库自己在 CI 注释里点名要防的失效模式，只是换了条路径发生。

## License

AGPL-3.0，见 [LICENSE](LICENSE)。
