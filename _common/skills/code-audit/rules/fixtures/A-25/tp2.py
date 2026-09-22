# TP2（白名单外标识符）：多值模式字段单向 + 重建继承旧值 = 无出口
def apply_mode(state, opts):
    mode = "direct" if opts["direct"] else (state.get("workflow") or "pr")
    if opts["direct"] and state.get("workflow") != "direct":
        state["workflow"] = "direct"     # ← 只有进来的一条路，没有出去的路
    return mode


def rebuild(state, head_sha):
    prev = load_prev() or {}
    out = {
        "workflow": prev.get("workflow") or "pr",   # ← 重建继承旧值，也切不回去
        "files": {},
    }
    save(out)
