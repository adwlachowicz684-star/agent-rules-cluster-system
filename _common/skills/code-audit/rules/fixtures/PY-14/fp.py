# FP：物化后再消费，或只消费一次
import difflib

old = ["a", "b", "c", "d"]
new = ["a", "X", "c"]

d = list(difflib.unified_diff(old, new, n=0))               # 物化
add = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
sub = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
print(f"+{add} / -{sub}")          # → +1 / -2  ✓
