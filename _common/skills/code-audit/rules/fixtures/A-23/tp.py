def push(state):
    commit = api("POST", "/git/commits", {...})    # ← 不可撤销的步骤，已成功
    save_state(state)                               # 可能抛 OSError
