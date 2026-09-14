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
except Exception:
    _REGISTRY = {'rules': []}

_RULE_INFO = {}
for _r in _REGISTRY.get('rules', []):
    _RULE_INFO[_r['rule_id']] = (_r.get('title', ''),
                                 _r.get('scene', ''),
                                 _r.get('level', 'P1'))


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
    if native_id.startswith(('TS-', 'APP-')):
        return native_id
    prefix = 'APP-' if scanner and 'app' in scanner else 'TS-'
    return prefix + native_id


def _fingerprint(path, rule, line, snippet):
    """稳定指纹：同文件同规则同片段 → 同一值。

    为什么不用行号：行号会随无关改动漂移，导致跨运行 diff 全是假的"新增"。
    用「相对路径 + 规则 + 片段内容」既能去重，又对代码位移不敏感。
    """
    raw = '%s|%s|%s|%s' % (path, rule, line, (snippet or '').strip()[:120])
    return hashlib.sha1(raw.encode('utf-8', 'replace')).hexdigest()[:16]


def build_sarif(findings, tool_name='code-audit', root=None, version='1.0.0'):
    """findings: [{'id','level','name','file','line','snippet'}] 或
                 [{'id','level','file','line','snippet'}]"""
    root = root or os.getcwd()
    rules_seen, results = {}, []

    for f in findings:
        native = f.get('id') or f.get('rule_id') or 'UNKNOWN'
        rid = _rule_id(native, f.get('scanner') or tool_name)
        title, scene, def_level = _RULE_INFO.get(rid, (f.get('name', ''), '', None))
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
                'properties': {'tags': [scene] if scene else []},
            }
        elif level == 'error':
            rules_seen[rid]['defaultConfiguration']['level'] = 'error'

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
    for p in args:
        base = os.path.basename(p).lower()
        scanner = 'scan-app.py' if 'app' in base else ('scan-ts.py' if 'ts' in base else None)
        findings += load_findings(p, scanner)
    doc = build_sarif(findings, root=root or os.getcwd())
    if out:
        write_sarif(doc, out)
        n = len(doc['runs'][0]['results'])
        nr = len(doc['runs'][0]['tool']['driver']['rules'])
        print('写出 %s：%d 条结果 · %d 条规则' % (out, n, nr))
    else:
        print(json.dumps(doc, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
