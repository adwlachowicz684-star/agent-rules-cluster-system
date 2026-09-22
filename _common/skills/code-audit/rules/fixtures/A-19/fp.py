def push(entries):
    created = create_branch()
    try:
        api("POST", "/git/trees", {"tree": entries})
        api("POST", "/git/commits", {...})
    except BaseException:                          # ← Ctrl-C 也执行
        cleanup(created)
        raise
