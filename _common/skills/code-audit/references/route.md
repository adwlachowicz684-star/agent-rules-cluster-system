# 场景命中判定（人读版）

`scripts/route.py` 是机器版（按信号扫）。**本文件是判据说明**，
用于三件事：脚本命中后你核实对不对、脚本漏了手工补、脚本多了手工剔。

## 信号分级

| 级别 | 判据 | 可信度 | 例子 |
|---|---|---|---|
| **强结构** | 目录/构建配置存在 | 几乎不会错 | `src-tauri/` · `Cargo.toml` · `plugins/` |
| **弱结构** | 通用文件存在 | 仅作提示 | `README.md` · `package.json` · `.gitignore` |
| **特征** | 代码正则命中 | 有命中即相关，看**种类**不看总数 | `postMessage` · `Command::new` |

**为什么特征信号看种类不看总数**：`\b(?:store|state|config)\b` 在任何项目都能命中几百次，
按总数排会把真正的项目特征压下去。脚本对每个特征只计一次。

## 逐场景判据

| 场景 | 强结构 | 特征信号（命中任一种即相关） |
|---|---|---|
| `s-numerics` | — | `clamp(` · 循环上界非字面量 · `while(` · 浮点运算 · `>>> 0` · `isFinite` |
| `s-structures` | — | `new Float32Array(` · `prewarm/acquire/release` · 分桶 `Map` · 裸对象查表 · `split('.')` · `Object.assign` |
| `s-lifecycle` | — | `addEventListener` · `setInterval` · `createObjectURL` · `update/tick` · `dispose/destroy` |
| `s-contracts` | `docs/` · README | `export interface/type/class` · JSDoc |
| `s-state` | — | `localStorage` · `JSON.parse(` · store 对象 |
| `s-atomicity` | — | `can*/is*/should*` 判定函数 · 空 catch · 交易类动词 · `enabled: true` |
| `s-boundary` | — | `postMessage` · `addEventListener('message')` · `iframe` · `invoke/listen/emit` · `bridge` · `__TAURI` |
| `s-sandbox` | `plugins/` · `extensions/` | CSP · `sandbox=` · 凭据关键词 · 隔离 |
| `s-backend` | `src-tauri/` · `Cargo.toml` | `Command::new` · `std::fs::` · `TcpListener` · `thread::spawn` |
| `s-build` | `package.json` · `.github/` · `.gitignore` | `frontendDist` · `files: [` |
| `s-concurrency` | — | `Thread(` · `threading` · `asyncio` · `create_task` · `go func` · `WaitGroup` · `chan ` · `ExecutorService` · `synchronized` · `std::thread` · `Lock(` |
| `p-python` | `.py` 文件 | `def f(x=[])` · `except:` / `except Exception:` · `requirements.txt` · `pyproject.toml` |
| `p-cocos` | `cc.config.json` · `assets/` | `from 'cc'` · `_decorator` |

**语言包是并列维度，不是第 12 个风险面**：命中 `p-python` 不代表可以跳过 `s-state`。
正确读法是「风险面 × 语言包」——Python 项目同样可能有状态、并发、边界问题，
只是判据要用 Python 语义去看。

## 人工审核清单

脚本输出后，逐条过：

```
□ 强结构命中 → 基本可信，除非该目录本次不在审查范围（如只审前端但探测到 src-tauri/）
□ 弱结构命中 → 几乎每个项目都有，不能作为加载依据
□ 特征命中 → 看「命中了几种」而非「命中了几次」；再看证据里的具体数字
□ 命中 >4 个 → **不要截断**，分批审（每批 ≤4，一批审完再加载下一批）
□ 明显该中却没中 → 相关代码可能在被 SKIP_DIRS 排除的路径，手工补
```

## 增量路由（最易漏）

**精审中发现新的结构特征 → 回路由层补加载**：

```
审 numerics 时发现对象池          → 补 s-structures
审 contracts 时发现插件走 postMessage → 补 s-boundary
审 lifecycle 时发现 Rust 在起子进程   → 补 s-backend
审 state 时发现有多套主题清单        → 补 s-contracts（C-09）
```

每审完一个模块回头问一次：**这个模块里有没有我还没加载的场景的特征？**

## 扫描器与场景的对应

| 扫描器 | 覆盖场景 |
|---|---|
| `scan-ts.py` | numerics · structures · lifecycle · atomicity · state · contracts |
| `scan-app.py` | sandbox · boundary · backend · build · lifecycle |
| `scan-py.py` | **p-python · concurrency · backend · sandbox**（Python 语义，AST 驱动） |
| `doc-deliverable.py` | contracts（单元三件套） |
| `doc-promise.py` | contracts（文档承诺） |
| `dep-scan.py` | build（依赖合规） |
| `cocos-audit.py` | p-cocos |

**多语言仓库要跑多个扫描器**，用 TS 侧的 0 命中推断 Python 侧无问题是错的。

## ⚠ 扫描器的语言覆盖边界（0 命中 ≠ 没问题）

`scan-ts.py` / `scan-app.py` 的模式全部按 **TS/JS 语法**编写
（`scan-app.py` 兼收 Tauri/Rust 与构建配置）。对 **Python / Go / Java / C++** 源码，
它们输出的是 `模块: 0   文件: 0   命中候选: 0` ——
**这不是「已修好」，是压根没看**。

**判据**：跑完路由先确认源码主语言是否在扫描器支持集内。不在 → 扫描结果一律作废，
改走全人工精审，**并在报告里写明「本次为人工精审，扫描器不覆盖该语言」**。

**确认方法**（三步，缺一不可）：

1. 看扫描器输出的 `文件: N`。`N=0` 但源码目录非空 → 语言不支持，不是没命中
2. 跑 `--self-test` 区分「模式失效」与「语言不支持」：
   自检全通过而真实项目 0 文件 → 必是后者
3. 多语言仓库按语言**分别**下结论，
   不得用 TS 侧的 0 命中推断 Python 侧无问题

**已知实例**：单文件 Python 推送脚本，路由按正则命中 4 个场景（含误判的
「浮点运算×6」），扫描器 62/62 与 28/28 自检全通过却扫出 0 文件 0 候选；
人工精审加探针实测后仍确认 4 个 P1。
**自检通过只能证明模式本身没坏，不能证明它对当前语言有效。**
