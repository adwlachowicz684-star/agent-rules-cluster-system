# 四个新机制

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
