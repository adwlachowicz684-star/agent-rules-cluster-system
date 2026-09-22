# TP2（白名单外标识符）：模式互斥的参数被静默忽略
# 用 -b 而非 --branch，函数名用 push() 而非 do_push()
def push(opts, state, files):
    mode = "direct" if opts["direct"] else (state.get("workflow") or "pr")
    target = "main"
    if mode == "pr":
        if opts["b"]:                 # ← 只有这一处读 -b
            target = opts["b"]
        elif opts["hold"] and state.get("task_branch"):
            target = state["task_branch"]
    # direct 模式下 -b / hold 全都不读，也不报错
    return send(target, files)
