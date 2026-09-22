# TP2：只修输出、漏输入 —— 最易误判为「已修」
import subprocess

# 输出方向：正确
subprocess.run(["git", "status"], capture_output=True,
               text=True, errors="surrogateescape")

# 输入方向：漏（同一文件里，几十行外）
subprocess.run(["git", "hash-object", "--stdin"],
               input=s, capture_output=True, text=True)
