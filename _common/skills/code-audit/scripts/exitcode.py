#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exitcode.py —— 退出码码表（AR-04 的落地）

为什么需要
----------
工具只返回「成功 / 失败」时，自动化拿到退出码后**无法分流**：
「照提示做即可」与「真出错」在它眼里是一样的。

最危险的组合是把**「被防护拦下（改动未丢，照提示处理即可）」当成错误**——
此时自动化的两种反应（重试、放弃）都是错的：重试会再撞一次同样的拦截，
放弃会让人以为数据丢了。

码表（与 `references/s-architecture.md` AR-04 一致，略有扩展）
-------------------------------------------------------------
    0    成功
    1    工具自身出错（未预期异常 / 内部错误）
    2    用法或参数错误（拼错的 flag、缺必填参数）
         —— POSIX 约定，argparse 与 _flagguard 都用这个码，不动
    3    环境或依赖不满足（缺模块、目录未初始化）
         —— 照提示配置即可，不是工具的 bug
    4    被防护拦下（gate 模式扫出问题；改动未丢）
         —— 照提示处理即可，**不要重试也不要放弃**
    130  被中断（Ctrl-C / SIGINT）

    与判据原文的偏离：判据写「2 被防护拦下 / 3 冲突未解决」，
    但 2 在本仓库已是参数错误的既成事实（argparse 约定 + _flagguard），
    改它会破坏 CI 里已有的判断。故把「被拦下」挪到 4，3 留给环境问题。

用法
----
    from exitcode import OK, ERR, USAGE, ENV, BLOCKED, die

    die(ENV, "找不到 domain.py，请设置 PYTHONPATH")

`die()` 会把原因打到 stderr 再退出——**不要**静默退出码：
调用方（人 / CI）需要同时看到码和原因，只给码等于让人去猜。

接入率由 `check-list-drift.py` 第 6 项守护（新建设施最容易死在
「造好了但没人接」——见 self-verification.md 第七条）。
"""

OK = 0
ERR = 1
USAGE = 2
ENV = 3
BLOCKED = 4
INTERRUPTED = 130

TABLE = [
    (OK, "成功"),
    (ERR, "工具自身出错（未预期异常）"),
    (USAGE, "用法或参数错误（拼错的 flag、缺参数）—— 照提示改命令"),
    (ENV, "环境或依赖不满足（缺模块、目录未初始化）—— 照提示配置"),
    (BLOCKED, "被防护拦下（改动未丢）—— 照提示处理，不要重试也不要放弃"),
    (INTERRUPTED, "被中断（Ctrl-C）"),
]


def die(code, msg=""):
    """打印原因到 stderr 后退出。msg 为空时也退出，但不静默——打印码的含义。"""
    import sys
    if msg:
        sys.stderr.write("%s\n" % msg)
    name = dict(TABLE).get(code, "")
    sys.stderr.write("退出码 %d（%s）\n" % (code, name))
    sys.exit(code)


def help_text():
    """给 --help 用的码表文本。"""
    lines = ["退出码："]
    for code, desc in TABLE:
        lines.append("  %-3d %s" % (code, desc))
    return "\n".join(lines)


if __name__ == "__main__":
    print(help_text())
