# 五个新机制

从 `SKILL.md` 下沉（体积预算：SKILL.md ≤200 行）。
这四件事解决的是「审查结果如何被管理、交换、续跑、定制」，
常规审查不一定要用，**接 CI / 大项目 / 多轮复核时才需要**。

---

## ① 规则注册表：90 条正则变成可管理资产

```bash
python3 scripts/rule-registry.py --sync     # 从扫描器重建（改扫描器后跑）
python3 scripts/rule-registry.py --check    # 漂移检查 + fixture 覆盖率
python3 scripts/rule-registry.py --test     # 跑 fixture：TP 必须命中 / FP 必须不命中
python3 scripts/rule-registry.py --scene s-numerics
```

**为什么需要**：正则散在扫描器里是隐式知识——没有 ID、无法灰度下线、
改一条不知道影响谁。注册表把它们变成可查可测的资产，
`--check` 防止注册表与扫描器漂移（改了扫描器忘了同步注册表）。

**CWE 映射与修复建议**（`rules/cwe-map.json`）：

每条规则带 `cwe`（标准编号数组）与 `fix`（一句话修法），
`--sync` 时写入注册表，SARIF 导出带出 `properties.cwe` / `properties.fix`。

```bash
python3 rule-registry.py --check     # 缺映射会告警
```

两个设计点：

1. **`cwe: []` 与 `cwe: null` 是两回事**。空数组 = 明确声明「这条不是安全漏洞」
   （死契约、每帧 GC 压力、孤儿源文件这类），
   null = 还没映射。`--check` 只告警后者。
   硬给非安全问题塞一个相近 CWE，会让下游把它当漏洞统计，污染安全视图。
2. **多 CWE 的规则不能合并成组**。`_group_defaults` 里一个组写两个 CWE，
   会让组内每条都继承全部编号（移位溢出被标成除零）。
   这类必须逐条写进 `_rules` 精确覆盖。

## ② SARIF 2.1.0：结果可交换

```bash
python3 scan-ts.py  --src=<根> --sarif=ts.sarif
python3 scan-app.py --src=<根> --sarif=app.sarif
python3 scan-py.py  --src=<根> --sarif=py.sarif    # 多语言同理
python3 sarif.py ts.sarif app.sarif py.sarif --root=<根> --out=all.sarif
python3 sarif.py --diff old.sarif new.sarif     # 新增 / 消失 / 持续
```

**为什么需要**：扫描器原本只输出人类可读文本，接不进任何 CI/IDE。
SARIF 是通用交换格式，接上就能在 PR 里内联显示。
`--diff` 用于复核：确认上一轮报的问题真的消失了，而不是报告重写了一遍。

导出结果里每条规则带 `properties.cwe` 与 `properties.fix`，
GitHub Code Scanning / DefectDojo 等消费者可直接读。

## ③ 编排器：预算控制 + 断点续跑

```bash
python3 audit.py --src=<根> --budget=120000 --batch=4 --sarif=out.sarif
python3 audit.py --src=<根> --resume            # 从断点继续
python3 audit.py --src=<根> --status            # 看进度
```

**为什么需要**：大项目全量扫可能超预算，失败即前功尽弃。
编排器按批推进、每批记账、超预算停下并可续跑。

## ④ 项目级规则：通用模式库覆盖不到的部分

```bash
python3 project-rules.py --src=<根> --init      # 生成 .audit-rules.json
python3 project-rules.py --src=<根> --match=<文件>  # 查该文件适用哪些规则
python3 project-rules.py --src=<根> --check     # 校验 + 报失效规则
```

**为什么需要**：11 个场景都是「换个项目还成立」的抽象模式，
但「改 providers.go 要同步四份语言文档」这类永远抽象不出来，对项目却极其有效。
按路径绑定，只对匹配的文件生效。

---

## ⑤ 条目级索引：加载粒度从「文件」降到「条目」

```bash
python3 item-index.py --sync                  # 从 references/*.md 重建
python3 item-index.py --check                 # 改了 Markdown 没 sync → 报错
python3 item-index.py --self-test             # 关联逻辑自检
python3 item-index.py --stats                 # 条目数 / token 账
python3 item-index.py --get PY-01 PY-05       # ← 核心：只取这几条
python3 item-index.py --scan scan.json        # 按扫描器命中取对应条目
python3 item-index.py --query "线程池"         # 关键词检索
python3 item-index.py --get N-01 --with-preamble   # 首次接触该场景时带前言
```

**为什么需要**：路由的最小粒度是文件，命中 `p-python` 就把 2771 tokens 整个读进来，
哪怕相关的只有 PY-01 和 PY-05。规则越加越多，浪费线性放大。
实测按条目取可省 **67%~91%**。

**Markdown 仍是源**，JSON 是产物（`rules/items.json`，不读入上下文）——
跟 `registry.json` 一个模式。`--check` 防止改了 Markdown 忘了 sync。

### 自动附带的三类上下文

只取条目会丢上下文，所以以下三类自动带上，不用手工拼：

| 类型 | 触发 | 为什么必须带 |
|---|---|---|
| **常见误报**段 | 总是带 | 判断「这条是不是误报」靠它，省了会抬高误报率 |
| 标题/正文**引用了该 ID** 的章节 | 引用匹配 | 如「双实现比对（高产区，**C-02** 的展开）」，命中 C-02 不带就是丢一半判据 |
| 标了**「必读」**的前置段 | 总是带 | 场景的心智模型（如「NaN 的三副面孔」），不读看不懂判据为什么成立 |

另外**指针条目**会自动带上它指向的目标：
G-07 全文只有一句「与 S-04 同源，归 s-sandbox」（23 tokens），
单独拿出来是一句空话 → 加载时自动带上 S-04。
判据是正文 < 60 tokens，实测短条目集中在 21~59、正常条目最短 71，无重叠。

### 什么时候仍要整文件读

条目级不是万能的，两种情况下别省：

1. **确认扫描候选时**。语言包的 Markdown 里标了
   `<!-- oversize-exempt: 确认候选时需整体对照本包全部判据 -->`——
   扫描器报出的候选要对照同包其他判据才能判真伪，只读命中那几条会误判。
2. **首次接触某场景**。还没建立心智模型时，
   文件前言（`--with-preamble`）和整体结构比单条判据更重要。

### 结构化带来的副产品

拆成结构化数据后，内容缺陷会自动暴露：
`--self-test` 会检查「条目正文为空」，本次就查出 **G-10 是空条目**（标题在、正文全无），已补齐。
人工通读时这种遗漏很难发现。
