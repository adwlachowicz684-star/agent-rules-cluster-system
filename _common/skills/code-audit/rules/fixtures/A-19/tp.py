def push(entries):
    created = create_branch()
    try:
        api("POST", "/git/trees", {"tree": entries})
        api("POST", "/git/commits", {...})
    except Exception:                              # ← Ctrl-C 时不执行
        cleanup(created)
        raise
