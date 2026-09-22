def audit_repo_state(s):
    # 同样白名单外命名，但既无 print 也无 SystemExit
    return bool(s)
