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
| `p-cocos` | `cc.config.json` · `assets/` | `from 'cc'` · `_decorator` |

## 人工审核清单

脚本输出后，逐条过：

```
□ 强结构命中 → 基本可信，除非该目录本次不在审查范围（如只审前端但探测到 src-tauri/）
□ 弱结构命中 → 几乎每个项目都有，不能作为加载依据
□ 特征命中 → 看「命中了几种」而非「命中了几次」；再看证据里的具体数字
□ 命中 >4 个 → 按 P0 密度取前 4，其余列候选
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
| `doc-deliverable.py` | contracts（单元三件套） |
| `doc-promise.py` | contracts（文档承诺） |
| `dep-scan.py` | build（依赖合规） |
| `cocos-audit.py` | p-cocos |
