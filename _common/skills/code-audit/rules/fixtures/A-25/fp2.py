# FP2：模式字段双向可写，且重建路径接受显式指定
def apply_mode(state, opts):
    if opts.get("workflow") in ("pr", "direct"):    # ← 显式切换入口
        state["workflow"] = opts["workflow"]
    return state.get("workflow") or "pr"


def rebuild(state, head_sha, workflow=None):
    out = {"workflow": workflow or "pr", "files": {}}
    save(out)
