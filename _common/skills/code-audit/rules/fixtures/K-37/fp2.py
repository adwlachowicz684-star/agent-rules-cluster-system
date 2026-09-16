# FP2：不翻页但明确告警截断
def list_first_page(path):
    r = api("GET", "%s&per_page=100" % path) or []
    if len(r) == 100:
        print("⚠ 结果可能不完整（达到单页上限）")
    return r
