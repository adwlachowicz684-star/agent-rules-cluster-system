# TP：确认的是 A，执行的是 A+B，且 B 被静音
def run(state, pr_number, yes):
    if not yes:
        ans = safe_input(f"推送到 {target}？(y/N) ").strip().lower()
        if ans != "y":
            return
    push_to_branch(target)
    # ← 用户只确认了「推送到分支」，这里连合并进主干一起做了，且不打印
    do_merge(state, pr_number, yes=True, quiet=True)
    print(f"已推送到 {target}")
