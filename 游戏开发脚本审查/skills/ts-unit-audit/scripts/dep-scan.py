#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dep-scan.py —— 模块依赖合规扫描

判据：每个模块只应依赖「基础设施目录」与「同目录文件」。
模块 → 模块的横向依赖会破坏「单目录拷走即可用」的可复用性。

用法：
    python3 dep-scan.py --src=<源码根>
    python3 dep-scan.py --src=. --infra=_core,ds,utils
    python3 dep-scan.py --src=. --json
    python3 dep-scan.py --src=. --violations-only
"""

import re
import os
import sys
import json

_flags = [a for a in sys.argv[1:] if a.startswith('--')]

SRC = None
for f in _flags:
    if f.startswith('--src='):
        SRC = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))

if SRC is None:
    for cand in ('src', '.'):
        if os.path.isdir(cand):
            SRC = os.path.abspath(cand)
            break
if SRC is None or not os.path.isdir(SRC):
    print('找不到源码目录，请用 --src=<路径> 指定')
    sys.exit(1)

INFRA = set()
for f in _flags:
    if f.startswith('--infra='):
        INFRA = {x.strip() for x in f.split('=', 1)[1].split(',') if x.strip()}
if not INFRA:
    INFRA = {'_core', 'ds', 'core', 'utils', 'shared', 'common'}

SKIP_DIRS = {'tests', 'test', 'examples', 'example', 'scripts', 'typings',
             'node_modules', '.build', 'build', 'dist', 'audit', 'docs',
             '__tests__', '__pycache__', '.git'}
SOURCE_EXT = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')

BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)
LINE_COMMENT = re.compile(r'^\s*//.*$', re.M)

IMPORT_RE = re.compile(
    r'''^[ \t]*(?:import|export)\s+(?:type\s+)?[\s\S]*?from\s+['"]([^'"]+)['"]''', re.M)


def strip_comments(src):
    def _keep(m):
        return '\n' * m.group(0).count('\n')
    return LINE_COMMENT.sub('', BLOCK_COMMENT.sub(_keep, src))


def module_of(rel_path):
    parts = rel_path.replace('\\', '/').split('/')
    return parts[0] if len(parts) > 1 else '(root)'


def scan():
    deps, detail, all_modules = {}, [], set()
    for d in sorted(os.listdir(SRC)):
        p = os.path.join(SRC, d)
        if not os.path.isdir(p) or d in SKIP_DIRS:
            continue
        if d.startswith('.') or (d.startswith('_') and d not in INFRA):
            continue
        files = [f for f in os.listdir(p) if f.endswith(SOURCE_EXT)]
        if files:
            all_modules.add(d)
        for fn in sorted(files):
            rel = os.path.join(d, fn)
            src = strip_comments(open(os.path.join(SRC, rel), encoding='utf-8',
                                      errors='ignore').read())
            for m in IMPORT_RE.finditer(src):
                spec = m.group(1)
                if not spec.startswith('.'):
                    continue
                tgt = module_of(os.path.normpath(os.path.join(d, spec)))
                if tgt == d:
                    continue
                kind = 'type-only' if re.search(r'\btype\s+', m.group(0)) else 'value'
                deps.setdefault(d, set()).add(tgt)
                detail.append((d, tgt, fn, spec, kind))
    return all_modules, deps, detail


def main():
    all_modules, deps, detail = scan()
    if not all_modules:
        print('未找到模块目录（SRC=%s）。扁平结构请改用 pattern-scan.py --flat' % SRC)
        return

    violations, zero_dep, infra_users = [], [], 0
    for m in sorted(all_modules):
        tgts = deps.get(m, set())
        bad = sorted(t for t in tgts if t not in INFRA)
        if bad:
            violations.append((m, bad))
        elif not tgts:
            zero_dep.append(m)
        else:
            infra_users += 1

    reverse = [(m, t) for m, tg in deps.items() if m in INFRA for t in sorted(tg)]

    if '--json' in _flags:
        json.dump({
            'src': SRC, 'infra': sorted(INFRA), 'modules': len(all_modules),
            'violations': [{'module': m, 'depends_on': b} for m, b in violations],
            'zero_dep_modules': zero_dep, 'infra_reverse_deps': reverse,
            'detail': [{'from': a, 'to': b, 'file': c, 'spec': d, 'kind': e}
                       for a, b, c, d, e in detail],
        }, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return

    if '--violations-only' in _flags:
        if not violations:
            print('无横向依赖违规')
            return
        for m, bad in violations:
            for b in bad:
                for h in [x for x in detail if x[0] == m and x[1] == b]:
                    print('%s -> %s  [%s]  %s' % (m, b, h[4], h[2]))
                    print('    import ... from "%s"' % h[3])
        return

    print('=' * 74)
    print('依赖合规扫描 · %d 个模块 · 基础设施=%s · src=%s'
          % (len(all_modules), ','.join(sorted(INFRA)) or '(无)', SRC))
    print('=' * 74)

    print('\n[1] 被依赖目标分布')
    cnt = {}
    for m, tgts in deps.items():
        for t in tgts:
            cnt[t] = cnt.get(t, 0) + 1
    for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
        print('  %-22s 被 %3d 个模块依赖   %s' % (k, v, 'OK 基础设施' if k in INFRA else '违规 横向依赖'))

    print('\n[2] 横向依赖违规')
    if not violations:
        print('  无')
    for m, bad in violations:
        for b in bad:
            for h in [x for x in detail if x[0] == m and x[1] == b]:
                print('  %s -> %s  [%s]  %s' % (m, b, h[4], h[2]))
                print('      import ... from "%s"' % h[3])

    print('\n[3] 基础设施反向依赖（应为 0）')
    if not reverse:
        print('  无')
    for m, t in reverse:
        print('  %s -> %s   <- 基础设施不得依赖业务模块' % (m, t))

    print('\n[4] 统计')
    print('  仅依赖基础设施的模块：%d' % infra_users)
    print('  零依赖模块（最易独立分发）：%d' % len(zero_dep))
    print('  存在横向依赖的模块：%d' % len(violations))
    if zero_dep:
        print('\n  零依赖模块清单：')
        for i in range(0, len(zero_dep), 6):
            print('    ' + '  '.join(zero_dep[i:i + 6]))

    print('\n' + '=' * 74)
    print('判据：模块只应依赖基础设施目录与同目录文件。')
    print('横向依赖使「单目录拷走」失效，需改为依赖注入或抽到基础设施。')
    print('=' * 74)


if __name__ == '__main__':
    main()
