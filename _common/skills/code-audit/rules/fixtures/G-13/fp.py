# FP：把「等外部就绪」显式化（带超时与进度，且不是固定 sleep）
def push(state, todo, msg, wait=False, timeout=600):
    commit = build_and_push(todo, msg)
    pr = ensure_pr(state["task_branch"], msg)
    if wait:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = check_runs(commit)          # 外部就绪信号
            print(f"  · checks: {st}")
            if st in ("success", "failure"):
                break
            time.sleep(min(30, max(5, (deadline - time.time()) / 10)))
        else:
            print("等待超时，改动在分支上没丢；就绪后跑 --merge")
            return commit
    do_merge(state, pr["number"], yes=True, quiet=True)
    return commit
