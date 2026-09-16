# TP2：生成器用于流程判定（升 P0 场景）
import re

pat = r"TODO"
text = "TODO here"

matches = re.finditer(pat, text)
if any(matches):                       # 第一次消费（耗尽）
    count = sum(1 for _ in matches)    # 恒为 0
    if count > 1:
        raise SystemExit("多处 TODO")   # 永远不触发 → 判定静默失效
