# FP2：模式互斥的参数要么生效，要么显式报错
def push(opts, state, files):
    mode = "direct" if opts["direct"] else (state.get("workflow") or "pr")
    if mode == "direct" and (opts["b"] or opts["hold"]):
        raise SystemExit("--direct 与 -b / --hold 互斥：直推主干没有分支可复用")
    target = opts["b"] or state.get("task_branch") or "main"
    return send(target, files)
