# FP：确认提示覆盖全部写操作，或后续写操作各自受控
def run(state, pr_number, yes):
    if not yes:
        ans = safe_input(
            f"推送到 {target} 并自动合并进 {BRANCH}？(y/N) ").strip().lower()
        if ans != "y":
            return
    push_to_branch(target)
    do_merge(state, pr_number, yes=True, quiet=False)
