# A-19

补偿式清理未覆盖中断：`except Exception` 抓不到 `KeyboardInterrupt`
（它是 `BaseException` 子类）。**判清理用的异常类型**。

- `tp.py` —— **必须命中**：清理写在 `except Exception` 里
- `fp.py` —— **必须不命中**：用 `except BaseException` 或 `finally`

**与 PY-13 同源**：tp 形态完全相同（都是「清理用 `except Exception`」）。
PY-13 是 Python 形态、可被 `scan-py.py` 机扫的版本；
本条从「中断路径残留」的后果角度记录，语言无关。报一次即可。
