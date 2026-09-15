def collect(args):
    todo, skipped = [], []
    for p in args:
        rel = safe_rel(p)
        if rel is None:
            skipped.append((p, "不在仓库内或类型不支持"))
            continue
        todo.append(rel)
    if skipped:
        print("已忽略：")
        for p, why in skipped:
            print(f"  {p}（{why}）")                # ← 逐条告知
    return todo
