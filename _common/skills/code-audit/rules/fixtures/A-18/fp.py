def push(entries):
    branch_missing = True
    api("POST", "/git/refs", {"ref": "refs/heads/task/x", "sha": head})
    try:
        tree = api("POST", "/git/trees", {"tree": entries})
        if "sha" not in tree:
            raise SystemExit("创建 tree 失败")
        api("POST", "/git/commits", {"tree": tree["sha"]})
    except BaseException:
        if branch_missing:
            delete_branch("task/x")                # ← 补偿式清理
        raise
