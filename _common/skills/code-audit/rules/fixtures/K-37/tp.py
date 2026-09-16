# TP：设了 per_page 不翻页，且结果用于完整性判定
def prune():
    branches = api("GET", "/branches?per_page=100") or []
    for b in branches:
        report(b)                  # ← 超 100 个分支时静默漏报
