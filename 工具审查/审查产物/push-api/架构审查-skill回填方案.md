# push_api 架构审查 → code-audit 技能回填方案

> **状态：已落地（2026-09-17）** —— 本文的提案部分已获批准并执行，下方「二、归位提案」保留原文作溯源。
>
> 实际落地清单：
> - 新建 `_common/skills/code-audit/references/s-architecture.md`（AR-01 ~ AR-05 五条判据）
> - `SKILL.md` 场景表新增 `s-architecture.md` 行，风险面 11 → 12（frontmatter 同步）
> - `scripts/route.py`：`SCENES` 新增架构面信号 + `SCENE_SCANNER` 映射 `scan-app.py`
> - `scripts/scan-py.py`：新增 4 个探测器（AR-01/03/04/05）+ 自检 40/40 通过
> - `scripts/rule-registry.py`：提取正则扩展至 `AR-*`，`PY2SCENE` 补 AR 映射
> - `rules/fixtures/AR-01|03|04|05/`：各 5 个样本（tp / tp2 / fp / fp2 / note），`--eval` 实测 precision+recall 全 pass
> - `rules/gaps.json`：AR-02 标 `manual`（机扫做不到，已声明非缺陷）
> - `rules/items.json` 277 → 282 条 · `rules/registry.json` 157 → 161 条（均为 `--sync` 生成）
> - `assets/changelog.md`：5 条 `note.py` 溯源
> - `references/common-reporting.md`：退出标准新增「报告必须附技能回填判定表」
> - `SKILLS/_preferences.md`：新增 F006（审查先给回填方案）


审查对象：`push_api.py`（5190 行 / 107 函数）+ 17 个 `test_*.py`（8732 行）
审查日期：2026-09-17　审查类型：**架构层**（分层 / 耦合 / 状态 / 边界 / 可演进性）
对照基准：`_common/skills/code-audit/rules/items.json`（277 条）

## 结论先行

**有。** 9 项架构发现里，**5 条是真新增**（`items.json` 中「分层 / 架构 / 耦合 / 可测 / 退出码」零命中），
**4 条已被现有规则覆盖**（不新建，只回填实测实例）。

真新增 5 条的共同特征：**都不是运行时行为缺陷，而是"改不动"类缺陷**。
现有 11 个风险面全部面向运行时行为，架构面是**类目空白**——
所以第 0 步是归位提案，不是直接写规则。

---

## 一、四问判定表

| # | 本次发现 | 可迁移 | 已抽象 | 可执行 | 已验证 | 判定 |
|---|---|---|---|---|---|---|
| A1 | 多层防护顺序只存在于注释，无机制保障 | ✅ | ✅ | ✅ | ✅ | **入库 AR-02** |
| A2 | 判定/执行/输出三层混写（340 处 print、深层 SystemExit） | ✅ | ✅ | ✅ | ✅ | **入库 AR-01** |
| A3 | 仓库外全局状态路径 + 目标写死为模块常量 → 跨仓库串档 | ✅ | ✅ | ✅ | ✅ | **入库 AR-03** |
| A4 | 重试策略在 raw / JSON 两分支重复实现并漂移 | ✅ | ✅ | ✅ | ✅ | ❌ **A-22 已覆盖**，补实例 |
| A6 | 单向同步，不支持删除/重命名 | ✅ | ✅ | ✅ | ✅ | ❌ **T-14 / A-25 已覆盖**，补实例 |
| A7 | 中间产物残留靠用户 `--prune` 巡检 | ✅ | ✅ | ✅ | ✅ | ❌ **A-18 / A-19 已覆盖**，补实例 |
| A8 | 自建测试 harness、断言焊在 stdout 与模块全局上 | ✅ | ✅ | ✅ | ✅ | **入库 AR-05** |
| A9 | 退出码恒为 1，无法区分「被拦下」与「出错」 | ✅ | ✅ | ✅ | ✅ | **入库 AR-04** |
| A5 | 在 Git Data API 之上手搓 git 语义 | ❌ 个案 | — | — | — | 项目事实，不入库 |
| A4′ | 每请求一次 curl 子进程（性能） | — | — | — | — | 风格/性能偏好，按驳回清单丢弃 |

**三件套齐备性**：5 条新增均有位置（行号）+ 证据（实测/量化）+ 后果（见下）。

---

## 二、【提案】归位：新建架构面 `s-architecture.md`

**我不能自行改结构**（`self-evolving_skill_mechanism` 硬约束：AI 在提案这步停住）。请你裁决。

### 为什么不放进现有面

| 候选面 | 为什么不合适 |
|---|---|
| `s-atomicity`（A-） | 讲**多步写的一致性**，AR-01/03/05 不涉及写入顺序 |
| `s-state`（T-） | 讲**持久化内容的正确性**，AR-03 是"存在哪"而非"存了什么" |
| `s-contracts`（C-/H-） | 讲**对外声明与实现是否一致**，AR-01 是内部结构，不是对外契约 |
| `p-python`（PY-） | 语言包讲**Python 语义特有坑**；这 5 条在 Go / TS 项目同样成立 |
| `common-global.md` | 只接"跨单元一致性"，装不下可测性与演进性 |

### 提案内容

```
新增场景：references/s-architecture.md
ID 前缀：AR-（与 A-/T-/K- 等不冲突；规则号取 AR01~AR05 便于 --map 对上）
触发条件：单文件 >1500 行 / 单函数 >300 行 / 工具型脚本（有 CLI 且有持久化状态）
主要风险：改不动 —— 缺陷不是"跑错"，是"下一次修改必然出错"
路由信号：单文件行数、print 密度、模块级常量数、无测试框架但有 test_*.py
```

**若不批准新建**：退而求其次——AR-01/05 进 `s-contracts`，AR-03 进 `s-state`，
AR-02 进 `s-atomicity`，AR-04 进 `s-backend`。代价是架构面永远没有独立入口，
下次同类发现仍要重新判定归位。

---

## 三、5 条新规则判据（可直接粘进 `s-architecture.md`）

### AR-01 判定逻辑与输出/副作用耦合

- **判据**：承担判定职责的函数内部直接 `print()`；`SystemExit` / `sys.exit` 从**非 CLI 层**抛出；
  判定结果不通过返回值/结构体向外传递
- **确认**：① 数非入口模块里的 `print(` 数量 ② grep 非 CLI 层的 `SystemExit`
  ③ 试着 `import` 该模块当库调用，看是否必须重定向 stdout 才能用
- **典型**：`push_api.py` 340 处 `print` 散布在 `validate_state` / `pull` / `prune`；
  `SystemExit` 从 `_write_local`(L2295) / `validate_state`(L1560) 深处抛出
- **后果**：不可当库调用 · 无法 `--json` / `--quiet` · **测试只能抓 stdout 断言**
  → 改提示文案即红、重构动全局即全量改测试（实测：8732 行测试全部依赖 `mod.ROOT=` 打补丁 + stdout 匹配）
- **修法**：判定返回结构（`Verdict` / `Plan`），输出集中到 ui 层；
  错误用带码的异常类型，顶层统一转退出码
- **定级**：**P1**；若导致关键判定路径无法被测试覆盖 → **P0**
- **与 A-23 的分界**：A-23 讲报错**措辞**（说了没说清），本条讲**位置与通道**（在哪说、以什么形式说）

### AR-02 多层防护的执行顺序无机制保障

- **判据**：≥3 层防护是同一函数内的**顺序代码块**，层间先后是语义的一部分，
  且该约束**只以注释形式存在**（源码出现"必须在 X 之前/之后"字样）
- **确认**：① 数防护层数与注释里的顺序约束条数
  ② **把相邻两层调换，看有没有测试变红**（不变红 = 顺序无保障）
  ③ 新增一层，看是否有任何机制阻止你放错位置
- **典型**：`push_api.py` 5 层防护；注释写明"未解决冲突拦截必须在 P0-1 之前"(L4310)、
  "`_refuse_if_rewound` 必须在写 `synced_commit` / `local_head` 之前"(L503)，
  均无代码机制保障
- **后果**：新增/调换一层 → **防护静默失效**，且没有任何测试会发现。
  失效的表现正是这类防护型代码最想消灭的"静默"
- **修法**：抽 Guard 管线，顺序写成显式列表 `GUARDS = [...]`；每层独立 import、独立可测
- **定级**：**P1**；当失效会直接导致数据丢失 → **P0**
- **与 `common-manual-review.md` 第 8 项的分界**：那条查**路径**（放行组合 / 拦截出口 / 终态复用），
  本条查**顺序**（层与层的先后）——互补，不重复

### AR-03 跨实例 / 跨仓库状态串档

- **判据**：状态文件路径是**被操作目录之外的固定绝对路径**；
  且操作目标（owner / repo / root / branch）是**模块级常量**，无 CLI 参数或环境变量可覆盖
- **确认**：① 状态文件路径是否落在被操作目录之外
  ② **同一台机器对两个不同目标各跑一次**，看状态是否互相覆盖
  ③ 该常量有没有参数能改（没有 = 换目标只能改源码）
- **典型**：`STATE_PATH = "/data/workspace/.push-sync.json"`（仓库外）
  + `OWNER, REPO = "adwlachowicz684-star", "tauriTools"`、`ROOT = "/data/workspace/tauriTools"`
  ——而该文件所在仓库叫 `push-api-tools`，常量指向的是**另一个仓库**
- **后果**：多仓库共用一份基线 → 交叉污染；换目标只能改源码
- **修法**：状态默认落在目标内（`<root>/.git/<tool>.json`）；目标收进 `Config` 显式传递
- **定级**：**P1**；私有仓库 / 一台机器推多个项目 → **P0**
- **与 PY-08 的分界**：PY-08 是"模块级**可变**全局被改"→ 进程内竞态，修法是**加锁**；
  本条是"状态文件**放错位置**"→ 跨实例串档，修法是**改默认路径**。
  两者可同时命中，修法完全不同，别合并
- **与 C-15 的分界**：C-15 是"报错建议了不存在的操作"；本条是"默认路径本身会串档"

### AR-04 退出码不分类（生产者侧）

- **判据**：CLI 的**所有**失败路径返回同一个退出码（Python 多为 `SystemExit(str)` → 1），
  没有"被防护拦下" / "参数错误" / "外部依赖失败"的区分
- **确认**：① grep 所有 `SystemExit` / `exit(` ② 统计不同退出码有几种
  ③ 在 CI 里能否仅凭退出码区分"按提示做即可"与"真出错"
- **典型**：`push_api.py` 退出码恒为 1，只有 Ctrl-C 是 130
- **后果**：自动化无法分流。最危险的是把**"被拦下（改动未丢，照提示做）"当成错误**——
  重试和放弃两种反应都是错的
- **修法**：定义码表（0 成功 / 2 被防护拦下 / 3 冲突未解决 / 1 错误 / 130 中断）并写进 `--help`
- **定级**：**P2**；若该工具被 CI 或别的脚本调用 → **P1**
- **与既有"退出码"条目的分界**：现有 4 处出现（`s-atomicity` L450/L632、`s-backend` L117、
  `s-concurrency` L91）讲的都是**消费者侧**——"调用外部命令后要检查它的退出码"；
  本条是**生产者侧**——"你自己应该分类自己的退出码"。方向相反，不重复

### AR-05 测试自建 harness，断言焊在实现与输出上

- **判据**：不用测试框架（无 `import pytest` / `unittest`）；
  以子进程跑脚本 + stdout 出现 `ALL PASS` 判定通过；
  用 `mod.X = ...` 打补丁替换**模块级全局**；断言靠字符串包含；
  **某个 `test_*.py` 被其他套件 import 当共享库用**
- **确认**：① 有没有 import 测试框架 ② 通过判定是不是 `if "ALL PASS" in out`
  ③ **改一句提示文案看是否变红**（变红 = 断言焊在输出上）
  ④ 是否用 `mod.GLOBAL = ...` 注入（是 = 焊在实现上）
- **典型**：17 个 `test_*.py` / 8732 行 / **0 pytest**；`run_all.py` 靠 `"ALL PASS" in out` 判定；
  `test_pr_flow.GH` 被 14 个套件 import 当 fixture 库
- **后果**：**债务放大器**——它让"该做的重构"看起来永远不划算，
  于是架构债只增不减；且"全绿"可能是根本没测到
- **修法**：`conftest.py` 提供 `fake_remote` / `tmp_repo` fixture，
  在**边界层**（Remote / Config）注入而非 patch 模块全局；断言结构化返回值
- **定级**：**P1**
- **与 `common-maintenance.md` 变异纪律的分界**：那条讲**变异定义怎么写**（NOT_APPLIED vs SURVIVED），
  本条讲 **harness 形态**——互补

---

## 四、回填七步（照 `references/common-maintenance.md` 执行）

> 第 ① 步是提案，等你批准 `s-architecture.md` 后才能往下走。

```bash
cd agent-rules-cluster-system/_common/skills/code-audit

# ① 归位：新建场景文件（需先批准提案）
#    touch references/s-architecture.md   ← 把上面 5 条判据粘进去

# ② 分配 ID：AR-01 ~ AR-05（items.json 中无 AR- 前缀，无冲突）

# ③ 写进 references/s-architecture.md（判据 / 确认 / 降级 / 默认级别）

# ④ 若能正则检出 → 加进扫描器 PATTERNS，并补 --self-test 用例
#    AR-01 → scripts/scan-py.py（print 密度 + 非 CLI 层 SystemExit）
#    AR-03 → scripts/scan-app.py（模块级绝对路径常量 + 状态路径在仓库外）
#    AR-04 → scripts/scan-py.py（SystemExit 计数 vs 不同退出码种类数）
#    AR-05 → scripts/scan-app.py（有 test_*.py 但无 import pytest/unittest）
#    AR-02 → 机扫做不到（需人工），gaps.json 标 manual

# ⑤ fixture
mkdir -p rules/fixtures/AR-01 rules/fixtures/AR-03 rules/fixtures/AR-04 rules/fixtures/AR-05
#    每个目录下 tp.<ext> / fp.<ext> / note.md
#    ⚠ 必做「白名单外名字」第二组样本（tp2/fp2），否则全绿却大量漏检

# ⑤′ 变异验证（证明规则能抓到回归，格式见 rules/mutations.example.md）
python3 scripts/mutate.py --src=<目标源码> --mutations=mutations.json --check   # 先查锚点
python3 scripts/mutate.py --src=<目标源码> --mutations=mutations.json           # 再跑

# ⑥ 变更溯源
python3 scripts/note.py "AR-01" 新增 "来源：push_api 架构审查 2026-09-17 A2"
python3 scripts/note.py "AR-02" 新增 "来源：push_api 架构审查 2026-09-17 A1"
python3 scripts/note.py "AR-03" 新增 "来源：push_api 架构审查 2026-09-17 A3"
python3 scripts/note.py "AR-04" 新增 "来源：push_api 架构审查 2026-09-17 A9"
python3 scripts/note.py "AR-05" 新增 "来源：push_api 架构审查 2026-09-17 A8"

# ⑦ 自检
python3 scripts/check-skill.py
python3 scripts/rule-registry.py --check     # 漂移 + fixture 覆盖
python3 scripts/rule-registry.py --test      # TP 命中 / FP 不命中
python3 scripts/rule-registry.py --map       # AR-xx ↔ 机扫规则映射
```

### fixture 要点（照 `common-maintenance.md` 的两条纪律）

- **fp 不是可选项**：只写 tp → `precision` 永远 `unverified`，不知道会不会误伤
- **必须配白名单外名字的第二组**（`tp2` / `fp2`）：
  实测 3 条规则在白名单内 5/5 命中、白名单外 0/8
- **反向验证**：把判据临时退回宽松写法，`--test` 必须变红；不变红说明样本没生效

### 变异验证：本次可直接复用的 4 条（对应 4 条真新增）

| 变异 ID | 规则 | 注入方式 | 期望 |
|---|---|---|---|
| `M-AR01` | AR-01 | 把 `validate_state` 的 `SystemExit` 换成 `return None`（静默放行） | KILLED（现有测试应抓到） |
| `M-AR02` | AR-02 | 把未解决冲突拦截块挪到 P0-1 之后 | **SURVIVED**（真盲区：无任何测试覆盖顺序）→ 补测试到 KILLED |
| `M-AR03` | AR-03 | `STATE_PATH` 默认改回仓库外全局路径 | SURVIVED → 补测试 |
| `M-AR04` | AR-04 | 顶层 `except` 统一 `sys.exit(1)` | SURVIVED → 补测试 |

**AR-05 不写变异**（它评的是 harness 形态，不是被测代码的回归）。

---

## 五、4 条已有规则：只补实测实例（不新建 ID）

按 `common-maintenance.md`「每次审查完都要回填」，实例是证据资产——
不入库但要在对应判据的「实测」段补一行。

| 本次发现 | 落到哪条 | 补什么 |
|---|---|---|
| A4 重试策略在 raw / JSON 两分支重复实现（L792-838 vs L839-901，约 60 行近似重复） | **A-22** | 新实例：横切关注点是"重试 + 限流提示"，后加的 **raw 分支**漏配（不看 Retry-After），而注释声称"与 JSON 分支同一套" |
| A6 单向同步，不支持删除（L1866 明说），`files` 基线只增不减 | **T-14** / **A-25** | 新实例：`detect_changes` 直接跳过已删除文件 → "同步"声明的作用范围小于"同步"这个词 |
| A7 僵尸分支靠 `--prune` 巡检，无状态机 | **A-18** / **A-19** | 新实例：中间产物（远端分支）**有编号可被枚举** → 按 A-18 降级条款应降 P2，该提示而非强行清理 |
| A3 的局部：3 个模块级缓存在 4 处手动失效（L2374/5019/4994），其中 L4994 的 `global` 写在嵌套块中间 | **PY-08** | 新实例：名为缓存、实际被改；失效点分散 4 处且靠人工记得调 |

---

## 六、偏好条目（待你确认后写入 `SKILLS/_preferences.md`）

本次你提出：「以后有可以回填补充的内容也要优先给出 skill 的补充方案」。
按 `capture-signals.md`，这是**用户主动表达的稳定偏好**（单次表达但明确指向未来行为），建议记为稳定项：

```markdown
| F006 | 审查交付顺序 | 审查类任务结束时，**先给 code-audit 技能回填方案**（四问判定 + 归位 + 七步命令），
        再给源码修复清单；回填内容优先于修复内容 | 稳定 | 0 |
```

**落地方式**（避免它变成"正确的废话"）：把这条写进 `code-audit/references/common-reporting.md`
的退出标准——「报告末尾必须附一节：本次发现的技能回填判定表」。
判据：**它改变了报告的哪一个章节？** 答：新增「回填判定表」节。能答出来，就不是孤立知识点。

---

## 附：本次审查的量化事实（回填时当证据用）

| 指标 | 值 |
|---|---|
| `push_api.py` | 5190 行 / 107 函数 / 340 处 `print` |
| 最长函数 `_main()` | 1056 行 |
| 其余长函数 | `pull` 377 · `api` 170 · `prune` 140 · `parse_args` 136 · `init_baseline` 113 · `do_merge` 109 |
| 测试 | 17 文件 / 8732 行 / **0 pytest** / 2 套假实现 |
| 模块级全局 | `OWNER` `REPO` `ROOT` `STATE_PATH` `BRANCH` + 3 个可变缓存 + 1 个标志 |
| 外部进程 | `subprocess.run` 16 处 + curl 每请求一次 |
| 单次推送请求数 | ≈ N(文件) + 11 |
