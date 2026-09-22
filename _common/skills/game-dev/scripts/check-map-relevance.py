#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【审】映射相关性扫描。

⚠ 为什么查这个：弱引用已清零（每个【审】都带 #N），但**"指到了"不等于"指对了"**。
   自动化只能保证编号存在、不歧义，保证不了这条坑跟当前 Step 真的有关。
   ⛔ 指错的后果是"我审过了，但审的不是这一步的坑" —— 比弱引用更隐蔽。

判据（可计算的近似信号）：
   Step 的【做】文本 与 被引用 audit 条目的「实际」列，
   若**技术标识零交集**，则该映射可疑。
   ⓘ 这是近似信号不是判定：少数条目靠概念而非 API 关联，会误报，需人工确认。
"""
import re, os, sys, glob, collections

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(SKILL, 'references', 'flow')

# ⓘ 高频虚词 bigram 无区分度，需剔除，否则任何两句都"有交集"。
STOP_BI = {'的时', '一个', '就会', '也会', '不能', '不要', '可能', '因为', '所以',
           '如果', '但是', '而且', '什么', '自己', '这个', '那个', '直接', '应该',
           '可以', '需要', '没在', '在了', '是的', '了的', '和是', '与的'}


def tokens(text):
    """抽取技术标识：代码串、API 名、英文标识符。"""
    t = set()
    for m in re.finditer(r'`([^`]+)`', text):
        for w in re.findall(r'[A-Za-z_][A-Za-z0-9_.:]{2,}', m.group(1)):
            t.add(w.split('.')[0])
    for m in re.finditer(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\b', text):
        t.add(m.group(1))
    for m in re.finditer(r'\b([A-Z][A-Za-z0-9]{3,})\b', text):
        t.add(m.group(1))
    # ⚠ 纯小写无下划线的英文词（如 hitbox / rpc / tick）此前**匹配不到** ——
    #   上一版只认「首字母大写」和「带下划线」两种，导致 hitbox↔hitbox 判为零交集。
    for m in re.finditer(r'\b([a-z][a-z0-9]{3,})\b', text):
        t.add(m.group(1))
    # ⓘ 中文用 **bigram 滑动窗口**：整词匹配会失效 ——
    #   "感知独立成层" 与 "感知和寻路" 明明共享"感知"，但整词切出来是两个词。
    for m in re.finditer(r'[\u4e00-\u9fff]{2,}', text):
        for i in range(len(m.group(0)) - 1):
            t.add(m.group(0)[i:i + 2])
    return t


def entry_text(path, num):
    p = os.path.join(SKILL, 'references', path)
    if not os.path.exists(p):
        return None
    lines = open(p, encoding='utf-8').read().split('\n')
    blocks, cur = [], []
    for l in lines:
        if l.startswith('|'):
            cur.append(l)
        else:
            if cur:
                blocks.append(cur); cur = []
    if cur:
        blocks.append(cur)
    for b in blocks:
        for l in b:
            m = re.match(r'^\|\s*(\d+)\s*\|', l)
            if m and m.group(1) == str(num):
                c = [x.strip() for x in l.strip('|').split('|')]
                return ' '.join(c[1:])
    return None


# ⓘ 豁免：确认为**语义相关但字面零交集**的映射。
#   典型：同义缩写（BT ↔ 行为树）、上位概念（"拖放转发意图" ↔ "UI 直接改数据"）。
#   ⛔ 每条必须写理由；⚠ 自检会校验豁免项**仍然存在**，映射改了而豁免没删 → 报"过期豁免"。
EXEMPT = {
    ('02-决策层选型与实现.md', 'S1', 'ai-behavior.md#1'):
        'BT 是"行为树"的英文缩写，同一概念不同字面',
    ('06-UI绑定.md', 'S4', 'game-systems.md#9'):
        '"拖放只转发意图"是"UI 不该改数据"这一原则的具体做法',
    ('07-音频验收.md', 'S3', 'audio-advanced.md#7'):
        '"三种状态行为"的验收点就是暂停后 UI 音是否还在响',
}


def scan():
    susp = []
    total = 0
    seen = set()
    for p in sorted(glob.glob(os.path.join(PROC, '**', '*.md'), recursive=True)):
        txt = open(p, encoding='utf-8').read()
        fn = os.path.basename(p)
        for b in re.split(r'\n(?=### Step )', txt):
            if not b.startswith('### Step'):
                continue
            m = re.search(r'#S(\d+)\]', b)
            if not m:
                continue
            # ⓘ 取**整个 Step**（标题+读+做+产出+判据）而非只有【做】：
            #   关键标识常在标题里（如"focus_neighbor 显式或自动"），
            #   只看【做】会把明明相关的映射判成零交集（假阳性）。
            stok = tokens(b)
            for a in re.findall(r'【审】`([^`]+)`', b):
                if '#' not in a:
                    continue
                path, sec = a.split('#', 1)
                if not sec.strip().isdigit():
                    continue
                total += 1
                et = entry_text(path, sec.strip())
                if et is None:
                    continue
                _sh = stok & tokens(et)
                _key = (fn, 'S' + m.group(1), path.split('/')[-1] + '#' + sec.strip())
                seen.add(_key)
                if _key in EXEMPT:
                    continue
                if not [x for x in _sh if x not in STOP_BI]:
                    susp.append((fn, 'S' + m.group(1),
                                 path.split('/')[-1] + '#' + sec.strip(),
                                 re.sub(r'　|`\[[a-z]+/\d+#S\d+\]`', '',
                                        b.split('\n')[0]).replace('### Step', '').strip()[:30],
                                 et[:80]))
    # ⚠ 过期豁免检测：映射已改但豁免没删 → 豁免变成掩盖真问题的遮羞布
    stale = [k for k in EXEMPT if k not in seen]
    return total, susp, stale


if __name__ == '__main__':
    total, susp, stale = scan()
    print('【审】映射相关性扫描：%d 个强引用，%d 个零交集（可疑）'
          % (total, len(susp)))
    if susp:
        print()
        by = collections.defaultdict(list)
        for fn, sid, ref, title, et in susp:
            by[fn.split('-')[0]].append((fn, sid, ref, title, et))
        for k in sorted(by):
            print('■ %s (%d)' % (k, len(by[k])))
            for fn, sid, ref, title, et in by[k][:12]:
                print('   %s %s %s' % (fn[:14], sid, ref))
                print('      步 %s' % title)
                print('      条 %s' % et)
    if stale:
        print()
        print('⚠ 过期豁免（映射已不存在，请删除）:')
        for k in stale:
            print('   %s %s %s' % k)
    sys.exit(1 if (susp or stale) else 0)
