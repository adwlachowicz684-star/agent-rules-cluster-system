#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan-gaps.py — 覆盖扫描（原子词版）

为什么需要这个脚本
------------------
旧做法：把一个概念当作「连续词组」去 grep，例如查 "录像回放"。
问题：如果库里写的是 "回放"（不含 "录像回放" 这个连续串），
      grep 判 0 命中 → 误判为「真空白」→ 去新建一个早已存在的域。

已经踩过两次：
  - "录像回放" 判 0，实际有 replay.md
  - "敌人AI"  判 0，实际有 ai-behavior/ai-navigation/ai-perception/stealth-ai 四篇

本脚本的做法：
  1. 原子词拆分：把概念拆成若干「原子词」，任一命中即算覆盖
  2. 同义词组：一个概念可以有多个说法（如 回放/录像/replay）
  3. 输出命中在哪些文档 —— 命中不等于覆盖得好，要看落在哪篇、那篇有多少行

输出三档：
  空白     所有说法都没命中          → 可考虑新建
  疑似     只命中了原子词/边缘词      → ⚠ 先反哺，不要新建
  已覆盖   命中了主说法              → 不要新建

用法：
  python3 scan-gaps.py                       # 扫描内置概念清单
  python3 scan-gaps.py 转职 觉醒 宝石        # 扫描指定概念
  python3 scan-gaps.py --file list.txt       # 从文件读（每行一个概念）
"""
import os
import re
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOWTO = os.path.join(ROOT, 'references', 'howto', 'godot')

# 概念 → 说法，分两级
#   core：强特征词。命中它，就能确定文档真的在讲这个东西。
#   weak：宽泛/易歧义词。命中它**不足以**判定覆盖，只能算「疑似」。
#
# ⚠ 为什么要分两级：2026-09 实测，扁平词表 + 「成节即算覆盖」的判据
#   产生了**反向误判** —— 把空白报成已覆盖，比漏报更危险：
#     · 「转职/觉醒」→ 词表里的「进阶」命中 movement-advanced 的标题
#       《进阶移动：二段跳、爬墙抓边…》→ 判已覆盖。实为「移动进阶」，
#       与转职无关；「转职」「觉醒」在全部 howto 里 0 命中。
#     · 「宝石/符文」→ 「socket」在 firearms.md 出现 5 次 → 判已覆盖。
#       实为 shoulder socket（摄像机肩部挂点）/ 命中源 socket，
#       是骨骼挂点不是宝石插槽；「宝石」「符文」同样 0 命中。
#   ⛔ 上一版 WEAK 集合更是把「宝石」「符文」「存档」这些**核心词**
#      列成了弱词，方向完全反了 —— 弱词应按「词本身的泛化度」定义，
#      而不是按「它属于哪个概念」。
CONCEPTS_CORE = {
    '转职/觉醒':        ['转职', '觉醒', 'class change', 'awaken', '职业进阶'],
    '宝石/符文':        ['宝石', '符文', '镶嵌', 'gem', 'rune'],
    '精炼/淬炼':        ['精炼', '淬炼', '洗练', '重铸', 'refine'],
    '卡牌构筑':         ['卡组', '卡池', '构筑', 'deck build'],
    'roguelike':        ['roguelike', '房间图', '关卡生成'],
    '局内构筑/遗物':     ['遗物', '词条选择', '局内成长', 'relic'],
    '天气/季节':        ['天气', '季节', 'weather', 'season'],
    '昼夜循环':         ['昼夜', '日夜', 'day night', 'time of day'],
    '竞技场/排位':      ['竞技场', '排位', '天梯', '段位', 'arena', 'ranked', 'ladder'],
    '跨服/据点战':      ['跨服', '据点战', '攻城', '国战', 'server war', 'siege'],
    '公会战':           ['公会战', '帮战', 'guild war'],
    '排行榜':           ['排行榜', '榜单', 'leaderboard'],
    '成就':             ['成就', 'achievement', '奖杯', 'trophy'],
    '签到/活跃度':      ['签到', '活跃度', 'login reward', 'daily check'],
    'VIP/累充':         ['vip', '累充', '首充', '月卡', '充值档位'],
    '客服/工单':        ['客服', '工单', 'ticket'],
    '植被/ foliage':    ['植被', 'foliage'],
    '云层/天空':        ['云层', '天空', 'sky', 'volumetric'],
    '后处理':           ['后处理', 'post process', 'bloom', '景深', 'dof'],
    '粒子/拖尾':        ['粒子', '拖尾', '残影', 'particle', 'trail'],
    '关卡流程':         ['关卡流程', '关卡编辑', '触发器'],
    '传送点/复活点':    ['传送点', '复活点', '检查点', 'checkpoint', 'teleport'],
    '编辑器工具':       ['编辑器工具', 'tool script', 'editorplugin'],
    '资源命名规范':     ['命名规范', '命名约定', '资源规范'],
    '掉落/开箱':        ['掉落', '开箱', 'loot', 'drop table', '宝箱'],
    '赛季/赛季制':      ['赛季', 'battlepass', '战令', 'season pass'],
    '观战/OB':          ['观战', 'spectate'],
    '教学/新手引导':    ['新手引导', 'tutorial', 'onboarding'],
    '技能树/天赋':      ['技能树', '天赋', 'talent', 'skill tree'],
    '宠物/坐骑':        ['宠物', '坐骑', 'pet', 'mount'],
    '捏脸/自定义':      ['捏脸', '角色自定义', 'customization'],
    '战斗手感':         ['打击感', 'game feel', 'juice'],
    'AI战术':           ['战术', '阵型', '攻击令牌', '掩体点'],
    'AI感知':           ['感知', '视锥', 'perception'],
    'AI决策':           ['行为树', '状态机', 'goap', 'behavior tree'],
    '寻路':             ['寻路', 'navigation', 'astar', 'pathfinding'],
    '音频':             ['音频', 'audio', '总线'],
    '存档':             ['存档', '序列化'],
    '网络同步':         ['同步', 'rpc', 'multiplayer', 'network'],
    '配置表':           ['配表', '配置表', 'datatable'],
    '性能优化':         ['profiler', '帧率'],
    '热更新':           ['热更新', '热更', 'hotupdate'],
    '安全/反作弊':      ['反作弊', '签名', 'security'],
    '合规/版号':        ['版号', '合规', '实名', '防沉迷', 'compliance'],
}

# 弱词：单独命中时**不能**证明覆盖，只能算「疑似」
# ⚠ 人工复核结论：扫不出结论的概念，人打开看一眼，**记录下来**。
#
#   ⛔ 为什么不只靠自动判据：「核心词高频但未成节」这一档，机器**无法**
#      区分「顺带提到」和「写了但没起小节」——两者在词频上完全相同。
#      ⛔ 更糟的是：不记录结论的话，下一轮扫描会**原样再报一遍**，
#        人又要重新核实一次，而且可能得出不同结论（结论漂移）。
#
#   ✅ 结论四选一：
#     blank            真空白 —— 命中全是别的话题，可新建
#     partial          部分覆盖 —— 有涉及但不是这个主题，反哺指定文档
#     covered_by_other 已被别的文档覆盖 —— 概念名起错了，改概念名
#     concept_split    概念本身混了两个主题 —— 拆开
REVIEWED = {
    'roguelike': (
        'covered_by_other',
        'roguelike 由 `genres-roguelike.md` 专讲（生成管线+房间图+道具池+'
        '可复现RNG），已覆盖；但「遗物/词条选择/局内成长」是**局内构筑**，'
        '另一回事且未覆盖。概念表已拆为「roguelike」与「局内构筑/遗物」。'),
    '宝石/符文': (
        'blank',
        'economy 的「镶嵌×3」只是数值管线的一环（`EquipmentInstance` 的'
        '一个字段名、属性链 `…→强化→镶嵌→外部buff`），全篇没讲宝石/符文'
        '系统本身（插槽数/宝石等级/拆卸损耗/套装触发）。'),
    '植被/ foliage': (
        'blank',
        '四处命中分属四个不同话题：upscaling 讲 MSAA 对 alpha scissor 的坑、'
        'procedural-generation 讲泊松采样布点、openworld 讲装饰内容、'
        'plugins 讲插件选型。**没有一篇在讲植被系统本身**。'),
    '竞技场/排位': (
        'partial',
        'sharding-matchmaking 的「段位×8」出现在**合服保留优先级**与'
        '**赛季结算**语境（按段位排序决定保留谁、赛季时间语义），'
        '不是匹配赛制本身。赛制/ELO/匹配池/禁用英雄未讲。'),
    '关卡流程': (
        'covered_by_other',
        '⚠ 本扫描器只扫 howto，**看不出流程层已有域**。'
        '流程层 `flow/godot/level/` 已铺（8 文件 / 37 节点）；'
        'howto 层分散在 level-design / systems / camera-cutscene / '
        'tilemap / openworld 五篇。建议反哺而非新建。'),
    '公会战': (
        'partial',
        'social 里只出现 1 次，是关系链/组队语境的顺带提及，'
        '公会战本身（报名/编队/集结/结算/跨服）未讲。'),
    '局内构筑/遗物': (
        'partial',
        '「遗物」散在 build-affix(×2) 与 genres-roguelike(×1)，'
        '都是举例。局内构筑系统本身（遗物池/稀有度/协同/三选一/局外解锁）未讲，'
        '应反哺 `genres-roguelike.md`。'),
    'VIP/累充': (
        'partial',
        'monetization 的「月卡×3」只讲**到期时间必须按 UTC 算**，'
        'VIP 等级、累充档位、权益分层、累充进度跨档结算未讲。'),
}

CONCEPTS_WEAK = {
    '转职/觉醒':        ['进阶'],
    '宝石/符文':        ['插槽', 'socket'],
    '精炼/淬炼':        ['品阶'],
    '卡牌构筑':         ['deck', 'build'],
    'roguelike':        ['rogue'],

    '竞技场/排位':      ['rank'],
    '跨服/据点战':      ['据点'],
    '公会战':           ['团战'],
    '排行榜':           ['排名', 'ranking'],
    '签到/活跃度':      ['日常'],
    '客服/工单':        ['申诉', 'support'],
    '植被/ foliage':    ['草', '树'],
    '云层/天空':        ['云', 'cloud'],
    '粒子/拖尾':        ['ghost'],
    '关卡流程':         ['trigger'],
    '编辑器工具':       ['批量'],
    '资源命名规范':     ['naming'],
    '掉落/开箱':        ['drop'],
    '赛季/赛季制':      ['season'],
    '观战/OB':          ['ob'],
    '教学/新手引导':    ['引导', '教学'],
    '战斗手感':         ['手感'],
    'AI战术':           ['仇恨'],
    'AI感知':           ['视野'],
    'AI决策':           ['决策'],
    '寻路':             ['导航'],
    '音频':             ['bus'],
    '存档':             ['save'],
    '网络同步':         ['网络'],
    '配置表':           ['csv'],
    '性能优化':         ['性能', '优化'],
    '热更新':           ['pck'],
    '安全/反作弊':      ['安全', '加密'],
}

# 扁平视图（供 dev-route 统计、命令行单概念查询用）
CONCEPTS = {k: CONCEPTS_CORE.get(k, []) + CONCEPTS_WEAK.get(k, [])
            for k in set(CONCEPTS_CORE) | set(CONCEPTS_WEAK)}

def load_docs():
    """返回 {docname: (text, lines, heads)}"""
    out = {}
    for fp in sorted(glob.glob(os.path.join(HOWTO, '*.md'))):
        name = os.path.basename(fp)[:-3]
        s = open(fp, encoding='utf-8').read()
        heads = [m.group(1).strip() for m in re.finditer(r'^#{1,3}\s+(.*)$', s, flags=re.M)]
        out[name] = (s, len(s.split('\n')), heads)
    return out


def stats():
    """输入语料计数。"""
    files = glob.glob(os.path.join(HOWTO, '*.md'))
    return {
        'howto_docs': len(files),
        'concepts': len(CONCEPTS),
        'terms': sum(len(v) for v in CONCEPTS.values()),
    }


def guard():
    """ⓘ 独立运行时也自检输入语料，不只在 dev-route 自检里兜。"""
    try:
        import corpus_guard
        _, fails = corpus_guard.run([sys.modules[__name__]])
        for f in fails:
            print('✗ ' + f, file=sys.stderr)
        return not fails
    except Exception as e:
        # ⚠ 必须 **fail-closed**：守卫自身出错时拒绝放行。
        #   上一版写的 `return True` 等于"守卫坏了 = 检查通过"，
        #   ⛔ 这正是本模块要消灭的那类静默放行 —— 在自己身上又犯了一次。
        print('⛔ 语料守卫不可用，拒绝放行（%s）' % e, file=sys.stderr)
        return False


def main():

    if not guard():
        return 2
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    docs = load_docs()
    if not docs:
        print('✗ 没找到 howto 文档：%s' % HOWTO)
        return 1

    if args:
        concepts = {}
        for a in args:
            concepts[a] = [a]
    else:
        concepts = CONCEPTS

    blank, mention, suspect, covered = [], [], [], []
    for name, terms in concepts.items():
        # ⓘ 命令行单概念查询时 concepts[name] == [name]，该词不在任何
        #   分级表里 —— 此时视为核心词，否则永远只判「仅提及」。
        core = set(CONCEPTS_CORE.get(name, []) or terms)
        # (doc, 命中的说法, 该说法出现次数, 是否成节, 文档行数)
        hits = []
        for doc, (text, lines, heads) in docs.items():
            best = None
            for t in terms:
                cnt = text.count(t)
                if cnt:
                    in_head = any(t in h for h in heads)
                    # ⚠ 第一维是「是否核心词」：核心词永远压过弱词。
                    #   ⛔ 上一版第一维是 in_head —— 于是「进阶」因为出现在
                    #      movement-advanced 的标题《进阶移动：二段跳…》里
                    #      就压过一切，把「转职/觉醒」误判为已覆盖
                    #      （实测「转职」「觉醒」在全部 howto 里 0 命中）。
                    score = (1 if t in core else 0,
                             1 if in_head else 0, cnt)
                    if best is None or score > best[0]:
                        best = (score, doc, t, cnt, in_head, lines)
            if best:
                hits.append((best[1], best[2], best[3], best[4], best[5]))
        if not hits:
            blank.append((name, terms))
            continue
        # ⚠ 覆盖判据：**核心词必须成节**（出现在 #/##/### 标题里）。
        #   ⛔ 为什么频次不再够用：词频区分不了「专门讲」和「反复顺带提」。
        #      2026-09 实测三个反例，词频都 ≥3 但都不是该主题：
        #        · 宝石/符文 ← economy「镶嵌×3」：装备实例的一个字段名、
        #          数值管线的一环，全篇没讲宝石/符文系统
        #        · roguelike ← ai-navigation×3：AStarGrid2D 的适用类型举例
        #        · 植被 ← upscaling×3：MSAA 对 alpha scissor 材质的已知坑
        #      ⛔ 据此判「已覆盖」就会把真空白当成已做 —— 比漏报危险得多。
        #   ✅ 成节是「专门讲」的强信号：写作者会给专门的主题单起一节。
        solid = [h for h in hits if h[1] in core and h[3]]
        if solid:
            covered.append((name, hits, solid))
            continue
        # 核心词在正文高频但**没成节** → 疑似，必须人工复核
        #   （是顺带提到，还是写了但没起小节）
        freq = [h for h in hits if h[1] in core and h[2] >= 3]
        if freq:
            suspect.append((name, terms, freq))
        else:
            mention.append((name, terms, hits))

    print('=' * 70)
    print('覆盖扫描（原子词 + 频次/成节判据）　howto 文档 %d 篇' % len(docs))
    print('=' * 70)

    print('\n### 空白（所有说法都没命中）—— 可考虑新建')
    if not blank:
        print('  （无）')
    for name, terms in blank:
        print('  • %-16s 说法：%s' % (name, '/'.join(terms)))

    print('\n### ⚠ 仅提及（命中但没成节、出现 <3 次）—— 先反哺，不要新建')
    if not mention:
        print('  （无）')
    unreviewed = []
    for name, terms, hits in mention:
        core = set(CONCEPTS_CORE.get(name, []) or terms)
        hs = sorted(hits, key=lambda h: -h[2])[:3]
        locs = ', '.join('%s(%s×%d%s%s)' % (
                    d, t, c, ',成节' if ih else '',
                    '' if t in core else ',弱词')
                         for d, t, c, ih, l in hs)
        print('  • %-16s → %s' % (name, locs))
        rv = REVIEWED.get(name)
        if rv:
            print('       ✅ 已复核（%s）：%s' % (rv[0], rv[1]))
        else:
            unreviewed.append(name)

    print('\n### ⚠ 疑似覆盖（核心词高频但未成节）—— 必须人工复核')
    if not suspect:
        print('  （无）')
    for name, terms, freq in suspect:
        hs = sorted(freq, key=lambda h: -h[2])[:3]
        locs = ', '.join('%s(%s×%d)' % (d, tt, c) for d, tt, c, ih, l in hs)
        print('  • %-16s → %s' % (name, locs))
        rv = REVIEWED.get(name)
        if rv:
            # ✅ 已复核：直接给结论 + 理由，不必再打开看一遍
            print('       ✅ 已复核（%s）：%s' % (rv[0], rv[1]))
        else:
            print('       ⚠ 未复核 —— 可能是「顺带提到」也可能是'
                  '「写了但没起小节」，打开看一眼再决定')
            unreviewed.append(name)

    if unreviewed:
        print('\n  ⚠ 有 %d 个疑似概念尚未人工复核：%s'
              % (len(unreviewed), '、'.join(unreviewed)))
        print('     复核后把结论写进 REVIEWED 表，'
              '⛔ 否则下一轮会原样再报一遍、且可能得出不同结论')

    print('\n### 已覆盖（核心词成节）—— 不要新建')
    for name, hits, solid in covered:
        b = max(solid, key=lambda h: (h[3], h[2]))
        print('  • %-16s → %s（%s×%d%s, %d 行）'
              % (name, b[0], b[1], b[2], ',成节' if b[3] else '', b[4]))

    print('\nⓘ 判据（三档）：')
    print('  已覆盖 = 核心词成节；疑似 = 核心词高频但未成节；')
    print('  仅提及 = 只有弱词命中 或 核心词低频。')
    print('  ⛔ 弱词（进阶/socket/云/树/ob…）永远不足以判定覆盖：它们是')
    print('     别的话题里也会出现的泛化词。')
    print('  ⛔ 频次也不足以判定覆盖：词频区分不了「专门讲」和')
    print('     「反复顺带提」（实测：镶嵌×3/roguelike×3/植被×3 全是后者）。')
    print('  即便"已覆盖"，也要看行数：薄文档仍需反哺而非新建。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
