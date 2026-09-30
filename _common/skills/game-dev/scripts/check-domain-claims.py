#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""域声明核查：索引声称"已铺"的域，必须在磁盘上真实存在。

⚠ 为什么查这个：本库出现过三次"对话里报告域已完成、磁盘上零个文件"
   （procgen / hotupdate / monetization）。特征是——设计、Step、核验数字
   都在对话里给出了，却从未落盘；而所有既有检查器都只校验**已存在文件**
   之间的引用关系，⛔ 对"根本不存在"的文件天然查不到，自检照样全绿。

   ⛔ 根因是把"设计完成"当成了"落盘完成"。本检查把两者的落差变成硬失败。

覆盖四类失败：
   1. **幽灵域** —— 索引的「已铺域」表登记了，磁盘上没有该目录 / 没有 00 入口
   2. **功能点缺文件** —— 域内表格链接到 `godot/xxx/0N-*.md`，文件不存在
   3. **点数不符** —— 索引声称的功能点数 ≠ 磁盘上实际的功能点文件数
   4. **表头数字失真** —— 头部"已有 N 个域""其余 M 个"与实际表行数/口径不符
       ⛔ 这是"凭印象写数字"的集中爆发点（openworld 精度表、index 头部都栽过）
   5. **接缝指向不存在的域** —— 00 总览接缝表写 `` `xxx` 域 ``，但 godot/xxx/ 不存在
       ⛔ 读者会以为是 flow 域，点过去发现没有 → 该接缝实际是悬空的。
       （实测全库 8 处：security / ops / performance / account-security /
         platform-export，全都只有 howto 没有 flow 域）
       ⓘ 允许显式标注 `` `xxx` ⓘ howto 层，暂无 flow 域 ``，此时校验 howto 文件存在。
   6. **howto 声明的流程域不存在** —— howto 正文写 ``流程域 → `flow/godot/xxx/```，
      但 godot/xxx/ 在磁盘上没有。
       ⛔ 本轮实证：`upscaling.md` 的「流程：按什么顺序做」节写了该指向，
          而当时域根本没建 —— howto / audit 都反哺好了，唯独流程域是空的，
          读者点过去什么都没有。
       ⛔ 既有检查只查「索引表登记 vs 磁盘」，查不到**正文里**的这类指向。

反向也查：**磁盘上有目录但索引没登记** —— 铺完忘了登记，等于别人找不到。

判据：
   ⛔ 解析结果必须非空。表结构变了 / 路径指错层 → 静默返回 0 → 整套机制
      形同虚设（与 verify.py 路径失效静默 0 条同类）。
"""
import re
import io
import os

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(SKILL, 'references')
PROC = os.path.join(REF, 'flow')
HOWTO = os.path.join(REF, 'howto', 'godot')
INDEX = os.path.join(PROC, 'index.md')

# ⓘ 域目录名 = 索引路径 `godot/<name>/00-xxx.md` 里的 <name>
# ⛔ 必须带 re.M，否则 ^ 只匹配文件开头 → 解析到 0 行 → 静默放行
#   （与 verify.py / 闭合检查脚本栽过的同类：正则漏 re.M 报"0 问题"）
DOM_ROW = re.compile(r'^\|\s*\*\*(.+?)\*\*\s*\|\s*`godot/([\w-]+)/(00-[^`]+?\.md)`\s*\|\s*(\d+)\s*\|',
                     re.M)
# 域内功能点表：`## xxx域（godot/<name>/）` 之后的链接行
SEC_HEAD = re.compile(r'^##\s+(.+?)域[（(]`godot/([\w-]+)/[）)]', re.M)
LINK = re.compile(r'\((godot/[\w-]+/[\w./-]+\.md)\)')


def _read(p):
    return io.open(p, encoding='utf-8').read()


def scan():
    if not os.path.isfile(INDEX):
        raise AssertionError('flow/index.md 不存在（扫描路径指错层）')
    txt = _read(INDEX)

    domains = []          # (中文名, dir名, 00文件名, 声称点数)
    for m in DOM_ROW.finditer(txt):
        domains.append((m.group(1), m.group(2), m.group(3), int(m.group(4))))
    if not domains:
        raise AssertionError('「已铺域」表未解析到任何行（表结构变了？）')

    ghosts = []           # 索引登记了但磁盘上没有
    missing_fp = []       # 域内表格链接的文件不存在
    miscount = []         # 声称点数 ≠ 实际文件数
    unregistered = []     # 磁盘上有但索引没登记

    seen = set()
    for cn, d, entry, n in domains:
        seen.add(d)
        dpath = os.path.join(PROC, 'godot', d)
        if not os.path.isdir(dpath):
            ghosts.append('%s（godot/%s/ 目录不存在）' % (cn, d))
            continue
        if not os.path.isfile(os.path.join(dpath, entry)):
            ghosts.append('%s（入口 %s 不存在）' % (cn, entry))
            continue
        # 实际功能点文件：0N- 开头且不是 00- 总览 / 不是验收
        fps = sorted(f for f in os.listdir(dpath)
                     if f.endswith('.md') and re.match(r'^0[1-9]-', f))
        if len(fps) != n:
            miscount.append('%s：声称 %d，磁盘 %d（%s）' % (cn, n, len(fps), fps[:2]))
        # 域内表格链接的每一个文件都要在
        sec = None
        for m in SEC_HEAD.finditer(txt):
            if m.group(2) == d:
                # 取到下一个 ## 为止
                nxt = txt.find('\n## ', m.end())
                sec = txt[m.end(): nxt if nxt > 0 else len(txt)]
                break
        if sec is None:
            # ⓘ 没有域内明细表也允许（有的域只在总表登记），不误报
            continue
        for link in LINK.findall(sec):
            if not os.path.isfile(os.path.join(PROC, link)):
                missing_fp.append('%s：%s' % (cn, link))

    # 反向：磁盘上的域目录是否被索引登记
    disk = set()
    root = os.path.join(PROC, 'godot')
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if os.path.isdir(os.path.join(root, name)) and not name.startswith('_'):
                disk.add(name)
    unregistered = sorted(disk - seen)

    # 表头数字：声称的域数与实际行数、以及 howto 文件数口径
    head_bad = []
    m = re.search(r'已有\s*(\d+)\s*个域', txt)
    if not m:
        head_bad.append('头部未写"已有 N 个域"（无法复核口径）')
    else:
        claimed = int(m.group(1))
        if claimed != len(domains):
            head_bad.append('头部声称 %d 个域，实际表内 %d 行' % (claimed, len(domains)))
    m2 = re.search(r'其余\s*(\d+)\s*个（口径：howto 文件\s*(\d+)\s*[−\-]\s*已铺\s*(\d+)）', txt)
    if m2:
        rest, n_how, n_done = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        real_how = len([f for f in os.listdir(HOWTO) if f.endswith('.md')]) \
            if os.path.isdir(HOWTO) else -1
        if n_done != len(domains):
            head_bad.append('口径里"已铺 %d" ≠ 表内 %d 行' % (n_done, len(domains)))
        if real_how >= 0 and n_how != real_how:
            head_bad.append('口径里 howto 文件 %d ≠ 实际 %d' % (n_how, real_how))
        if n_done == len(domains) and real_how >= 0 and rest != real_how - len(domains):
            head_bad.append('"其余 %d" ≠ %d − %d' % (rest, real_how, len(domains)))

    # 5. 接缝表指向的域是否真实存在
    #    ⛔ 判据：解析结果必须非空 —— 扫描失效会静默归零，整套机制形同虚设
    seam_bad = []          # `xxx` 域 但目录不存在
    seam_howto_bad = []    # 标注了 howto 层但 howto 文件不存在
    n_seam = 0
    g_root = os.path.join(PROC, 'godot')
    if os.path.isdir(g_root):
        for name in sorted(os.listdir(g_root)):
            dpath = os.path.join(g_root, name)
            if not os.path.isdir(dpath):
                continue
            f00 = [os.path.join(dpath, f) for f in sorted(os.listdir(dpath))
                   if f.startswith('00-') and f.endswith('.md')]
            if not f00:
                continue
            t = _read(f00[0])
            for m in re.finditer(r'`([\w-]+)`\s*域', t):
                tgt = m.group(1)
                n_seam += 1
                if not os.path.isdir(os.path.join(g_root, tgt)):
                    seam_bad.append('%s → `%s` 域（目录不存在）' % (name, tgt))
            # ⓘ 显式标注 howto 层的：允许无 flow 域，但 howto 文件必须在
            for m in re.finditer(r'`([\w-]+)`\s*ⓘ\s*howto 层', t):
                tgt = m.group(1)
                n_seam += 1
                if not os.path.isfile(os.path.join(HOWTO, tgt + '.md')):
                    seam_howto_bad.append('%s → `%s` 标注 howto 层但文件不存在'
                                          % (name, tgt))
    if n_seam == 0:
        raise AssertionError('接缝表未解析到任何行（扫描路径失效 / 格式变了）')

    # 6. howto 正文声明的流程域必须真实存在
    #    ⛔ 判据同样是"解析结果必须非空"：扫描失效会静默归零 → 形同虚设
    howto_fp_bad = []
    n_howto_fp = 0
    if os.path.isdir(HOWTO):
        for f in sorted(os.listdir(HOWTO)):
            if not f.endswith('.md'):
                continue
            t = _read(os.path.join(HOWTO, f))
            for m in re.finditer(r'`flow/godot/([\w-]+)/`', t):
                tgt = m.group(1)
                n_howto_fp += 1
                if not os.path.isdir(os.path.join(g_root, tgt)):
                    howto_fp_bad.append('%s → flow/godot/%s/（不存在）' % (f[:-3], tgt))
    if n_howto_fp == 0:
        raise AssertionError('howto 流程域声明未解析到任何处（扫描失效 / 格式变了）')

    return {
        'howto_fp_bad': howto_fp_bad,
        'n_howto_fp': n_howto_fp,
        'seam_bad': seam_bad,
        'seam_howto_bad': seam_howto_bad,
        'n_seam': n_seam,
        'domains': domains,
        'ghosts': ghosts,
        'missing_fp': missing_fp,
        'miscount': miscount,
        'unregistered': unregistered,
        'head_bad': head_bad,
    }


if __name__ == '__main__':
    r = scan()
    print('接缝引用：%d 处（不合格 %d / howto 层失效 %d） %s'
          % (r['n_seam'], len(r['seam_bad']), len(r['seam_howto_bad']),
             (r['seam_bad'] + r['seam_howto_bad'])[:3]))
    print('索引登记域：%d 个' % len(r['domains']))
    print('幽灵域（登记了但磁盘没有）：%d %s' % (len(r['ghosts']), r['ghosts'][:5]))
    print('功能点文件缺失：%d %s' % (len(r['missing_fp']), r['missing_fp'][:5]))
    print('功能点数不符：%d %s' % (len(r['miscount']), r['miscount'][:5]))
    print('未登记域（磁盘有、索引无）：%d %s' % (len(r['unregistered']), r['unregistered'][:5]))
    print('表头数字失真：%d %s' % (len(r['head_bad']), r['head_bad'][:5]))
    print('howto 流程域声明：%d 处（指向不存在 %d %s）'
          % (r['n_howto_fp'], len(r['howto_fp_bad']), r['howto_fp_bad'][:3]))
    # ⛔ seam 必须进退出码：漏掉它 = 打印了问题却返回 0 → 挂进自检后
    #    整套接缝检查形同虚设（变异验证实测：报"不合格 1"但 exit=0）
    bad = bool(r['ghosts'] or r['missing_fp'] or r['miscount']
               or r['unregistered'] or r['head_bad']
               or r['seam_bad'] or r['seam_howto_bad']
               or r['howto_fp_bad'])
    raise SystemExit(1 if bad else 0)
