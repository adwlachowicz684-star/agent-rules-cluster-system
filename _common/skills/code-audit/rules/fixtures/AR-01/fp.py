def validate_state(state):
    """判定函数只返回结论，不打印、不终止 —— 可当库调用。"""
    return isinstance(state, dict)
