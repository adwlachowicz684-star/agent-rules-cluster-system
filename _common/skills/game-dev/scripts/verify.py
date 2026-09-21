#!/usr/bin/env python3
"""待核对项清单：收集 · 过滤 · 运行时录入验证结果

为什么要有这个脚本
------------------
Godot 的技能文档里写着大量"我没有真机/目标版本实测过"的结论。
这些结论如果和已验证结论混在一起，读者无法区分"可以直接信"和
"要先测一下"——而后者被当成前者用，正是最难排查的一类问题：
代码写对了、逻辑想通了，但前提是错的。

之前的做法是散落在各文档里写"待核对"。问题有三个：
  1. 没有索引，想知道"我现在该验证哪些"要全文搜
  2. 没有状态，验证完了也不知道记在哪
  3. 没有归属，不知道该在什么环境验证

本脚本把"待核对"从**一句注解**变成**可追踪的条目**。

用法
----
  python3 verify.py                      列出全部待核对项
  python3 verify.py --pending            只看还没验证的（默认）
  python3 verify.py --all                含已验证的
  python3 verify.py --doc=xr.md          只看某个文档
  python3 verify.py --grep=手部          按关键词过滤
  python3 verify.py --stats              统计

  # 运行时录入：在真机/目标版本上验证后记录结果
  python3 verify.py --verify=V012 --result=ok
  python3 verify.py --verify=V012 --result=failed --note="4.7.2 实测没有该节点"
  python3 verify.py --verify=V012 --result=skipped --note="无 Quest 设备"

  python3 verify.py --self-test          自检

状态文件：`<skill>/.verify-state.json`（不入库，见 .gitignore）
  为什么状态不写回文档：多窗口并行改文档会互相覆盖（已发生过两次）。
  状态放独立文件，文档保持静态。

标记格式（写在文档里）
----------------------
  ⚠ 待核对：{结论} · 验证：{怎么验证}

  例：⚠ 待核对：ArcCast3D 节点是否存在 · 验证：4.7.2 编辑器节点搜索

"验证："后面那句很重要——它决定了这条能不能被验证。
只写"待核对"不写验证方法的，脚本会报出来要求补。
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                    # game-dev/
# 流程与审核两部分都要扫（待核对项可能写在任一侧）
# ⚠ 迁移：原 flow/godot/（做法层，按域分文件）已改名 howto/godot/。
#   改名后 flow/ 下是**功能点子目录**，不再有直接的 .md，
#   os.listdir() 过滤 .md 会得到空列表 → 收集到 0 条而**不报错**。
#   ⛔ 这是"路径失效静默变成空结果"的典型：脚本正常退出，只是什么都没找到。
DOCS_FLOW = os.path.join(ROOT, 'references', 'howto', 'godot')
DOCS_AUDIT = os.path.join(ROOT, 'references', 'audit', 'godot')
DOCS = DOCS_FLOW
DOCS_ALL = [d for d in (DOCS_FLOW, DOCS_AUDIT) if os.path.isdir(d)]
STATE_PATH = os.path.join(ROOT, '.verify-state.json')

# 标记：⚠ 待核对：xxx · 验证：yyy
MARK = re.compile(r'待核对[：:]\s*(.+?)\s*[·|]\s*验证[：:]\s*(.+?)(?:\s*[。;；]|$)')
# 只写了"待核对"没写验证方法的（要提醒补）
MARK_NOHOW = re.compile(r'待核对[：:]\s*(.+?)(?:\s*[。;；]|$)')

RESULT_OK = 'ok'            # 验证通过，结论成立
RESULT_FAILED = 'failed'    # 验证推翻，结论错了
RESULT_SKIPPED = 'skipped'  # 无条件验证（缺设备/版本）

RESULT_LABEL = {
    RESULT_OK: '✓ 已验证',
    RESULT_FAILED: '✗ 已推翻',
    RESULT_SKIPPED: '— 跳过',
}


def stable_id(path, content):
    """稳定 ID：按文档顺序编号，内容变化不导致 ID 漂移。

    不用内容哈希——改一个字 ID 就变，之前录入的验证结果会全部失配。
    用「文档内序号」：V{文档序号}{条序号}，文档改名才需要重录。
    """
    return None  # 由 collect() 填充


def collect():
    """扫描全部文档，收集待核对项"""
    items = []
    if not os.path.isdir(DOCS):
        return items
    files = sorted(f for f in os.listdir(DOCS) if f.endswith('.md'))
    if not files:
        # ⚠ 目录存在却没有 md：说明路径指错了层（如上一次的迁移遗漏）。
        #   ⛔ 静默返回 0 条会让整套待核对机制形同虚设，必须显式报出。
        print('⚠ %s 下没有 .md 文件，待核对项收集为空（路径可能指错层）' % DOCS,
              file=sys.stderr)
    for order, fn in enumerate(files, 1):
        path = os.path.join(DOCS, fn)
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = fh.read().splitlines()
        idx = 0
        for lineno, line in enumerate(lines, 1):
            m = MARK.search(line)
            if not m:
                continue
            idx += 1
            items.append({
                'id': 'V%02d%02d' % (order, idx),
                'doc': fn,
                'line': lineno,
                'claim': m.group(1).strip(),
                'how': m.group(2).strip(),
            })
    return items


def collect_nohow():
    """收集「只写了待核对、没写验证方法」的条目"""
    out = []
    if not os.path.isdir(DOCS):
        return out
    for fn in sorted(f for f in os.listdir(DOCS) if f.endswith('.md')):
        path = os.path.join(DOCS, fn)
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = fh.read().splitlines()
        for lineno, line in enumerate(lines, 1):
            if MARK.search(line):
                continue
            m = MARK_NOHOW.search(line)
            if m:
                out.append((fn, lineno, m.group(1).strip()[:60]))
    return out


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding='utf-8') as fh:
                return json.load(fh)
        except (ValueError, OSError):
            return {}
    return {}


def save_state(st):
    with open(STATE_PATH, 'w', encoding='utf-8') as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)


def cmd_verify(vid, result, note):
    items = {i['id']: i for i in collect()}
    if vid not in items:
        print('✗ 没有这个待核对项：%s' % vid)
        print('  跑 python3 verify.py 看全部 ID')
        return 1
    if result not in RESULT_LABEL:
        print('✗ result 必须是 %s 之一' % ' / '.join(RESULT_LABEL))
        return 1
    st = load_state()
    st[vid] = {'result': result, 'note': note or '', 'claim': items[vid]['claim']}
    save_state(st)
    print('✓ %s %s %s' % (vid, RESULT_LABEL[result], items[vid]['claim'][:40]))
    if note:
        print('  备注：%s' % note)
    return 0


def cmd_list(show_all=False, doc=None, grep=None, stats=False):
    items = collect()
    st = load_state()
    if doc:
        items = [i for i in items if i['doc'] == doc]
    if grep:
        items = [i for i in items if grep in i['claim'] or grep in i['how']]
    if not show_all:
        items = [i for i in items if i['id'] not in st]

    if stats:
        allitems = collect()
        n_ok = sum(1 for v in st.values() if v['result'] == RESULT_OK)
        n_fail = sum(1 for v in st.values() if v['result'] == RESULT_FAILED)
        n_skip = sum(1 for v in st.values() if v['result'] == RESULT_SKIPPED)
        print('待核对项：共 %d 条' % len(allitems))
        print('  未验证 %d' % (len(allitems) - len(st)))
        print('  已验证 %d · 已推翻 %d · 跳过 %d' % (n_ok, n_fail, n_skip))
        by = {}
        for i in allitems:
            by[i['doc']] = by.get(i['doc'], 0) + 1
        if by:
            print('  按文档：')
            for k in sorted(by, key=lambda x: -by[x])[:8]:
                print('    %-26s %2d' % (k, by[k]))
        nohow = collect_nohow()
        if nohow:
            print('\n⚠ 以下只写了"待核对"没写验证方法（无法验证，请补）：')
            for fn, ln, c in nohow[:10]:
                print('    %s:%d  %s' % (fn, ln, c))
        return 0

    if not items:
        print('没有符合条件的待核对项。')
        return 0
    print('待核对项 %d 条%s' % (len(items), '' if show_all else '（仅未验证）'))
    print()
    for i in items:
        v = st.get(i['id'])
        tag = RESULT_LABEL[v['result']] if v else '· 未验证'
        print('%s  %s  [%s:%d]' % (i['id'], tag, i['doc'], i['line']))
        print('     结论：%s' % i['claim'])
        print('     验证：%s' % i['how'])
        if v and v.get('note'):
            print('     备注：%s' % v['note'])
        print()
    return 0


def cmd_self_test():
    """自检：造坏样例验证脚本本身有效

    按技能自己的规则——「永远 0 命中的检查等于没有检查」——
    光能跑通不算数，要造坏样例证明它真会红。
    """
    passed = 0
    failed = 0

    def chk(cond, msg):
        nonlocal passed, failed
        if cond:
            print('  ✓ %s' % msg)
            passed += 1
        else:
            print('  ✗ %s' % msg)
            failed += 1

    items = collect()
    chk(len(items) > 0, '能收集到待核对项（当前 %d 条）' % len(items))

    ids = [i['id'] for i in items]
    chk(len(ids) == len(set(ids)), 'ID 无重复')

    missing = [i['id'] for i in items if not i['how'] or len(i['how']) < 4]
    chk(not missing, '每条都写了验证方法%s' % (
        '（缺：%s）' % ', '.join(missing[:3]) if missing else ''))

    # 造坏样例 1：写一条"只写待核对、没写验证方法"的探针
    probe = os.path.join(DOCS, '__probe_verify.md')
    with open(probe, 'w', encoding='utf-8') as fh:
        fh.write('# 探针\n\n⚠ 待核对：某个没有写验证方法的结论。\n')
    try:
        nohow = collect_nohow()
        chk(any('__probe_verify.md' in n[0] for n in nohow),
            '能检出「只写待核对没写验证方法」的条目')
    finally:
        if os.path.exists(probe):
            os.remove(probe)

    # 造坏样例 2：状态读写往返（写进去要能读出来）
    bak = None
    if os.path.exists(STATE_PATH):
        bak = open(STATE_PATH, encoding='utf-8').read()
    try:
        save_state({'V9999': {'result': RESULT_OK, 'note': 'probe', 'claim': 'x'}})
        st = load_state()
        chk(st.get('V9999', {}).get('result') == RESULT_OK, '状态写入后能读回')
    except OSError as e:
        chk(False, '状态读写正常（%s）' % e)
    finally:
        if bak is not None:
            with open(STATE_PATH, 'w', encoding='utf-8') as fh:
                fh.write(bak)
        elif os.path.exists(STATE_PATH):
            os.remove(STATE_PATH)

    print('\n自检：%d 通过 / %d 失败' % (passed, failed))
    return 1 if failed else 0


def main():
    args = sys.argv[1:]
    if '--self-test' in args:
        return cmd_self_test()
    if '--stats' in args:
        return cmd_list(stats=True)

    vid = None
    result = None
    note = ''
    doc = None
    grep = None
    for a in args:
        if a.startswith('--verify='):
            vid = a.split('=', 1)[1]
        elif a.startswith('--result='):
            result = a.split('=', 1)[1]
        elif a.startswith('--note='):
            note = a.split('=', 1)[1]
        elif a.startswith('--doc='):
            doc = a.split('=', 1)[1]
        elif a.startswith('--grep='):
            grep = a.split('=', 1)[1]

    if vid and result:
        return cmd_verify(vid, result, note)
    if vid:
        print('✗ 给了 --verify 就要给 --result（ok / failed / skipped）')
        return 1

    return cmd_list(show_all=('--all' in args), doc=doc, grep=grep)


if __name__ == '__main__':
    sys.exit(main())
