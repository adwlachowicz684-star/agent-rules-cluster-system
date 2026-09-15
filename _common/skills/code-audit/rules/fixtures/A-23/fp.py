def push(state):
    commit = api("POST", "/git/commits", {...})
    try:
        save_state(state)
    except OSError as e:
        raise SystemExit(
            f"✅ 已推送到远端（{commit['sha'][:8]}）。\n"
            f"⚠️  但基线写入失败：{e.strerror}\n"
            f"   请不要用 --reset-baseline —— 那会丢掉防覆盖的参照。\n"
            f"   腾出空间后重跑本命令即可。")
