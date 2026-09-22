# FP：粗粒度只判语义唯一的取值，其余下落给细粒度命中表
_CI_PENDING_HINTS = ("Required status check", "checks have not")
_NEED_UPDATE_HINTS = ("Base branch was modified", "not up to date")


def classify(number, msg):
    mergeable, mstate = _pr_mergeability(number)
    if mstate:
        s = mstate.lower()
        if s == "dirty":
            return "conflict"          # 语义唯一
        if s == "behind":              # 语义唯一
            return "need_update"
        # blocked / unstable / unknown 可能由多种成因产生 → 交给下面细分
    low = msg.lower()
    if any(h.lower() in low for h in _CI_PENDING_HINTS):
        return "ci_pending"
    if any(h.lower() in low for h in _NEED_UPDATE_HINTS):
        return "need_update"
    return "conflict"
