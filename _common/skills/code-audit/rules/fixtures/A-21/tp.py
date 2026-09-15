def collect(args):
    todo = []
    for p in args:
        rel = safe_rel(p)
        if rel is None:
            continue                               # ← 静默丢弃
        todo.append(rel)
    return todo
