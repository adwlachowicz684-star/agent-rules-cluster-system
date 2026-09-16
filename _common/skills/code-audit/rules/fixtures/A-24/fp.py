# FP：物理隔离到专属目录，不进用户数据区
import os
import tempfile

AUX_DIR = "/var/lib/mytool/aux"
os.makedirs(AUX_DIR, exist_ok=True)


def on_conflict(rel, remote_bytes):
    safe = rel.replace(os.sep, "__")       # 扁平化，避免目录穿越
    with open(os.path.join(AUX_DIR, safe + ".remote"), "wb") as f:
        f.write(remote_bytes)


def on_conflict_tmp(rel, remote_bytes):
    d = tempfile.mkdtemp(prefix="mytool-aux-")
    with open(os.path.join(d, "conflict.remote"), "wb") as f:
        f.write(remote_bytes)
