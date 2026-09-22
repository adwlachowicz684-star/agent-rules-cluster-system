def save(state, path):
    if os.path.exists(path):
        n = len(glob.glob(path + ".*.bak"))        # ← 序号递增，只增不减
        shutil.copy(path, f"{path}.{n}.bak")
    with open(path, "w") as f:
        json.dump(state, f)
