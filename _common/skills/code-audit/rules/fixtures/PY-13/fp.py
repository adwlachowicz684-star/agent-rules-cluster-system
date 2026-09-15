def push():
    tmp = mkstemp()
    try:
        write(tmp)
        commit()
    finally:                                        # ← 中断时也执行
        os.unlink(tmp)
