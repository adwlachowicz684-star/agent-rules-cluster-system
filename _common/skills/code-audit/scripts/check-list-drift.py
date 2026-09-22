#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-list-drift.py —— 硬编码名单与事实源的一致性检查。

为什么需要：本仓库已**六次**踩同一个坑——
    「名单写死 → 漏一个 → 不报错 → 静默少做」

前五次：
  1. `--scanners` 写死 scan-ts/scan-app，新增 Rust 包后一条自检都没跑
  2. `_rule_id` 的 known 前缀写死，APP-K34 从没进过注册表
  3. `route.py` 的 SKIP_DIRS 含 scripts/，非 flat 时必空转
  4. `item-index.py` 的 SKIP_FILES 漏 p-cocos，整份文档一条判据都没进索引
  5. `audit.py` 的 ALL_SCANNERS 漏 cocos-audit.py，整个平台包从不执行
第六次就是本脚本要防的。

共同特征：**不报错、不为空、只是悄悄少做了一点**。
单看代码永远发现不了，只有把名单和它该覆盖的事实源交叉比对才抓得到。

用法：
    python3 scripts/check-list-drift.py            # 检查
    python3 scripts/check-list-drift.py --self-test  # 自检（含变异验证）
"""
import ast
import os
import sys
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


def _read(p):
    try:
        return open(p, encoding='utf-8').read()
    except OSError:
        return ''


def check_all():
    """返回 [(级别, 检查项, 说明)]。级别 ERR=必须修，WARN=提示。"""
    out = []

    # ── 1. ALL_SCANNERS ⊇ SCENE_SCRIPTS 值域 ────────────────────
    # 事实源：SCENE_SCRIPTS 声明了「哪个场景需要哪个扫描器」。
    # ALL_SCANNERS 是主循环实际遍历的名单。前者有、后者没有 → 该扫描器永不执行。
    src = _read(os.path.join(HERE, 'audit.py'))
    if src:
        allsc, scenescripts = _parse_tuple(src, 'ALL_SCANNERS'), _parse_scene_scripts(src)
        if allsc and scenescripts:
            need = set()
            for v in scenescripts.values():
                need.update(v)
            missing = sorted(need - set(allsc))
            if missing:
                out.append(('ERR', 'ALL_SCANNERS 漏扫描器',
                            'SCENE_SCRIPTS 里声明了但主循环从不执行 → '
                            '整个场景 0 条候选：%s' % ', '.join(missing)))
            extra = sorted(set(allsc) - need)
            if extra:
                out.append(('WARN', 'ALL_SCANNERS 有多余',
                            '没有任何场景声明需要它（可能是新场景忘了登记）：%s'
                            % ', '.join(extra)))

    # ── 2. 扫描器文件 ⊇ 注册表里的 scanner 字段 ──────────────────
    # 事实源：registry.json 里每条规则的 scanner。
    # 磁盘上没有该文件 → 规则扫不出来。
    import json
    regp = os.path.join(SKILL, 'rules', 'registry.json')
    if os.path.isfile(regp):
        try:
            reg = json.load(open(regp, encoding='utf-8'))
            declared = {r.get('scanner') for r in reg.get('rules', []) if r.get('scanner')}
            for s in sorted(declared):
                if not os.path.isfile(os.path.join(HERE, s)):
                    out.append(('ERR', '注册表指向不存在的扫描器',
                                '%s —— 规则扫不出来，且 --test 会把它算成「扫描器没跑起来」' % s))
            # 反向：磁盘有、注册表没有
            # 原先只认 `scan-` 前缀 —— godot-audit.py 因此从未被这道检查看到，
            # 它的 34 条 GD 规则在注册表里 0 条（能报、有自检，但没有 eval、
            # 不计入覆盖率、CI 也不跑它）。cocos-audit.py 是当初手工补进
            # rule-registry 的，才没一起漏掉 —— 靠人记着补，迟早再漏。
            # 改成按「是不是扫描器」判断：scan-*.py 或 *-audit.py。
            on_disk = {f for f in os.listdir(HERE)
                       if f.endswith('.py')
                       and (f.startswith('scan-') or f.endswith('-audit.py'))}
            for s in sorted(on_disk - declared):
                # 级别是 ERR 不是 WARN：实测后果是**整个包变成幽灵** ——
                # godot-audit.py 的 34 条规则因此没有 eval、不计入覆盖率、
                # --scanners 里看不到（CI 也就不跑它的自检）。
                out.append(('ERR', '磁盘上的扫描器未进注册表',
                            '%s —— 它的规则不会被 --check / --test 统计，'
                            '且 --scanners 推导不到它 → CI 不跑它的自检' % s))
        except (ValueError, OSError) as e:
            out.append(('ERR', 'registry.json 解析失败', str(e)[:80]))

    # ── 3. 语言包 ID 前缀名单 ⊇ 实际存在的语言包 ────────────────
    # 事实源：references/p-*.md 里的判据 ID 前缀 + LANG_SCENE。
    # audit.py 靠前缀决定候选归到哪个场景，前缀漏了 → 候选全落到 s-contracts，
    # 而 s-contracts 常常没被路由命中 → **候选静默丢失**（RS-05/CC-13 实测全丢）。
    if src:
        known = _parse_known_prefix(src)
        langscene = _parse_lang_scene(src)
        mode = _parse_prefix_mode(src)
        if mode is None:
            # 既不写死也不派生：这是最危险的状态 —— 前缀一个都认不出来。
            # 原先 `if known is not None` 会把这种状态当成「无需检查」跳过，
            # 于是改成派生式之后，这道检查**自己悄悄停了**。
            out.append(('ERR', 'audit.py 没有可识别的语言前缀判断',
                        '既不写死 `^(PY|GO|...)-`，也不调用 _lang_prefixes() '
                        '→ 语言包候选会被加错前缀归到 s-contracts，'
                        '该场景未命中路由时整包静默丢失（RS / CC 实测全丢）'))
        elif mode == 'literal':
            # LANG_SCENE 的键 = 应当被识别的语言前缀
            for pfx in sorted(langscene):
                if pfx not in known:
                    out.append(('ERR', '语言前缀名单漏了 %s' % pfx,
                                'LANG_SCENE 里有它，但前缀名单没有 → '
                                '候选被加错前缀 → 归到 s-contracts → 常因未命中路由而丢失'
                                % pfx if False else
                                'LANG_SCENE 里有它，但前缀名单没有 → '
                                '候选被加错前缀归到 s-contracts（LANG_SCENE 该分支是死配置）'))
            # 平台包：p-cocos 无 ID 前缀，靠 SCENE_SCRIPTS 反查
            for scenefile in sorted(os.listdir(os.path.join(SKILL, 'references'))):
                if scenefile.startswith('p-') and scenefile.endswith('.md'):
                    stem = scenefile[:-3]
                    ids = _ids_in(os.path.join(SKILL, 'references', scenefile))
                    if ids:
                        pfxs = {i.split('-')[0] for i in ids}
                        for p in sorted(pfxs):
                            if p not in known and p not in langscene:
                                out.append(('ERR', '平台包 %s 的 ID 前缀 %s 未登记' % (stem, p),
                                            '判据用了 %s-xx 编号，但前缀名单与 LANG_SCENE 都没有它 → '
                                            '候选会被加错前缀' % p))
        elif mode == 'derived':
            # 派生式：前缀自动覆盖 LANG_SCENE + p-*.md，**前缀不会漏**。
            # 但另一件事**不会**自动成立：每个 p-*.md 都得在 SCENE_SCRIPTS 里
            # 登记它的扫描器 —— 否则前缀认出来了，候选却没地方归，
            # 依旧进不了报告（p-godot 刚合进来时就是这个状态）。
            scenescripts2 = _parse_scene_scripts(src) or {}
            for scenefile in sorted(os.listdir(os.path.join(SKILL, 'references'))):
                if scenefile.startswith('p-') and scenefile.endswith('.md'):
                    stem = scenefile[:-3]
                    if stem != 'p-common' and stem not in scenescripts2:
                        out.append(('ERR', '平台/语言包 %s 未登记扫描器' % stem,
                                    'SCENE_SCRIPTS 里没有它 → 前缀认出来也无处可归，'
                                    '候选照样进不了报告'))

    # ── 4. SKIP_DIRS 各扫描器一致 ───────────────────────────────
    # 不一致会让同一份代码在不同扫描器下"有的看得见、有的看不见"。
    skips = {}
    for f in sorted(os.listdir(HERE)):
        if f.startswith('scan-') and f.endswith('.py'):
            s = _read(os.path.join(HERE, f))
            d = _parse_skip_dirs(s)
            if d:
                skips[f] = d
    if len(skips) >= 2:
        base = min(skips, key=lambda k: len(skips[k]))
        for f, d in sorted(skips.items()):
            if f == base:
                continue
            diff = sorted(skips[base] - d)
            if diff and f != 'scan-app.py':   # app 侧扫描范围本就不同，仅提示
                out.append(('WARN', 'SKIP_DIRS 不一致',
                            '%s 比 %s 少了 %s' % (f, base, ', '.join(diff[:5]))))

    # ── 5. 每个脚本的入口都必须能拒绝未知参数 ────────────────────
    #
    # 为什么需要（新建设施的接入率，见 self-verification.md 第七条）：
    # `_flagguard.py` 造好之后，没有任何机制提醒「还有 17 个入口没接」。
    # 它稳定处于「有这个东西，但大部分地方没用」的状态，而**没接的地方
    # 表现与没造之前完全一样**——手写 sys.argv 解析会把拼错的 flag 完全
    # 无视，脚本照常跑完并返回 0。
    #
    # 实测：装守卫前，`route.py --zzz` 退出码 0（照常跑完整路由），
    # `audit.py --zzz` 退出码 124（跑全量直到超时）。两种都不会说
    # 「你给的参数我不认识」。
    #
    # 判据：脚本要么接入 `_flagguard.guard`，要么用 argparse
    # （argparse 自带未知参数报错，退出码也是 2）。两者都没有 → 会静默。
    unguarded = []
    for f in sorted(os.listdir(HERE)):
        if not f.endswith('.py') or f == '_flagguard.py':
            continue
        src5 = _read(os.path.join(HERE, f))
        if not src5:
            continue
        # 只查**入口脚本**：不解析 argv 的是库模块（exitcode.py /
        # _flagguard.py 这类），它没有"命令行参数"这回事，要求装守卫
        # 属于噪音 —— 噪音会让人把整条检查关掉。
        #
        # ⚠ 不能靠 `'argparse' in src` 判断：exitcode.py 的**文档字符串**
        # 里提到 argparse，会被误判成入口脚本。这与「规则扫到注释/文档串」
        # 是同一类失效——用 AST 看真实引用，别看文本。
        if not _is_entry_script(src5):
            continue
        has_guard = ('from _flagguard import' in src5
                     or 'import _flagguard' in src5)
        uses_argparse = ('argparse' in src5 and 'ArgumentParser' in src5)
        # 第三种合法形态：自己维护一份显式名单（如 KNOWN_FLAGS），
        # 遇到不认识的就报错。判据是「有名单」且「有拒绝动作」——
        # 只有名单不报错等于没接；只有报错没有名单无法维护。
        own_list = (re.search(r'KNOWN[_A-Z]*\s*=', src5) is not None
                    and ('未知' in src5 or 'unknown' in src5.lower()))
        if not (has_guard or uses_argparse or own_list):
            unguarded.append(f)
    if unguarded:
        out.append(('ERR', '脚本入口会静默忽略未知参数',
                    '%s —— 拼错的 flag 会被无视，脚本照常跑完并返回 0；'
                    '接 `from _flagguard import guard` 或改用 argparse'
                    % ', '.join(unguarded)))

    # ── 6. 退出码码表的接入率（AR-04 的落地守护）──────────────────
    #
    # 为什么需要：`exitcode.py` 定义了 0/1/2/3/4/130 的码表，但造好之后
    # 没人提醒「还有 N 个脚本没接」。没接的脚本继续 `sys.exit(1)` 一把梭，
    # 表现与没造之前完全一样 —— 新建设施的老问题（见 self-verification
    # 第七条）。
    #
    # 判据：脚本若**有 3 个以上退出点**（说明它有多种失败语义），就该用
    # 码表里的语义常量，而不是裸数字。
    #
    # ⚠ 只统计「退出点 ≥3」的脚本：小工具只有 0/1 两种语义，
    # 强行要求接码表属于噪音，会让人把这条检查关掉。
    if not os.path.isfile(os.path.join(HERE, 'exitcode.py')):
        out.append(('ERR', '码表模块 exitcode.py 不存在',
                    'AR-04 的落地依赖它；删了会让退出码重新变成一把梭'))
    else:
        flat = []
        for f in sorted(os.listdir(HERE)):
            if not f.endswith('.py') or f == 'exitcode.py':
                continue
            src6 = _read(os.path.join(HERE, f))
            if not src6:
                continue
            try:
                t6 = ast.parse(src6)
            except SyntaxError:
                continue
            n_exits = 0
            for n in ast.walk(t6):
                if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) \
                        and getattr(n.exc.func, 'id', None) == 'SystemExit':
                    n_exits += 1
                elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr == 'exit' \
                        and getattr(n.func.value, 'id', None) == 'sys':
                    n_exits += 1
            if n_exits < 3:
                continue
            uses_code = ('from exitcode import' in src6
                         or 'import exitcode' in src6)
            if not uses_code:
                flat.append('%s(%d)' % (f, n_exits))
        if flat:
            out.append(('ERR', '多退出点脚本未接退出码码表',
                        '%s —— 所有失败都返回同一个码，CI 无法区分'
                        '「被拦下」与「出错」；接 `from exitcode import '
                        'ERR, USAGE, ENV, BLOCKED, die`' % ', '.join(flat)))

    return out


# ---------------- 解析辅助（只读 AST / 正则，不 import 被测脚本）----------------


def _is_entry_script(src):
    """是不是命令行入口脚本（会解析 argv）。

    用 AST 判，不用文本匹配：文档字符串里提到 argparse / sys.argv
    不代表脚本真的解析命令行参数。
    """
    try:
        t = ast.parse(src)
    except SyntaxError:
        return False
    for n in ast.walk(t):
        # sys.argv / sys.argv[1:] 的引用
        if isinstance(n, ast.Attribute) and n.attr == 'argv':
            v = n.value
            if isinstance(v, ast.Name) and v.id == 'sys':
                return True
        # argparse.ArgumentParser()
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == 'ArgumentParser':
                return True
            if isinstance(f, ast.Name) and f.id == 'ArgumentParser':
                return True
    return False


def _parse_tuple(src, name):
    """取 `NAME = (...)` 的字符串元组。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    if isinstance(node.value, (ast.Tuple, ast.List)):
                        vals = []
                        for e in node.value.elts:
                            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                                vals.append(e.value)
                        return vals
                    # 派生式（ALL_SCANNERS = tuple(sorted({...SCENE_SCRIPTS...}))）：
                    # 没有字面量可解析。不推导的话调用处 `if allsc and ...`
                    # 会整段跳过 —— 这道检查自己失效，却无人知晓。
                    try:
                        frag = ast.unparse(node.value)
                    # audit: ignore —— 反解析失败退回空串当派生式处理，后果是多报而非漏报
                    except Exception:
                        frag = ''
                    if 'SCENE_SCRIPTS' in frag:
                        ss = _parse_scene_scripts(src) or {}
                        vals = set()
                        for v in ss.values():
                            vals.update(v)
                        return sorted(vals)
    return None


def _parse_scene_scripts(src):
    """取 SCENE_SCRIPTS 字典（值可能是 list）。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == 'SCENE_SCRIPTS':
                    if isinstance(node.value, ast.Dict):
                        d = {}
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant) and isinstance(v, (ast.List, ast.Tuple)):
                                d[k.value] = [e.value for e in v.elts
                                              if isinstance(e, ast.Constant)]
                        return d
    return None


def _parse_lang_scene(src):
    """取 LANG_SCENE 的键。"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == 'LANG_SCENE':
                    if isinstance(node.value, ast.Dict):
                        return {k.value for k in node.value.keys
                                if isinstance(k, ast.Constant)}
    return {}


def _parse_known_prefix(src):
    """从 `re.match(r'^(TS|APP|PY|GO|JAVA|CPP)-', ...)` 里取前缀集合。

    只对**写死**的写法有结果；改成派生式（调用 `_lang_prefixes()`）后
    返回 None —— 调用处必须区分「写死且完整」与「根本没有写死」，
    不能一律当「跳过」。
    """
    import re
    m = re.search(r"re\.match\(r'\^\(([A-Z|]+)\)-'", src)
    if not m:
        return None
    return set(m.group(1).split('|'))


def _parse_prefix_mode(src):
    """判 audit.py 的语言前缀是怎么定的：'literal' / 'derived' / None。

    - literal：写死 `re.match(r'^(PY|GO|...)-', rid)` —— 漏一个就整包丢失
    - derived：调用 `_lang_prefixes()`（从 LANG_SCENE + p-*.md 推导）
    - None：**两者都没有** —— 所有语言包候选都会被加错前缀，
      归到 s-contracts，未命中路由时静默全丢（RS / CC 实测都这么丢过）
    """
    if _parse_known_prefix(src) is not None:
        return 'literal'
    if re.search(r'_lang_prefixes\s*\(\s*\)', src) \
            and re.search(r'def _lang_prefixes\b', src):
        return 'derived'
    return None


def _parse_skip_dirs(src):
    import re
    m = re.search(r'SKIP_DIRS\s*=\s*\{([^}]*)\}', src, re.S)
    if not m:
        return set()
    return set(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))


def _ids_in(path):
    """取 md 里 `### XX-99` 形式的判据 ID。"""
    import re
    return re.findall(r'^###\s+([A-Z]{2,4}-\d{1,2})\b',
                      _read(path), re.M)


# ---------------- 自检 ----------------

def self_test():
    """自检：每项检查都要能红。

    只验证「检查逻辑本身有效」不够——必须验证「**变坏了会报错**」。
    否则又是一个永远绿的自检（本仓库踩过：--cross 漏 import 时恒绿）。
    """
    print('check-list-drift · 自检')
    print('=' * 60)
    ok = fail = 0

    # 1. 解析函数能工作
    src = _read(os.path.join(HERE, 'audit.py'))
    if _parse_tuple(src, 'ALL_SCANNERS') and _parse_scene_scripts(src):
        print('  ✓ 能解析 audit.py 的 ALL_SCANNERS / SCENE_SCRIPTS')
        ok += 1
    else:
        print('  ✗ 解析失败')
        fail += 1

    # 2. 变异验证：造**独立的最小源码**做变异，不依赖真实文件当前长什么样。
    #
    # 第一版是「从真实 audit.py 里删掉 cocos-audit.py 再检查」，
    # 但真实文件里本来就没有它（正是要抓的 bug）→ 替换不生效 →
    # 走的 else 分支，却打印「当前 ALL_SCANNERS 已含 cocos-audit.py」——
    # **输出在骗人**：明明是没找到变异目标，说成了已经包含。
    # 自检自己说谎，比没有自检更糟。
    MUT_SRC = """
SCENE_SCRIPTS = {
    's-numerics': ['scan-ts.py'],
    'p-cocos': ['cocos-audit.py'],
    'p-rust': ['scan-rust.py'],
}
LANG_SCENE = {'RS': 'p-rust'}
ALL_SCANNERS = ('scan-ts.py', 'scan-rust.py')
"""
    allsc = _parse_tuple(MUT_SRC, 'ALL_SCANNERS') or []
    ss = _parse_scene_scripts(MUT_SRC) or {}
    need = set()
    for v in ss.values():
        need.update(v)
    if need - set(allsc):
        print('  ✓ 变异验证：ALL_SCANNERS 漏扫描器时会报错（cocos-audit.py）')
        ok += 1
    else:
        print('  ✗ 变异验证失败：漏了却没报')
        fail += 1

    # 3. 变异验证：前缀名单漏一个（同样用独立源码，不依赖真实文件）
    MUT_PREFIX = """
LANG_SCENE = {'PY': 'p-python', 'RS': 'p-rust'}
import re
if re.match(r'^(TS|APP|PY|GO|JAVA)-', native):
    pass
"""
    known = _parse_known_prefix(MUT_PREFIX) or set()
    ls = _parse_lang_scene(MUT_PREFIX)
    if ls - known:
        print('  ✓ 变异验证：语言前缀名单漏项时会报错（RS）')
        ok += 1
    else:
        print('  ✗ 变异验证失败：漏了却没报')
        fail += 1

    # 4. 变异验证：改成派生式之后，**这道检查自己不能停**。
    #
    # 真实的失效经过：audit.py 的前缀判断改为调用 _lang_prefixes() 后，
    # _parse_known_prefix 匹配不到写死的正则 → 返回 None →
    # 调用处 `if known is not None` 整段跳过 → 检查静默失效。
    # 自检当时只报「解析失败」，说的是另一件事。
    MUT_DERIVED = """
LANG_SCENE = {'PY': 'p-python', 'RS': 'p-rust'}
def _lang_prefixes():
    return set(LANG_SCENE)
if m and m.group(1) in _lang_prefixes():
    pass
"""
    MUT_NONE = """
LANG_SCENE = {'PY': 'p-python'}
scene = 's-contracts'
"""
    if _parse_prefix_mode(MUT_DERIVED) == 'derived' \
            and _parse_prefix_mode(MUT_NONE) is None:
        print('  ✓ 变异验证：派生式能识别、两者皆无时会报')
        ok += 1
    else:
        print('  ✗ 变异验证失败：前缀判断形态识别有误（%s / %s）'
              % (_parse_prefix_mode(MUT_DERIVED), _parse_prefix_mode(MUT_NONE)))
        fail += 1

    print()
    print('自检：%d 通过 · %d 失败' % (ok, fail))
    return 1 if fail else 0


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _flagguard import guard
    guard(sys.argv, {'--self-test'})

    if '--self-test' in sys.argv:
        return self_test()
    print('check-list-drift · 硬编码名单一致性')
    print('=' * 60)
    res = check_all()
    errs = [r for r in res if r[0] == 'ERR']
    warns = [r for r in res if r[0] == 'WARN']
    if not res:
        print('\n  ✓ 所有名单与事实源一致')
        return 0
    if errs:
        print('\n错误 %d：' % len(errs))
        for _, name, desc in errs:
            print('  ✗ %s' % name)
            print('      %s' % desc)
    if warns:
        print('\n警告 %d：' % len(warns))
        for _, name, desc in warns:
            print('  ▲ %s' % name)
            print('      %s' % desc)
    print('\n结论：%d 错误 · %d 警告' % (len(errs), len(warns)))
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
