def save(state, path):
    if os.path.exists(path):
        shutil.copy(path, path + ".bak")           # ← 固定名覆盖，始终 1 份
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)                          # ← 原子替换
