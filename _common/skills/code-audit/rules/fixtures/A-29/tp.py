# TP：用「键存在」代替语义判定 → 过宽
KEYS = ("required_pull_request_reviews", "required_status_checks",
        "enforce_admins", "restrictions", "required_signatures",
        "required_linear_history", "allow_force_pushes",
        "allow_deletions", "required_conversation_resolution")


def refuse_direct_if_protected(branch):
    prot = branch_protection(branch)
    if prot is None:
        return
    if prot is False:
        return
    # ← GitHub 对任何受保护分支都返回 allow_force_pushes / allow_deletions，
    #   于是 any(...) 恒为真：只开了 CI 检查的仓库也被拒绝直推
    if not any(k in prot for k in KEYS):
        return
    raise SystemExit("已开启分支保护，--direct 会被服务端拒绝")
