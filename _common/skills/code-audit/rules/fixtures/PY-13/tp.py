def push():
    tmp = mkstemp()
    try:
        write(tmp)
        commit()
    except Exception:                               # ← Ctrl-C 时清理不执行
        os.unlink(tmp)
        raise
