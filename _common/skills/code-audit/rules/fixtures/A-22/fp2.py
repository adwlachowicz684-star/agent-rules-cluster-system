# FP2：所有出口统一走同一个编码函数
def _ref(branch):
    return "/git/refs/heads/" + quote(branch, safe="/")


def head_of(branch):
    r = api("GET", _ref(branch), allow_404=True)
    return (r or {}).get("object", {}).get("sha")


def drop(branch):
    api("DELETE", _ref(branch), allow_404=True)
