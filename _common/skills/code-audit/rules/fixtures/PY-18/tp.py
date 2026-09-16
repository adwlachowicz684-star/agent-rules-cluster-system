# TP：文档字符串写在第一条语句之后 → 变成死表达式
import os


def prune(state, grace_days=3):
    _report_conflict_artifacts()
    """分支体检：**只报告，绝不删除**。

    判据用「合并状态 + 活动状态」，不用「N 天没用」——
    一个开发到一半的 WIP 分支，恰恰就是「开着、没合并、可能好几天没动」。
    """
    if not state:
        return
    for b in list_branches():
        print(b)


class Runner:
    def start(self):
        self._boot()
        """启动编排器。带断点续跑。"""
        return self._run()
