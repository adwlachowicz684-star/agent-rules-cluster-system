# TP1：生成器被二次消费 —— 第二次恒为空
import difflib

old = ["a", "b", "c", "d"]
new = ["a", "X", "c"]

d = difflib.unified_diff(old, new, n=0)                     # 生成器
add = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
sub = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
print(f"+{add} / -{sub}")          # → +1 / -0，真实为 +1 / -2
