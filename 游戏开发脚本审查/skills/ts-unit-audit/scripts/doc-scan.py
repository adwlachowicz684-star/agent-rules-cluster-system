#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc-scan.py —— 单元交付物「三件套」完整性扫描

判据：每个单元应当同时具备 README、测试、可运行示例。

用法：
    python3 doc-scan.py --src=<源码根>
    python3 doc-scan.py --src=<根> --tests=tests --examples=examples
    python3 doc-scan.py --src=<根> --missing-only
    python3 doc-scan.py --src=<根> --strict      # 要求专属示例文件
    python3 doc-scan.py --src=<根> --json

示例判定分三态：
    dedicated = 有以该单元命名的专属示例文件（最理想）
    shared    = 仅被批量/综合示例间接引用（能跑通，但不专属）
    无        = 完全没有被任何示例引用（确定缺失）

默认口径：被任何示例引用即算「有」。--strict 下才要求专属文件。
不同仓库的示例组织约定不同，判据错了会得出无意义结论 —— 先确认约定再选模式。
"""

import os
import re
import sys
import json

_flags = [a for a in sys.argv[1:] if a.startswith('--')]

SRC = None
TESTS_DIR = 'tests'
EXAMPLES_DIR = 'examples'
for f in _flags:
    if f.startswith('--src='):
        SRC = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
    elif f.startswith('--tests='):
        TESTS_DIR = f.split('=', 1)[1]
    elif f.startswith('--examples='):
        EXAMPLES_DIR = f.split('=', 1)[1]

if SRC is None:
    for cand in ('src', '.'):
        if os.path.isdir(cand):
            SRC = os.path.abspath(cand)
            break
if SRC is None or not os.path.isdir(SRC):
    print('找不到源码目录，请用 --src=<路径> 指定')
    sys.exit(1)

SKIP_DIRS = {'node_modules', '.build', 'build', 'dist', '__pycache__', '.git',
             'examples', 'example', 'tests', 'test', 'scripts', 'typings',
             'docs', 'audit', 'assets'}
SOURCE_EXT = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')


def _files_in(d):
    return [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))] if os.path.isdir(d) else []


def _match(files, name):
    key = name.replace('-', '').replace('_', '').lower()
    for f in files:
        if key in f.replace('-', '').replace('_', '').lower():
            return f
    return None


def _content_match(dirpath, files, name):
    pat = re.compile(r'[\'\"][^\'\"]*[/\\]?' + re.escape(name) + r'[/\\][^\'\"]+[\'\"]')
    for f in files:
        if not f.endswith(SOURCE_EXT):
            continue
        try:
            txt = open(os.path.join(dirpath, f), encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        if pat.search(txt):
            return f
    return None


def main():
    modules = []
    for d in sorted(os.listdir(SRC)):
        p = os.path.join(SRC, d)
        if not os.path.isdir(p) or d in SKIP_DIRS or d.startswith('.') or d.startswith('_'):
            continue
        if any(f.endswith(SOURCE_EXT) for f in os.listdir(p)):
            modules.append(d)

    roots = [SRC, os.path.dirname(SRC)]
    test_sets, example_sets = [], []
    for r in roots:
        for d, sink in ((os.path.join(r, TESTS_DIR), test_sets),
                        (os.path.join(r, EXAMPLES_DIR), example_sets)):
            if os.path.isdir(d):
                sink.append((d, _files_in(d)))

    rows = []
    for m in modules:
        mp = os.path.join(SRC, m)
        readme = next((f for f in os.listdir(mp) if f.lower().endswith('.md')), None)
        inline_test = next((f for f in os.listdir(mp)
                            if re.search(r'\.(test|spec)\.(ts|js)$', f)), None)
        ext_test = None
        for td, files in test_sets:
            ext_test = _match(files, m) or _content_match(td, files, m)
            if ext_test:
                break
        has_test = inline_test or ext_test

        dedicated = None
        for ed, files in example_sets:
            dedicated = _match(files, m)
            if dedicated:
                break
        shared = None
        for ed, files in example_sets:
            shared = _content_match(ed, files, m)
            if shared:
                break
        example = dedicated if '--strict' in _flags else (dedicated or shared)

        rows.append({
            'module': m, 'readme': readme, 'test': inline_test or ext_test,
            'example': example, 'example_dedicated': dedicated,
            'example_shared_only': (None if dedicated else shared),
            'missing': [k for k, v in (('README', readme), ('测试', has_test),
                                       ('示例', example)) if not v],
        })

    if '--json' in _flags:
        json.dump({'src': SRC, 'modules': len(rows), 'rows': rows},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
        return

    total = len(rows)
    incomplete = [r for r in rows if r['missing']]

    print('=' * 74)
    print('交付物完整性扫描 · %d 个模块 · src=%s' % (total, SRC))
    print('=' * 74)

    if '--missing-only' in _flags:
        for r in incomplete:
            extra = ''
            if '示例' in r['missing'] and r.get('example_shared_only'):
                extra = '  (仅被批量示例间接引用: %s)' % r['example_shared_only']
            print('  %-20s 缺: %s%s' % (r['module'], '、'.join(r['missing']), extra))
        print('\n共 %d / %d 个模块不完整' % (len(incomplete), total))
        return

    print('\n%-20s %-10s %-10s %-10s' % ('模块', 'README', '测试', '示例'))
    print('-' * 74)
    for r in rows:
        mark = lambda v: '有' if v else '缺'
        flag = '  <<< 缺 ' + '、'.join(r['missing']) if r['missing'] else ''
        print('%-20s %-10s %-10s %-10s%s'
              % (r['module'], mark(r['readme']), mark(r['test']), mark(r['example']), flag))

    print('\n[统计]')
    print('  三件套齐全：%d / %d' % (total - len(incomplete), total))
    for key in ('README', '测试', '示例'):
        print('  缺 %-6s %d' % (key, sum(1 for r in rows if key in r['missing'])))
    if incomplete:
        print('\n  不完整模块：')
        for i in range(0, len(incomplete), 5):
            print('    ' + '  '.join(r['module'] for r in incomplete[i:i + 5]))

    print('\n' + '=' * 74)
    print('判据：每个单元应同时具备 README、测试、可运行示例。')
    print('缺示例 = 集成方式不受 smoke test 保护；缺测试 = 所有缺陷裸奔。')
    print('注意：--strict 才要求专属示例；批量示例组织下用默认模式。')
    print('=' * 74)


if __name__ == '__main__':
    main()
