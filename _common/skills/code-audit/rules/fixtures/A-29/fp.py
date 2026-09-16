# FP：判到取值层，且只把真正阻止本操作的规则作为依据
BLOCKING = ("required_pull_request_reviews", "restrictions")


def refuse_direct_if_protected(branch):
    prot = branch_protection(branch)
    if not isinstance(prot, dict):
        return
    # 读取值：GitHub 未开启时该键为 None / {"enabled": False}
    if any(prot.get(k) for k in BLOCKING):
        raise SystemExit("已开启 PR 强制或推送限制，--direct 会被拒绝")
