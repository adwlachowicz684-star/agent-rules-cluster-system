#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""item-index.py — 判据条目结构化索引

解决什么问题
------------
路由现在的最小粒度是**文件**：命中 `p-python` 就把 2771 tokens 整个读进来，
哪怕实际相关的只有 PY-01 和 PY-05 两条（各约 150 tokens）。
规则越加越多，这个浪费会线性放大。

本脚本把 `references/*.md` 里的判据条目抽成结构化记录，
让**加载粒度从「文件」降到「条目」**。

为什么 Markdown 仍是源
----------------------
JSON 是产物（跟 `rules/registry.json` 一个模式），Markdown 是给人读、给人改的。
`--check` 负责防止改了 Markdown 忘了 sync。
反过来（JSON 是源、Markdown 生成）会让改一个错别字都要跑生成器。

用法
----
    python3 item-index.py --sync                  # 从 Markdown 重建索引
    python3 item-index.py --check                 # 漂移检查
    python3 item-index.py --stats                 # 统计（条目数 / token 账）
    python3 item-index.py --get PY-01 PY-05       # 只取这几条正文 ← 核心
    python3 item-index.py --query "线程池"         # 关键词检索
    python3 item-index.py --scan <扫描结果.json>   # 按扫描器命中取对应条目
    python3 item-index.py --scene s-numerics --all  # 整场景（=旧行为，兜底）
"""
import os
import re
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REF = os.path.join(SKILL, 'references')
OUT = os.path.join(SKILL, 'rules', 'items.json')

# `### PY-01 (P0) 可变默认参数（跨调用累积）`
ENTRY_RX = re.compile(r'^### ([A-Z]{1,4}-\d{1,2}) \((P\d)\)\s+(.+?)\s*$')
# 只认二级标题 `## xxx` 为分节。
# 一级标题 `# 场景：xxx` 是**文件标题**，它到第一个 ## 之间的内容是文件前言，
# 归 preamble（用 --with-preamble 显式加载），不混进 sections。
SECTION_RX = re.compile(r'^## (?!#)')
FIELD_RX = re.compile(r'^[-*]\s+\*\*(.+?)\*\*\s*[:：]?\s*(.*)$')

# 哪些场景文件要索引（注意：common-*.md 是流程不是判据，不索引）
SKIP_FILES = {'common.md', 'common-workflow.md', 'common-severity.md',
              'common-reporting.md', 'common-manual-review.md',
              'common-global.md', 'common-maintenance.md',
              'mechanisms.md', 'route.md'}

# 文件名 → 场景 id
def scene_of(fname):
    return fname[:-3] if fname.endswith('.md') else fname


def token_estimate(text):
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    return int(cjk * 1.5 + (len(text) - cjk) / 4)


ID_REF_RX = re.compile(r'\b([A-Z]{1,4}-\d{1,2})\b')
# 分节标题里出现这些词 → 标记为「误报段」，加载任何条目时都默认附带
FP_TITLE = ('误报', 'False Positive', 'false positive')
# 标了「必读」的分节（如 s-numerics 的「NaN 的三副面孔」）→ 同样默认附带。
# 这类段是场景的**心智模型**，不读它看不懂条目里的判据为什么成立。
REQ_TITLE = ('必读',)

# 正文短于这个值的条目视为**指针条目**（如 G-07 全文就一句「与 S-04 同源，归 s-sandbox」）：
# 它自己不构成完整判据，加载时必须把指向的目标一并带上，否则拿到的是一句空话。
# 阈值 60 是按实测定的：短条目集中在 21~59，正常条目最短 71，中间没有重叠。
PTR_MAX_TOKENS = 60


def split_doc(text):
    """把 Markdown 切成 entries / sections / preamble 三部分。

    为什么不只切条目：**条目正文只占整文件的 39%**，剩下的 61% 里
    有两样不能丢——
      1. 「常见误报」段：判断某条是不是误报要靠它，丢了误报率会上升
      2. 引用了具体条目 ID 的方法论章节：
         如 s-contracts 的「双实现比对（高产区，**C-02** 的展开）」，
         标题里就写着 C-02，命中 C-02 时不带它就是丢了一半判据
    所以分节也结构化，靠**标题/正文里引用的条目 ID 自动关联**。
    """
    lines = text.split('\n')
    if not any(ENTRY_RX.match(l) for l in lines):
        return [], [], ''

    entries, sections, pre = [], [], []
    cur_e, cur_s, started = None, None, False

    def flush():
        nonlocal cur_e, cur_s
        if cur_e:
            cur_e['body'] = '\n'.join(cur_e['body']).strip('\n')
            entries.append(cur_e)
            cur_e = None
        if cur_s:
            cur_s['body'] = '\n'.join(cur_s['body']).strip('\n')
            sections.append(cur_s)
            cur_s = None

    for ln in lines:
        m = ENTRY_RX.match(ln)
        if m:
            flush()
            cur_e = {'id': m.group(1), 'level': m.group(2),
                     'name': m.group(3), 'body': [], 'fields': {}}
            started = True
            continue
        if SECTION_RX.match(ln):
            flush()
            title = ln.lstrip('#').strip()
            if title.startswith('###'):
                continue
            cur_s = {'title': title, 'body': [],
                     'is_fp': any(k in title for k in FP_TITLE),
                     'is_required': any(k in title for k in REQ_TITLE)}
            started = True
            continue
        if not started:
            pre.append(ln)
            continue
        if cur_e is not None:
            cur_e['body'].append(ln)
            fm = FIELD_RX.match(ln)
            if fm:
                cur_e['fields'].setdefault(fm.group(1).strip(), []).append(
                    fm.group(2).strip())
        elif cur_s is not None:
            cur_s['body'].append(ln)
    flush()

    for s in sections:
        s['refs'] = sorted(set(ID_REF_RX.findall(s['title'] + ' ' + s['body'])))
        s['tokens'] = token_estimate(s['body'])
    for e in entries:
        e['tokens'] = token_estimate(e['body'])
    return entries, sections, '\n'.join(pre).strip('\n')


CODE_TOKEN_RX = re.compile(r'[A-Za-z_][A-Za-z0-9_]{2,}(?:\.[A-Za-z_][A-Za-z0-9_]{2,})*')


def keywords_of(entry):
    """从「判据 / 特征 / 典型 / 正确」里抽代码标识符做检索键。

    为什么只抽代码标识符：中文关键词做全匹配意义不大（人检索时会带上下文），
    而 `sync.Mutex`、`pickle.loads`、`size() - 1` 这类是**判据的核心指纹**，
    源码里出现同样的标识符就高度可疑。
    """
    # fields 的值是 list[list[str]]（同名键可出现多次），先摊平
    parts = []
    for k in ('判据', '特征', '典型', '正确', '确认', '各语言形态'):
        for v in entry['fields'].get(k, []):
            parts.append(v if isinstance(v, str) else ' '.join(v))
    src = ' '.join(parts)
    kws = set()
    for m in CODE_TOKEN_RX.finditer(src):
        t = m.group(0)
        if len(t) < 3:
            continue
        kws.add(t)
    # 中文短词也留一份，供 --query 用
    for zh in re.findall(r'[\u4e00-\u9fff]{2,6}', entry['name']):
        kws.add(zh)
    return sorted(kws)[:40]


def build():
    items, files, secs = [], [], []
    for fn in sorted(os.listdir(REF)):
        if not fn.endswith('.md') or fn in SKIP_FILES:
            continue
        text = open(os.path.join(REF, fn), encoding='utf-8').read()
        ents, sections, pre = split_doc(text)
        if not ents:
            continue
        files.append({'file': fn, 'scene': scene_of(fn), 'entries': len(ents),
                      'sections': len(sections),
                      'preamble': pre,
                      'preamble_tokens': token_estimate(pre)})
        for e in ents:
            items.append({
                'id': e['id'],
                'level': e['level'],
                'name': e['name'],
                'scene': scene_of(fn),
                'file': fn,
                'fields': e['fields'],
                'keywords': keywords_of(e),
                'body': e['body'],
                'tokens': e['tokens'],
                'xrefs': sorted(set(ID_REF_RX.findall(e['body'])) - {e['id']}),
            })
        for s in sections:
            secs.append({'scene': scene_of(fn), 'file': fn,
                         'title': s['title'], 'is_fp': s['is_fp'],
                         'is_required': s.get('is_required', False),
                         'refs': s['refs'], 'tokens': s['tokens'],
                         'body': s['body']})
    return {'version': '1.0.0',
            'note': '由 scripts/item-index.py --sync 从 references/*.md 提取。'
                    '不要手改（会被 --check 判为漂移）；改 Markdown 后重新 sync。',
            'files': files,
            'items': items,
            'sections': secs}


def load():
    if not os.path.isfile(OUT):
        return None
    try:
        return json.load(open(OUT, encoding='utf-8'))
    except (ValueError, OSError) as e:
        print('[warn] items.json 解析失败: %s' % e, file=sys.stderr)
        return None


def cmd_sync():
    d = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(d, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已索引 %d 条判据（来自 %d 个文件）→ rules/items.json'
          % (len(d['items']), len(d['files'])))
    return 0


def cmd_check():
    saved = load()
    if saved is None:
        print('没有索引，先跑 --sync')
        return 1
    live = build()
    si = {i['id']: i for i in saved['items']}
    li = {i['id']: i for i in live['items']}
    errs = []
    for rid in sorted(set(si) | set(li)):
        if rid not in li:
            errs.append('%s 索引里有、Markdown 里没了（改了 Markdown 没 sync？）' % rid)
        elif rid not in si:
            errs.append('%s Markdown 里有、索引里没有 → 跑 --sync' % rid)
        elif si[rid]['body'] != li[rid]['body'] or si[rid]['level'] != li[rid]['level']:
            errs.append('%s 内容已变（Markdown 改过）→ 跑 --sync' % rid)
    print('item-index · 检查')
    print('条目: 索引 %d / Markdown %d' % (len(si), len(li)))
    for e in errs:
        print('  ✗ %s' % e)
    print('结论：%s' % ('一致。' if not errs else '%d 处漂移。' % len(errs)))
    return 1 if errs else 0


def cmd_stats():
    d = load()
    if d is None:
        print('先跑 --sync')
        return 1
    items = d['items']
    from collections import Counter
    byfile = Counter(i['file'] for i in items)
    bylevel = Counter(i['level'] for i in items)
    print('item-index · 统计')
    print('条目总数: %d（%d 个文件）' % (len(items), len(d['files'])))
    print('按级别:', dict(sorted(bylevel.items())))
    print()
    print('%-30s %5s %8s %10s' % ('文件', '条目', '整文件tok', '均每条'))
    for f in sorted(os.listdir(REF)):
        if not f.endswith('.md') or f in SKIP_FILES:
            continue
        full = token_estimate(open(os.path.join(REF, f), encoding='utf-8').read())
        n = byfile.get(f, 0)
        if not n:
            continue
        sub = sum(i['tokens'] for i in items if i['file'] == f)
        print('%-30s %5d %8d %10d' % (f, n, full, sub // n))
    print()
    tot_full = sum(token_estimate(open(os.path.join(REF, f), encoding='utf-8').read())
                   for f in os.listdir(REF)
                   if f.endswith('.md') and f not in SKIP_FILES)
    tot_items = sum(i['tokens'] for i in items)
    print('全部整读: %d tokens ／ 全部条目正文合计: %d tokens' % (tot_full, tot_items))
    return 0


def expand(idx, items):
    """指针条目展开：正文过短的条目把它指向的目标一并带上（只展开一层）。

    单独抽出来是为了 self-test 能直接测这段逻辑，不用走完整 cmd_get。
    """
    got, seen = list(items), {i['id'] for i in items}
    for i in list(items):
        if i['tokens'] < PTR_MAX_TOKENS:
            for xr in i.get('xrefs', []):
                if xr in idx and xr not in seen:
                    got.append(idx[xr])
                    seen.add(xr)
    return got


def related_sections(d, ids):
    """取与这批条目相关的分节。

    两条规则：
      1. **误报段默认全带** —— 判断「这条是不是误报」靠它，省了会抬高误报率
      2. **标题或正文引用了这批 ID 的分节** —— 如「双实现比对（C-02 的展开）」
    """
    idset = set(ids)
    scenes = {i['scene'] for i in d['items'] if i['id'] in idset}
    out = []
    for s in d.get('sections', []):
        if s['scene'] not in scenes:
            continue
        if s['is_fp']:
            out.append(('常见误报', s))
        elif s.get('is_required'):
            out.append(('必读前置', s))
        elif idset & set(s['refs']):
            out.append(('关联章节', s))
    return out


def render(items, secs=None):
    out = []
    for i in items:
        head = '### %s (%s) %s' % (i['id'], i['level'], i['name'])
        out.append('%s\n\n%s' % (head, i['body']))
    for kind, s in (secs or []):
        out.append('## %s〔%s · %s〕\n\n%s'
                   % (s['title'], kind, s['scene'], s['body']))
    return '\n\n---\n\n'.join(out)


def cmd_get(ids, json_out=False, no_fp=False, with_preamble=False):
    d = load()
    if d is None:
        print('先跑 --sync')
        return 1
    idx = {i['id']: i for i in d['items']}
    got, miss = [], []
    for rid in ids:
        rid = rid.strip()
        if rid in idx:
            got.append(idx[rid])
        else:
            miss.append(rid)
    if miss:
        print('未找到: %s' % ' '.join(miss), file=sys.stderr)
    # 指针条目（正文过短）→ 把它指向的目标条目一并带上（见 expand）
    got = expand(idx, got)
    secs = [] if no_fp else related_sections(d, [i['id'] for i in got])
    pres = []
    if with_preamble:
        scenes = {i['scene'] for i in got}
        pres = [f for f in d['files'] if f['scene'] in scenes and f.get('preamble')]
    if json_out:
        print(json.dumps({'items': got,
                          'sections': [{'title': s['title'], 'kind': k,
                                        'body': s['body']} for k, s in secs],
                          'preambles': [{'scene': f['scene'], 'body': f['preamble']}
                                        for f in pres]},
                         ensure_ascii=False, indent=1))
    else:
        parts = []
        for f in pres:
            parts.append('# %s〔前言 · %s〕\n\n%s' % (f['scene'], f['scene'], f['preamble']))
        if parts:
            parts.append(render(got, secs))
            print('\n\n---\n\n'.join(parts))
        else:
            print(render(got, secs))
    it = sum(i['tokens'] for i in got)
    st = sum(s['tokens'] for _, s in secs) + sum(f['preamble_tokens'] for f in pres)
    whole = sum(f['preamble_tokens'] for f in d['files']
                if f['scene'] in {i['scene'] for i in got})
    full = sum(token_estimate(open(os.path.join(REF, f['file']), encoding='utf-8').read())
               for f in d['files'] if f['scene'] in {i['scene'] for i in got})
    print('\n〔%d 条判据 %d + 关联分节 %d = %d tokens；整文件读要 %d，省 %d%%〕'
          % (len(got), it, st, it + st, full,
             int((1 - (it + st) / full) * 100) if full else 0),
          file=sys.stderr)
    return 0 if got else 1


def cmd_query(q, scene=None, json_out=False):
    d = load()
    if d is None:
        print('先跑 --sync')
        return 1
    q = q.lower()
    hits = []
    for i in d['items']:
        if scene and i['scene'] != scene:
            continue
        hay = (i['name'] + '\n' + i['body']).lower()
        if q in hay:
            # 命中位置权重：名字 > 字段 > 正文
            score = (3 if q in i['name'].lower() else 0) + hay.count(q)
            hits.append((score, i))
    hits.sort(key=lambda kv: (-kv[0], kv[1]['id']))
    items = [i for _, i in hits]
    if json_out:
        print(json.dumps([{'id': i['id'], 'level': i['level'], 'name': i['name'],
                           'scene': i['scene']} for i in items],
                         ensure_ascii=False, indent=1))
    else:
        if not items:
            print('（无命中）')
            return 1
        for i in items:
            print('  %-9s %-3s %-40s %s' % (i['id'], i['level'], i['name'][:40], i['scene']))
        print('\n%d 条命中（--get <id> 看正文）' % len(items))
    return 0


def cmd_scan(path, json_out=False):
    """按扫描器结果取对应条目。

    扫描器输出的 rule_id 形如 PY-01 / TS-A01 / APP-R05。
    注册表里有 native_id ↔ rule_id 映射，这里直接对上就取；
    对不上的（人工判据）不出来——那些靠 --query 或整场景兜底。
    """
    d = load()
    if d is None:
        print('先跑 --sync')
        return 1
    try:
        rows = json.load(open(path, encoding='utf-8'))
    except (ValueError, OSError) as e:
        print('读扫描结果失败: %s' % e, file=sys.stderr)
        return 1
    ids = sorted({r.get('rule_id') or r.get('id') for r in rows
                  if r.get('rule_id') or r.get('id')})
    idx = {i['id']: i for i in d['items']}
    got = [idx[i] for i in ids if i in idx]
    miss = [i for i in ids if i not in idx]
    if json_out:
        print(json.dumps([{'id': i['id'], 'level': i['level'], 'name': i['name'],
                           'scene': i['scene']} for i in got],
                         ensure_ascii=False, indent=1))
        return 0
    for i in got:
        print('  %-9s %-3s %-40s %s' % (i['id'], i['level'], i['name'][:40], i['scene']))
    if miss:
        print('\n扫描器报了但索引里没有（人工判据，需整场景读）：%s' % ' '.join(miss))
    print('\n%d 条可精确定位 · %d tokens（整场景读要 %d）'
          % (len(got), sum(i['tokens'] for i in got),
             sum(i['tokens'] for i in d['items']
                 if i['scene'] in {g['scene'] for g in got})))
    return 0


SELF_TEST_CASES = [
    # (要取的条目, 必须出现在关联分节里的关键词, 说明)
    (['C-02'], '双实现比对',
     '分节标题引用了 C-02 → 必须自动带上（否则丢一半判据）'),
    (['N-01'], 'NaN 的三副面孔',
     '标了「必读」的前置段 → 必须自动带上'),
    (['PY-01'], '常见误报',
     '误报段默认总是带（判断是不是误报靠它）'),
    (['GO-06'], '常见误报', 'Go 包同样要带误报段'),
]
# 指针条目 → 必须自动带上它指向的目标（否则只拿到一句「归 X」）
SELF_TEST_XREF = [
    ('G-07', 'S-04'), ('T-07', 'C-03'), ('T-09', 'A-01'),
]


def cmd_self_test():
    d = load()
    if d is None:
        print('先跑 --sync')
        return 1
    ok = fail = 0

    def chk(cond, msg):
        nonlocal ok, fail
        if cond:
            ok += 1
            print('  ✓ %s' % msg)
        else:
            fail += 1
            print('  ✗ %s' % msg)

    idx = {i['id']: i for i in d['items']}
    for ids, kw, why in SELF_TEST_CASES:
        miss = [i for i in ids if i not in idx]
        if miss:
            chk(False, '%s 不在索引里' % ' '.join(miss))
            continue
        secs = related_sections(d, ids)
        joined = ' '.join(s['title'] for _, s in secs)
        chk(kw in joined, '%s → 带「%s」：%s' % ('+'.join(ids), kw, why))

    # 指针条目：加载结果里必须出现它指向的目标
    for src, dst in SELF_TEST_XREF:
        chk(src in idx and dst in idx, '%s / %s 都在索引里' % (src, dst))
        if src not in idx or dst not in idx:
            continue
        got_ids = {g['id'] for g in expand(idx, [idx[src]])}
        chk(dst in got_ids, '%s（指针条目）→ 自动带 %s' % (src, dst))

    # 关联分节不能喧宾夺主：查 1 条时，分节 token 不该超过条目本身的 4 倍
    it = idx['PY-01']
    secs = related_sections(d, ['PY-01'])
    st = sum(s['tokens'] for _, s in secs)
    chk(st < it['tokens'] * 4,
        '分节不喧宾夺主（PY-01 条目 %d vs 分节 %d tokens）' % (it['tokens'], st))

    # 每条判据都能取到（body 非空）
    empty = [i['id'] for i in d['items'] if not i['body'].strip()]
    chk(not empty, '所有条目正文非空（空: %s）' % (empty[:5] or '无'))

    # 收益：单条加载必须显著小于整文件
    whole = token_estimate(open(os.path.join(REF, 'p-python.md'), encoding='utf-8').read())
    saved = sum(s['tokens'] for _, s in secs) + it['tokens']
    chk(saved < whole * 0.5,
        '单条加载省一半以上（%d vs 整文件 %d）' % (saved, whole))

    print()
    print('自检：%d 通过 / %d 失败' % (ok, fail))
    if not fail:
        print('结论：条目级索引工作正常')
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sync', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--get', nargs='*', default=None)
    ap.add_argument('--query', default='')
    ap.add_argument('--scan', default='')
    ap.add_argument('--scene', default='')
    ap.add_argument('--no-fp', action='store_true',
                    help='不带「常见误报」段（默认带：判断误报要靠它）')
    ap.add_argument('--with-preamble', action='store_true',
                    help='附带文件前言（触发条件/风险背景）。首次接触该场景时建议带')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    if args.sync:
        return cmd_sync()
    if args.check:
        return cmd_check()
    if args.self_test:
        return cmd_self_test()
    if args.stats:
        return cmd_stats()
    if args.get is not None:
        return cmd_get(args.get, args.json, args.no_fp, args.with_preamble)
    if args.query:
        return cmd_query(args.query, args.scene or None, args.json)
    if args.scan:
        return cmd_scan(args.scan, args.json)
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
