# FP：双向写入，有反向分支
import os


def write_local(path, data, mode):
    with open(path, "wb") as f:
        f.write(data)
    if mode == "100755":
        os.chmod(path, 0o755)
    else:
        os.chmod(path, 0o644)


def apply_flag(state, enabled):
    state["feature"] = bool(enabled)      # 无条件赋值，天然双向
