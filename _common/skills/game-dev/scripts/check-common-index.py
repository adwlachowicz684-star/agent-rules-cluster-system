#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局层（common/）多对多索引校验。

背景：全局块是"⛔ 不可能每个功能里单独写"的内容（如"参数类型不符"）。
它们必须能被**多个**功能域索引到，否则就是"放着该有用的时候索引不到"。

⚠ 为什么不能只做单向：
   索引表里写了「A 域用 GC-01」但 A 域文档里没有引用 → 做 A 域时照样找不到。
   反过来，文档里引用了表里没登记的块 → 改那个块时不知道要回归这里。
   ⛔ 单向登记等于没有索引。

判据：
  1. 表 → 文档：表里声明的引用，文档里必须真有
  2. 文档 → 表：文档里的引用，表里必须登记
  3. 锚点有效：引用的 GC-xx / GA-xx 必须在目标文件里真实存在
  4. 无孤儿：每个全局块至少被引用一次（否则写了没人能找到）
  5. 路径存在：表里写的路径不能是断链
"""
import os, re, sys, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'references')
INDEX = os.path.join(ROOT, 'common', 'index.md')
BLOCK_FILES = {
    'GC': os.path.join(ROOT, 'common', 'howto', 'principles.md'),
    'GA': os.path.join(ROOT, 'common', 'audit', 'global.md'),
}
ROW_RX = re.compile(r'^\|\s*(G[CA]-\d+)\s*\|\s*(.+?)\s*\|(.+)\|\s*$')
BLOCK_RX = re.compile(r'^##\s+(G[CA]-\d+)')


def parse_index():
    """返回 (table: {block_id: {'topic','paths'}}, errors)"""
    if not os.path.isfile(INDEX):
        return {}, ['索引表不存在: %s' % INDEX]
    table, errs = {}, []
    for ln in open(INDEX, encoding='utf-8').read().split('\n'):
        m = ROW_RX.match(ln)
        if not m:
            continue
        bid, topic, cells = m.group(1), m.group(2), m.group(3)
        paths = re.findall(r'`([^`]+\.md)`', cells)
        table[bid] = {'topic': topic, 'paths': paths}
    return table, errs


def block_ids():
    """全局块文件里真实存在的锚点 ID"""
    ids = set()
    for _, path in BLOCK_FILES.items():
        if not os.path.isfile(path):
            continue
        for ln in open(path, encoding='utf-8').read().split('\n'):
            m = BLOCK_RX.match(ln)
            if m:
                ids.add(m.group(1))
    return ids


def doc_refs(path):
    """文档里**真正的**全局块引用集合。

    ⓘ 只认带【读】/【审】标记的引用。为什么：
       框架文档（structure.md 等）讲解结构时会**举例**提到 `GC-01`，
       那是说明不是引用。若按"出现即引用"统计，会报一堆假阳性 ——
       而假阳性会让人去改判定条件而不是修真问题。
    """
    if not os.path.isfile(path):
        return set()
    out = set()
    for ln in open(path, encoding='utf-8').read().split('\n'):
        if '【读】' not in ln and '【审】' not in ln:
            continue
        out |= set(re.findall(r'\b(G[CA]-\d+)\b', ln))
    return out


def scan():
    problems = []
    table, errs = parse_index()
    problems += errs
    real_ids = block_ids()

    # ③ 锚点有效：表里每个 ID 在块文件里真实存在
    for bid in sorted(table):
        if bid not in real_ids:
            problems.append('索引表里的 %s 在全局块文件里不存在（锚点失效）' % bid)

    # ④ 无孤儿：块文件里每个 ID 都被表登记
    for bid in sorted(real_ids):
        if bid not in table:
            problems.append('全局块 %s 没有被索引表登记（孤儿，写了没人能找到）' % bid)

    # ⑤ 路径存在 + ① 表→文档
    for bid in sorted(table):
        for p in table[bid]['paths']:
            full = os.path.join(ROOT, p)
            if not os.path.isfile(full):
                problems.append('%s 引用的路径不存在（断链）：%s' % (bid, p))
                continue
            if bid not in doc_refs(full):
                problems.append('表说 %s 用了 %s，但文档里没有该引用' % (p, bid))

    # ② 文档→表：全库扫引用，未在表登记的
    declared = {}
    for bid, info in table.items():
        for p in info['paths']:
            declared.setdefault(os.path.join(ROOT, p), set()).add(bid)
    for d, ds, fs in os.walk(ROOT):
        ds[:] = [x for x in ds if x != '__pycache__']
        for f in fs:
            if not f.endswith('.md'):
                continue
            full = os.path.join(d, f)
            rel = os.path.relpath(full, ROOT)
            if rel.startswith('common' + os.sep) or rel == 'common.md':
                continue            # 块文件与索引表自身不算引用方
            for bid in doc_refs(full):
                if bid not in declared.get(full, set()):
                    problems.append('%s 引用了 %s，但索引表没登记它' % (rel, bid))
    return problems


if __name__ == '__main__':
    res = scan()
    if '--json' in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(0)
    if not res:
        print('全局层多对多索引校验：通过（0 问题）')
    else:
        print('全局层多对多索引校验：%d 个问题\n' % len(res))
        for r in res:
            print('  ✗', r)
        sys.exit(1)
