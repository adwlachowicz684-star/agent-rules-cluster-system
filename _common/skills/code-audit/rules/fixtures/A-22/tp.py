def api(method, path, payload=None, raw=False):
    if raw:
        # 与 JSON 分支同一套重试语义
        return _request(method, path, payload, retries=1)   # ← 注释说同一套，实际没有
    for attempt in range(3):                                 # ← 主路径有退避重试
        try:
            return _request(method, path, payload)
        except TransientError:
            time.sleep(2 ** attempt)
