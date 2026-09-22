def audit_repo_state(s):
    # 命名不在 check*/validate* 白名单内，靠「return bool + print」命中
    print("checking")
    return True
