def push(entries):
    api("POST", "/git/refs", {"ref": "refs/heads/task/x", "sha": head})
    tree = api("POST", "/git/trees", {"tree": entries})
    if "sha" not in tree:
        raise SystemExit("创建 tree 失败")          # ← 分支已建，没人删
    api("POST", "/git/commits", {"tree": tree["sha"]})
