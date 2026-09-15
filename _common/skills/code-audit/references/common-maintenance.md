<!-- oversize-exempt: 维护流程与回填步骤的操作手册，含七步流程、fixture 规范与变异验证，按步骤执行时需整体查阅 -->
# 维护本技能

本技能来自对真实项目的审查聚类，**每次审查完都要回填**。
不回填的模式库会停止生长，最终变成一份过时的清单。

## 回填流程

审查结束后，对每个**新发现的、不属于现有 52 条**的缺陷问四问：

1. **可迁移吗？**（换个项目还成立吗）—— 不成立 → 项目事实，不入库
2. **已抽象吗？**（是模式还是个案）—— 个案 → 不入库
3. **可执行吗？**（能照着检查吗）—— 不能 → 写成判据再入库
4. **已验证吗？**（真确认过的吗）—— 推理未验证 → 标 `unverified`

四问全过 → 入库：

```
① 归入 A~G 某一族（都不合适 → 新建族，并同步改 SKILL.md 的族总览）
② 分配新 ID（族字母 + 下一个序号）
③ 写进对应场景文件（references/s-*.md）：判据 / 确认 / 降级 / 默认级别
④ 若能正则检出 → 加进对应扫描器的 PATTERNS（应用级 → scripts/scan-app.py，
   TS/JS → scripts/scan-ts.py，Python/Go/Java/C++ → scripts/scan-<lang>.py），并补 --self-test 用例
⑤ rules/fixtures/<ID>/ 下补 tp / fp 样本（见下方「加模式必须配 fixture」）
⑤′【若有对应测试】用 mutate.py 证明「退回旧代码后测试会变红」（见下方）
⑥ python3 scripts/note.py "<ID>" 新增 "<一句话来源>"
⑦ python3 scripts/check-skill.py  确认体积与断链
```

### ⑤′ 变异验证：证明规则**能抓到回归**

`--self-test` 证明规则**能命中**（TP 命中 / FP 不命中）；
变异测试证明规则**能抓到回归** —— 两条是**对偶命题**，只做前一半不够。

> **只是入库而测试抓不到 = 规则形同虚设。**
> 「永远 0 命中的检查等于没有检查」；
> 同理，**永远抓不到回归的规则也等于没有规则**。

```bash
# 给被审项目写变异定义（格式见 rules/mutations.example.md）
python3 scripts/mutate.py --src=<目标源码> --mutations=mutations.json --check  # 先查锚点
python3 scripts/mutate.py --src=<目标源码> --mutations=mutations.json           # 再跑
```

**三种结果的处理**：

| 结果 | 含义 | 该做什么 |
|---|---|---|
| `KILLED` | 测试守住了 | ✅ 验收通过 |
| `SURVIVED` | **真盲区** | 补测试，直到变 KILLED |
| `NOT_APPLIED` | **变异没生效**，是 mutate 定义的问题 | 改 `old` 串，**不要去补测试** |

**`SURVIVED` 与 `NOT_APPLIED` 必须分开** —— 混在一起会产出假信号：
空变异让测试继续绿，被误判成「测试有盲区」，
于是去补**不存在的测试**。假信号比没信号更糟。

**反向验证的实例**（可作为流程范例）：

| 回退的修复 | 测试结果 |
|---|---|
| 白名单放宽回「可打印 ASCII」 | ✓ 变红（放行 5 个危险字符） |
| 补偿式清理不覆盖 PATCH | ✓ 变红（PATCH 后残留孤儿分支） |
| 报错不加上下文 | ✓ 变红 |
| `safe_rel` 去掉 realpath | ✓ 变红 |
| 大文件阈值放大到 1GB | ✓ 变红 |

**反面教训（必读）**：测错误路径时，要确认错误是**从被测代码内部抛出的**，
不是在它外面伪造的。实测：替换 `mod.save_state` 来注入失败 →
新增的错误处理**根本没执行**，测试报的是旧的裸错误，看起来像「修复没生效」。
正确做法是注入 `builtins.open`，让错误真的从被测代码内部抛出来。
（完整自检清单见 `common-manual-review.md` 第 9 项）

## 两条纪律

**只写正确路径。** 不写「我犯过什么错」，只写「这类事该怎么做」。

**操作一律命令化。** 能写成脚本的绝不写散文。
技能里出现「先…然后…再…」就该抽命令了。

## 体积预算（超了就拆）

| 文件 | 上限 |
|---|---|
| `SKILL.md` | 200 行 |
| `references/*.md` | 400 行（查表型可声明豁免） |
| `assets/*.md` | 300 行 |
| `scripts/*.py` | 300 行 |

场景文件已声明体积豁免：确认候选时需整体对照该场景全部判据，
拆分反而增加往返。若超过 500 行，按族拆成 `s-numerics.md（数值族）等场景文件` 等。

## 自检

```bash
for s in scan-ts scan-app scan-py scan-go scan-java scan-cpp; do
  python3 scripts/$s.py --self-test         # 模式必须全通过（加模式后同步加用例）
done
python3 scripts/rule-registry.py --check    # 漂移 + fixture 覆盖 + eval 状态
python3 scripts/rule-registry.py --test     # TP 必须命中 / FP 必须不命中
python3 scripts/check-skill.py              # 断链 / 孤儿 / 体积 / frontmatter
```

**加模式后必须跑 `--self-test`**：永远 0 命中的检查等于没有检查。

## 加模式必须配 fixture

新规则不配 fixture = 无法判断它是「有效」还是「从来没命中过」。
`--check` 会报未覆盖，`--test` 会实跑断言。

```bash
mkdir -p rules/fixtures/<规则ID>
# 单文件规则
rules/fixtures/<ID>/tp.<ext>     # 必须命中
rules/fixtures/<ID>/fp.<ext>     # 必须不命中（证明规则不过宽）
rules/fixtures/<ID>/note.md      # 一句话说明「什么算、什么不算」
python3 scripts/rule-registry.py --test
```

**项目级规则用整树形态**：J13 / P01~P05 / R08 判的是「整棵工程」
（忽略清单、CI 配置、多入口的安全策略覆盖、孤儿文件），单文件表达不了。
改放 `tp.d/` / `fp.d/` 目录，内容原样铺到扫描根：

```
rules/fixtures/APP-P04/tp.d/index.html      # 有 CSP
rules/fixtures/APP-P04/tp.d/admin.html      # 无 CSP → 必须命中
rules/fixtures/APP-P04/fp.d/index.html      # 有 CSP
rules/fixtures/APP-P04/fp.d/admin.html      # 有 CSP → 必须不命中
```

**fp 不是可选项**。只写 tp 的话 `precision` 永远是 `unverified`——
知道规则抓得到真问题，却不知道它会不会误伤。

### 变体样本：换名字后还成立吗

一组 tp/fp 只证明「作者想到的那种写法能命中」。若判据靠**变量名白名单**，
而 fixture 恰好用了白名单内的名字，就会全绿却大量漏检。

实测过三条规则（同一缺陷只换标识符名字）：

```
TS-O02 除法分母无零防护    白名单内 5/5 命中 · 白名单外 0/8
TS-K02 clear 漏清容器      白名单内 4/4 命中 · 白名单外 0/8
TS-I01 容量字段无裁剪      白名单内 5/5 命中 · 白名单外 0/8
```

`step` / `_queue` / `denom` 这些再平常不过的名字，一律抓不到。
所以**给规则补第二组样本，刻意用白名单外的同义标识符**：

```
rules/fixtures/TS-O02/tp.ts     # 分母叫 count（白名单内）
rules/fixtures/TS-O02/tp2.ts    # 分母叫 step（白名单外）
rules/fixtures/TS-O02/fp2.ts    # 同样叫 step，但先判零
```

支持 `tp / tp2 / tp3 …`，每组**单独跑、单独判定，任一组不过即失败**。
加完请做一次反向验证：把判据临时退回白名单写法，`--test` 必须变红；
不变红说明这组样本没生效（曾因 `files` 用 `startswith('tp.')` 筛选，
`'tp2.ts'` 被静默跳过，加了个寂寞）。

### 机扫规则 → 人工判据 的映射（`--map`）

`items.json` 按 **scene** 编号（A=s-atomicity / N=s-numerics / D=s-structures…），
`scan-ts` 按**族**编号（A=数值族 / C=原型污染族 / T=循环族…）。
两套体系独立演进，撞在同一个字母上：

```
TS-A05「>>> 0 / |0 把 NaN 变 0」  归一化 → A05  ← 撞
A-05 「调试/作弊/后门默认启用」    归一化 → A05
```

按 ID 推算会**静默给出完全无关的一条判据**——实测 41/131 条错配。
更坑的是 `family` 字母会误导：TS-A05 的 family 是 A，
但它真正的 scene 是 `s-numerics`，对应判据在 **N-05**。

所以映射必须显式写进 `registry.json` 的 `item` 字段：

```bash
python3 scripts/rule-registry.py --map           # 预览
python3 scripts/rule-registry.py --map --apply   # 写入
```

取值三态（与 `cwe` 同一套哲学——区分「确认没有」与「还没查」）：

| `item` | 含义 |
|---|---|
| `"N-05"` | 已映射 |
| `null` | 确认无对应判据（机扫能报、items 里没有人工判据，正常） |
| 缺字段 | 尚未做过映射 → `--check` 会报 |

自动打分低于阈值的**不写入**，保留候选等人工确认——措辞差异会让
语义正确的映射只有 0.33 分（如 TS-A05 对 N-05），自动阈值再调低
就会引入真错配。人工结论写进 `MANUAL_MAP`（在脚本里，带理由），
**重跑 `--map` 不会被冲掉**。

**改 ID 或加规则后**：`--sync` 会继承 `item`（否则跑一次 sync 全丢），
但新增规则仍需重跑 `--map`。`--check` 会报未映射数与悬空映射。

### 判据缺口：`--gaps`

`items.json` 里的判据不一定都有机扫规则对应。直接报「N 条没覆盖」等于没说——
缺口有三种成因，混在一起会让人反复纠结「要不要给它写规则」：

| 分类 | 含义 | 该做什么 |
|---|---|---|
| `xref` | 判据正文自己写了「与 X 同源，报一次即可」 | **不是缺口**，别管 |
| `manual` | 跨函数 / 时序 / 架构 / 需运行验证 | 机扫做不到，已声明，别纠结 |
| `todo` | 有明确文本特征 | 真的该写规则 |

```bash
python3 scripts/rule-registry.py --gaps
```

分类写在 `rules/gaps.json`（`items.json` 是 `item-index --sync` 的生成物，
不能手改；分类单独落盘，与 `registry.json` 承载扫描器表达不了的元数据同理）。

**写新规则时把规则号取成判据号**（如 K-17 → 规则 `K17`），便于 `--map` 对上。
但注意：归一化后的编号**不等于语义同源**——见下一节。

### 不要靠「编号同源」猜映射

曾试过「规则号取成判据号就自动直映」，实测是错的，且错的正是本批次要修的那类：

```
TS-S01 native=S01 → 直映 S-01「隔离后能力静默失效」
                    （正确：A-05「调试/作弊/后门默认启用」）
TS-K01 native=K01 → 直映 K-01「读入是否有界」
                    （正确：L-10「状态字段只置 true 没有复位」）
```

归一化只是**格式**对齐，不代表语义同源。真正的同源写进 `MANUAL_MAP`（带理由）。
`KNOWN_MAP` 锚了一批曾经算错的映射，`--check` 会在它们被改坏时报错。

### 改判据前先确认改的是「生效的那份定义」

`scan-ts.py` 装配时**按 id 去重、保留最后定义**（修正区覆盖 core34 的失效实现）。
于是同一规则若有两份定义，**改前面的完全不生效**：diff 有、代码变了、
行为纹丝不动，且不报任何错。

`python3 scripts/rule-registry.py --check` 会列出重复定义的规则。
改判据前先跑它；改完用「白名单外名字」的样本复测召回率，别只看 tp 命中。

本节的双样本、三态返回值、扫描范围自报，已提炼为跨领域通用协议：
`self-evolving_skill_mechanism/skills/reference/self-verification.md`。
改本技能的自检逻辑前先看它，避免两边走偏。

## 变更溯源

```bash
python3 scripts/note.py "<ID>" 新增 "来源：Nexus Panel 审查 M-02"
python3 scripts/note.py "<ID>" 修正 "原判据漏了 merge patch 语义"
python3 scripts/note.py --show
```

类型：新增 / 补充 / 修正 / 更新 / 参考 / 合并 / 拆分 / 冷藏

## 冷热分层

**不删除任何模式。** 长期 0 命中的模式标为冷藏（仅存索引），
下次命中自动回热。0 命中可能是「已全部修好」也可能是「模式失效」——
跑 `--self-test` 区分：自检能检出但真实项目 0 命中 = 前者。

## 违反即升级

某条规则写进技能后仍被违反 ≥2 次 → 不是记性问题，是规则设计问题：
不够显眼（上浮到 SKILL.md 硬约束）· 不够具体（改成可执行判据）·
反直觉（加 ⚠）· 放错层（挪到必读位置）。
