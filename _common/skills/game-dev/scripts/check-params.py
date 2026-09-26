#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参数登记检查（check-params.py）

查什么：
    flow 层各域「## 4. 参数登记」表 与 代码块里标了「待实测」的常量，
    两边是否对得上。

为什么查：
    流程文档里有大量"需要实测才能定"的数值（手感窗口、并发上限、阈值）。
    ⛔ 这些值一旦只在代码里标了"待实测"却没进参数表，就**无处追踪**：
       没人知道它没测、改了也没地方回填、回归时不知道要重测哪些。
    这正是 GA-08「占位值当最终值」要防的 —— 本脚本是它的机械检查。

判据：
    代码块里标了「待实测」的常量名 → 必须在本域参数表里出现（可反查）。

⛔ 反向不成立：参数表里写中文名是可以的（"土狼时间窗"），
   但代码里用的是常量名，两边必须对得上，否则读者无法互相定位。

用法：
    python3 scripts/check-params.py [--json]
退出码：0 无问题 / 1 有未登记常量
"""

import os
import re
import sys
import glob
import json as _json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
FLOW = os.path.join(ROOT, 'references', 'flow')

CONST = re.compile(r'const\s+([A-Z][A-Z0-9_]{2,})\s*:?=[^\n]*待实测')


def domain_of(path):
    rel = os.path.relpath(path, FLOW)
    return rel.split(os.sep)[1] if os.sep in rel else rel.split('/')[0]


def scan():
    """返回 (登记行数, [(域, 常量) 未登记], [(域, 文件) 域内无参数登记节但有待实测常量])"""
    rows = []          # (域, 行内容)
    pending = {}       # 域 -> set(常量)
    for f in sorted(glob.glob(os.path.join(FLOW, '**', '*.md'), recursive=True)):
        if os.path.basename(f).startswith('_'):
            continue
        dom = domain_of(f)
        txt = open(f, encoding='utf-8').read()
        for l in txt.split('\n'):
            if l.startswith('|') and ('待实测' in l or '实测值' in l or '待定' in l):
                cells = [c.strip() for c in l.strip().strip('|').split('|')]
                if len(cells) >= 3 and not set(cells[0]) <= set('-: '):
                    rows.append((dom, l))
        for blk in re.findall(r'```gdscript\n(.*?)```', txt, re.S):
            for m in CONST.finditer(blk):
                pending.setdefault(dom, set()).add(m.group(1))

    missing = []
    nosection = []
    reg_by_dom = {}
    for dom, l in rows:
        reg_by_dom.setdefault(dom, []).append(l)
    for dom, cs in sorted(pending.items()):
        reg = '\n'.join(reg_by_dom.get(dom, []))
        if not reg:
            nosection.append((dom, sorted(cs)))
            continue
        for c in sorted(cs):
            if c not in reg:
                missing.append((dom, c))
    return len(rows), missing, nosection


def main():
    n, missing, nosection = scan()
    if '--json' in sys.argv:
        print(_json.dumps({'rows': n, 'missing': missing, 'nosection': nosection},
                          ensure_ascii=False))
        return 1 if (missing or nosection) else 0
    print('参数登记检查：登记行 %d 条' % n)
    if missing:
        print('\n⛔ 标了「待实测」但没进本域参数表的常量 %d 个：' % len(missing))
        for dom, c in missing:
            print('   ✗ %s: %s' % (dom, c))
    if nosection:
        print('\n⛔ 本域有待实测常量但没有参数登记节：')
        for dom, cs in nosection:
            print('   ✗ %s: %s' % (dom, ', '.join(cs)))
    if not missing and not nosection:
        print('全部「待实测」常量都已在参数表登记 ✓')
    return 1 if (missing or nosection) else 0


if __name__ == '__main__':
    sys.exit(main())
