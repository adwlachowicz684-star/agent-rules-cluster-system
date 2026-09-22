#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_flagguard.py —— 未知 flag 必须报错，不能静默忽略。

为什么需要：本仓库的脚本多用**手写 sys.argv 解析**（不是 argparse），
典型写法是 `if '--foo' in sys.argv` 或 `x for x in sys.argv if x.startswith('--xx=')`。
这种写法下，拼错的 flag 会被**完全无视**，脚本照常跑完并返回 0。

实测：`rule-registry.py --self-test` 会跑默认列表命令并退出 0 ——
用户以为跑了自检、CI 以为过了，实际什么都没验。
「有自检的暗示但静默不执行」比没有自检更危险：它给出一个绿色的空信号。

用法（每个脚本在 main() 开头调一次）：

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _flagguard import guard
    guard(sys.argv, {'--src=', '--json', '--violations-only'})

前缀型（`--src=xxx`）用带等号的形式声明，值不参与校验。
"""
import sys


def guard(argv, known, script=None):
    """发现未知 flag 就打印可用列表并 exit(2)。"""
    seen = set()
    for a in argv[1:]:
        if not a.startswith('--'):
            continue
        key = a.split('=', 1)[0]
        if key in known:
            continue
        # 前缀型：--src=xxx 声明为 '--src='，也接受 '--src'
        if (key + '=') in known:
            continue
        seen.add(key)
    if not seen:
        return
    name = script or '本脚本'
    sys.stderr.write(
        '%s：未知参数 %s\n'
        '可用参数：%s\n'
        % (name, ' '.join(sorted(seen)), ' '.join(sorted(known))))
    sys.exit(2)
