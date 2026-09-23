#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check-rule-regex.py —— 对所有扫描器的规则正则做静态体检。

为什么需要（起因）：
    rule-registry.py 里提取 Godot 规则的正则写的是 `GD\\d{2}` —— 只认两位编号。
    GD 编号排到 GD384 之后，**GD101–GD384 共 230 条从未进过 registry.json**，
    而 `--check` 的「扫描器有、注册表没有」告警没接进任何自检，于是漂移了很久。

    ⛔ 这属于「只覆盖一种写法」：编号位数涨了，提取正则没跟着涨。
    ⓘ 同类还有 scan-ts.py 的 Q06 —— 第 4 个参数跨行写成 `'a'\\n  'b'`，
       原提取正则 `'([^']*)'\\s*\\)` 在换行处失配，整条规则被漏。

本脚本用 **AST 结构提取**（不是全文正则），因此不会把注释、文档字符串、
代码样本里的字符串误当成规则 —— 全文正则扫会产生 70+ 条假阳性。

检查项：
    C1  每条规则的正则都能编译（位置错误 / 未闭合分组 / 变长后顾）
    C2  「改了 X 却没调 Y」类规则：pat 的字面骨架不会自己命中 absent（否则永不触发）
    C3  规则 ID 在同一扫描器内不跨表冲突（同表内多写法共用 ID 是允许的）
    C4  每条规则都至少被验证一次（tp fixture 或 扫描器内联自检断言）
    C5  硬编码 `add(…, "GDxx", …)` 的规则也必须在 registry.json 里

        ⓘ 为什么需要：规则「能跑、能报」不等于「被验证过」。
          没有样本的规则改坏了，自检**全绿**——它压根没被测到。
          实测 godot-audit 296 条规则 **0 个 tp fixture**，
          全靠 self_test 里的内联样本；而内联样本也只覆盖了 275 条，
          剩 14 条（GD08/GD12/GD26/GD32/GD33/GD34/GD51/GD147…）**两种都没有**。
        ⓘ 判据取「或」而非「且」：fixture 与内联样本是两种等价验证手段，
          要求两者齐备会让 275 条已验证的规则被误报成未验证。

用法：
    python3 scripts/check-rule-regex.py            # 体检
    python3 scripts/check-rule-regex.py --json     # 机器可读
"""
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 扫描器文件名 → 其规则表变量名（留空表示自动发现所有「元素是元组、首元素是 ID」的列表）
def _registry_mod():
    """加载 rule-registry.py 取共享常量（SCANNERS）与共享函数。

    ⓘ 为什么单一来源：两边各维护一份扫描器列表，改一处忘另一处会让
      另一边**静默少查一个**——表现为「0 问题」，与真没问题无法区分。
      这是本技能反复出现过的失效形态，能集中的一律集中。
    ⓘ 文件名带连字符不能 import，只能按路径加载。
    """
    import importlib.util as _ilu
    sp = _ilu.spec_from_file_location(
        'rule_registry_src', os.path.join(HERE, 'rule-registry.py'))
    m = _ilu.module_from_spec(sp)
    try:
        sp.loader.exec_module(m)
        return m
    except Exception:
        return None


_RM = _registry_mod()
SCANNERS = list(getattr(_RM, 'SCANNERS', None) or [
    'godot-audit.py', 'cocos-audit.py', 'scan-ts.py', 'scan-py.py',
    'scan-app.py', 'scan-cpp.py', 'scan-go.py', 'scan-java.py',
    'scan-rust.py',
])

# 规则 ID 形状：GD384 / GDS01 / CC-02 / CPP-01 / APP-G01 / Q06 / PY-01 …
ID_SHAPE = re.compile(r'^[A-Z]{1,4}S?-\d{1,3}$|^[A-Z]{1,4}S?\d{1,4}$')


def literal_strings(tup):
    """取元组里所有 str 常量（含下标），用于挑出正则参数。"""
    out = []
    for el in tup.elts:
        if isinstance(el, ast.Constant) and isinstance(el.value, str):
            out.append(el.value)
        else:
            out.append(None)
    return out


def looks_like_regex(s):
    """区分正则与说明文本：说明文本通常很长且是中文句子。"""
    if s is None:
        return False
    if len(s) > 400:
        return False
    # 含正则元字符
    return bool(re.search(r'\\[bdsSvwWnrt()\[\]{}|+*?^$]|\[[^\]]+\]|\(\?', s))


def collect():
    """返回 [(scanner, table_name, lineno, [str|None,...]), ...]"""
    res = []
    for fn in SCANNERS:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except SyntaxError as e:
            res.append((fn, '<SYNTAX_ERROR>', 0, [str(e)]))
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.List)):
                continue
            elts = node.value.elts
            if not elts or not all(isinstance(e, ast.Tuple) for e in elts):
                continue
            first = elts[0].elts
            if not first or not isinstance(first[0], ast.Constant):
                continue
            v = first[0].value
            if not (isinstance(v, str) and ID_SHAPE.match(v)):
                continue
            for tname in node.targets:
                if not isinstance(tname, ast.Name):
                    continue
                # ⓘ 自检用例表（SELF_TEST_CASES / *_SAMPLES）也用「首元素是规则 ID」
                #   的元组，但第 2 个元素是**代码样本不是正则**。
                #   把它们当规则会造出上百条假阳性（CPP-03「编译失败」就是这么来的）。
                if re.search(r'TEST|CASE|SAMPLE|FIXTURE|DEMO', tname.id, re.I):
                    continue
                for e in elts:
                    res.append((fn, tname.id, node.lineno, literal_strings(e)))
    return res


def drop_lookaround(s):
    """去掉 (?!...) / (?<!...) / (?=...) / (?<=...) —— 连同内部嵌套括号。"""
    out = []
    i = 0
    while i < len(s):
        if s.startswith('(?', i) and i + 2 < len(s) and s[i + 2] in '!=<':
            j, depth = i + 2, 1
            while j < len(s) and depth:
                if s[j] == '(':
                    depth += 1
                elif s[j] == ')':
                    depth -= 1
                j += 1
            out.append(' ')
            i = j
            continue
        out.append(s[i])
        i += 1
    return ''.join(out)


def skeleton(rx):
    """从正则里抽出「字面骨架」——去掉量词/分组/字符类后剩下的单词。

    用于 C2：判断一条坏样本（由 pat 骨架拼成）会不会顺带命中 absent。
    """
    s = rx
    # ⓘ 先剔除**环视**（(?!..) (?<!..) (?=..)）。
    #   环视里写的是「不该出现的词」，把它算进骨架会让 C2 把这些词
    #   当成"坏样本自带"，从而误报（GD380/GD381 就是这么被误判的）。
    s = drop_lookaround(s)
    s = re.sub(r'\(\?[aiLmsux]+:?[^)]*\)', ' ', s)      # 内联 flag / 注释组
    s = re.sub(r'\\.', ' ', s)                            # 转义序列
    s = re.sub(r'\[[^\]]*\]', ' ', s)                     # 字符类
    s = re.sub(r'[?*+|^$(){}\[\]]', ' ', s)               # 量词与分组
    s = s.replace('\\', ' ')
    return ' '.join(t for t in s.split() if len(t) >= 2)


def collect_inline_verified():
    """内联自检断言覆盖 → 复用 rule-registry.py 的实现（单一来源）。

    ⓘ 本文件最早自己实现过一份，与 rule-registry.py 里的那份重复。
      两份实现一旦漂移，C4 与 --test 会给出**不同的未覆盖数**，
      而两者都自称正确 —— 这类分歧最难排查。故统一到 registry 侧。
    """
    if _RM is not None and hasattr(_RM, 'collect_inline_verified'):
        return _RM.collect_inline_verified()
    return {}


def collect_fixture_tp():
    """registry.json 里有 tp 样本的规则 native_id → 扫描器。"""
    out = {}
    p = os.path.join(HERE, '..', 'rules', 'registry.json')
    if not os.path.exists(p):
        return out
    try:
        reg = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return out
    for r in reg.get('rules', []):
        if (r.get('fixtures') or {}).get('tp'):
            out.setdefault(r.get('scanner'), set()).add(r.get('native_id'))
    return out


def collect_hardcoded_ids():
    """扫 `add(<line>, "GDxx", …)` 这类**完全硬编码**的规则 ID。

    ⓘ 为什么单列一条：C4 的规则全集取自 registry.json，而 registry 的
      extract() 认不出纯硬编码的规则 —— 它只在某处被写成元组时才被收录。
      ⛔ 实测反例：往 analyze() 里插 `add(0, "GD998", …)`，
         `--sync` 后总数仍是 487（没变），C4 也报「全部通过」。
         也就是说 C4 对这类规则**完全无感**，边界必须显式声明并单列检查。
      ⓘ GD15 属于「半个硬编码」：判定逻辑硬编码，但它同时出现在 --rules
         的清单元组里，所以 extract() 碰巧收录了它。这种收录是**偶然**的，
         不能当作机制。
    """
    out = {}
    for fn in SCANNERS:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except (SyntaxError, OSError):
            continue
        ids = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ('add', '_add')):
                continue
            # ⚠ 只取第 2 个实参（rid）。取 args[1:3] 会把第 3 位的 level
            #   （"P0"/"P1"/"P2"）也当成规则 ID —— 它同样匹配 ID 形状，
            #   于是每条硬编码规则都附带报出 3 个假阳性（P0/P1/P2）。
            if len(node.args) < 2:
                continue
            a = node.args[1]
            if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                    and re.match(r'^[A-Z]{1,4}S?-?\d{1,4}$', a.value) \
                    and not re.match(r'^P\d$', a.value):   # 排除 level
                ids.add(a.value)
        if ids:
            out[fn] = ids
    return out


def main():
    items = collect()
    # C3：规则 ID → 出现过的表名集合
    id_tables = {}
    pat_rules = 0
    problems = []

    for fn, table, ln, vals in items:
        if table == '<SYNTAX_ERROR>':
            problems.append(('C0', fn, 0, '文件无法解析：%s' % vals[0][:60]))
            continue
        rid = vals[0]
        if not rid:
            continue
        id_tables.setdefault((fn, rid), set()).add(table)
        # ✅ 按**结构下标**取，不再靠「看起来像正则」猜：
        #    7 元组 (id, level, title, lang, pat, msg, fix)
        #    8 元组 同上 + absent（「改了 X 却没调 Y」类的豁免词）
        if len(vals) >= 5 and vals[4]:
            pat = vals[4]
        else:
            continue
        pat_rules += 1
        # C1 编译
        try:
            re.compile(pat)
        except re.error as e:
            problems.append(('C1', fn, ln, '%s 正则编译失败：%s | %s'
                             % (rid, str(e)[:50], pat[:40])))
            continue
        # C2 永不触发：pat 骨架命中 absent
        absent = vals[7] if len(vals) >= 8 else None
        if absent and looks_like_regex(absent) and len(absent) < 200:
            try:
                if re.search(absent, skeleton(pat), re.M):
                    problems.append(('C2', fn, ln, '%s 的 pat 骨架已命中 absent → 规则永不触发 | absent=%s'
                                     % (rid, absent[:40])))
            except re.error:
                pass

    # C3 跨表冲突（同表多写法共用 ID 合法，跨表同名视为冲突）
    for (fn, rid), tables in sorted(id_tables.items()):
        if len(tables) > 1:
            problems.append(('C3', fn, 0, '%s 同时定义在 %s（跨表同名，报出时无法区分）'
                             % (rid, '/'.join(sorted(tables)))))

    # C4 验证覆盖：每条规则至少被 tp fixture 或 内联自检断言 覆盖一次
    inline = collect_inline_verified()
    tpfix = collect_fixture_tp()
    # ⚠ 规则全集必须取 registry.json，**不能**只取源码里的规则表。
    #   ⓘ GD15 是硬编码在 analyze() 里的 special 规则（`add(i, "GD15", …)`），
    #     不在任何规则表中 —— 按 id_tables 统计根本看不见它。
    #      实测：C4 报「0 缺口」而 `--test` 报「GD-15 未覆盖」，
    #      两边口径不一致，差的就是这一条。
    #   ⛔ 任何「只数规则表里的项」的检查都会漏掉硬编码规则，
    #      而它们恰恰是最容易漏验证的（没表就没位置放样本）。
    reg_all = []
    _rp = os.path.join(HERE, '..', 'rules', 'registry.json')
    if os.path.exists(_rp):
        try:
            _reg = json.load(open(_rp, encoding='utf-8'))
            reg_all = [(r.get('scanner'), r.get('native_id'))
                       for r in _reg.get('rules', [])
                       if r.get('scanner') and r.get('native_id')]
        except (OSError, ValueError):
            reg_all = []
    if not reg_all:      # 没有注册表就退回源码表，并显式声明降级
        print('  ▲ C4 降级：读不到 registry.json，改用源码规则表'
              '（会漏掉硬编码 special 规则，如 GD15）')
        reg_all = sorted(id_tables, key=lambda x: (x[0], len(x[1]), x[1]))
    unverified = []
    for (fn, rid) in sorted(set(reg_all)):
        if rid in (tpfix.get(fn) or set()):
            continue
        if rid in (inline.get(fn) or set()):
            continue
        unverified.append((fn, rid))
    # ✅ 基线为 0：14 条历史缺口已补样本（gap.gd / gap.cs / part.gdshader），
    #   并顺带暴露出 GDS06 是一条**永不触发**的死规则（逐行扫描 + `[^]*]` 误写）。
    #   ⛔ 不许放宽回「不增长」：放宽后新规则不配样本就不会被拦，
    #      而"无样本的规则"恰恰是最容易悄悄失效的那一类。
    BASELINE_UNVERIFIED = 0
    if len(unverified) > BASELINE_UNVERIFIED:
        problems.append(('C4', '<all>', 0,
                         '无任何验证样本的规则 %d 条 > 基线 %d（新增：%s）'
                         % (len(unverified), BASELINE_UNVERIFIED,
                            ', '.join('%s:%s' % (f, r)
                                      for f, r in unverified[:8]))))

    # C5 硬编码规则必须在注册表里：否则它「能跑能报」却在
    # registry / fixture 覆盖率 / CWE / SARIF 全部统计口径中不存在。
    reg_ids = {(f, r) for f, r in reg_all}
    for fn, ids in sorted(collect_hardcoded_ids().items()):
        miss = sorted(i for i in ids if (fn, i) not in reg_ids)
        if miss:
            problems.append(('C5', fn, 0,
                             '硬编码 add() 规则 %d 条不在 registry.json：%s'
                             % (len(miss), ', '.join(miss[:8]))))

    if '--json' in sys.argv:
        print(json.dumps({'checked_rules': pat_rules, 'problems': problems},
                         ensure_ascii=False, indent=1))
    else:
        print('规则正则 · 体检')
        print('  含正则的规则 %d 条' % pat_rules)
        if not problems:
            print('  ✓ C1 编译 / C2 永不触发 / C3 跨表冲突 —— 全部通过')
        else:
            by = {}
            for c, fn, ln, msg in problems:
                by.setdefault(c, []).append('%s:%s %s' % (fn, ln, msg))
            for c in sorted(by):
                print('  ✗ %s —— %d 条' % (c, len(by[c])))
                for m in by[c][:10]:
                    print('      %s' % m)
        print('  结论：%s' % ('全部通过' if not problems else '%d 处问题' % len(problems)))
    return 1 if problems else 0


if __name__ == '__main__':
    # ⚠ 未知参数守卫：拼错的 flag 会被手写解析静默忽略，脚本照常跑完
    #   并返回 0 —— 在 CI 里表现就是「通过」。
    #   ⓘ 这段是远端 1e04e2df 加的，本地基线停在 e80918de 没收到；
    #      直接 --force-overwrite 会把它抹掉，故先手工合并回来。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _flagguard import guard
    guard(sys.argv, {'--json', '--root=', '--self-test'})
    sys.exit(main())
