# AR-01 判定与输出 / 副作用耦合

- **TP 必须命中**：非 CLI 层 `raise SystemExit`（tp.py）
- **TP2 必须命中**：命名不在 `check*`/`validate*` 白名单内，但 `return bool` + `print`（tp2.py）
- **FP 必须不命中**：判定函数只 `return`，不打印不终止（fp.py）
- **FP2 必须不命中**：白名单外命名且无可疑输出（fp2.py）

⚠ TP2 是召回率样本：只靠函数名白名单会漏掉全部自定义命名的判定函数
（同类实测：TS-O02 白名单内 5/5 命中、白名单外 0/8）。

实测来源：某推送工具 `validate_state()` / `_write_local()` 深处直接 `SystemExit(str)`，
340 处 `print` 散布在 `pull()` / `prune()` 等领域函数里。
