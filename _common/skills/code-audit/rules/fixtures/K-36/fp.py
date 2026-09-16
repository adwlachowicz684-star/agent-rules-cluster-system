# FP：命中词唯一 + 保留原文
_NEED_UPDATE = ("Base branch was modified", "not up to date")


def merge(n):
    try:
        return api("PUT", "/pulls/%d/merge" % n)
    except SystemExit as e:
        print("上游原文：%s" % e)            # ← 兜底信息保留
        if any(h in str(e) for h in _NEED_UPDATE):
            print("分支不是最新的，请点 Update branch")
            return None
        print("合并冲突，需人工解决")         # 其余按冲突处理
        return None
