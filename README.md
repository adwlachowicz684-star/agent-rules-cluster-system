# agent-rules-cluster-system

一套 **agents + skills + rules** 的矩阵集群。核心是两个 skill：

| Skill | 位置 | 角色 |
|---|---|---|
| **code-audit** | `_common/skills/code-audit` | 干活的手：代码审查矩阵（12 风险面 × 7 语言 / 平台包） |
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
有 Python / Go / Java / C++ / Rust 就跑对应的 `scan-py.py` / `scan-go.py` /
`scan-java.py` / `scan-cpp.py` / `scan-rust.py`。

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
│   ├── registry.json    248 条机扫规则（--sync 生成，勿手改）
│   ├── items.json       288 条判据条目索引（Markdown 是源，JSON 是产物）
│   ├── cwe-map.json     CWE 映射与修复建议
│   ├── gaps.json        判据缺口分类（同源 / 需人工 / 待写）
│   └── fixtures/        每条规则的 TP（必须命中）/ FP（必须不命中）样本
├── scripts/
│   ├── 扫描器 9 个      scan-{ts,app,py,cpp,go,java,rust} + cocos-audit + godot-audit
│   ├── 编排             audit（断点续跑）/ route（场景路由）/ item-index（条目级取判据）
│   ├── 交换 / 维护      sarif（CI）/ rule-registry（注册表 + fixture）/ check-skill（结构）
│   ├── 文档一致性       doc-deliverable（交付物三件套）/ doc-promise（文档 vs 代码）
│   ├── 实验设施         mutate（变异测试）/ dep-scan / project-rules
│   └── 基础设施         _flagguard（未知参数守卫）/ exitcode（退出码码表）
├── 审查产物/             自审档案（保留：记录本仓库的重要失效事件）
└── assets/               报告模板、检查清单、变更溯源

self-evolving_skill_mechanism/skills/
├── SKILL.md              自进化引擎
├── config.yaml           大类注册表 + 体积上限 + 泛词表
├── scripts/              domain / structure / index / consolidate / lint
└── reference/            分层 / 路由 / 加载 / 整合 / 结构演进协议
```

> **已删除**：`工具审查/` 与 `游戏开发脚本审查/`（45 个文件）。
> skill 本体早在 2026-09-14 迁入 `code-audit`，两个目录此后只剩
> `MIGRATED.md` 与审查产物。产物里的通用机制已反哺完毕（见下），目录随之删除。

## 从审查产物反哺了什么

两个废弃目录下的 7 份报告是 code-audit 判据的**主要来源**（A-24 / T-15 /
K-36~40 / PY-14 / C-15 / AR-01~05 等数十条）。判据早已入库，
但这些报告里还有一批**不针对某个项目、而是关于"怎么审"**的教训，
此前只留在产物里。本轮把它们反哺进技能本体：

| 反哺内容 | 来源产物 | 落点 |
|---|---|---|
| **检查长期红灯 = 检查已经死了** | 自审报告 P0-1（CI 持续红 → 五个语言包自检从未跑） | 引擎 `self-verification.md` 第十三条 |
| **判据看语义方向，不看表面特征** | 全量扫描 Q04（`has()` 两处语义相反）+ Godot 调研（`CONNECT_ONE_SHOT` 不该要求 disconnect） | 引擎 第十四条 |
| **证据三级标注**【实测】/【代码事实】/【推演】 | push-api 三轮报告（二态会低估"读码即可确证"的可信度） | `common-reporting.md` |
| **报告必须声明审查对象的版本** | push-api README（546 行→2761 行后行号全对不上，整轮复验失效） | `common-reporting.md` |
| **静态命中 ≠ 已确认缺陷**（三级输出） | Godot 调研 | `common-reporting.md` |
| **约束要么生效要么正式改掉** | 自审报告 P2-3（7 个脚本超 300 行只打 INFO） | 引擎 第十五条 |
| **分支不可达 = 规则静默失效** | 自审报告 P1-1（Q06 对 clear 形态恒不报，且藏着未执行的 NameError） | 引擎 第十六条 |
| **格式缺陷 100% 静默** | 本轮连犯 3 次的 `## ## 标题` 拼接 bug | 引擎 第十七条 + `lint.py` 自动检查 |

判据级的具体发现（A-24 三态布尔化、A-16 多处状态只修一处等于没修等）
此前已随各轮审查入 `items.json`，不在本轮范围。

## 几条硬约束

改这个仓库前先知道，不然 PR 会被自己人打回：

- **三件套缺一不可**：报问题必须给 位置 + 证据 + 后果。"应该""可能""似乎"一律不成立
- **没实测就标 `unverified`**，不得伪装成已验证
- **`cwe: []` 与 `cwe: null` 是两回事**：前者明确声明"这条不是安全漏洞"，
  硬给非安全问题塞相近 CWE 会污染安全视图
- **只增不减**：长期不用的技能**冷藏**而非删除；归错类比不归更糟
- **AI 在结构提案这步停住**：`structure.py --propose-new` 只生成提案，执行必须用户确认
- **`-- exclude` 须显式声明**：加排除路径不写理由等于静默降低检出
- **退出码要分类**（`scripts/exitcode.py`）：`0` 成功 / `1` 出错 / `2` 用法参数错 /
  `3` 环境不满足 / `4` 被拦下（改动未丢）/ `130` 中断。
  一律 `sys.exit(1)` 会让 CI 分不清「照提示做即可」和「真出错」，
  把「被拦下」当成错误是最危险的——重试和放弃两种反应都是错的

## 当前状态

| 项 | 状态 |
|---|---|
| 机扫规则 | **224 条**（scan-ts 65 / scan-app 53 / godot-audit 34 / scan-py 21 / cocos-audit 11 / cpp 10 / go 10 / java 10 / rust 10） |
| 判据条目 | **288 条**，来自 18 个参考文件；已有规则覆盖 167，无规则 121（同源重复 13 + 需人工判断 108，**可机扫待写 0**） |
| fixture 实测 | **通过 380 · 失败 0**；有 TP 样本的规则 190/224（缺的 34 条全是 godot，搭建中） |
| 自扫自身 | `scan-py.py --src=scripts` → **0 条** |
| CI | `.github/workflows/self-audit.yml`：fixture 实测 + 扫描器自检 + 交叉审计 + 注释化测试 + SARIF 上传 |

> ⚠ **本表数字会过期**：规则数与判据数随回填变化，写死的口径必然过期
> （曾出现 README 说 131 条 / registry 只有 93 条 / 语言包自称 20 条自检的三方不一致）。
> **查当前值用 `python3 scripts/rule-registry.py --check`** —— 以它的实时输出为准，
> 本表只是上次快照。改完规则或判据后，记得回来更新这张表。

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
