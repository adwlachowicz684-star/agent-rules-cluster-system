# AR-05 测试 harness 焊死实现与输出

- **TP 必须命中**：无测试框架 + `mod.X = ...` 打补丁 + stdout 里的 `ALL PASS`（tp.py）
- **TP2 必须命中**：换个模块别名 `module.` 同样命中（tp2.py）
- **FP 必须不命中**：已用 pytest（monkeypatch 是框架机制，不是打补丁）（fp.py）
- **FP2 必须不命中**：已用 unittest（fp2.py）

降级前提：文件里出现 `import pytest` / `import unittest` 即不报——
判的是「自建 harness」，不是「用了打补丁」。

实测来源：某工具 17 个 `test_*.py` / 8732 行 / **0 pytest**；
`run_all.py` 靠 `"ALL PASS" in out` 判定通过；
`test_pr_flow.GH` 被 14 个套件 import 当 fixture 库。
