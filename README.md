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
| 机扫规则 | 见 `registry.json`（`--sync` 生成，勿手改）。**以 `--check` 实时输出为准**：上次快照 151 条（scan-ts 65 / scan-app 33 / scan-rust 10 / scan-py 13 / cpp 10 / go 10 / java 10） |
| 判据条目 | 见 `items.json`（Markdown 是源，JSON 是产物）。上次快照 259 条，覆盖 16 个参考文件 |
| fixture 实测 | 通过 295 · 失败 0（另有 16 条人工判据无对应机扫规则，未实测、非失败） |
| 机扫规则 | 见 `registry.json`（`--sync` 生成，勿手改）。**以 `--check` 实时输出为准**：上次快照 157 条（scan-ts 65 / scan-app 38 / scan-rust 10 / scan-py 14 / cpp 10 / go 10 / java 10） |
| 判据条目 | 见 `items.json`（Markdown 是源，JSON 是产物）。上次快照 272 条，覆盖 16 个参考文件 |
| fixture 实测 | 通过 314 · 失败 0（另有 26 条人工判据无对应机扫规则，未实测、非失败）；`eval` 已回填：157/157 实测通过，0 条 unverified |
| CI | `.github/workflows/self-audit.yml`：fixture 实测 + 扫描器自检 + SARIF 上传 |

> ⚠ **本表不写死数字**：规则数与判据数随回填变化，写死的口径必然过期
> （曾出现 README 说 131 条 / registry 只有 93 条 / 语言包自称 20 条自检的三方不一致）。
> 查当前值用 `python3 scripts/rule-registry.py --check`。

### 已修复的漂移（2026-09-16）

`registry.json` 曾只收 TS/APP 两族（`--sync` 未跑），导致 `--check` 退出码 1、
五个语言包的自检在 CI 里一次都没执行。已通过 `--sync` + `--map --apply` 修复：
规则 93 → **151 条**（7 个扫描器全覆盖），`--check` 退出码 0。

**第 4 轮回填（2026-09-16，push_api.py 审查）**：新增 K-42 / A-29 / G-13 / PY-18 四条判据
（PY-18 配机扫，scan-py 自检 29/29；原拟用 PY-16，已让位给远端先占用的 `timeout=TimeoutExpired`），补 8 段已有判据的形态扩展，新增 31 个 fixture 样本，
并把 `eval` 从「157 条全 unverified」回填到「157/157 实测通过」。

**fixture 目录名必须跟住规则 ID**：改名不留样本会静默退出测试。
本次修了 12 条失配（`APP-K*` → `K-*`、`TS-D02-*` 并入 `TS-D02` 的 fp2/fp3/fp4），
并在 `--test` 里加了失配检测 —— 规则改 ID 而 fixture 没跟上，现在会报错而非跳过。


## License

AGPL-3.0，见 [LICENSE](LICENSE)。
