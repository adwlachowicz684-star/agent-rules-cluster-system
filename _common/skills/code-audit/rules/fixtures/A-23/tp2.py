# TP2：主操作已生效，收尾步骤失败但**连返回值都没检查**
def push_all(state, todo, commit):
    api("PATCH", "/git/refs/heads/" + b, {"sha": commit})     # 不可撤销的一步
    state["synced_commit"] = commit
    save_state(state)
    git("add", "--", *todo)                 # ← 失败只打印警告
    git("commit", "-q", "-m", msg, "--", *todo)
    print("已推送")                          # ← 没说本地提交是否成功
