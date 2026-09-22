# PY-13

清理/回滚用 `except Exception` —— **看起来规范**，
但 `KeyboardInterrupt` 是 `BaseException` 子类，Ctrl-C 时清理不执行。
与 PY-11（裸 `except:`）不同：本条指定了类型，只是类型不对。

- `tp.py` —— **必须命中**：`except Exception` 里做清理
- `fp.py` —— **必须不命中**：`finally` 或 `except BaseException`
