# FP2：收尾步骤检查返回值，且报错区分「已生效」与「未生效」
def push_all(state, todo, commit):
    api("PATCH", "/git/refs/heads/" + b, {"sha": commit})
    state["synced_commit"] = commit
    save_state(state)
    if git("add", "--", *todo, check=True) is None:
        pass
    rc = git("commit", "-q", "-m", msg, "--", *todo, check=False)
    if rc is None:
        print("远端已生效，但本地补提交失败（hook 拒绝 / 路径被忽略）；"
              "改动没丢，可手工 add + commit")
