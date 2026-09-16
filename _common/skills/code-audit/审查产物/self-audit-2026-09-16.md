# agent-rules-cluster-system 自审报告

**审查对象**：本仓库（`_common/skills/code-audit` 为主，含 `self-evolving_skill_mechanism`）
**审查日期**：2026-09-16
**审查依据**：本仓库自己的 `code-audit`（路由 → 扫描 → 验证 → 精审 → 定级）
**审查方式**：跑通全部自检脚本 + `pyflakes` 静态扫描 + 人工精审
**结论**：**P0 ×2**、P1 ×5、P2 ×4；代码类问题**已修 3 条**；新增判据 **12 条** + 补强 3 条

---

## 一、审查边界

| 项 | 说明 |
|---|---|
| **自指问题** | 用本技能审本技能。判据来自本仓库，天然存在「看不出自己盲区」的风险；因此本轮**以实跑脚本为主、精读为辅**，结论优先取实测输出 |
| **未覆盖** | `self-evolving_skill_mechanism` 的五个脚本只做了 `pyflakes` 与自检，未做人工精审 |
| **证据标注** | 【实测】= 本地跑出；【代码事实】= 读码可确证 |

---

## 二、P0：检查存在但从未运行

### P0-1　注册表未同步 → 五个语言包的自检在 CI 里一次都没跑

**证据**【实测】：

```
$ python3 scripts/rule-registry.py --check
规则总数: 93（scan-app 32 / scan-ts 61）
有 TP fixture: 0 / 93
✗ 扫描器有规则 PY-01 … PY-13 / GO-* / JAVA-* / CPP-* / RS-* 但注册表没有 → 跑 --sync
✗ 已知映射被改坏（撞号回归锚点）：TS-A05→None(应为N-05) …
退出码 = 1        ← CI 当前是红的
```

`--scanners` 只推导出 `scan-ts.py` / `scan-app.py`，并附带告警：

```
▲ 有扫描器文件但注册表里没有它的规则：scan-cpp.py, scan-go.py,
  scan-java.py, scan-py.py, scan-rust.py
```

而 CI 的自检循环正是从 `--scanners` 推导的（`self-audit.yml:43`），
所以 **py / go / java / cpp / rust 五个扫描器的 `--self-test` 从未被执行**。

讽刺的是这五个单独跑**全绿**：

| 扫描器 | `--self-test` |
|---|---|
| scan-py | 26 通过 / 0 失败 |
| scan-go | 15 / 0 |
| scan-java | 16 / 0 |
| scan-cpp | 17 / 0 |
| scan-rust | 20 / 0 |

**后果**：CI 里那条「扫描器自检」步骤名义覆盖 7 个扫描器，实际只覆盖 2 个。
按本仓库自己的判据 —— *「永远 0 命中的检查等于没有检查」* ——
这五个语言包的规则**处于「写了但没人验证它还在工作」的状态**。
更麻烦的是 CI 又因为 `--check` 退出码 1 **一直是红的**，
红灯常态化之后真漂移混进来也看不出来。

**连带**：`--check` 还报 `有 TP fixture: 0 / 93`、`93 条规则无 TP fixture`、
`93 条缺 CWE 映射`、`eval 全部 unverified`。注册表与实际能力严重脱节。

**修法**（未执行，属数据重建，建议人工确认后跑）：

```bash
python3 scripts/rule-registry.py --sync      # 从扫描器重新提取，继承 item 映射
python3 scripts/rule-registry.py --map --apply
python3 scripts/rule-registry.py --check     # 必须退出码 0
python3 scripts/rule-registry.py --test
```

**定级 P0**：静默（红灯被当成常态）+ 覆盖面与声明不符。

---

### P0-2　`--test` 有 138 项「因扫描器执行失败未计入」，且修复提示指向不存在的参数

**证据**【实测】：

```
$ python3 scripts/rule-registry.py --test
fixture 实测：通过 191 · 失败 1 · 未覆盖规则 0
  ! 另有 138 项因扫描器执行失败**未计入**（已排除，勿当作「无问题」）

样例：
  ! A-18 tp(tp.py)：扫描器执行失败（输出非 JSON：未找到可扫描的模块目录
     （SRC=/tmp/fix-vvf1famq）
    提示：扁平结构请加 --flat；子目录结构请确认 --src 指向模块根。
```

根因在 `rule-registry.py:527`：`meta` 缺失时 `scanner` 默认取 `'scan-ts.py'`。
Python / Rust / Go / Java / C++ 的 fixture 因为 P0-1 未入册，取不到 `meta` →
被送去给 **scan-ts** 扫 → 报「未找到可扫描的模块目录」。

**提示是错的**：`--flat` 只存在于 `scan-ts.py` 与 `scan-app.py`，
而 `scan-py` / `scan-rust` / `scan-java` / `scan-go` / `scan-cpp` **全都没有这个参数**：

```
$ python3 scripts/scan-py.py --flat …
scan-py.py: error: unrecognized arguments: --flat
```

**这正是本仓库 C-15 与 A-16 的自用实例**：报错建议的操作在当前版本里根本不存在。
维护文档 `common-maintenance.md` 里写得明明白白 ——
*「只是入库而测试抓不到 = 规则形同虚设」*，这里则是
**规则已入库、fixture 也写了，但测试跑不起来且提示指错方向**。

**修法**：随 P0-1 的 `--sync` 一并解决（有 `meta` 后就会用对扫描器）。
另外建议把「未计入」从 `!` 提示升级为**计数进退出码**，否则它永远只是噪声。

---

## 三、P1（3 条已修，2 条待决）

| 编号 | 问题 | 位置 | 证据 | 状态 |
|---|---|---|---|---|
| P1-1 | `head` 未定义 → 命中即 `NameError` | `scan-ts.py:1266`（`q06`） | pyflakes `undefined name 'head'` | ✅ **已修**（改用同源 `prev`） |
| P1-2 | 依赖 `globals()` 注入的 `TEXT_BY_FILE`，提前调用即 `NameError` | `scan-app.py:561` / `713` | 【代码事实】 | ✅ **已修**（模块级预置空表） |
| P1-3 | 死代码 `return out if False else []`（`out` 此时未定义） | `scan-app.py:423` | pyflakes | ✅ **已修**（改 `return []`） |
| P1-4 | README 规则数三方不一致 | `README.md:99` | 【实测】README 131 / registry 93 / `p-python.md` 自称 20/20 | ✅ **已修**（改为动态口径 + 记录漂移） |
| P1-5 | `check-skill.py` 报 2 处悬挂引用 | `s-contracts.md`→`runner.ts`、`s-sandbox.md`→`crypto.ts` | 【实测】 | 待决（不影响功能，建议清理） |

**P1-1 补充**：该分支当前**不可达** —— 排除② 的 `prev` 切片包含了当前行，
`var.clear()` 自身必然命中 `.clear(` → 恒 `continue`。
换句话说 **Q06 对 `clear` 形态永远不报**（漏报），顺带把这个 `NameError` 藏住了。
本次只修 `NameError`、**未改检测语义**（避免无 fixture 支撑的行为变更），
漏报问题留给后续：建议补 `clear` 形态的 tp/fp 后再改 `prev` 切片范围。

---

## 四、P2

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| 1 | 未用变量 / 未用 import | `audit.py:682`、`check-skill.py:226`、`item-index.py:457`、`project-rules.py:45`、`sarif.py:29`、`structure.py:23`、`domain.py:26` | pyflakes 报出，无害但增加阅读成本 |
| 2 | f-string 缺占位符 | `consolidate.py:393`、`domain.py:308/312`、`structure.py:80/212/213/351` | 形如 `f"xxx"` 无 `{}`，多半是改造遗留 |
| 3 | 体积豁免形同虚设 | 7 个脚本超 300 行上限（scan-ts 1992、rule-registry 1115、scan-app 864、item-index 824、audit 688、scan-py 684、route 503） | `check-skill.py` 以 INFO 打印，理由「脚本按需执行不占上下文」合理，但**等于取消了这条约束**。要么正式提高脚本上限，要么按 INFO 的理由把它写成例外条款 |
| 4 | `probe_push_api.py` 未用 import | `工具审查/审查产物/push-api/探针/probe_push_api.py:19` | `tempfile` 未使用 |

---

## 五、验证过没问题的部分

1. **七个扫描器的 `--self-test` 全部通过**（26/28/61 条 / 15/16/17/20），逐条模式按预期工作。
2. **`check-skill.py` 退出码 0**，显式引用的 19 个资源文件全部存在，无断链。
3. **CI 的扫描器推导设计是对的** —— `self-audit.yml:39` 明确拒绝了写死名单
   （注释：「新增 Rust 语言包时 scan-rust.py 一条自检都没跑，流水线照样绿」）。
   这次的问题不在设计，在**注册表没跟上**。
4. **`common-maintenance.md` 的七步回填流程、双样本 fixture、变异验证、三态映射**
   写得比多数工程规范都扎实；本轮新增判据严格按它执行。
5. **SARIF 导出与 P0 退出码**已接入 CI，且对「退出码 1 有两种含义」做了区分处理
   （`self-audit.yml:64`）—— 这个细节很专业。

---

## 六、本轮回填（新增判据 12 条 + 补强 3 条）

来源：`push_api.py` 三轮审查（2761 行，P0 ×5 / P1 ×7 / P2 ×12）。

### 新增

| ID | 归位 | 名称 | 级别 |
|---|---|---|---|
| **A-24** | `s-atomicity` | 三态布尔化（保守返回值被当成肯定信号） | **P0** |
| **A-25** | `s-atomicity` | 中间产物落在工作目录内，被自身流程拾取 | P1 |
| **T-15** | `s-state` | 预演开关的作用范围小于命令集 | **P0** |
| **T-16** | `s-state` | 状态写入只升不降 / 单向更新 | P1 |
| **K-36** | `s-backend` | 异常处理范围与错误语义不匹配（过窄） | P1 |
| **K-38** | `s-backend` | 创建符号链接时目标未做越界校验 | P1 |
| **K-39** | `s-backend` | 循环内逐条发起外部请求（N+1） | P2 |
| **K-40** | `s-backend` | 列表查询无分页 | P2 |
| **D-18** | `s-structures` | 查表取首个匹配，未处理多匹配与状态 | P1 |
| **PY-14** | `p-python` | 生成器 / 迭代器被消费两次 | P1 |
| **PY-15** | `p-python` | 解析外部时间戳时漏掉负时区偏移 | P2 |
| **C-15** | `s-contracts` | 工具自述与实际能力不一致（`--help` 缺失 / 建议的操作不存在） | P1 |

### 补强（已有判据的新实例）

| 判据 | 补了什么 |
|---|---|
| **A-16** | 新实例「**出路空转**」：执行了提示的动作但状态毫无变化。附实测教训——出口常不止一处状态（commit 级 + 文件级 + 索引级），只修一处等于没修 |
| **A-18** | 新维度「残留**位置**被自身流程拾取」（展开见 A-25） |
| **A-19** | 新实例「**正常 `return` 路径**同样绕过清理」+「创建动作本身在 try 之外」+ 修法「清理路径唯一化（`_Abort`）」 |

### 同步更新的脚手架

- `SKILL.md` 硬约束新增两条：三态返回值不得当布尔用（A-24）、预演开关须覆盖全部子命令（T-15）
  —— 按 `common-maintenance.md` 的「违反即升级」原则，这两条在真实项目里已被命中
- 六个场景文件的「检查方法」清单同步补入对应勾选项
- 各文件头部 `oversize-exempt` 的条数声明同步更新（A 25 / T 16 / K 39 / C 26 / PY 15）

### 尚未执行（按维护流程应由人工确认）

```bash
python3 scripts/rule-registry.py --sync          # 新判据入册
python3 scripts/rule-registry.py --map --apply   # 机扫 ↔ 判据映射
python3 scripts/rule-registry.py --check
python3 scripts/note.py "A-24" 新增 "来源：push_api.py 三轮审查"
```

新增判据均**未配 fixture**（K-36 / K-38 / K-39 / K-40 / D-18 具备机扫条件，建议补 tp/fp；
A-24 / A-25 / T-15 / T-16 属跨函数与时序判据，按 `--gaps` 分类应标 `manual`）。

---

## 七、待验证（`unverified`）

- `--sync` 之后 `--check` 是否能回到退出码 0（会否暴露新的漂移）
- 138 项未计入的 fixture 在修正扫描器归属后的真实通过率
- Q06 `clear` 形态漏报的实际影响面（需要真实 TS 项目样本）
- `self-evolving_skill_mechanism` 五个脚本未做人工精审

---

# 第二轮：合并上游后的深挖（同日 21:40 后）

拉取上游最新并与本地改动合并后，**用上游新增的检查项反查我自己的回填质量**，
结果当场抓出问题。这一轮的教训比第一轮更值得记。

## R2-P0　我上一版引入 2 处判据撞号，被上游 IX001 当场抓出

上游同期新增了 `check-skill.py` 的 **IX001（判据 ID 撞号）**，跑一遍：

```
✗ [IX001] 判据 ID 撞号 C-15：同时定义在 s-contracts.md / s-contracts.md
✗ [IX001] 判据 ID 撞号 PY-14：同时定义在 p-python.md / p-python.md
```

两处都是**我造成的**：回填前没查该 ID 是否已存在。

- `s-contracts.md` 原有 `C-15 (P2) CLI 无 --help`，我又加了一条 `C-15 (P1)`
- `p-python.md` 上一轮已加过 `PY-14`，这一轮又加了一遍

**讽刺之处**：上游 changelog 里刚记了一条「H-12 撞号修正」，
而我在**同一批提交里犯了两次同类错误**，且提交前只跑了
`check-skill.py`（当时还没有 IX001），没跑判据一致性检查。

**已修**：C-15 合并为一条 P1（吸收原 P2 的 `--help` 形态）；PY-14 去重。

> 教训（建议进 `common-maintenance.md`）：
> **回填新判据前，先 grep 该 ID 是否已被占用。**
> 「新增」和「已存在」在 Markdown 里长得一模一样，人眼看不出，必须工具查。

## R2-P1　修复 P0-1：注册表漂移（93 → 151 条）

按上一轮的检查项执行了 `--sync` + `--map --apply`：

| 项 | 修复前 | 修复后 |
|---|---|---|
| 规则总数 | 93（只 TS/APP 两族） | **151**（7 个扫描器全覆盖） |
| `--check` 退出码 | 1 | **0** |
| 有 TP fixture | 0 / 93 | **148 / 151** |
| 判据映射 | 6 个撞号锚点被冲成 None | 142 / 151 已映射 |
| `--scanners` 推导 | 2 个 | **7 个**（CI 终于会跑全部自检） |

`--scanners` 的对比最能说明问题 —— 修复前 CI 只跑 2 个扫描器的自检，
修复后 7 个全覆盖。上一轮报的「五个语言包自检从未执行」至此闭环。

## R2-P2　fixture 目录名与规则 ID 失配：12 条规则悄悄退出测试

`--test` 修复后仍有 32 项跑不起来。根因不是目录结构，是**两套 ID 体系**：

```
fixture 目录用判据 ID（A-18）或过期规则 ID（APP-K03）
注册表用机扫规则 ID（TS-A18 / RS-01）
→ 匹配不到就 fallback 到 scan-ts.py，拿 TS 扫描器扫 .py / .rs 样本
→ 报「未找到可扫描的模块目录」，32 项永远失败
```

已改为**按成因分流，两种都可见、都不静默**：

| 成因 | 判据 | 处理 |
|---|---|---|
| 判据库里确有此条（A-18 / K-35） | 人工判据，无机器形态 | 跳过（○），单独计数，**不计失败** |
| 判据库里也没有（APP-K03） | **ID 失配**，规则改过名 | 报错（✗），**计入 errs 阻断** |

区分二者很关键：混为一谈就会把「规则改了 ID、样本没跟上」当成
「本来就没机器形态」，于是**改个名字就能让一批规则悄悄退出测试**。

已修 12 条失配：`APP-K*` → `K-*`（9 条，`note.md` 自证对应 K-03/K-08 等）；
`TS-D02-dts/-long/-regex` 并入 `TS-D02` 的 `fp2/fp3/fp4`。

结果：`--test` **通过 295 · 失败 0 · 退出码 0**（上一轮是 191 通过 / 138 未计入）。

### 顺带核实的一个疑虑：fp2.d.ts 会不会是「假通过」？

`.d.ts` 样本不命中，到底是「规则正确地跳过了它」，还是「扫描器压根没读它」？
后者就是假通过 —— 样本证明不了任何事。

实测：`scan-ts.py:847` 明确降级 `.d.ts`，但文件**仍被读取**
（total=0 是该规则未命中，不是文件未读）。所以这个 FP 样本有效：
它守的正是「有人删掉 847 行降级 → 立刻误报」这条回归线。

## R2-P3　eval 全库 unverified（151 条）= 等于没标

`--check` 报 `eval 全部 unverified`。按维护文档的三态哲学
（区分「确认没有」与「还没查」），**全库 unverified 等同于没标** ——
看不出哪些规则真被验证过。

跑 `--eval` 回填后：**147 条实测通过 · 0 条有问题 · 剩 4 条 unverified**。

## R2-P4　仓库存的脚本与报告差 3.5 倍，报告行号对不上

`工具审查/scripts/push_api.py` 存档是 **788 行**，
而三轮综合报告的审查对象是 **2761 行**。

关键：**三轮报告里 5 个 P0 全部针对 788 行版本根本没有的机制**
（PR 工作流 / `--pull` 三方合并 / 分支体检）。所以对不上时的第一反应
「这些 P0 是不是没修？」是错的 —— 不是没修，是版本变了。

这恰恰是 `MIGRATED.md` 自己写的警告成真：
> 报告说「第 405 行有宽泛异常」，代码早改了。存一份**与报告同版本的脚本**，
> 才能复现问题、回归验证修复是否真的生效。

已更新存档为 2761 行版，README 补了版本演进表（546 → 788 → 2761）。
确认脚本**无硬编码凭据**（token 走环境变量），仅含 OWNER/REPO/ROOT/STATE_PATH。

## R2 验证结果

```
check-skill.py          错误 0（退出码 0）
rule-registry --check   退出码 0（151 条规则 / 148 有 TP fixture）
rule-registry --test    退出码 0（通过 295 · 失败 0）
--scanners              7 个（修复前 2 个）
eval                    147 pass / 0 fail / 4 unverified
```

## R2 仍待处理

- 4 条规则缺 CWE / fix（`APP-G07~G10`）—— `--check` 现在是 warn，不阻断
- 16 条人工判据无对应机扫规则（A-18~A-23 / K-03~K-35）：
  有样本、无机扫形态。按 `--gaps` 该标 `manual` 还是补规则，需人工定
- Q06 `clear` 形态漏报（上一轮发现，未改，需先补 fixture）
- `self-evolving_skill_mechanism` 五个脚本仍未人工精审
