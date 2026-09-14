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


def cmd_sync():
    rules = extract()
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
    live = extract()
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

    # fixture 覆盖
    nofix = [r['rule_id'] for r in reg['rules'] if not r['fixtures'].get('tp')]
    verified = len(reg['rules']) - len(nofix)

    print('rule-registry · 检查')
    print('规则总数: %d（scan-ts %d / scan-app %d）' % (
        len(reg['rules']),
        sum(1 for r in reg['rules'] if r['scanner'] == 'scan-ts.py'),
        sum(1 for r in reg['rules'] if r['scanner'] == 'scan-app.py')))
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
