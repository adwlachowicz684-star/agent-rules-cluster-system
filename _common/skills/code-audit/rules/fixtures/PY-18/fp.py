# FP：文档字符串在函数体首位（或根本没有文档字符串）
def prune(state, grace_days=3):
    """分支体检：**只报告，绝不删除**。"""
    _report_conflict_artifacts()
    for b in list_branches():
        print(b)


def no_doc(x):
    return x + 1          # 没有文档字符串，不算
