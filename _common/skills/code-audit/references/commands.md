# 命令速查

> 从 `SKILL.md` 下沉而来：命令是**用到了才查**的，不该常驻路由层。
> 内容不删减，只搬位置——需要时按场景在这里找，**不要凭记忆敲**。

## 路由（先跑这个）

```bash
python3 scripts/route.py --src=<根>            # 出场景命中 + 证据
python3 scripts/route.py --src=<根> --json     # 机器可读
python3 scripts/route.py --src=<根> --all      # 列出全部场景（含未命中的）
python3 scripts/route.py --src=<根> --items    # 列出建议加载的判据条目
```

## 模式扫描（按命中场景 + 语言选）

```bash
# TS/JS 模式扫描（numerics / structures / lifecycle / atomicity / state 用）
python3 scripts/scan-ts.py --src=<根> [--p0] [--json] [--flat]
python3 scripts/scan-ts.py --self-test

# ⚠ 有 Python 代码时必须额外跑这个（scan-ts/scan-app 不覆盖 Python）
python3 scripts/scan-py.py --src=<根> [--p0] [--json] [--sarif=py.sarif]
python3 scripts/scan-py.py --self-test

# ⚠ 多语言仓库按实际语言跑；各语言扫描器都支持 --exclude（抑制须显式声明）
python3 scripts/scan-go.py   --src=<根> [--p0]      # Go
python3 scripts/scan-java.py --src=<根> [--p0]      # Java
python3 scripts/scan-cpp.py  --src=<根> [--p0]      # C/C++
python3 scripts/scan-rust.py --src=<根> [--p0]      # Rust（**含 Tauri 专项**）
python3 scripts/scan-rust.py --self-test

# 应用级模式扫描（sandbox / boundary / backend / build 用）
python3 scripts/scan-app.py --src=<根> [--p0] [--json]
python3 scripts/scan-app.py --self-test
```

**语言覆盖是硬约束**：`scan-ts.py` / `scan-app.py` 只认 TS/JS 语法，
对 Python / Go / Java / C++ / Rust 输出 **0 文件 0 候选**——不是"没问题"，是**压根没看**。
有多语言代码就必须跑对应扫描器。

**Rust / Tauri 专项**（`p-rust.md`，RS-01~10）：
`unwrap` 在 `#[tauri::command]` 里会把 panic 翻译成前端的模糊错误；
整数溢出在 release 下**静默回绕**（debug 会 panic，正好掩盖问题）；
`unsafe` 无 `// SAFETY:` 注释则契约无法复核。
证明：UB 用 `cargo miri`，溢出加 `RUSTFLAGS=-C overflow-checks=on` 重编译。

## 判据条目级加载（省 67%~91% 上下文）

```bash
# 精准路径（推荐）：扫描器报哪条取哪条
python3 scripts/scan-go.py --src=<根> --json > /tmp/go.json
python3 scripts/item-index.py --scan /tmp/go.json

# 全自动：编排器跑完直接把判据落盘（推荐）
python3 scripts/audit.py --src=<根> --items       # → <根>/.audit-items/<场景>.md

python3 scripts/item-index.py --get PY-01 PY-05   # 手工指定
python3 scripts/item-index.py --query "线程池"      # 关键词检索
python3 scripts/item-index.py --check             # 索引防漂移（改了判据后跑）
python3 scripts/item-index.py --self-test
```

## 编排与结果交换

```bash
python3 scripts/audit.py --src=<根>               # 全量，自动分批
python3 scripts/audit.py --src=<根> --resume      # 断点续跑
python3 scripts/audit.py --src=<根> --budget=80000
python3 scripts/audit.py --src=<根> --sarif=out.sarif
python3 scripts/audit.py --src=<根> --no-gitignore  # 别动被审查项目的 .gitignore

python3 scripts/sarif.py --diff old.sarif new.sarif   # 新增 / 消失 / 持续
<<<<<<< 本地
python3 scripts/sarif.py --self-test                  # 前缀映射 / 去重 自检
# 开发用：给**手写 sys.argv 解析**的脚本加未知 flag 校验，
# 防止 `--self-test` 这类拼错/不存在的参数被静默忽略后返回 0
# （scripts/_flagguard.py，已被 check-skill / dep-scan / doc-* / project-rules 调用）
python3 scripts/check-list-drift.py               # 硬编码名单 vs 事实源（防第六次静默漏做）

python3 scripts/rule-registry.py --check          # 注册表漂移 + fixture 覆盖率
python3 scripts/rule-registry.py --cross        # 交叉审计：fp 里有没有藏真缺陷
python3 scripts/check-list-drift.py              # 硬编码名单 vs 事实源（防「漏一个静默失效」）
=======
python3 scripts/rule-registry.py --check          # 注册表漂移 + fixture 覆盖率
>>>>>>> 远端
python3 scripts/project-rules.py                  # 项目特化规则（按路径绑定）
```

## 文档一致性

```bash
# 交付物完整性（单元有无 README/测试/示例）
python3 scripts/doc-deliverable.py --src=<根> [--missing-only] [--strict]
# 文档承诺一致性（README 说的 vs 代码有的）
python3 scripts/doc-promise.py --src=<根> [--commands-only] [--links-only]
```

## 专项

```bash
python3 scripts/dep-scan.py --src=<根> [--violations-only]
<<<<<<< 本地

# Cocos 专项：**位置参数**接路径（不是 --src=），参数风格与其余扫描器不同
python3 scripts/cocos-audit.py <路径> [--level P0] [--rule memory] [--json]
python3 scripts/cocos-audit.py <路径> --level P0   # 有 P0 时退出码 1，可接 CI
# 规则 CC-11~21 已纳入注册表（--check / --test / item-index 都能看到）；
# 引擎侧的 scripts/cocos_audit.py 是转发壳，指向这里
=======
python3 scripts/cocos-audit.py <路径> [--level P0] [--rule memory]
>>>>>>> 远端

# 探针（numerics 实测用）
cp scripts/probe-template.ts audit/probe_<单元>.ts
```

## 维护本技能

```bash
python3 scripts/note.py "<ID>" <类型> "<原因>"     # 变更溯源（改了就记）
python3 scripts/note.py --show
python3 scripts/check-skill.py                     # 结构 / 断链 / 体积
```

## 自检：永远 0 命中的检查等于没有检查

每个扫描器都有 `--self-test`。**改过模式逻辑后必须重跑**——
自检全通过却在真实项目上 0 命中，只能说明两件事之一：
项目确实没问题（罕见），或检查已经失效（常见）。

## 变异测试（验证「测试有没有能力发现问题」）

测试全绿只证明**代码与测试当前一致**，证明不了测试有能力发现问题。
`mutate.py` 把**真实修过的缺陷**逐个注入回去，看测试会不会变红。

```bash
python3 scripts/mutate.py --mutations=<定义.json> --list                    # 列出变异
python3 scripts/mutate.py --src=<目标源码> --mutations=<定义.json> --check    # 只校验锚点
python3 scripts/mutate.py --src=<目标源码> --mutations=<定义.json>            # 跑
python3 scripts/mutate.py --src=<目标源码> --mutations=<定义.json> --only=id1,id2
```

| 结果 | 含义 | 该做什么 |
|---|---|---|
| `KILLED` | 测试守住了 | ✅ |
| `SURVIVED` | **真盲区** | 补测试 |
| `NOT_APPLIED` | 变异没生效（`old` 串没对上） | 改定义，**不是代码问题** |

**`SURVIVED` 与 `NOT_APPLIED` 必须分开** —— 空变异会让测试继续绿，
被误判成盲区，于是去补不存在的测试。

**改完目标代码要跑 `--check`**：锚点失效后变异不生效，
「KILLED」可能只是假象。

定义格式与示例见 `rules/mutations.example.md`；
流程位置见 `common-maintenance.md` 的步骤 ⑤′。
