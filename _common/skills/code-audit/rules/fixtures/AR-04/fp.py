def push():
    raise SystemExit(2)     # 2 = 被防护拦下


def pull():
    raise SystemExit(3)     # 3 = 冲突未解决


def merge():
    raise SystemExit(1)     # 1 = 真出错
