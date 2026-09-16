# TP1：命中词语义模糊 + 丢弃原文
_NEED_UPDATE_HINTS = (
    "Base branch was modified",
    "not mergeable",              # ← 既是「分支旧」也是「真冲突」
    "Required status check",      # ← 与「分支旧」无关
)


def merge(n):
    try:
        return api("PUT", "/pulls/%d/merge" % n)
    except SystemExit as e:
        msg = str(e)
        if any(h.lower() in msg.lower() for h in _NEED_UPDATE_HINTS):
            # ← 原文被丢弃，只输出预设模板
            print("分支不是最新的，请点网页上的 Update branch")
            return None
        raise
