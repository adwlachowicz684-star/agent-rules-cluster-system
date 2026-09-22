#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sarif.py —— SARIF 2.1.0 输出（静态分析结果交换格式）

为什么要有它：扫描器原本只输出人类可读文本，接不进 GitHub Code Scanning、
IDE、任何 CI 面板。SARIF 是这些工具的通用输入格式，接上就能在 PR 里内联显示、
在 Code Scanning 里按规则聚合、在两次运行间做 diff。

设计要点：
    · rules 段一次声明全部规则（含 help 文本与默认级别）
    · results 段每条含 ruleId / level / 精确定位（含 snippet）
    · fingerprint 稳定：同文件同规则同片段 → 同一指纹，用于跨运行去重与 diff
    · 级别映射：P0→error, P1→warning, P2/P3→note

用法（作为模块）：
    from sarif import build_sarif, write_sarif
    doc = build_sarif(findings, tool_name='scan-ts.py', root=src_root)
    write_sarif(doc, 'out.sarif')

用法（命令行，合并两个扫描器的 JSON 输出）：
    python3 scan-ts.py  --src=<根> --json > ts.json
    python3 scan-app.py --src=<根> --json > app.json
    python3 sarif.py --merge ts.json app.json --root=<根> --out out.sarif
    python3 sarif.py --diff old.sarif new.sarif      # 新增/消失的问题
"""

import os
import re
import sys
import json
import hashlib

LEVEL_MAP = {'P0': 'error', 'P1': 'warning', 'P2': 'note', 'P3': 'note'}
SARIF_VERSION = '2.1.0'
SARIF_SCHEMA = ('https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/'
                'Schemata/sarif-schema-2.1.0.json')

# 规则说明：rule_id -> (shortDescription, help 文本)
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _REG = os.path.join(os.path.dirname(_HERE), 'rules', 'registry.json')
    _REGISTRY = json.load(open(_REG, encoding='utf-8')) if os.path.isfile(_REG) else {'rules': []}
except Exception as _e:
    # 不能静默降级成空表：注册表加载失败 → 导出的每条规则都没有说明与 CWE，
    # 而输出看起来是「一份正常的 SARIF」。这正是本仓库反复修的
    # 「配置坏了静默降级」——cwe-map.json 带冲突标记时就是这么丢的 190 条。
    print('[warn] sarif.py 读不到规则注册表（%s：%s）→ 导出的规则将缺少说明与 CWE'
          % (_REG, _e), file=sys.stderr)
    _REGISTRY = {'rules': []}

# audit: ignore —— 模块加载时从注册表一次性填充的只读索引，之后不再写入
_RULE_INFO = {}
for _r in _REGISTRY.get('rules', []):
    _RULE_INFO[_r['rule_id']] = (_r.get('title', ''),
                                 _r.get('scene', ''),
                                 _r.get('level', 'P1'),
                                 tuple(_r.get('cwe') or ()),
                                 _r.get('fix', ''))


def _rule_properties(rid, scene, cwes, fix, native):
    """规则元数据：CWE 关系 + 修复建议 + 场景标签。

    为什么塞进 properties：SARIF 的 relationships[].target 要指向 reportingDescriptor，
    写起来冗长；cwe 放 properties 是 SARIF 消费者的**事实标准做法**
    （GitHub Code Scanning、DefectDojo 都认 `properties.cwe` 或 `tags`）。
    """
    props = {'tags': ([scene] if scene else []) + list(cwes)}
    if cwes:
        props['cwe'] = list(cwes)
    if fix:
        props['fix'] = fix
    if native and native != rid:
        props['nativeId'] = native
    return props


def _severity_to_level(sev):
    if sev in LEVEL_MAP:
        return LEVEL_MAP[sev]
    s = str(sev).lower()
    if s in ('error', 'warning', 'note', 'none'):
        return s
    return 'warning'


def _rule_id(native_id, scanner):
    """把扫描器原生 ID 映射到注册表里的统一 rule_id。"""
    if not native_id:
        return 'UNKNOWN'
    # 已知前缀直接返回。名单**不能写死**——漏一个就静默加错前缀。
    # 这里踩过三次：先是 PY-01 被改成 TS-PY-01（已修），
    # 然后 Rust 包进来后 RS-01 又被改成 TS-RS-01，cocos 的 CC-13 同理。
    # 后果是 SARIF 里查不到元数据 → 规则描述与 CWE 全部丢失。
    # 改为从注册表真实 rule_id 推导，新增语言包自动纳入。
    known = _known_prefixes()
    if native_id.startswith(tuple(known)):
        return native_id
    prefix = 'APP-' if scanner and 'app' in scanner else 'TS-'
    return prefix + native_id


def _known_prefixes():
    # 从 rules/registry.json 的真实 rule_id 推导前缀集合。
    # 推不出来（注册表缺失）时回退到内置名单——宁可可能过时，
    # 也不能让 SARIF 生成失败。
    reg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'rules', 'registry.json')
    try:
        rules = json.load(open(reg, encoding='utf-8'))['rules']
        out = set()
        for r in rules:
            m = re.match(r'^([A-Z]{2,4})-', r.get('rule_id', ''))
            if m:
                out.add(m.group(1) + '-')
        if out:
            return out
    except (OSError, ValueError, KeyError):
        pass
    return {'TS-', 'APP-', 'PY-', 'GO-', 'JAVA-', 'CPP-', 'RS-', 'CC-'}


def _fingerprint(path, rule, line, snippet):
    """稳定指纹：同文件同规则同片段 → 同一值。

    为什么不用行号：行号会随无关改动漂移，导致跨运行 diff 全是假的"新增"。
    用「相对路径 + 规则 + 片段内容」既能去重，又对代码位移不敏感。
    """
    # 注：这里**保留行号**。注释一度写过「不用行号」，但实现里一直带着——
    # 注释与实现不符比没有注释更误导。
    # 保留的理由：同一规则在同一文件不同行的两处相同代码，
    # 是**两个独立问题**（如两个不同的 `x / count`），
    # 若按「路径+规则+片段」去重会合并成一条，等于漏报。
    # 真正要去掉的是「完全相同的重复上报」（合并多份 SARIF 时必现）。
    raw = '%s|%s|%s|%s' % (path, rule, line, (snippet or '').strip()[:120])
    return hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:16]


def build_sarif(findings, tool_name='code-audit', root=None, version='1.0.0'):
    """findings: [{'id','level','name','file','line','snippet'}] 或
                 [{'id','level','file','line','snippet'}]"""
    root = root or os.getcwd()
    rules_seen, results = {}, []
    # 去重：合并多份 SARIF（--merge）时，同一条 finding 常来自多个输入，
    # 不去重会让结果翻倍——Code Scanning 里同一处问题显示两遍。
    # 实测：传两份相同 findings，修之前输出 2 条，修之后 1 条。
    seen_fp = set()

    for f in findings:
        # scan-ts 的 items 用 `pattern`，scan-app 用 `id`；
        # audit.py 缓存的 JSON 两种都可能出现，缺一个就退化成 UNKNOWN
        native = f.get('id') or f.get('rule_id') or f.get('pattern') or 'UNKNOWN'
        rid = _rule_id(native, f.get('scanner') or tool_name)
        title, scene, def_level, cwes, fix = _RULE_INFO.get(
        rid, (f.get('name', ''), '', None, (), ''))
        level = _severity_to_level(f.get('level') or def_level or 'P1')

        fp = f.get('file') or f.get('path') or ''
        # 已经是相对路径就别再 relpath —— 那会把 'js/x.js' 又算一次相对，
        # 得到 '../../a/b/js/x.js' 这种嵌套垃圾（合并 SARIF 时必踩）
        if fp and not os.path.isabs(fp) and not fp.startswith(('/', './', '../')):
            rel = fp.replace(os.sep, '/')
        else:
            try:
                rel = os.path.relpath(fp, root)
            except (ValueError, TypeError):
                rel = fp
            rel = rel.replace(os.sep, '/')
        # 兜底：仍带 ../ 说明拼接错了，取 basename 之外的部分做修正
        if rel.startswith('../'):
            rel = rel.lstrip('./')

        line = int(f.get('line') or 1)
        snippet = (f.get('snippet') or '').strip()

        if rid not in rules_seen:
            help_txt = title or native
            if scene:
                help_txt += '　（场景：%s）' % scene
            rules_seen[rid] = {
                'id': rid,
                'name': rid.replace('-', ''),
                'shortDescription': {'text': title or native},
                'fullDescription': {'text': help_txt},
                'defaultConfiguration': {'level': level},
                'help': {'text': help_txt,
                         'markdown': '**%s**\n\n%s\n\n判据见 `references/%s.md`。'
                                     % (rid, help_txt, scene or 'common')},
                'properties': _rule_properties(rid, scene, cwes, fix, native),
            }
        elif level == 'error':
            rules_seen[rid]['defaultConfiguration']['level'] = 'error'

        fp_key = _fingerprint(rel, rid, line, snippet)
        if fp_key in seen_fp:
            continue
        seen_fp.add(fp_key)

        res = {
            'ruleId': rid,
            'level': level,
            'message': {'text': '%s：%s' % (rid, title or (f.get('name') or '命中'))},
            'locations': [{
                'physicalLocation': {
                    'artifactLocation': {'uri': rel, 'uriBaseId': '%SRCROOT%'},
                    'region': {'startLine': max(1, line),
                               'snippet': {'text': snippet[:200]}}}}],
            'fingerprints': {'primaryLocationLineHash': _fingerprint(rel, rid, line, snippet)},
        }
        if f.get('scanner'):
            res['properties'] = {'scanner': f['scanner']}
        results.append(res)

    return {
        '$schema': SARIF_SCHEMA,
        'version': SARIF_VERSION,
        'runs': [{
            'tool': {
                'driver': {
                    'name': tool_name,
                    'version': version,
                    'informationUri': 'https://github.com/adwlachowicz684-star/agent-rules-cluster-system',
                    'rules': [rules_seen[k] for k in sorted(rules_seen)],
                }},
            'results': results,
        }],
    }


def write_sarif(doc, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    return out


def load_findings(path, scanner=None):
    """读扫描器 --json 输出，或另一个 SARIF 文件（--merge 用）。"""
    data = json.load(open(path, encoding='utf-8'))
    out = []

    if isinstance(data, dict) and 'runs' in data:
        # SARIF：反解回 findings 结构
        for run in data['runs']:
            for res in run.get('results', []):
                loc = res['locations'][0]['physicalLocation']
                out.append({
                    'id': res['ruleId'],
                    'level': {'error': 'P0', 'warning': 'P1',
                              'note': 'P2', 'none': 'P3'}.get(res.get('level'), 'P1'),
                    'name': res['message']['text'],
                    'file': loc['artifactLocation']['uri'],
                    'line': loc['region'].get('startLine', 1),
                    'snippet': loc['region'].get('snippet', {}).get('text', ''),
                    'scanner': (res.get('properties') or {}).get('scanner') or scanner,
                })
        return out

    for f in data:
        if isinstance(f, dict):
            f = dict(f)
            if scanner:
                f['scanner'] = scanner
            out.append(f)
    return out


def diff_sarif(old, new):
    """比对两次结果：新增 / 消失 / 持续存在。"""
    def keys(doc):
        return {r['fingerprints']['primaryLocationLineHash']: r
                for r in doc['runs'][0]['results']}
    a, b = keys(old), keys(new)
    added = [b[k] for k in b if k not in a]
    gone = [a[k] for k in a if k not in b]
    kept = [b[k] for k in b if k in a]
    return added, gone, kept


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _flagguard import guard
    guard(sys.argv, {'--root=', '--out=', '--diff', '--self-test'})

    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    out = None
    root = None
    for f in flags:
        if f.startswith('--out='):
            out = f.split('=', 1)[1]
        if f.startswith('--root='):
            root = f.split('=', 1)[1]

    if '--diff' in flags and len(args) >= 2:
        old = json.load(open(args[0], encoding='utf-8'))
        new = json.load(open(args[1], encoding='utf-8'))
        added, gone, kept = diff_sarif(old, new)
        print('SARIF 比对：新增 %d · 已消失 %d · 持续 %d' % (len(added), len(gone), len(kept)))
        for r in added[:20]:
            loc = r['locations'][0]['physicalLocation']
            print('  + [%s] %s %s:%s' % (r['level'], r['ruleId'],
                                         loc['artifactLocation']['uri'],
                                         loc['region']['startLine']))
        for r in gone[:20]:
            loc = r['locations'][0]['physicalLocation']
            print('  - [%s] %s %s:%s' % (r['level'], r['ruleId'],
                                         loc['artifactLocation']['uri'],
                                         loc['region']['startLine']))
        return

    findings = []
    missing = []
    for p in args:
        # 缺失输入原本直接抛 FileNotFoundError 崩掉，导致 --out 文件根本不生成；
        # 而调用方常常带 `|| true`，于是整条链静默失效——
        # 本仓库 CI 曾因此**每次**都在「上传 SARIF」失败（ts.sarif 从未生成过）。
        # 缺失不是致命错误：跳过并明确报出，让调用方能看见。
        if not os.path.isfile(p):
            missing.append(p)
            continue
        base = os.path.basename(p).lower()
        scanner = 'scan-app.py' if 'app' in base else ('scan-ts.py' if 'ts' in base else None)
        findings += load_findings(p, scanner)
    if missing:
        print('[warn] 跳过不存在的输入：%s' % ', '.join(missing), file=sys.stderr)
        if not findings:
            print('[warn] 所有输入均不存在，仍写出空的 %s' % out, file=sys.stderr)
    doc = build_sarif(findings, root=root or os.getcwd())
    if out:
        write_sarif(doc, out)
        n = len(doc['runs'][0]['results'])
        nr = len(doc['runs'][0]['tool']['driver']['rules'])
        print('写出 %s：%d 条结果 · %d 条规则' % (out, n, nr))
    else:
        print(json.dumps(doc, ensure_ascii=False, indent=2))


def self_test():
    # 自检：把**手工实测发现过的 bug** 固化成断言，防止改回去。
    #
    # 为什么需要：SARIF 是 CI 里「上传 Code Scanning」这一环的依赖，
    # 但它此前没有任何自检。上一轮给它修的两个 bug（RS 前缀、合并去重）
    # 都是靠手工实测撞出来的——没固化就等于没验证过。
    print('sarif · 自检')
    print('=' * 60)
    ok = fail = 0

    def chk(name, cond, detail=''):
        nonlocal ok, fail
        if cond:
            print('  \u2713 %s' % name)
            ok += 1
        else:
            print('  \u2717 %s  %s' % (name, detail))
            fail += 1

    # ① 语言包/平台包前缀不得被加 TS-（踩过三次：PY / RS / CC）
    chk('RS-01 不被误加前缀', _rule_id('RS-01', 'scan-rust.py') == 'RS-01',
        _rule_id('RS-01', 'scan-rust.py'))
    chk('CC-13 不被误加前缀', _rule_id('CC-13', 'cocos-audit.py') == 'CC-13',
        _rule_id('CC-13', 'cocos-audit.py'))
    chk('PY-05 不被误加前缀', _rule_id('PY-05', 'scan-py.py') == 'PY-05',
        _rule_id('PY-05', 'scan-py.py'))
    # ② 裸族号仍要补前缀
    chk('裸族号 A01 补 TS-', _rule_id('A01', 'scan-ts.py') == 'TS-A01',
        _rule_id('A01', 'scan-ts.py'))
    chk('空 ID 变 UNKNOWN', _rule_id('', 'scan-ts.py') == 'UNKNOWN', '')

    # ③ 合并两份**相同**的 findings 不应翻倍（fingerprint 去重）
    f = [{'file': 'a.ts', 'line': 3, 'snippet': 'x', 'rule': 'TS-A01',
          'level': 'P0', 'name': 'n', 'scanner': 'scan-ts.py'}]
    d1 = build_sarif(f, root='/tmp')
    d2 = build_sarif(f + f, root='/tmp')
    n1 = len(d1['runs'][0]['results'])
    n2 = len(d2['runs'][0]['results'])
    chk('重复 findings 去重（%d → %d）' % (n2, n1), n1 == n2,
        '合并后 %d 条，未去重会翻倍' % n2)

    # ④ 指纹稳定：同输入两次构建结果一致
    chk('指纹稳定', _fingerprint('a.ts', 'TS-A01', 3, 'x')
        == _fingerprint('a.ts', 'TS-A01', 3, 'x'), '')

    # ⑤ 去重**不能过头**：同一规则在同一文件不同行的两处相同代码
    #    是两个独立问题，误合并等于漏报。
    #    锁这条是为了防止有人按「路径+规则+片段」去重而去掉行号。
    two = [{'file': 'a.ts', 'line': 3, 'snippet': 'x / count', 'rule': 'TS-O02',
            'level': 'P1', 'scanner': 'scan-ts.py'},
           {'file': 'a.ts', 'line': 9, 'snippet': 'x / count', 'rule': 'TS-O02',
            'level': 'P1', 'scanner': 'scan-ts.py'}]
    n_two = len(build_sarif(two, root='/tmp')['runs'][0]['results'])
    chk('不同行的同类问题不误合并（%d 条）' % n_two, n_two == 2,
        '期望 2 条，实际 %d —— 去掉行号会合并成 1 条（漏报）' % n_two)

    # ⑤ 空输入也能产出合法 SARIF（CI 依赖这一点）
    d0 = build_sarif([], root='/tmp')
    chk('空输入产出合法 SARIF',
        d0.get('version') == '2.1.0' and not d0['runs'][0]['results'], '')

    print()
    print('自检：%d 通过 · %d 失败' % (ok, fail))
    return 1 if fail else 0


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        sys.exit(self_test())
    main()
