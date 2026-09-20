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
    # 未知 flag 必须报错：手写 sys.argv 解析会**静默忽略**拼错的 flag，
    # 脚本照常跑完并返回 0 —— `check-skill.py --self-test` 就是这么
    # 「通过」的，而它压根没有自检。见 scripts/_flagguard.py。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _flagguard import guard
    guard(sys.argv, {'--json', '--skill='})

    skill_md = os.path.join(SKILL_DIR, 'SKILL.md')
    if not os.path.isfile(skill_md):
        print('错误：找不到 SKILL.md（%s）' % skill_md)
        sys.exit(1)

    content = open(skill_md, encoding='utf-8').read()
    # 用 splitlines() 而非 split('\n')：后者对以换行结尾的文件会多出一个
    # 末尾空串，行数**恒虚高 1**——上限 200 实际只让写 199 行，
    # 且 `wc -l` 报 200 而本脚本报 201，看起来像误报。
    lines = content.splitlines()
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
    # 外部配置文件：属于**被审查项目**的标准配置，不是本技能的文件。
    # 引用它们（如「tauri.conf.json 的 allowlist 要按需开启」）是在描述
    # 审查动作的对象，不是指向技能内部的文档。
    _known = {'rule.json',  # open-code-review 的外部配置，非本技能文件
              'registry.json', '.audit-rules.json', '.audit-state.json',
              'README.md', 'package.json', '.gitignore', 'Cargo.toml',
              'cc.config.json', 'tauri.conf.json',
              'SKILL.md', 'AGENTS.md', 'CLAUDE.md',
              # 以下是**被审项目**的文件名：判据里拿它们当例子讲（「某仓库的
              # conftest.py 提供了 fixture…」），不是指向本技能的文档。
              # 挂在警告里会淹没真断链，故显式登记——清单受版本控制，可审计。
              'conftest.py', 'run_all.py', 'runner.ts', 'crypto.ts',
              'plugins/foo/bar.md', 'lib/channel.ts', 'tests/crypto.test.ts'}
    _exts = ('.md', '.py', '.ts', '.json')
    # 原先只在几个固定目录下查**直接子文件** —— 于是 references 一分层
    # （如 references/godot-api/）就全查不到：godot-api/physics.md 明明存在，
    # 却被报成悬挂引用。更糟的是反过来也会发生：子目录里的**真**断链
    # 因为路径带 / 而从来查不到，这项检查在分层之后等于半失效。
    # 改成：① 递归收集所有相对路径 ② 按纯文件名索引 ③ 带 / 的按引用文件
    # 所在目录解析。
    _allrel = set()
    for _dp, _dns, _fns in os.walk(SKILL_DIR):
        _dns[:] = [d for d in _dns if d not in ('.git', '__pycache__',
                                               'fixtures', '审查产物')]
        for _f in _fns:
            _allrel.add(os.path.relpath(os.path.join(_dp, _f), SKILL_DIR))
    _byname = {}
    for _r in _allrel:
        _byname.setdefault(os.path.basename(_r), _r)

    def _exists(name, src_file=None):
        if name in _known:
            return True
        if name in _allrel or name in _byname:
            return True
        # 带目录的引用：从引用文件所在目录**逐级向上**找基准。
        #
        # 为什么要逐级：`references/godot-api/index.md` 里写的是
        # `godot-api/physics.md`，基准是 references/ 而不是它自己所在的
        # godot-api/ —— 只试一层就会把存在的四个文件全报成断链
        # （实测 4 条假断链）。向上到仓库根，还能覆盖
        # `self-evolving_skill_mechanism/...` 这种跨 skill 引用。
        if '/' in name and src_file:
            d = os.path.dirname(src_file)
            for _ in range(6):
                if os.path.isfile(os.path.normpath(os.path.join(d, name))):
                    return True
                parent = os.path.dirname(d)
                if not parent or parent == d:
                    break
                d = parent
        return os.path.isfile(name)
    _targets = [os.path.join(SKILL_DIR, 'SKILL.md')]
    for _sub in ('references', 'assets'):
        _dd = os.path.join(SKILL_DIR, _sub)
        if not os.path.isdir(_dd):
            continue
        # 递归：references 一分层（references/godot-api/），只扫直接子文件
        # 会让**整个子目录的文档都不在检查范围内** —— 断链查不到、
        # 撞号也查不到。分层是这两轮才出现的结构，检查得跟着走。
        for _dp, _dns, _fns in os.walk(_dd):
            _dns[:] = [d for d in _dns if d not in ('.git', '__pycache__')]
            for f in sorted(_fns):
                if not f.endswith('.md'):
                    continue
                # changelog 记录的是「当时叫什么」，被删掉的文件名在这里出现是合法的
                if f == 'changelog.md':
                    continue
                _targets.append(os.path.join(_dp, f))
    # LK002：**代码块里的命令**也必须指向真实脚本。
    #
    # 为什么单列：PD003 只认**反引号包裹**的引用 `` `scripts/x.py` ``，
    # 而文档里最常见的是代码块中的可执行命令：
    #     python3 scripts/doc-scan.py --src=<根>
    # 这种写法 PD003 一条都提取不到 —— 实测两条真死链（common-workflow.md
    # 与 review-checklist.md 里的 doc-scan.py，该脚本 2026-09-14 已拆成
    # doc-deliverable / doc-promise）因此**长期存在而无人知晓**。
    # 照着代码块敲命令是新手最典型的用法，这里的死链危害最大。
    _CMD_RX = re.compile(
        r'(?:python3?\s+|bash\s+)?'
        r'((?:scripts|references|assets)/[A-Za-z0-9_][A-Za-z0-9_./-]*\.'
        r'(?:py|sh|md|json|ts))')
    # 跨 skill 引用：本集群有两个 skill，互相指向对方 scripts/ 下的文件
    # 是常态（如引擎侧的 cocos_audit.py 转发壳）。从本 skill 解析必然
    # "不存在"。显式登记而非关掉检查——清单受版本控制，可审计。
    _CROSS = {'self-evolving_skill_mechanism/skills/scripts/cocos_audit.py',
              # game-dev / code-audit / localization 三 skill 互相指向对方文件是常态
              # （split-dev-audit.md 定的分工：开发侧指审查侧判据，审查侧指开发侧写法）。
              # 从本 skill 解析必然"不存在"——显式登记而非关掉检查。
              'game-dev/references/flow/godot/shaders.md',
              'game-dev/references/flow/godot/i18n.md',
              'code-audit/references/p-cocos.md',
              'code-audit/scripts/route.py',
              '../code-audit/scripts/route.py',
              'code-audit/scripts/godot-audit.py',
              '../../code-audit/scripts/godot-audit.py',
              '../../code-audit/references/p-godot.md'}
    # 按前缀放行（整目录互指，逐个登记太脆）：
    # 开发侧 godot 文档 ↔ 审查侧反模式清单是 1:1 互指，共 79 组。
    # 注意路径已被 _CMD_RX 规范化：它从 `game-dev/references/flow/godot/x.md`
    # 里截取的是 `references/flow/godot/x.md`（正则不要求行首），
    # 所以这里两种写法都要列，否则放行不生效。

    for _tf in _targets:
        if os.path.basename(_tf) == 'changelog.md':
            continue      # 同上：历史记录里的旧名是合法的
        try:
            _ctxt = open(_tf, encoding='utf-8').read()
        except OSError:
            continue
        # 先按**完整跨包路径**过滤掉已登记的引用，再提短路径，
        # 否则写全路径的跨包引用仍会被当成短路径匹配出来。
        _ctxt2 = _ctxt
        for _c in _CROSS:
            _ctxt2 = _ctxt2.replace(_c, ' ')
        # 同 skill 内的 flow/ → audit/ 互指（game-dev 拆分后的镜像引用）。
        # 注意文件名段不含 '/'，所以不会误伤 references/godot-api/ 这类引用。
        _ctxt2 = re.sub(r'references/(?:flow|audit)/godot/[A-Za-z0-9_.-]+\.md',
                        ' ', _ctxt2)
        for _m in sorted(set(_CMD_RX.findall(_ctxt2))):
            if not _exists(_m, _tf):
                add('error', 'LK002',
                    '代码块里的命令指向不存在的脚本: %s 内 %s'
                    % (os.path.basename(_tf), _m))

    for _tf in _targets:
        try:
            _txt = open(_tf, encoding='utf-8').read()
        except OSError:
            continue
        # 正则必须认路径分隔符：文档分层后引用写成 `godot-api/physics.md`，
        # 原先的字符类里没有 `/` → **带路径的引用一条都提取不到**，
        # 于是 references 一分层，这项检查对新结构就完全失效了
        # （实测：往 godot-api/index.md 里加一条指向不存在文件的引用，不报）。
        for _m in set(re.findall(r'`([A-Za-z0-9][A-Za-z0-9\-_./]*\.(?:md|py|ts|json))`', _txt)):
            if not _exists(_m, _tf):
                add('warn', 'PD003', '悬挂引用（文件不存在）: %s 内引用 %s'
                    % (os.path.basename(_tf), _m))

    # ---- IX001 撞号 / IX002 定义了却取不到 ----
    #
    # 为什么必须自动查（三次真实事故，全部「静默」）：
    #   ① 两个文件各自定义了 H-12（s-sandbox 与 s-contracts），撞号后
    #      --get H-12 返回两条，分不清属于哪个场景
    #   ② 整个 H 族写成 `### H-03 标题`（无 (Px) 级别括号），解析器匹配不到
    #      → 索引里 0 条、只能整文件读，而文件本身看起来完全正常
    #   ③ S-10/S-11/S-12/C-14 的正文被覆盖删除后，items.json 还留着全文副本，
    #      --get 仍能返回，直到有人跑 --sync 才真正消失
    # 三者都只能靠「定义数 vs 索引数」的差值发现。
    _refd = os.path.join(SKILL_DIR, 'references')
    if os.path.isdir(_refd):
        import collections as _col
        _rx = re.compile(r'^###\s+([A-Z]{1,4}-\d{1,3})', re.M)   # re.M 必需：^ 要匹配行首
        _defs = _col.defaultdict(list)
        for _f in sorted(os.listdir(_refd)):
            if not _f.endswith('.md'):
                continue
            try:
                _txt = open(os.path.join(_refd, _f), encoding='utf-8').read()
            except OSError:
                continue
            for _m in _rx.finditer(_txt):
                _defs[_m.group(1)].append(_f)
        for _id in sorted(_defs):
            if len(_defs[_id]) > 1:
                add('error', 'IX001', '判据 ID 撞号 %s：同时定义在 %s'
                    % (_id, ' / '.join(_defs[_id])))
        _ix = os.path.join(SKILL_DIR, 'rules', 'items.json')
        if os.path.exists(_ix):
            try:
                _have = {i['id'] for i in json.load(open(_ix, encoding='utf-8'))['items']}
            except Exception as _e:
                # 不能静默 None：items.json 坏了会让 IX002（定义了却取不到）
                # 整项检查跳过，输出里看不出少查了一项 —— 正是 IX002 自己
                # 要抓的那类「静默少做」。
                add('error', 'IX002',
                    '判据索引 items.json 读不出来（%s）→ 本项检查已跳过，'
                    '下方结果不完整' % _e)
            if _have is not None:
                _miss = sorted(i for i in _defs if i not in _have)
                if _miss:
                    add('error', 'IX002',
                        '定义了 %d 条判据但索引里取不到（%s）'
                        % (len(_miss),
                           ' '.join(_miss[:12]) + (' …' if len(_miss) > 12 else '')))

                # IX003 反向：索引里有、正文里没定义了 —— 正文被删了，
                # items.json 留的是过期副本，--get 仍能返回（最会骗人的一种），
                # 直到有人跑 --sync 才真正消失（S-10/S-11/S-12/C-14 就是这么丢的）。
                # 只查 source=='entry'：table 来源的 35 条本来就没有 ### 定义。
                _ent = [i['id'] for i in json.load(open(_ix, encoding='utf-8'))['items']
                        if i.get('source') == 'entry']
                _ghost = sorted(set(_ent) - set(_defs))
                if _ghost:
                    add('error', 'IX003',
                        '索引里是过期副本，正文定义已被删（%d 条，跑 --sync 后会真正消失）: %s'
                        % (len(_ghost),
                           ' '.join(_ghost[:12]) + (' …' if len(_ghost) > 12 else '')))

    refdir = os.path.join(SKILL_DIR, 'references')
    if os.path.isdir(refdir):
        for f in sorted(os.listdir(refdir)):
            if not f.endswith('.md'):
                continue
            txt = open(os.path.join(refdir, f), encoding='utf-8').read()
            # 同 main() 里的 splitlines()：split('\n') 会虚高 1 行
            n, t = len(txt.splitlines()), token_estimate(txt)
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
                n = len(open(os.path.join(sdir, f), encoding='utf-8').read().splitlines())
            except Exception as _e:
                # 读不出来就 continue 会让体积检查对该文件静默失效。说一声。
                print('[warn] 读不到 %s 的行数（%s）→ 跳过体积检查'
                      % (f, _e), file=sys.stderr)
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
