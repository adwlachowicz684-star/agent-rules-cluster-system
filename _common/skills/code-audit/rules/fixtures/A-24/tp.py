# TP：工具产物写在用户数据目录 + 用户可能采用的命名模式
import os

ROOT = "/workspace/user-repo"     # 用户可编辑目录


def on_conflict(rel, remote_bytes):
    # ← 直接写用户数据目录，无存在性检查
    with open(os.path.join(ROOT, rel + ".remote"), "wb") as f:
        f.write(remote_bytes)


def on_conflict_copy(rel, remote_bytes):
    with open(os.path.join(ROOT, rel + ".base"), "wb") as f:
        f.write(remote_bytes)
