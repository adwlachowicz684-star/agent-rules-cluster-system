#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
project-rules.py —— 按路径绑定的项目级规则

补的是**通用模式库的反面**。

11 个场景全是「换个项目还成立」的抽象模式（NaN 穿透、成对契约、fail-open…）。
但有些规则永远抽象不出来，对项目却极其有效：

    「改 internal/llm/providers.go 必须检查：
       · 字段顺序 Name→DisplayName→Protocol→…
       · 同步中/英/日/俄四份文档
       · 每个新 provider 必须有 TestLookupProvider_<Name>Details 测试」

这类**项目特化、路径绑定**的规则，就是本脚本管的。
（机制借鉴 alibaba/open-code-review 的 `.opencodereview/rule.json`。）

规则文件位置（按优先级，先找到哪个用哪个）：
    <项目根>/.audit-rules.json
    <项目根>/.ai-local/audit-rules.json       ← 与元技能覆盖层共用

格式：
    {
      "rules": [
        {
          "path": "internal/llm/providers.go",   // 精确路径 或 glob
          "rule": "改此文件必须检查：…",
          "severity": "P1",                       // 可选，默认 P1
          "merge_system_rule": true               // 可选：是否与系统规则合并
        }
      ]
    }

用法：
    python3 project-rules.py --src=<根> --init            # 生成模板
    python3 project-rules.py --src=<根> --check           # 校验格式 + 查失效规则
    python3 project-rules.py --src=<根> --list            # 列出全部
    python3 project-rules.py --src=<根> --match=<文件路径> # 查某文件适用哪些规则
    python3 project-rules.py --src=<根> --for-json=out.json
    python3 project-rules.py --src=<根> --json
"""

import os
import re
import sys
import json
import fnmatch

_flags = [a for a in sys.argv[1:] if a.startswith('--')]
SRC = None
MATCH = None
OUT = None
for f in _flags:
    if f.startswith('--src='):
        SRC = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
    elif f.startswith('--match='):
        MATCH = f.split('=', 1)[1]
    elif f.startswith('--for-json='):
        OUT = f.split('=', 1)[1]
if SRC is None:
    SRC = os.path.abspath('.')
AS_JSON = '--json' in _flags

CANDIDATES = ('.audit-rules.json', os.path.join('.ai-local', 'audit-rules.json'))
TEMPLATE = {
    "_comment": "按路径绑定的项目级规则。path 支持精确路径与 glob（** 匹配多级）。"
                "severity 可选 P0/P1/P2，默认 P1。",
    "rules": [
        {
            "path": "src/store/**",
            "rule": "改状态存储必须检查：① 反序列化有 try/catch 兜底；"
                    "② 新增字段要有迁移路径；③ 旧版本数据加载后不静默损坏。",
            "severity": "P1"
        },
        {
            "path": "README.md",
            "rule": "改 README 必须同步检查：① 提到的 npm 脚本在 package.json 里存在；"
                    "② 数量/默认值声明与代码一致；③ 不把缺陷写成设计意图。",
            "severity": "P1"
        }
    ]
}


def find_file(root):
    for c in CANDIDATES:
        p = os.path.join(root, c)
        if os.path.isfile(p):
            return p
    return None


def load(root):
    p = find_file(root)
    if not p:
        return None, []
    try:
        d = json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError) as e:
        return p, ['_error', str(e)]
    return p, d.get('rules', [])


def norm(p):
    return p.replace('\\', '/').lstrip('./')


def matches(pattern, path):
    """glob 匹配：** 跨目录，* 单层。精确路径也按相等处理。"""
    a, b = norm(pattern), norm(path)
    if a == b:
        return True
    if not any(ch in a for ch in '*?['):
        return False
    # fnmatch 的 * 会跨 /，需先按 ** 处理
    if '**' in a:
        head, _, tail = a.partition('**/')
        if b.startswith(norm(head)) and fnmatch.fnmatch(b[len(norm(head)):].lstrip('/'), tail or '*'):
            return True
        if fnmatch.fnmatch(b, a.replace('**', '*')):
            return True
    return fnmatch.fnmatch(b, a)


def cmd_init():
    p = os.path.join(SRC, '.audit-rules.json')
    if os.path.isfile(p):
        print('已存在：%s' % p)
        return 0
    os.makedirs(SRC, exist_ok=True)
    json.dump(TEMPLATE, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('已生成模板：%s' % p)
    print('改完 rules 后跑 --check 校验')
    return 0


def cmd_check():
    p, rules = load(SRC)
    if p is None:
        print('未找到规则文件（已查 %s）' % ' / '.join(CANDIDATES))
        print('跑 --init 生成模板')
        return 0
    if rules and rules[0] == '_error':
        print('✗ 解析失败：%s\n  %s' % (p, rules[1]))
        return 1
    print('project-rules · 校验')
    print('文件: %s' % p)
    errs, warns = [], []
    for i, r in enumerate(rules):
        if not r.get('path'):
            errs.append('rules[%d] 缺 path' % i)
        if not r.get('rule'):
            errs.append('rules[%d] 缺 rule 文本' % i)
        sev = r.get('severity', 'P1')
        if sev not in ('P0', 'P1', 'P2', 'P3'):
            errs.append('rules[%d] severity 非法：%s' % (i, sev))
        # 失效检测：精确路径（无通配符）但文件不存在
        pa = r.get('path', '')
        if pa and not any(c in pa for c in '*?['):
            if not os.path.exists(os.path.join(SRC, pa)):
                warns.append('rules[%d] 目标不存在：%s（规则已失效）' % (i, pa))
    print('规则数: %d' % len(rules))
    for e in errs:
        print('  ✗ %s' % e)
    for w in warns:
        print('  ▲ %s' % w)
    if errs:
        print('\n结论：格式有误')
        return 1
    print('\n结论：通过')
    return 0


def cmd_list(as_json=False):
    p, rules = load(SRC)
    if not rules:
        print('无规则')
        return 0
    if as_json:
        print(json.dumps(rules, ensure_ascii=False, indent=1))
        return 0
    print('project-rules · %d 条（%s）' % (len(rules), p))
    for r in rules:
        print('\n── %s  [%s]' % (r.get('path'), r.get('severity', 'P1')))
        for ln in str(r.get('rule', '')).split('\n'):
            print('   %s' % ln)
    return 0


def cmd_match(path):
    p, rules = load(SRC)
    hits = [r for r in rules if matches(r.get('path', ''), path)]
    if not hits:
        print('无适用规则：%s' % path)
        return 0
    print('适用于 %s 的规则（%d 条）：' % (path, len(hits)))
    for r in hits:
        print('\n── %s  [%s]' % (r.get('path'), r.get('severity', 'P1')))
        for ln in str(r.get('rule', '')).split('\n'):
            print('   %s' % ln)
    return 0


def main():
    if '--init' in _flags:
        sys.exit(cmd_init())
    if '--check' in _flags:
        sys.exit(cmd_check())
    if MATCH:
        sys.exit(cmd_match(MATCH))
    if OUT:
        p, rules = load(SRC)
        json.dump({'file': p, 'rules': rules},
                  open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('写出 %s（%d 条）' % (OUT, len(rules)))
        return
    sys.exit(cmd_list(AS_JSON))


if __name__ == '__main__':
    main()
