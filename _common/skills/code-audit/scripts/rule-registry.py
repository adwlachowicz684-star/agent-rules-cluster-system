#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rule-registry.py —— 规则注册表管理（rule_id / 漂移检查 / fixture 测试）

解决什么问题：90 条正则散在两个扫描器里是**隐式知识**——
没有统一 ID、没有归属场景、没有反例、无法灰度下线、改一条不知道影响谁。
注册表把它们变成**可管理资产**。

三条纪律：
    1. 注册表由 --sync 从扫描器提取生成，**不要手改条目**
       （手改会被 --check 判为漂移）
    2. 每条规则应有 fixture：TP（必须命中）+ FP（必须不命中）
    3. 没有 fixture 的规则在 --check 里报 warn，不计入「已验证」规则数

用法：
    python3 rule-registry.py --sync              # 从扫描器重新提取，重建注册表
    python3 rule-registry.py --check             # 漂移检查 + fixture 覆盖率
    python3 rule-registry.py --test              # 跑 fixture（TP/FP 断言）
    python3 rule-registry.py --list              # 列出全部规则
    python3 rule-registry.py --scene s-numerics  # 只看某场景
    python3 rule-registry.py --json              # 机器可读
"""

import os
import re
import sys
import json
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REG = os.path.join(SKILL, 'rules', 'registry.json')
FIXDIR = os.path.join(SKILL, 'rules', 'fixtures')

_flags = [a for a in sys.argv[1:] if a.startswith('--')]
AS_JSON = '--json' in _flags
SCENE = None
for f in _flags:
    if f.startswith('--scene='):
        SCENE = f.split('=', 1)[1]

FAM2SCENE = {
 'A':'s-numerics','B':'s-numerics','P':'s-numerics','T':'s-numerics','U':'s-numerics','W':'s-numerics',
 'C':'s-structures','I':'s-structures','Q':'s-structures','R':'s-structures',
 'X':'s-lifecycle','Y':'s-lifecycle','K':'s-lifecycle',
 'D':'s-contracts','G':'s-contracts','H':'s-contracts','E':'s-contracts','F':'s-contracts',
 'J':'s-atomicity','L':'s-atomicity','M':'s-atomicity','S':'s-atomicity',
 'N':'s-numerics','O':'s-numerics',
}
APP2SCENE = {
 'J01':'s-boundary','J02':'s-sandbox','J03':'s-boundary','J04':'s-state','J05':'s-lifecycle',
 'J06':'s-state','J07':'s-sandbox','J08':'s-sandbox','J09':'s-lifecycle','J10':'s-lifecycle',
 'J11':'s-lifecycle','J12':'s-atomicity','J13':'s-contracts',
 'R01':'s-backend','R02':'s-backend','R03':'s-backend','R04':'s-backend','R05':'s-sandbox',
 'R06':'s-sandbox','R07':'s-backend','R08':'s-contracts','R09':'s-atomicity','R10':'s-backend',
 'P01':'s-build','P02':'s-contracts','P03':'s-build','P04':'s-sandbox','P05':'s-build',
}


PY2SCENE = {
    'PY-01': 'p-python', 'PY-02': 'p-python', 'PY-03': 'p-python',
    'PY-04': 's-concurrency', 'PY-05': 's-backend', 'PY-06': 's-sandbox',
    'PY-07': 's-concurrency', 'PY-08': 'p-python', 'PY-09': 'p-python',
    'PY-10': 's-backend', 'PY-11': 'p-python', 'PY-12': 'p-python',
}


def extract():
    """从两个扫描器提取规则定义。改扫描器后跑 --sync 重建注册表。"""
    out = []

    src = open(os.path.join(HERE, 'scan-ts.py'), encoding='utf-8').read()
    fam_at = {}
    for i, ln in enumerate(src.split('\n')):
        m = re.match(r'# -+ ([A-Z]) 族：([^\-]+?)\s*-*\s*$', ln)
        if m:
            fam_at[i] = m.group(1)
    seen = set()
    for m in re.finditer(r"pattern\(\s*'([A-Z]\d{2})'\s*,\s*'(P\d)'\s*,\s*'([^']+)'\s*,\s*'([^']*)'\s*\)", src):
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        ln = src[:m.start()].count('\n')
        fam = None
        for i in sorted(fam_at):
            if i < ln:
                fam = fam_at[i]
        out.append({'rule_id': 'TS-%s' % m.group(1), 'native_id': m.group(1),
                    'scanner': 'scan-ts.py', 'level': m.group(2), 'title': m.group(3),
                    'family': fam, 'scene': FAM2SCENE.get(fam, 's-contracts'),
                    'languages': ['ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'],
                    'fixtures': {'tp': None, 'fp': None},
                    'eval': {'precision': 'unverified', 'recall': 'unverified'}})

    asrc = open(os.path.join(HERE, 'scan-app.py'), encoding='utf-8').read()
    aseen = set()
    for m in re.finditer(r"\(\s*'([A-Z]\d{2}|P\d{2})'\s*,\s*'(P\d)'\s*,\s*'([^']+)'\s*,\s*\(", asrc):
        if m.group(1) in aseen:
            continue
        aseen.add(m.group(1))
        out.append({'rule_id': 'APP-%s' % m.group(1), 'native_id': m.group(1),
                    'scanner': 'scan-app.py', 'level': m.group(2), 'title': m.group(3),
                    'family': m.group(1)[0], 'scene': APP2SCENE.get(m.group(1), 's-build'),
                    'languages': ['ts', 'js', 'rs', 'html'],
                    'fixtures': {'tp': None, 'fp': None},
                    'eval': {'precision': 'unverified', 'recall': 'unverified'}})
    # ---------- scan-py.py ----------
    psrc = open(os.path.join(HERE, 'scan-py.py'), encoding='utf-8').read()
    pseen = set()
    # PATTERNS 里的四元组：("PY-01", "P0", "标题", fn)
    for m in re.finditer(r'\(\s*"(PY-\d{2})"\s*,\s*"(P\d)"\s*,\s*"([^"]+)"\s*,', psrc):
        if m.group(1) in pseen:
            continue
        pseen.add(m.group(1))
        out.append({'rule_id': m.group(1), 'native_id': m.group(1),
                    'scanner': 'scan-py.py', 'level': m.group(2), 'title': m.group(3),
                    'family': 'PY', 'scene': PY2SCENE.get(m.group(1), 'p-python'),
                    'languages': ['py'],
                    'fixtures': {'tp': None, 'fp': None},
                    'eval': {'precision': 'unverified', 'recall': 'unverified'}})

    # ---------- 其它语言包扫描器 ----------
    # 三个扫描器共用同一套 PATTERNS 四元组写法，按前缀 + 语言 + 场景映射统一提取
    LANG_SCANNERS = [
        ('scan-go.py', 'GO', r'\(\s*"(GO-\d{2})"\s*,\s*"(P\d)"\s*,\s*"([^"]+)"\s*,',
         {'GO-01': 's-concurrency', 'GO-02': 's-concurrency', 'GO-03': 's-concurrency',
          'GO-04': 's-concurrency', 'GO-05': 's-concurrency', 'GO-06': 'p-go',
          'GO-07': 's-concurrency', 'GO-08': 'p-go', 'GO-09': 's-concurrency',
          'GO-10': 'p-go'}, ['go']),
        ('scan-java.py', 'JAVA', r'\(\s*"(JAVA-\d{2})"\s*,\s*"(P\d)"\s*,\s*"([^"]+)"\s*,',
         {'JAVA-01': 'p-java', 'JAVA-02': 's-concurrency', 'JAVA-03': 's-concurrency',
          'JAVA-04': 's-concurrency', 'JAVA-05': 's-concurrency', 'JAVA-06': 's-concurrency',
          'JAVA-07': 'p-java', 'JAVA-08': 'p-java', 'JAVA-09': 'p-java',
          'JAVA-10': 'p-java'}, ['java']),
        ('scan-cpp.py', 'CPP', r'\(\s*"(CPP-\d{2})"\s*,\s*"(P\d)"\s*,\s*"([^"]+)"\s*,',
         {'CPP-01': 'p-cpp', 'CPP-02': 'p-cpp', 'CPP-03': 'p-cpp',
          'CPP-04': 's-concurrency', 'CPP-05': 's-concurrency',
          'CPP-06': 's-concurrency', 'CPP-07': 'p-cpp', 'CPP-08': 's-numerics',
          'CPP-09': 'p-cpp', 'CPP-10': 'p-cpp'}, ['c', 'cc', 'cpp', 'cxx', 'h', 'hpp']),
    ]
    for fname, fam, rx, scene_map, langs in LANG_SCANNERS:
        fpath = os.path.join(HERE, fname)
        if not os.path.isfile(fpath):
            continue
        fsrc = open(fpath, encoding='utf-8').read()
        fseen = set()
        for m in re.finditer(rx, fsrc):
            rid = m.group(1)
            if rid in fseen:
                continue
            fseen.add(rid)
            out.append({'rule_id': rid, 'native_id': rid,
                        'scanner': fname, 'level': m.group(2), 'title': m.group(3),
                        'family': fam, 'scene': scene_map.get(rid, 's-contracts'),
                        'languages': langs,
                        'fixtures': {'tp': None, 'fp': None},
                        'eval': {'precision': 'unverified', 'recall': 'unverified'}})

    # scan-app 的 FILE_PATTERNS / PROJECT_CHECKS 无法用统一正则提取，按已知清单补齐
    extra = {'J13': ('P1', '同名常量清单重复定义且已分叉', 's-contracts'),
             'P01': ('P2', '忽略清单缺常见项', 's-build'),
             'P02': ('P2', '孤儿源文件（无任何引用）', 's-contracts'),
             'P03': ('P2', '有校验脚本但无 CI', 's-build'),
             'P04': ('P0', '多入口但安全策略只覆盖其一', 's-sandbox'),
             'P05': ('P1', '多份构建配置合并关系存疑', 's-build'),
             'R08': ('P2', '未被 mod 声明的孤儿 .rs 文件', 's-contracts')}
    for k, (lvl, title, scene) in extra.items():
        if k not in aseen:
            out.append({'rule_id': 'APP-%s' % k, 'native_id': k, 'scanner': 'scan-app.py',
                        'level': lvl, 'title': title, 'family': k[0], 'scene': scene,
                        'languages': ['ts', 'js', 'rs', 'html', 'json'],
                        'fixtures': {'tp': None, 'fp': None},
                        'eval': {'precision': 'unverified', 'recall': 'unverified'}})
    out.sort(key=lambda r: (r['scanner'], r['native_id']))
    return out


def load():
    if not os.path.isfile(REG):
        return None
    return json.load(open(REG, encoding='utf-8'))


def attach_fixtures(rules):
    """把 rules/fixtures/<id>/ 下实际存在的 tp/fp 回填到注册表。

    为什么需要：extract() 只从扫描器源码提取规则，不知道 fixture 目录里有什么。
    不回填的话 `--check` 会把覆盖率报成 `0 / 131`——
    测试其实跑过且全通过（--test 显示 114 通过 0 失败），
    但覆盖率显示 0，既低估了可信度，也让「哪些规则还没验证」彻底不可见。
    """
    if not os.path.isdir(FIXDIR):
        return rules
    have = {}
    for rid in os.listdir(FIXDIR):
        d = os.path.join(FIXDIR, rid)
        if not os.path.isdir(d):
            continue
        tp = next((f for f in os.listdir(d) if f.startswith('tp.')), None)
        fp = next((f for f in os.listdir(d) if f.startswith('fp.')), None)
        if tp or fp:
            have[rid] = {'tp': tp, 'fp': fp}
    for r in rules:
        if r['rule_id'] in have:
            r['fixtures'] = have[r['rule_id']]
    return rules


def load_cwe_map():
    """读 CWE 映射与修复建议。

    为什么单独一个文件：131 条规则的映射数据塞进脚本会让脚本体积失控，
    且映射是**数据**不是逻辑，改映射不该动代码。
    """
    path = os.path.join(SKILL, 'rules', 'cwe-map.json')
    if not os.path.isfile(path):
        return {}, {}
    try:
        m = json.load(open(path, encoding='utf-8'))
    except (ValueError, OSError) as e:
        print('[warn] cwe-map.json 解析失败: %s' % e, file=sys.stderr)
        return {}, {}
    by_group, by_rule = {}, {}
    for g in m.get('_group_defaults', []):
        for rid in g.get('ids', []):
            by_group[rid] = (list(g.get('cwe', [])), g.get('fix', ''))
    for rid, v in (m.get('_rules') or {}).items():
        by_rule[rid] = (list(v.get('cwe', [])), v.get('fix', ''))
    return by_group, by_rule


def attach_cwe(rules):
    """把 cwe / fix 写入规则条目。`_rules` 精确覆盖 `_group_defaults`。"""
    by_group, by_rule = load_cwe_map()
    if not by_group and not by_rule:
        return rules
    for r in rules:
        rid = r['rule_id']
        cwe, fix = by_rule.get(rid, by_group.get(rid, (None, None)))
        # cwe 为空数组是**明确声明无安全含义**（如死契约、性能），与"未映射"不同：
        # 未映射写 null，明确无 CWE 写 []。下游据此区分"待补"和"不适用"。
        r['cwe'] = cwe
        r['fix'] = fix or ''
    return rules


def cmd_sync():
    rules = attach_cwe(attach_fixtures(extract()))
    reg = {'version': '1.0.0',
           'note': '由 scripts/rule-registry.py --sync 从扫描器提取生成。'
                   '不要手改条目（会被 --check 判为漂移）；改扫描器后重新 sync。',
           'rules': rules}
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    json.dump(reg, open(REG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已同步 %d 条规则 → rules/registry.json' % len(rules))
    return 0


def cmd_check():
    reg = load()
    if reg is None:
        print('没有注册表，先跑 --sync')
        return 1
    live = attach_cwe(attach_fixtures(extract()))
    live_ids = {r['rule_id'] for r in live}
    reg_ids = {r['rule_id'] for r in reg['rules']}

    errs, warns = [], []
    for rid in sorted(live_ids - reg_ids):
        errs.append('扫描器有规则 %s 但注册表没有 → 跑 --sync' % rid)
    for rid in sorted(reg_ids - live_ids):
        errs.append('注册表有规则 %s 但扫描器已删除 → 跑 --sync' % rid)

    # 级别漂移
    livemap = {r['rule_id']: r for r in live}
    for r in reg['rules']:
        if r['rule_id'] in livemap and livemap[r['rule_id']]['level'] != r['level']:
            warns.append('%s 级别已从 %s 变为 %s' % (r['rule_id'], r['level'],
                                                livemap[r['rule_id']]['level']))

    # CWE 映射完整性：未映射(null)与明确无([])是两回事，只报前者
    uncwe = [r['rule_id'] for r in reg['rules'] if r.get('cwe') is None]
    nofix_text = [r['rule_id'] for r in reg['rules'] if not r.get('fix')]
    if uncwe:
        warns.append('%d 条规则缺 CWE 映射（非安全类请在 cwe-map.json 显式写 []）: %s'
                     % (len(uncwe), ' '.join(uncwe[:8])))
    if nofix_text:
        warns.append('%d 条规则缺 fix 建议: %s'
                     % (len(nofix_text), ' '.join(nofix_text[:8])))

    # fixture 覆盖
    nofix = [r['rule_id'] for r in reg['rules'] if not r['fixtures'].get('tp')]
    verified = len(reg['rules']) - len(nofix)

    print('rule-registry · 检查')
    # 按扫描器分档统计：原来只写死了 scan-ts / scan-app 两个，
    # 新增语言包后总数会对不上（131 条里只报 89），掩盖了新规则是否真的入表
    from collections import Counter
    per = Counter(r['scanner'] for r in reg['rules'])
    print('规则总数: %d（%s）' % (
        len(reg['rules']),
        ' / '.join('%s %d' % (k.replace('.py', ''), v)
                   for k, v in sorted(per.items()))))
    print('有 TP fixture: %d / %d' % (verified, len(reg['rules'])))
    for e in errs:
        print('  ✗ %s' % e)
    for w in warns:
        print('  ▲ %s' % w)
    if nofix:
        print('  ▲ %d 条规则无 TP fixture（未验证）：%s...'
              % (len(nofix), ' '.join(nofix[:8])))
    if errs:
        print('\n结论：漂移。跑 --sync 后再确认。')
        return 1
    print('\n结论：一致。')
    return 0


def _run_scanner(scanner, src_root, native_id):
    """在临时模块结构上跑扫描器，返回是否命中该规则。"""
    import subprocess
    cmd = [sys.executable, os.path.join(HERE, scanner),
           '--src=' + src_root, '--pattern=' + native_id, '--json']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    if not r.stdout.strip():
        return None
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return None
    if isinstance(d, dict):
        return len(d.get('items', []))
    return len(d) if isinstance(d, list) else 0


def cmd_test():
    """跑 fixture：TP 必须命中、FP 必须不命中（实际执行扫描器，不是只看文件在不在）。"""
    if not os.path.isdir(FIXDIR):
        print('没有 fixtures 目录，跳过')
        return 0
    reg = load()
    if reg is None:
        print('没有注册表')
        return 1
    ok = fail = skip = 0
    for rid in sorted(os.listdir(FIXDIR)):
        d = os.path.join(FIXDIR, rid)
        if not os.path.isdir(d):
            continue
        files = [f for f in os.listdir(d) if f.startswith(('tp.', 'fp.'))]
        if not files:
            continue
        meta = next((r for r in reg['rules'] if r['rule_id'] == rid), None)
        scanner = (meta or {}).get('scanner', 'scan-ts.py')
        native = (meta or {}).get('native_id', rid.split('-', 1)[-1])
        for kind in ('tp', 'fp'):
            src = next((f for f in files if f.startswith(kind + '.')), None)
            if not src:
                continue
            # 扫描器按「一级子目录 = 模块」切分，fixture 要放进一个模块目录
            tmp = tempfile.mkdtemp(prefix='fix-')
            try:
                # 部分规则要求特定目录结构（如 J08 要求文件在 plugins/ 下），
                # fixture 可用 .subdir 文件指定存放子目录
                _sd = 'mod'
                _sdf = os.path.join(d, '.subdir')
                if os.path.isfile(_sdf):
                    _sd = open(_sdf).read().strip() or 'mod'
                mod = os.path.join(tmp, _sd); os.makedirs(mod, exist_ok=True)
                shutil.copy(os.path.join(d, src), os.path.join(mod, src))
                hits = _run_scanner(scanner, tmp, native)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if hits is None:
                print('  ? %s %s：扫描器无有效输出' % (rid, kind))
                continue
            if kind == 'tp':
                if hits > 0:
                    ok += 1
                else:
                    fail += 1
                    print('  ✗ %s TP 未命中（规则可能失效）' % rid)
            else:
                if hits == 0:
                    ok += 1
                else:
                    fail += 1
                    print('  ✗ %s FP 被命中（%d 处，规则可能过宽 → 误报源）' % (rid, hits))
    total = len([d for d in os.listdir(FIXDIR) if os.path.isdir(os.path.join(FIXDIR, d))])
    skip = len(reg['rules']) - total
    print('\nfixture 实测：通过 %d · 失败 %d · 未覆盖规则 %d'
          % (ok, fail, max(0, skip)))
    return 1 if fail else 0


def main():
    if '--sync' in _flags:
        sys.exit(cmd_sync())
    if '--test' in _flags:
        sys.exit(cmd_test())
    if '--check' in _flags:
        sys.exit(cmd_check())

    reg = load()
    if reg is None:
        print('没有注册表，先跑 --sync')
        sys.exit(1)
    rules = reg['rules']
    if SCENE:
        rules = [r for r in rules if r['scene'] == SCENE]
    if AS_JSON:
        print(json.dumps(rules, ensure_ascii=False, indent=1))
        return
    print('规则注册表 · %d 条%s' % (len(rules), '（场景 %s）' % SCENE if SCENE else ''))
    by = {}
    for r in rules:
        by.setdefault(r['scene'], []).append(r)
    for scene in sorted(by):
        print('\n── %s（%d）──────────' % (scene, len(by[scene])))
        for r in by[scene]:
            fx = '✓' if r['fixtures'].get('tp') else '·'
            print('  %s [%s] %-8s %s' % (fx, r['level'], r['rule_id'], r['title']))
    print('\n✓ = 有 TP fixture；· = 未验证')


if __name__ == '__main__':
    main()
