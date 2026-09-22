#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cocos_audit.py —— 转发壳，真正实现在 _common/skills/code-audit/scripts/cocos-audit.py。

为什么改成壳：本文件原先是那份脚本的**逐字节副本**（md5 完全相同）。
两份副本意味着修 bug 只改一处、另一处静默过期 —— 这正是 MIGRATED.md 里
批判过的重复问题在脚本层的重演。canonical 实现只保留一份，这里只做转发。

本文件不删除是因为 SKILLS/_commands.md 的 C060~C067 仍以
`python3 scripts/cocos_audit.py` 的形式引用它；直接删会打断这些命令。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_CANON = os.path.normpath(os.path.join(
    _HERE, '..', '..', '..', '_common', 'skills', 'code-audit',
    'scripts', 'cocos-audit.py'))

if not os.path.isfile(_CANON):
    sys.stderr.write(
        '找不到 canonical 实现：%s\n'
        '确认 _common/skills/code-audit/ 是否完整。\n' % _CANON)
    sys.exit(2)

# 用 runpy 在同进程内跑，保证 sys.argv 与退出码（P0 → 1，CI 卡口依赖它）原样透传
import runpy
sys.argv[0] = _CANON
runpy.run_path(_CANON, run_name='__main__')
