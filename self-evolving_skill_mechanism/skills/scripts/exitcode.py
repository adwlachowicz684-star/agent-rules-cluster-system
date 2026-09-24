#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exitcode.py —— 退出码码表（反哺自 code-audit 的 AR-04 落地）

为什么需要
----------
工具只返回「成功 / 失败」时，自动化拿到退出码后**无法分流**：
「照提示做即可」与「真出错」在它眼里是一样的。

实测（引擎侧）两个真实失效：

    ① lint.py --json 模式下，有 error 也返回 0
       → CI 用它解析 = 永远绿灯，gate 形同虚设
    ② 环境未初始化（domains/ 不存在）与「真有问题」混在退出码 1 里
       → 无法区分「先去 init」和「库里有违规」

最危险的组合是把**「被防护拦下（改动未丢，照提示改即可）」当成错误**——
此时自动化的两种反应（重试、放弃）都是错的。

码表（与 code-audit 侧一致）
----------------------------
    0    成功
    1    工具自身出错（未预期异常 / 内部错误）
    2    用法或参数错误（拼错的 flag、缺必填参数）
         —— POSIX 约定，argparse 与 _flagguard 都用这个码，不动
    3    环境或依赖不满足（缺模块、目录未初始化）
         —— 照提示配置即可，不是工具的 bug
    4    被防护拦下（gate 扫出问题；改动未丢）
         —— 照提示改即可，**不要重试也不要放弃**
    130  被中断（Ctrl-C / SIGINT）

    ⚠ 关键区分：4 是「你的内容有问题，改它」；
      1 是「工具有问题，修它」。混了会让人去修工具。

用法
----
    from exitcode import OK, ERR, USAGE, ENV, BLOCKED, die, help_text

    die(ENV, "domains/ 未初始化，先跑 domain.py --init")
    sys.exit(BLOCKED)          # gate 模式扫出问题

`die()` 会把原因打到 stderr 再退出——**不要**静默退出码：
调用方（人 / CI）需要同时看到码和原因，只给码等于让人去猜。

接入率由 `lint.py --self-test` 的「退出码码表接入」用例守护
（新建设施最容易死在「造好了但没人接」——
见 `reference/audit/self-verification-silent.md` 第七条）。
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
    (BLOCKED, "被防护拦下（gate 扫出问题；改动未丢）—— 照提示改，不要重试也不要放弃"),
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
