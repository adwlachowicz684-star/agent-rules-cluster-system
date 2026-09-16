# TP：单向属性写入 —— 只升不降
import os


def write_local(path, data, mode):
    with open(path, "wb") as f:
        f.write(data)
    if mode == "100755":
        os.chmod(path, 0o755)
    # ← 无 else：mode == "100644" 时不回退权限位


def apply_flag(state, enabled):
    if enabled:
        state["feature"] = True
    # ← 无 else：从不置回 False
