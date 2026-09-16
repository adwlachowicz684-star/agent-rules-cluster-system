# TP2：只丢弃原文（命中词本身没问题）
_NEED_UPDATE = ("Base branch was modified", "not up to date")


def merge(n):
    try:
        return api("PUT", "/pulls/%d/merge" % n)
    except SystemExit as e:
        if any(h in str(e) for h in _NEED_UPDATE):
            print("分支不是最新的，请点 Update branch")   # ← 原文未保留
            return None
        raise
