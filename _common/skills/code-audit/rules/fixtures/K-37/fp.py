# FP1：翻页
def list_all(path):
    out, page = [], 1
    while True:
        batch = api("GET", "%s&per_page=100&page=%d" % (path, page)) or []
        out += batch
        if len(batch) < 100:
            break
        page += 1
    return out
