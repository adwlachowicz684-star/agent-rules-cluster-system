def validate_state(state):
    """非 CLI 层的判定函数：直接终止 + 直接打印，结论无法被复用。"""
    if not isinstance(state, dict):
        raise SystemExit("状态非法")
    print("状态校验通过")
    return True
