# TP2（白名单外标识符）：URL 编码这一横切关注点漏了一个出口
def head_of(branch):
    # ← 直接拼路径，漏掉编码；含 / 之外的特殊字符（? # % 空格）会打到错误端点
    r = api("GET", f"/git/refs/heads/{branch}", allow_404=True)
    return (r or {}).get("object", {}).get("sha")


def drop(branch):
    api("DELETE", "/git/refs/heads/" + quote(branch, safe="/"))
