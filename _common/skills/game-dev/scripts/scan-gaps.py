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

# 概念 → 说法列表（第一个是主说法，其余是同义/原子词）
# ⚠ 维护原则：新增概念时，把「所有可能已经写过的说法」都列上，
#    否则会重演"录像回放"的误判。
CONCEPTS = {
    '转职/觉醒':        ['转职', '觉醒', '进阶', '职业进阶', 'class change', 'awaken'],
    '宝石/符文':        ['宝石', '符文', '镶嵌', '插槽', 'gem', 'rune', 'socket'],
    '精炼/淬炼':        ['精炼', '淬炼', '洗练', '重铸', '品阶', 'refine'],
    '卡牌构筑':         ['构筑', '卡组', '卡池', '抽卡组', 'deck', 'build'],
    'roguelike词条':    ['roguelike', 'rogue', '词条选择', '局内成长', '遗物'],
    '天气/季节':        ['天气', '季节', 'weather', 'season'],
    '昼夜循环':         ['昼夜', '日夜', 'day night', 'time of day'],
    '竞技场/排位':      ['竞技场', '排位', '天梯', '段位', 'arena', 'ranked', 'ladder'],
    '跨服/据点战':      ['跨服', '据点', '攻城', '国战', 'server war', 'siege'],
    '公会战':           ['公会战', '帮战', '团战', 'guild war'],
    '排行榜':           ['排行榜', '榜单', '排名', 'leaderboard', 'ranking'],
    '成就':             ['成就', 'achievement', '奖杯', 'trophy'],
    '签到/活跃度':      ['签到', '活跃度', '日常', 'daily check', 'login reward'],
    'VIP/累充':         ['vip', '累充', '首充', '充值档位', '月卡'],
    '客服/工单':        ['客服', '工单', '申诉', 'ticket', 'support'],
    '植被/ foliage':    ['植被', 'foliage', '草', '树', '植被系统'],
    '云层/天空':        ['云', '天空', 'sky', 'cloud'],
    '后处理':           ['后处理', 'post process', 'bloom', '景深', 'dof'],
    '粒子/拖尾':        ['粒子', '拖尾', '残影', 'particle', 'trail', 'ghost'],
    '关卡流程':         ['关卡流程', '关卡编辑', '触发器', 'trigger'],
    '传送点/复活点':    ['传送点', '复活点', '检查点', 'checkpoint', 'teleport'],
    '编辑器工具':       ['编辑器工具', 'tool script', '批量', 'editorplugin'],
    '资源命名规范':     ['命名规范', '命名约定', '资源规范', 'naming'],
    '掉落/开箱':        ['掉落', '开箱', 'loot', 'drop table', '宝箱'],
    '赛季/赛季制':      ['赛季', 'season pass', 'battlepass', '战令'],
    '观战/OB':          ['观战', 'ob', 'spectate'],
    '教学/新手引导':    ['教学', '新手引导', '引导', 'onboarding', 'tutorial'],
    '技能树/天赋':      ['技能树', '天赋', 'talent', 'skill tree'],
    '宠物/坐骑':        ['宠物', '坐骑', 'pet', 'mount'],
    '捏脸/自定义':      ['捏脸', '角色自定义', 'customization'],
    '战斗手感':         ['手感', '打击感', 'game feel', 'juice'],
    'AI战术':           ['战术', '阵型', '攻击令牌', '仇恨', '掩体点'],
    'AI感知':           ['感知', '视锥', '视野', 'perception'],
    'AI决策':           ['行为树', '状态机', 'goap', '决策', 'behavior tree'],
    '寻路':             ['寻路', 'navigation', '导航', 'astar', 'pathfinding'],
    '音频':             ['音频', 'audio', '总线', 'bus'],
    '存档':             ['存档', 'save', '序列化'],
    '网络同步':         ['网络', '同步', 'rpc', 'multiplayer', 'network'],
    '配置表':           ['配表', '配置表', 'datatable', 'csv'],
    '性能优化':         ['性能', '优化', 'profiler', '帧率'],
    '热更新':           ['热更新', '热更', 'pck', 'hotupdate'],
    '安全/反作弊':      ['反作弊', '安全', '加密', '签名', 'security'],
    '合规/版号':        ['版号', '合规', '实名', '防沉迷', 'compliance'],
}

# 太短/太泛的词，命中它们只能算「疑似」不能算「已覆盖」
WEAK = {
    '草', '树', '云', '天空', '批量', '日常', '手感', '引导',
    '同步', '网络', '性能', '优化', '安全', '加密', '音频', '存档',
    '网络', '导航', '决策', '感知', '视野', '教学', '宠物', '坐骑',
    '掉落', '赛季', '排位', '成就', '日常', '宝石', '符文',
}


def load_docs():
    """返回 {docname: (text, lines, heads)}"""
    out = {}
    for fp in sorted(glob.glob(os.path.join(HOWTO, '*.md'))):
        name = os.path.basename(fp)[:-3]
        s = open(fp, encoding='utf-8').read()
        heads = [m.group(1).strip() for m in re.finditer(r'^#{1,3}\s+(.*)$', s, flags=re.M)]
        out[name] = (s, len(s.split('\n')), heads)
    return out


def main():
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

    blank, mention, covered = [], [], []
    for name, terms in concepts.items():
        # (doc, 命中的说法, 该说法出现次数, 是否成节, 文档行数)
        hits = []
        for doc, (text, lines, heads) in docs.items():
            best = None
            for t in terms:
                cnt = text.count(t)
                if cnt:
                    in_head = any(t in h for h in heads)
                    # 优先取「成节的」说法；其次取出现最多的
                    score = (1 if in_head else 0, cnt, t not in WEAK)
                    if best is None or score > best[0]:
                        best = (score, doc, t, cnt, in_head, lines)
            if best:
                hits.append((best[1], best[2], best[3], best[4], best[5]))
        if not hits:
            blank.append((name, terms))
            continue
        # ⚠ 覆盖判据：成节，或单篇出现 >=3 次（且不是弱词）
        solid = [h for h in hits if h[3] or (h[2] >= 3 and h[1] not in WEAK)]
        if solid:
            covered.append((name, hits, solid))
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
    for name, terms, hits in mention:
        hs = sorted(hits, key=lambda h: -h[2])[:3]
        locs = ', '.join('%s(%s×%d%s)' % (d, t, c, ',成节' if ih else '')
                         for d, t, c, ih, l in hs)
        print('  • %-16s → %s' % (name, locs))

    print('\n### 已覆盖（成节 或 单篇 ≥3 次）—— 不要新建')
    for name, hits, solid in covered:
        b = max(solid, key=lambda h: (h[3], h[2]))
        print('  • %-16s → %s（%s×%d%s, %d 行）'
              % (name, b[0], b[1], b[2], ',成节' if b[3] else '', b[4]))

    print('\nⓘ 判据：成节(出现在 ## 标题) 或 单篇出现≥3次 才算覆盖。')
    print('  "仅提及"通常是别的话题顺带提到 —— 反哺，不要新建域。')
    print('  即便"已覆盖"，也要看行数：薄文档仍需反哺而非新建。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
