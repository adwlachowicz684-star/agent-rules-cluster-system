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
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 扫描器文件名 → 其规则表变量名（留空表示自动发现所有「元素是元组、首元素是 ID」的列表）
SCANNERS = [
    'godot-audit.py', 'cocos-audit.py', 'scan-ts.py', 'scan-py.py',
    'scan-app.py', 'scan-cpp.py', 'scan-go.py', 'scan-java.py',
    'scan-rust.py',
]

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
    """各扫描器里「被内联自检断言过」的规则 ID。

    ⓘ 提取口径必须按各扫描器的实际写法分别取，不能用统一正则：
      · scan-* 系列写在 SELF_TEST_CASES / SELF_TEST_CONTEXT_CASES
        （有的扫描器是 dict 以规则 ID 为 key，有的是 list 元组首元素）
      · godot-audit.py 写在 self_test() 里，形态有三种：
        for rid, label in (('GD21', '…'), …) / for rid in ('GD91', …)
        / check('GD11' not in ids('x.gd'), …)
      · 用统一正则会漏掉 `'(GDxx)' not in` 那一类（此前就把 GD11 误报成未覆盖）。
    """
    out = {}
    # ---- scan-* 系列：AST 取 dict key / list 首元素 ----
    for fn in SCANNERS:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            continue
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except SyntaxError:
            continue
        ids = set()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign)
                    and isinstance(node.value, (ast.List, ast.Dict))):
                continue
            names = [tg.id for tg in node.targets if isinstance(tg, ast.Name)]
            if not any(n.startswith('SELF_TEST') for n in names):
                continue
            v = node.value
            if isinstance(v, ast.Dict):
                for k in v.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        ids.add(k.value)
            else:
                for el in v.elts:
                    if isinstance(el, ast.Tuple) and el.elts \
                            and isinstance(el.elts[0], ast.Constant) \
                            and isinstance(el.elts[0].value, str):
                        ids.add(el.elts[0].value)
        out.setdefault(fn, set()).update(ids)
    # ---- godot-audit.py：self_test() 里的 rid 断言 ----
    gp = os.path.join(HERE, 'godot-audit.py')
    if os.path.exists(gp):
        s = open(gp, encoding='utf-8').read()
        i = s.find('def self_test')
        body = s[i:] if i >= 0 else ''
        ids = set()
        for m in re.finditer(r"for rid, label in \((.*?)\):", body, re.S):
            ids |= set(re.findall(r"\('(GD(?:S)?\d{2,4})'", m.group(1)))
        for m in re.finditer(r"for rid in \(([^)]*)\):", body):
            ids |= set(re.findall(r"'(GD(?:S)?\d{2,4})'", m.group(1)))
        for m in re.finditer(r"'(GD(?:S)?\d{2,4})'\s*(?:not\s+)?in\s+", body):
            ids.add(m.group(1))
        out.setdefault('godot-audit.py', set()).update(ids)
    return out


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
    unverified = []
    for (fn, rid) in sorted(id_tables, key=lambda x: (x[0], len(x[1]), x[1])):
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
    # 未知参数守卫：拼错的 flag 会被 argparse 之外的手写解析静默忽略，
    # 脚本照常跑完并返回 0 —— 在 CI 里表现就是「通过」。
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _flagguard import guard
    guard(sys.argv, {'--json', '--root=', '--self-test'})

    sys.exit(main())
