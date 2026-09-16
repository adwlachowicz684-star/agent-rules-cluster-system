# TP1：输入方向缺 errors=
import os
import subprocess


def hash_symlink(full):
    out = subprocess.run(["git", "-C", "/repo", "hash-object", "--stdin"],
                         input=os.readlink(full),      # ← 输入方向严格 UTF-8
                         capture_output=True, text=True)
    return out.stdout.strip()
