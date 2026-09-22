# TP：粗粒度状态字段先判，细粒度命中表永不执行
_CI_PENDING_HINTS = (
    "Required status check",
    "required status checks",
    "checks have not",
)
_NEED_UPDATE_HINTS = ("Base branch was modified", "not up to date")


def classify(number, msg):
    """合并失败 → 归类。"""
    mergeable, mstate = _pr_mergeability(number)
    if mstate:
        s = mstate.lower()
        if s == "dirty":
            return "conflict"
        if s in ("behind", "blocked", "unstable", "draft"):
            # ← CI 未跑完时 mstate 恰是 blocked/unstable，
            #   于是下面的 _CI_PENDING_HINTS 永远走不到
            return "need_update"
    low = msg.lower()
    if any(h.lower() in low for h in _CI_PENDING_HINTS):   # 死代码
        return "ci_pending"
    if any(h.lower() in low for h in _NEED_UPDATE_HINTS):
        return "need_update"
    return "conflict"
