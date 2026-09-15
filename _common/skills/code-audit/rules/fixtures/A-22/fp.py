def with_retry(fn):                                # ← 抽成统一装饰器
    def wrapper(*a, **k):
        for attempt in range(3):
            try:
                return fn(*a, **k)
            except TransientError:
                time.sleep(2 ** attempt)
    return wrapper

@with_retry
def api(method, path, payload=None, raw=False):     # ← 所有出口共用
    return _request(method, path, payload)
