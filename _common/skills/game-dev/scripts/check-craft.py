#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""【品】映射检查：craft 层的断链、相关性与孤儿。

⚠ 为什么查这个：craft 是第四层，回答"做到什么程度算好"。
   ⛔ 它是**主观经验层**，最容易被写成摆设 —— 内容写完了没人引用，
      或者引用了但指到不相干的条目，两种方式都会让这一层实际失效。

   本检查覆盖三类失败：
   1. **断链** —— 【品】指向的文件或条目标题不存在
   2. **零交集** —— 【品】指到了，但跟这一步无关（"指错了"）
   3. **孤儿** —— craft 条目从未被任何 Step 引用（本层形同虚设）

⚠ 孤儿口径：只统计**内容条目**。「自检（30 秒）」「待核对项」「怎么用这张表」
   这类**元条目是使用说明**，本来就不该被 Step 引用 —— 把它们算进孤儿，
   基线里会永远混着一批不可能挂上的项，真正漏挂的内容条目反而被淹没。
   ⛔ 元条目单列返回，由调用方断言其非空（防扫描路径失效静默返回空）。

⚠ 孤儿的"被用"有两种合法方式：Step 的【品】引用，或 index.md 的入口引用。
   ⛔ 只认前者会把总纲条目（四层模型 / 怎么判断够了）逼成"必须挂到某个 Step"，
      而它们挂到具体 Step 就是指错方向。两种都承认，且 index 解析为空时直接报错。


判据：
   ⛔ 与【审】同级的约束：**填了就必须指得准**，不允许靠豁免掩盖。
   ⓘ 【品】是可选字段，所以不强制每个 Step 都填；但填了的要受同样严格的检查。
"""
import re
import io
import os
import glob

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(SKILL, 'references')
PROC = os.path.join(REF, 'flow')
CRAFT = os.path.join(REF, 'craft')

# ⓘ 元条目：使用说明类标题，本来就不该被 Step 的【品】引用。
#   ⛔ 若把它们计入孤儿，基线里会永远混着一批不可能挂上的项，
#      真正漏挂的内容条目反而被淹没（实测：11 个元条目淹没了 7 个真内容条目）。
META_PAT = ('自检', '待核对', '怎么用', '总判据')

# ⓘ 与 check-map-relevance 同源的停用 bigram：高频虚词无区分度。
STOP_BI = {'的时', '一个', '就会', '也会', '不能', '不要', '可能', '因为', '所以',
           '如果', '但是', '而且', '什么', '自己', '这个', '那个', '直接', '应该',
           '可以', '需要', '没在', '在了', '是的', '了的', '和是', '与的'}

# ⛔ 通用标识符：判相关性时不能算数，否则任何两条都能"对上"。
#   实测教训：顶点悬停 Step 故意指向"输入延迟预算"，靠 `delta` 一个词蒙混过关。
STOP_ID = {'delta', 'self', 'var', 'const', 'func', 'true', 'false', 'null',
           'print', 'return', 'gdscript', 'extends', 'export', 'onready',
           'float', 'int', 'bool', 'string', 'void', 'the', 'and', 'for',
           'with', 'not', 'this', 'that', 'from', 'then', 'else', 'elif',
           'while', 'break', 'pass', 'class', 'enum', 'signal', 'tool'}


def bigrams(text):
    """中文 bigram 滑动窗口（与 tokens 同源，单独抽出供标题级比对用）。"""
    out = set()
    for m in re.finditer(r'[\u4e00-\u9fff]{2,}', text):
        for i in range(len(m.group(0)) - 1):
            out.add(m.group(0)[i:i + 2])
    return out


def tokens(text):
    """抽取技术标识与中文 bigram（与 check-map-relevance 口径一致）。"""
    t = set()
    for m in re.finditer(r'`([^`]+)`', text):
        for w in re.findall(r'[A-Za-z_][A-Za-z0-9_.:]{2,}', m.group(1)):
            t.add(w.split('.')[0])
    for m in re.finditer(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\b', text):
        t.add(m.group(1))
    for m in re.finditer(r'\b([A-Z][A-Za-z0-9]{3,})\b', text):
        t.add(m.group(1))
    for m in re.finditer(r'\b([a-z][a-z0-9]{3,})\b', text):
        t.add(m.group(1))
    t |= bigrams(text)
    return t - STOP_BI


def strong(text):
    """强标识：英文标识符/代码串，剔除到处都有的通用标识符。

    ⛔ 为什么要剔除：判相关性时用 `delta`、`self`、`var` 这类词做交集，
       任何两条都能"对上" —— 变异测试里 S6（顶点悬停）指向"输入延迟预算"
       就是靠 `delta` 蒙混过关的。
    """
    out = set()
    for m in re.finditer(r'`([^`]+)`', text):
        for w in re.findall(r'[A-Za-z_][A-Za-z0-9_.:]{2,}', m.group(1)):
            out.add(w.split('.')[0])
    for m in re.finditer(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,})\b', text):
        out.add(m.group(1))
    for m in re.finditer(r'\b([A-Z][A-Za-z0-9]{3,})\b', text):
        out.add(m.group(1))
    return out - STOP_ID


def common_bigrams(heads, ratio=0.20):
    """自动学习"无区分度 bigram"。

    ⛔ 为什么不能只靠手工停用词表：craft 条目是散文，
       "失效""手感""明显""反馈"这类词**到处都出现**，
       与领域词（"土狼""顶点"）混在一起，靠人列永远列不全。
       ⓘ 实测 df：反馈 41% / 廉价 33% / 音效 31% / 失效 23%，
         而 土狼 8% / 顶点 3% / 悬停 5% —— 分布明显分离。
    """
    import collections
    df = collections.Counter()
    n = 0
    for _path, items in heads.items():
        for t, body in items:
            n += 1
            for b in bigrams(t + '\n' + body):
                df[b] += 1
    if not n:
        return set()
    thr = max(6, int(ratio * n))
    return {b for b, c in df.items() if c >= thr}


# ⛔ 元话语词：讲"文档/实现本身"的词，不是领域内容。
#   ⓘ 为什么必须单列：实测把「攻击节奏与破绽」故意指向「土狼时间」（完全无关），
#      正文交集凑出 3 个词 —— `实现`/`常见`/`问题` —— **刚好达到阈值 3 而漏报**。
#      这三个词在 craft 全库的 df 都很低（4/42、3/42、4/42），
#      ⛔ 所以按文档频率学的停用词（STOP_BI + common_bigrams）**抓不到它们**：
#      它们在统计上"罕见"，但在语义上是纯粹的废话。
#   ⚠ 这是与"同领域邻居漏报"不同的一类漏报：**完全无关的条目靠元话语词蒙混过关**，
#      比邻居漏报更严重 —— 邻居至少还同领域。
DISC = {
    '实现', '常见', '问题', '方式', '情况', '以为', '需要', '注意', '说明', '以下',
    '例如', '可以', '应该', '使用', '方法', '处理', '判断', '进行', '出现', '产生',
    '结果', '过程', '时候', '之后', '之前', '如果', '因为', '所以', '但是', '而且',
    '这样', '那样', '一样', '一次', '一定', '部分', '全部', '相关', '对应', '基本',
    '主要', '直接', '实际', '最后',
}


def strip_refs(text):
    """剔除【读】【审】【品】引用行。

    ⛔ 为什么必须剔除：**引用行本身就在 Step 文本里**，
       条目锚点的文字会出现在 Step 中，导致交集**必然非空** ——
       实测：把顶点悬停故意指向"输入延迟预算"，零交集判据**没报**，
       根因就是 `输入到画`、`到画`、`迟预` 这些 bigram 来自【品】行自己。
       ⚠ 这与"用待检验对象当证据"是同一类错误。
    """
    out = []
    for ln in text.split('\n'):
        if ln.startswith(('【读】', '【审】', '【品】')):
            continue
        out.append(ln)
    return '\n'.join(out)


def related(step_text, anchor, entry_body, stop=STOP_BI):
    """【品】是否指对了 —— 两级判据。

    ⓘ 为什么不用单一判据：
       craft 条目是**散文**，正文几百字，与任何 Step 都能凑出通用中文 bigram
       （"失效""手感""明显"……）。实测：S6 顶点悬停故意指向"输入延迟预算"，
       纯 bigram 交集有 15 个词，**全部是通用词** → 漏报。

    判据（满足任一即算相关）：
       ① **标题级**：Step 标题 与 craft 条目标题 有共享 bigram —— 信号最强
       ② **强标识级**：Step 全文 与 条目正文 共享**技术标识符**（已剔通用词）
    """
    body = strip_refs(step_text)
    step_title = step_text.split('\n')[0]
    t1 = bigrams(step_title)
    t2 = bigrams(anchor)
    if (t1 & t2) - stop:
        return True
    # ⓘ 正文级：Step 实质内容（已剔引用行、再剔元话语词）与条目正文的中文 bigram。
    #   ⚠ 阈值取 2（原为 3）：加入 DISC 后废话词被剔除，真映射的交集普遍下降 1–2，
    #      阈值 3 会误伤 4 条真映射（实测）；而错挂的土狼时间过滤后归 0，
    #      ⛔ 阈值 2 仍能抓住它 —— 所以 2 是过滤后能分开两者的取值。
    #      ⛔ 已知局限（诚实记录）：抓不了"同领域邻居条目" ——
    #         实测把顶点悬停故意指向"输入延迟预算"（同讲物理/时间），
    #         正文交集 4 个词（即时/手感/输入/重力）→ 漏报。
    #         字面判据在散文层无法区分"相关"与"邻居"，后者靠人工。
    if len((bigrams(body) & bigrams(entry_body)) - stop - DISC) >= 2:
        return True
    if strong(body) & strong(entry_body):
        return True
    return False


def craft_headings():
    """收集 craft 层全部条目标题 → {相对路径: [(标题, 正文)]}。

    ⓘ 只取二级标题（## N. xxx）作为**可被引用的条目单位**；
       三级标题是条目内部的细分，不作为引用目标。
    """
    out = {}
    for p in sorted(glob.glob(os.path.join(CRAFT, '**', '*.md'), recursive=True)):
        rel = os.path.relpath(p, REF).replace(os.sep, '/')
        if rel.endswith('index.md'):
            continue
        lines = open(p, encoding='utf-8').read().split('\n')
        items, cur_title, cur_body = [], None, []
        for l in lines:
            m = re.match(r'^##\s+(.+?)\s*$', l)
            if m:
                if cur_title is not None:
                    items.append((cur_title, '\n'.join(cur_body)))
                cur_title, cur_body = m.group(1), []
            elif cur_title is not None:
                cur_body.append(l)
        if cur_title is not None:
            items.append((cur_title, '\n'.join(cur_body)))
        out[rel] = items
    return out


# ⓘ 豁免：**语义相关但字面低交集**的映射。
#   ⛔ 每条必须写理由；⚠ 自检会校验豁免项**仍然存在**，
#      映射改了而豁免没删 → 报"过期豁免"（与 check-map-relevance 同款）。
# ⚠ 豁免必须有理由，且**映射一改就要复查** —— 否则豁免会变成掩盖真问题的遮羞布。
# 过期检测：本表中的项若在当前映射里找不到，自检报红。
#
# ⓘ 2026-09-26 移除过一项：ui/04 S4 → cheapness#1。
#   原因：craft 层新增「生成类廉价感」后，自动学习的停用词集变化，
#   该映射不再零交集（"切换/瞬时"成为有效交集词）→ 豁免已无必要。
#   ⛔ 不是"它变好了"，是判据口径变了；这类变化必须留下记录，否则无从追溯。
EXEMPT = {
    # ⓘ 语义相关，但字面被停用词集吃掉：
    #   Step 讲「暴击/普攻走不同反馈分支、四类反馈可区分」，
    #   条目讲「强度分档、连续事件不重复播同一反馈」——是同一件事。
    #   ⛔ 零交集的原因："反馈" 在本层文档频率 41%，被自动判为无区分度停用词，
    #   而它恰恰是本条映射唯一的共享词。
    #   ⚠ 这不是"判据放宽"，是判据在本层的一个已知盲区（高频领域词被过滤）。
    ('05-打击感反馈.md', 'S3', 'craft/godot/polish.md#2. 润色层（第 3 层）：让反馈有层次'),
}


def scan():
    """返回 (total, broken, suspicious, orphans)。"""
    heads = craft_headings()
    if not heads:
        # ⛔ 必须返回与主路径相同的 6 元组。
        #   实测教训：这里原本只返回 4 个值，路径失效时调用方
        #   `ValueError: not enough values to unpack` 直接崩溃 ——
        #   表现为"检查报错了"，但报的是解包错，不是"扫描失效"，
        #   归因被带偏（与"检查没跑起来却显示通过"是同一类失败的两面）。
        return 0, ['craft 层条目扫描为空（路径失效）'], [], [], [], []

    total, broken, suspicious = 0, [], []
    used = set()
    hit_ex = set()
    stop = STOP_BI | common_bigrams(heads)

    for p in sorted(glob.glob(os.path.join(PROC, '**', '*.md'), recursive=True)):
        txt = open(p, encoding='utf-8').read()
        fn = os.path.basename(p)
        # ⓘ 取整个 Step（标题+【做】+【判据】），
        #   ⛔ 只取【做】会漏掉标题里的关键标识（check-map-relevance 栽过）。
        blocks = re.split(r'\n(?=### Step )', txt)
        for b in blocks:
            m = re.match(r'### Step (\d+)', b)
            if not m:
                continue
            sid = 'S' + m.group(1)
            for ln in re.findall(r'【品】([^\n]+)', b):
                for ref in re.findall(r'`([\w./-]+\.md#[^`]+)`', ln):
                    total += 1
                    path, _, anchor = ref.partition('#')
                    if path not in heads:
                        broken.append('%s %s %s → 文件不存在' % (fn, sid, ref))
                        continue
                    hit = [h for h in heads[path] if h[0] == anchor]
                    if not hit:
                        broken.append('%s %s %s → 条目标题不存在'
                                      % (fn, sid, ref))
                        continue
                    used.add((path, anchor))
                    if not related(b, anchor, hit[0][1], stop):
                        if (fn, sid, ref) in EXEMPT:
                            hit_ex.add((fn, sid, ref))
                        else:
                            suspicious.append((fn, sid, ref))

    # ⓘ 总纲条目由 craft/index.md 在本层入口显式引用 —— 这也是一种"被用"，
    #   与 Step 的【品】并列。
    #   ⛔ 只认【品】会让框架性条目永远显示为孤儿，进而诱导把"四层模型""怎么判断够了"
    #      这类内容硬挂到某个具体 Step —— 那正是【审】挂错的同一类错误。
    idx_p = os.path.join(CRAFT, 'index.md')
    idx_used = set()
    if os.path.exists(idx_p):
        idx = io.open(idx_p, encoding='utf-8').read()
        for ref in re.findall(r'`(godot/[\w./-]+\.md#[^`]+)`', idx):
            path, _, title = ref.partition('#')
            idx_used.add(('craft/' + path, title))
    if not idx_used:
        raise AssertionError('index.md 未解析到任何总纲引用（扫描失效）')

    orphans, meta = [], []
    for path, items in sorted(heads.items()):
        for title, _ in items:
            if (path, title) in used or (path, title) in idx_used:
                continue
            if any(k in title for k in META_PAT):
                meta.append('%s#%s' % (path, title))
            else:
                orphans.append('%s#%s' % (path, title))
    stale = sorted(set(EXEMPT) - hit_ex)
    return total, broken, suspicious, orphans, stale, meta


if __name__ == '__main__':
    t, b, s, o, st, meta = scan()
    print('【品】引用：%d 处' % t)
    print('断链：%d %s' % (len(b), b[:5]))
    print('零交集：%d %s' % (len(s), s[:5]))
    print('过期豁免：%d %s' % (len(st), st[:3]))
    print('孤儿条目（内容）：%d %s' % (len(o), o[:8]))
    print('元条目（使用说明，不计孤儿）：%d' % len(meta))
    raise SystemExit(1 if (b or s or st) else 0)
