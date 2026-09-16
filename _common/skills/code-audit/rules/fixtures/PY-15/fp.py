# FP：传 bytes 绕开文本层，或双端显式 errors
import os
import subprocess


def hash_symlink_bytes(full):
    return subprocess.run(["git", "hash-object", "--stdin"],
                          input=os.readlink(full).encode("utf-8", "surrogateescape"),
                          capture_output=True)


def hash_symlink_errors(full, s):
    return subprocess.run(["git", "hash-object", "--stdin"], input=s,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="surrogateescape")
