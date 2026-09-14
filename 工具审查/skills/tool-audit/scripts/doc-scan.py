#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doc-scan.py —— 文档一致性扫描（README 承诺 vs 实现）

整机审查特有的一步：单库审查不会对文档，但工具型应用的用户（以及下一个
接手的 AI）是靠 README 认识它的。文档说 4 个测试脚本、实际 13 个；
文档说默认主题 A、实际是 B —— 都是真缺陷，且只有这一步能发现。

三类候选，全部需人工核对：
    1. 命令不存在     —— README 写了 `npm run xxx`，package.json 里没有
    2. 引用文件不存在 —— README 目录树写了某路径，实际没有（断链）
    3. 数量声明待核对 —— README 说「22 套 / N 个」，代码里数出另一个值

用法：
    python3 doc-scan.py --src=<根>                 # 全量
    python3 doc-scan.py --src=<根> --commands-only # 只查命令
    python3 doc-scan.py --src=<根> --links-only    # 只查引用
    python3 doc-scan.py --src=<根> --json          # 机器可读
"""

import os
import re
import sys
import json

_args = [a for a in sys.argv[1:] if not a.startswith('--')]
_flags = [a for a in sys.argv[1:] if a.startswith('--')]

ROOT = None
for f in _flags:
    if f.startswith('--src='):
        ROOT = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
if ROOT is None:
    ROOT = os.path.abspath('.')

CMD_ONLY = '--commands-only' in _flags
LINK_ONLY = '--links-only' in _flags
AS_JSON = '--json' in _flags

DOC_NAMES = ('README.md', 'readme.md', 'README.MD', 'README.rst', 'docs/README.md')
SKIP_DIRS = {'node_modules', 'dist', 'target', '.git', 'build', 'vendor'}
# 代码围栏里的命令不计入「文档承诺」
FENCE = re.compile(r'```.*?```', re.S)
INLINE_CMD = re.compile(r'`([^`\n]{2,120})`')
NUM_CLAIM = re.compile(r'(\d+)\s*(套|个|条|项|类|种|步|层|版)')
PATH_LIKE = re.compile(r'[\w./-]+\.(?:md|js|mjs|ts|tsx|jsx|json|css|html|py|rs|toml|yaml|yml|sh)\b')
RUN_RE = re.compile(r'\b(?:npm run|yarn|pnpm|bun run|deno task)\s+([\w:.-]+)')
SCRIPT_RE = re.compile(r'\b(?:python3?|node|bash|sh)\s+(?:scripts/)?([\w./-]+\.(?:py|js|mjs|sh))')


_NAME_INDEX = None

def build_name_index(root):
    """全仓库 basename → 是否存在。文档常只写文件名，不写完整路径。"""
    idx = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            idx.add(fn.lower())
    return idx


def exists_anywhere(p):
    global _NAME_INDEX
    if os.path.exists(os.path.join(ROOT, p)):
        return True
    if _NAME_INDEX is None:
        _NAME_INDEX = build_name_index(ROOT)
    return os.path.basename(p).lower() in _NAME_INDEX


def find_docs(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in DOC_NAMES:
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def read(p):
    try:
        return open(p, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


def main():
    docs = find_docs(ROOT)
    if not docs:
        print('未找到 README（已查 %s）' % ', '.join(DOC_NAMES))
        return
    pkg_scripts = {}
    pkg = os.path.join(ROOT, 'package.json')
    if os.path.isfile(pkg):
        try:
            pkg_scripts = json.load(open(pkg, encoding='utf-8')).get('scripts', {}) or {}
        except (OSError, ValueError):
            pass

    findings = []   # (类型, 位置, 内容)
    for d in docs:
        raw = read(d)
        body = FENCE.sub('\n', raw)          # 先剥代码块：示例里的路径不代表承诺
        fences = '\n'.join(FENCE.findall(raw))
        rel = os.path.relpath(d, ROOT)

        # 1) 命令是否存在
        if not LINK_ONLY:
            for scope, text in (('正文', body), ('代码块', fences)):
                for m in RUN_RE.finditer(text):
                    name = m.group(1)
                    if pkg_scripts and name not in pkg_scripts:
                        ln = text[:m.start()].count('\n') + 1
                        findings.append(('命令不存在', '%s:%s（%s）' % (rel, ln, scope),
                                         'npm run %s —— package.json 无此脚本' % name))
                for m in SCRIPT_RE.finditer(text):
                    cand = m.group(1)
                    for base in (os.path.join(ROOT, cand),
                                 os.path.join(ROOT, 'scripts', os.path.basename(cand))):
                        if os.path.exists(base):
                            break
                    else:
                        ln = text[:m.start()].count('\n') + 1
                        findings.append(('命令不存在', '%s:%s（%s）' % (rel, ln, scope),
                                         '脚本 %s 不存在' % cand))

        # 2) 引用的文件是否存在（只查正文与目录树，代码块里的示例不算）
        #    文档常只写文件名（`host.js`、`theme-manager.js`）而非完整路径，
        #    所以先按相对路径找，找不到再按 basename 全仓库找——都找不到才是断链。
        if not CMD_ONLY:
            for m in PATH_LIKE.finditer(body):
                p = m.group(0).lstrip('./')
                if p.startswith('http') or ('/' not in p and '.' not in p):
                    continue
                if exists_anywhere(p):
                    continue
                ln = body[:m.start()].count('\n') + 1
                findings.append(('引用不存在', '%s:%s' % (rel, ln), p))

        # 3) 数量声明（只列出来供人工核对，不判定对错）
        if not (CMD_ONLY or LINK_ONLY):
            for m in NUM_CLAIM.finditer(raw):
                ln = raw[:m.start()].count('\n') + 1
                line = raw.split('\n')[ln - 1].strip()[:90]
                findings.append(('数量待核对', '%s:%s' % (rel, ln),
                                 '「%s」→ %s' % (m.group(0), line)))

    # 4) 脚本数量对照：package.json 里的 test/lint 脚本 vs 文档提及
    if pkg_scripts and not (CMD_ONLY or LINK_ONLY):
        checks = [k for k in pkg_scripts if re.search(r'test|lint|typecheck|check', k, re.I)]
        mentioned = {k for k in checks
                     if any(re.search(r'`?%s`?' % re.escape(k), read(d)) for d in docs)}
        if checks and len(mentioned) < len(checks):
            miss = sorted(set(checks) - mentioned)
            findings.append(('脚本未覆盖', 'package.json',
                             '%d 个校验脚本，文档只提到 %d 个，漏：%s'
                             % (len(checks), len(mentioned), ', '.join(miss[:8]))))

    if AS_JSON:
        print(json.dumps([{'type': a, 'at': b, 'detail': c} for a, b, c in findings],
                         ensure_ascii=False, indent=1))
        return

    print('doc-scan · 文档一致性扫描')
    print('根: %s   文档: %d 份   候选: %d' % (ROOT, len(docs), len(findings)))
    if not findings:
        print('\n（无候选）')
        return
    by = {}
    for a, b, c in findings:
        by.setdefault(a, []).append((b, c))
    for kind in ('命令不存在', '引用不存在', '脚本未覆盖', '数量待核对'):
        if kind not in by:
            continue
        print('\n── %s（%d）──────────' % (kind, len(by[kind])))
        for at, detail in by[kind][:40]:
            print('  %-34s %s' % (at, detail))
        if len(by[kind]) > 40:
            print('  ... 还有 %d 条' % (len(by[kind]) - 40))
    print('\n候选 ≠ 结论：「数量待核对」需人工数一遍代码再定论；')
    print('「命令不存在」先确认执行根（子项目用 --src 再跑一次）。')


if __name__ == '__main__':
    main()
