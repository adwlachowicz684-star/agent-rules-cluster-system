# TP：推完立刻合并，外部 checks 还没跑，且无等待入口
def push(state, todo, msg):
    commit = build_and_push(todo, msg)
    pr = ensure_pr(state["task_branch"], msg)
    # ← checks 由外部系统异步执行，此刻必然未就绪
    do_merge(state, pr["number"], yes=True, quiet=True)
    print("已合并进主干")
    return commit
