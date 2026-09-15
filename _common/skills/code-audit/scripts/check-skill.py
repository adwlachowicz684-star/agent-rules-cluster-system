#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check-skill.py —— skill 自身结构与引用完整性检查

对应社区 lint 工具的核心检查项：
    FM001  frontmatter 必填字段        FM013  frontmatter 未闭合
    NR001  目录名与 name 一致          SK005  description 写明「何时使用」
    SK006  体积预算                    LK001  引用了不存在的文件（断链）← 唯一 error
    PD001  孤儿文件                    PD002  根目录冗余文件
    SK009  reference 单文件过大（支持 oversize-exempt 声明豁免）

用法：
    python3 check-skill.py                    # 检查本 skill
    python3 check-skill.py --skill=<路径>
    python3 check-skill.py --json
"""

import os
import re
import sys
import json

_flags = [a for a in sys.argv[1:] if a.startswith('--')]

SKILL_DIR = None
for f in _flags:
    if f.startswith('--skill='):
        SKILL_DIR = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
if SKILL_DIR is None:
    SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

REDUNDANT_ROOT = {'README.md', 'CHANGELOG.md', 'INSTALLATION_GUIDE.md',
                  'QUICK_REFERENCE.md', 'INSTALLATION.md'}

MAX_SKILL_LINES = 500      # 绝对上限：超过必须拆
# 建议上限：与 skill-evolution 的 config.yaml size_limits.SKILL.md 一致。
# 两处若不统一，会出现「本文件 235 行、自检却说通过」——超了没人管。
MAX_SKILL_SOFT = 200
MAX_REF_LINES = 200
MAX_REF_TOKENS = 8192
MAX_SCRIPT_LINES = 300

errors, warnings, infos = [], [], []


def add(level, code, msg):
    (errors if level == 'error' else warnings if level == 'warn' else infos).append(
        '[%s] %s' % (code, msg))


def token_estimate(text):
    """中英混合粗估：中文 1 字 ≈ 1.5 token，其余 4 字符 ≈ 1 token"""
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    return int(cjk * 1.5 + (len(text) - cjk) / 4)


# ---- SY001：体积阈值与 skill-evolution 的 config.yaml 一致性 ----
#
# 为什么不是「直接读 config.yaml」：两个 skill 是独立可分发的单元。
# 把 code-audit 单独拷到别的项目，进化侧路径就不存在了——
# 运行时依赖会让自检在这里崩，或更糟：静默降级成默认值。
# 硬编码 + 注释溯源，代价是数字可能漂移；运行时依赖，代价是换环境就失效。
# 前者是慢性病，后者是急性的，所以选前者。
#
# 但「漂移没人知道」这半个风险必须堵掉：找到 config 就比对，找不到就跳过。
# 这样口头约定变成了可验证的，同时保留了独立分发能力。
EV_CONFIG_REL = ('..', '..', '..', '..',
                 'self-evolving_skill_mechanism', 'skills', 'config.yaml')


def evolution_skill_limit():
    """返回进化侧 config.yaml 里的 SKILL.md 上限；拿不到则返回 None。

    None 一律按「跳过」处理——不因为环境缺失而误报，
    否则单独分发时会冒出一条无法解释的告警。
    """
    p = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), *EV_CONFIG_REL))
    if not os.path.isfile(p):
        return None
    # 只取 size_limits 块下的 SKILL.md，手撕而不引入 yaml 依赖：
    # 本脚本要求零第三方依赖（CI 里可能没装 pyyaml）。
    try:
        txt = open(p, encoding='utf-8').read()
    except OSError:
        return None
    m = re.search(r'^size_limits:\s*$', txt, re.M)
    if not m:
        return None
    block = txt[m.end():]
    nxt = re.search(r'^\S', block, re.M)
    if nxt:
        block = block[:nxt.start()]
    kv = re.search(r'^\s+SKILL\.md:\s*(\d+)\s*$', block, re.M)
    return int(kv.group(1)) if kv else None


def check_threshold_drift():
    """本文件的硬编码上限 vs 进化侧 config，不一致就报。"""
    want = evolution_skill_limit()
    if want is None:
        # 独立分发场景：进化侧不在，跳过（不误报）
        return []
    if want == MAX_SKILL_SOFT:
        return []
    return [{'level': 'warn', 'code': 'SY001',
             'msg': ('SKILL.md 建议上限 %d 与 skill-evolution config.yaml 的 %d 不一致；'
                     '本文件注释已失真，两侧标准会各说各话' % (MAX_SKILL_SOFT, want))}]


def main():
    skill_md = os.path.join(SKILL_DIR, 'SKILL.md')
    if not os.path.isfile(skill_md):
        print('错误：找不到 SKILL.md（%s）' % skill_md)
        sys.exit(1)

    content = open(skill_md, encoding='utf-8').read()
    lines = content.split('\n')
    name = desc = None

    if content.startswith('---'):
        m = re.match(r'^---\n(.*?)\n---\n', content, re.S)
        if m:
            fm = m.group(1)
            nm = re.search(r'^name:\s*(.+)$', fm, re.M)
            dm = re.search(r'^description:\s*(.+)$', fm, re.M)
            name = nm.group(1).strip() if nm else None
            desc = dm.group(1).strip() if dm else None
            if not name:
                add('warn', 'FM001', 'frontmatter 缺少 name')
            if not desc:
                add('warn', 'FM001', 'frontmatter 缺少 description')
        else:
            add('warn', 'FM013', 'frontmatter 未正确闭合')
    else:
        add('info', 'FM001', '无 YAML frontmatter（本平台可省略；跨平台分发时必须补）')

    if name and name != os.path.basename(SKILL_DIR):
        add('warn', 'NR001', 'name "%s" 与目录名 "%s" 不一致' % (name, os.path.basename(SKILL_DIR)))

    if desc:
        if not re.search(r'use when|when to use|何时使用|用于|适用', desc, re.I):
            add('warn', 'SK005', 'description 未写明触发时机')
        if len(desc) > 1024:
            add('warn', 'SK006', 'description 超过 1024 字符（%d）' % len(desc))
    elif not re.search(r'何时使用|用于|适用|何时触发', '\n'.join(lines[:15])):
        add('warn', 'SK005', '正文开头未说明何时使用（影响触发准确性）')

    if len(lines) > MAX_SKILL_SOFT:
        add('warn', 'SK006', 'SKILL.md %d 行，超过建议上限 %d 行'
            '（依据 skill-evolution config.yaml 的 size_limits；细节应下沉 reference/）'
            % (len(lines), MAX_SKILL_SOFT))
    # 阈值本身是否还对齐进化侧 config（独立分发时自动跳过）
    for issue in check_threshold_drift():
        add(issue['level'], issue['code'], issue['msg'])
    if len(lines) > MAX_SKILL_LINES:
        add('error', 'SK006', 'SKILL.md %d 行，超过绝对上限 %d 行（必须拆）'
            % (len(lines), MAX_SKILL_LINES))
    tok = token_estimate(content)
    if tok > MAX_REF_TOKENS:
        add('warn', 'SK006', 'SKILL.md 约 %d tokens，超过 %d' % (tok, MAX_REF_TOKENS))
    infos.append('[INFO] SKILL.md: %d 行 / 约 %d tokens' % (len(lines), tok))

    # LK001：剥离 #锚点 与 ?查询，否则 workflow.md#第-1-步 会误判为断链
    def _clean(r):
        return r.split('#')[0].split('?')[0].rstrip('/')

    refs = set()
    for m in re.findall(r'`((?:references|scripts|assets)/[^`\s]+)`', content):
        refs.add(_clean(m))
    for m in re.findall(r'\]\(((?:references|scripts|assets)/[^)\s]+)\)', content):
        refs.add(_clean(m))
    refs.discard('')
    broken = [r for r in sorted(refs) if not os.path.exists(os.path.join(SKILL_DIR, r))]
    for r in broken:
        add('error', 'LK001', '引用了不存在的文件: %s' % r)
    infos.append('[INFO] SKILL.md 显式引用 %d 个资源文件，%s'
                 % (len(refs), '全部存在' if not broken else '有断链'))

    # 提及范围：SKILL.md + 子文档（references/ assets/ 下的 .md）。
    #
    # 为什么不能只看 SKILL.md：内容下沉到 reference 后，引用关系随内容一起搬走
    # （例：命令速查表下沉到 references/commands.md 后，那里引用的脚本
    # 在 SKILL.md 里就不出现了）。只扫主文件会把它们全判成孤儿，
    # 逼人把内容搬回主文件——与「细节下沉」直接冲突。
    corpus = content
    for _sub in ('references', 'assets'):
        _d = os.path.join(SKILL_DIR, _sub)
        if not os.path.isdir(_d):
            continue
        for _f in sorted(os.listdir(_d)):
            if _f.endswith('.md') and not _f.startswith('.'):
                try:
                    corpus += '\n' + open(os.path.join(_d, _f), encoding='utf-8').read()
                except OSError:
                    pass

    for sub in ('references', 'scripts', 'assets'):
        d = os.path.join(SKILL_DIR, sub)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.startswith('.') or f == '__pycache__':
                continue
            rel = '%s/%s' % (sub, f)
            if rel in refs or f in corpus or rel in corpus:
                continue
            add('warn', 'PD001', '孤儿文件（无任何文档提及）: %s' % rel)

    for f in sorted(os.listdir(SKILL_DIR)):
        if f in REDUNDANT_ROOT and os.path.isfile(os.path.join(SKILL_DIR, f)):
            add('warn', 'PD002', '根目录冗余文件（社区共识应移除）: %s' % f)

    # PD003 悬挂引用：正文里反引号引用的技能内部文件必须真实存在。
    # 改名/拆分后最容易留下这类断链——读文档的人点过去是 404，
    # 而它在 SKILL.md 层面完全看不出问题，只有逐个文件扫才能发现。
    _known = {'rule.json',  # open-code-review 的外部配置，非本技能文件
              'registry.json', '.audit-rules.json', '.audit-state.json',
              'README.md', 'package.json', '.gitignore', 'Cargo.toml',
              'cc.config.json', 'SKILL.md', 'AGENTS.md', 'CLAUDE.md'}
    _exts = ('.md', '.py', '.ts', '.json')
    def _exists(name):
        if name in _known:
            return True
        for d in (SKILL_DIR, os.path.join(SKILL_DIR, 'references'),
                  os.path.join(SKILL_DIR, 'scripts'),
                  os.path.join(SKILL_DIR, 'assets'),
                  os.path.join(SKILL_DIR, 'rules')):
            if os.path.isfile(os.path.join(d, name)):
                return True
        return os.path.isfile(name)
    _targets = [os.path.join(SKILL_DIR, 'SKILL.md')]
    for _sub in ('references', 'assets'):
        _dd = os.path.join(SKILL_DIR, _sub)
        if os.path.isdir(_dd):
            for f in sorted(os.listdir(_dd)):
                if not f.endswith('.md'):
                    continue
                # changelog 记录的是「当时叫什么」，被删掉的文件名在这里出现是合法的
                if f == 'changelog.md':
                    continue
                _targets.append(os.path.join(_dd, f))
    for _tf in _targets:
        try:
            _txt = open(_tf, encoding='utf-8').read()
        except OSError:
            continue
        for _m in set(re.findall(r'`([A-Za-z0-9][A-Za-z0-9\-_.]*\.(?:md|py|ts|json))`', _txt)):
            if not _exists(_m):
                add('warn', 'PD003', '悬挂引用（文件不存在）: %s 内引用 %s'
                    % (os.path.basename(_tf), _m))

    refdir = os.path.join(SKILL_DIR, 'references')
    if os.path.isdir(refdir):
        for f in sorted(os.listdir(refdir)):
            if not f.endswith('.md'):
                continue
            txt = open(os.path.join(refdir, f), encoding='utf-8').read()
            n, t = len(txt.split('\n')), token_estimate(txt)
            em = re.search(r'<!--\s*oversize-exempt\s*:\s*([^-]*)-->', txt[:300])
            if n > MAX_REF_LINES:
                if em:
                    infos.append('[INFO] references/%s %d 行（已声明豁免：%s）'
                                 % (f, n, em.group(1).strip()))
                else:
                    add('warn', 'SK009', 'references/%s %d 行，超过建议 %d 行'
                        % (f, n, MAX_REF_LINES))
            if t > MAX_REF_TOKENS and not em:
                add('warn', 'SK009', 'references/%s 约 %d tokens，超过 %d'
                    % (f, t, MAX_REF_TOKENS))

    sdir = os.path.join(SKILL_DIR, 'scripts')
    if os.path.isdir(sdir):
        for f in sorted(os.listdir(sdir)):
            if f.startswith('.') or f == '__pycache__':
                continue
            try:
                n = len(open(os.path.join(sdir, f), encoding='utf-8').read().split('\n'))
            except Exception:
                continue
            if n > MAX_SCRIPT_LINES:
                infos.append('[INFO] scripts/%s %d 行（%d 为参考值；脚本按需执行不占上下文）'
                             % (f, n, MAX_SCRIPT_LINES))

    if '--json' in _flags:
        json.dump({'skill': SKILL_DIR, 'errors': errors, 'warnings': warnings,
                   'infos': infos}, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print('=' * 70)
        print('skill 结构检查 · %s' % SKILL_DIR)
        print('=' * 70)
        print('\n错误 %d · 警告 %d' % (len(errors), len(warnings)))
        for x in errors:
            print('  ✗ ' + x)
        for x in warnings:
            print('  ▲ ' + x)
        print('\n信息：')
        for x in infos:
            print('  · ' + x)
        print('\n' + '=' * 70)
        print('结论：%s' % ('通过' if not errors else '存在 %d 个错误需修复' % len(errors)))
        print('=' * 70)

    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
