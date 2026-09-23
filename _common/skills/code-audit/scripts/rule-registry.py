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
    python3 rule-registry.py --eval              # 跑 fixture 并把结论回填 eval 字段
    python3 rule-registry.py --list              # 列出全部规则
    python3 rule-registry.py --scene s-numerics  # 只看某场景
    python3 rule-registry.py --json              # 机器可读
"""

import os
import glob
import re
import sys
import json
import shutil
import hashlib
import tempfile
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exitcode import OK, ERR, USAGE, ENV, BLOCKED, die  # 码表：0/1/2/3/4（AR-04）

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
REG = os.path.join(SKILL, 'rules', 'registry.json')
ITEMS = os.path.join(SKILL, 'rules', 'items.json')
FIXDIR = os.path.join(SKILL, 'rules', 'fixtures')
GAPS = os.path.join(SKILL, 'rules', 'gaps.json')

# ID 撞号阈值说明见 cmd_map 的文档串

_flags = [a for a in sys.argv[1:] if a.startswith('--')]

# 未知 flag 必须报错，不能静默忽略。
#
# 实测：`rule-registry.py --self-test` 会**跑默认列表命令**并退出 0——
# 用户以为跑了自检、CI 以为过了，实际什么都没验。
# 这类「有自检的暗示但静默不执行」比没有自检更危险：
# 它给出一个绿色的信号，而那个信号是空的。
# 同源问题：手写 sys.argv 解析的脚本会**静默忽略**不存在的 flag
# （如 `--self-test`），照常跑完并返回 0 —— 见 scripts/_flagguard.py。
# 注：仓库里没有 mutate.py，那是外部清单的笔误；对应的概念
# 「无 mutate 即跳过」实现在 scan-py.py 的 PY-08 里。
KNOWN_FLAGS = {'--apply', '--check', '--comment-test', '--cross', '--eval', '--gaps',
               '--json', '--map', '--scanners', '--sync', '--test'}
_unknown = [f for f in _flags if f not in KNOWN_FLAGS]
if _unknown:
    sys.stderr.write(
        '未知参数：%s\n'
        '本脚本没有 --self-test —— 自检是 `rule-registry.py --test`（跑 fixture）'
        '与 `--cross`（交叉审计），CI 里两个都跑。\n'
        '可用参数：%s\n' % (', '.join(_unknown), ' '.join(sorted(KNOWN_FLAGS))))
    sys.exit(2)

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
    # 架构可演进性：判据在 references/s-architecture.md（AR-02 为人工判据，无机扫）
    'AR-01': 's-architecture', 'AR-03': 's-architecture',
    'AR-04': 's-architecture', 'AR-05': 's-architecture',
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
    # ⚠ 第四个参数可能跨行写成 `'a'\n    'b'`（Python 字符串拼接），
    #   原正则 `'([^']*)'\s*\)` 遇到换行后的第二个引号就失配 → Q06 这类被漏。
    #   ✅ 允许任意多个相邻字符串字面量拼接。
    for m in re.finditer(r"pattern\(\s*'([A-Z]\d{1,3})'\s*,\s*'(P\d)'\s*,\s*'([^']+)'\s*,"
                         r"\s*'([^']*)'(?:\s*'[^']*')*\s*\)", src):
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
    cseen = set()
    # 标题允许单引号或双引号：J03 用的是双引号（`postMessage` 描述里含单引号，
    # 作者改用了双引号），原正则只认单引号 → J03 从未进入注册表。
    # 更麻烦的是 --check 也用同一条正则算「扫描器现有规则」，
    # 两边一起漏，于是它永远报「一致」—— 检查与被测对象共用同一个 bug。
    for m in re.finditer(
            r"\(\s*'([A-Z]\d{2}|P\d{2})'\s*,\s*'(P\d)'\s*,\s*"
            r"(?:'([^']+)'|\"([^\"]+)\")\s*,\s*\(", asrc):
        if m.group(1) in aseen:
            continue
        aseen.add(m.group(1))
        _title = m.group(3) or m.group(4)
        out.append({'rule_id': 'APP-%s' % m.group(1), 'native_id': m.group(1),
                    'scanner': 'scan-app.py', 'level': m.group(2), 'title': _title,
                    'family': m.group(1)[0], 'scene': APP2SCENE.get(m.group(1), 's-build'),
                    'languages': ['ts', 'js', 'rs', 'html'],
                    'fixtures': {'tp': None, 'fp': None},
                    'eval': {'precision': 'unverified', 'recall': 'unverified'}})
    # ---------- scan-py.py ----------
    psrc = open(os.path.join(HERE, 'scan-py.py'), encoding='utf-8').read()
    pseen = set()
    # PATTERNS 里的四元组：("PY-01", "P0", "标题", fn)
    #
    # 原先写死 `PY-\d{2}` —— 于是往 scan-py 里加 K-43 / K-44（判据来自 s-backend，
    # 实测样本是 .py）时，两条规则**根本进不了注册表**：扫描器能报、自检能过，
    # 但没有 eval、没有判据映射、不计入覆盖率。和 --map 的语言包名单、
    # CI 的扫描器名单是同一类「名单漏一个就静默失效」，这是第三次。
    # 改成通用匹配：任何 `("X-NN", "Pn", "标题",` 形态都收。
    # AR-*（架构可演进性）与 PY-* 共用同一套 PATTERNS 四元组写法，
    # 通用正则一并提取，无需另列前缀。
    for m in re.finditer(r'\(\s*"([A-Z]{1,4}-\d{1,3})"\s*,\s*"(P\d)"\s*,'
                         r'\s*"([^"]+)"\s*,', psrc):
        if m.group(1) in pseen:
            continue
        pseen.add(m.group(1))
        out.append({'rule_id': m.group(1), 'native_id': m.group(1),
                    'scanner': 'scan-py.py', 'level': m.group(2), 'title': m.group(3),
                    'family': m.group(1).split('-')[0],
                    'scene': PY2SCENE.get(m.group(1), 'p-python'),
                    'languages': ['py'],
                    'fixtures': {'tp': None, 'fp': None},
                    'eval': {'precision': 'unverified', 'recall': 'unverified'}})

    # ---------- 其它语言包扫描器 ----------
    # 各语言扫描器共用同一套 PATTERNS 四元组写法，按前缀 + 语言 + 场景映射统一提取
    LANG_SCANNERS = [
        ('scan-rust.py', 'RS', r'\(\s*"(RS-\d{2})"\s*,\s*"(P\d)"\s*,\s*"([^"]+)"\s*,',
         {'RS-01': 'p-rust', 'RS-02': 's-numerics', 'RS-03': 'p-rust',
          'RS-04': 's-concurrency', 'RS-05': 's-backend', 'RS-06': 's-backend',
          'RS-07': 'p-rust', 'RS-08': 'p-rust', 'RS-09': 'p-rust',
          'RS-10': 's-sandbox'}, ['rs']),
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

    # ---------- 项目级检查（PROJECT_CHECKS）----------
    # 原先是硬编码清单 extra —— 与批次10在 --map 里修掉的是同一类 bug：
    # 「名单漏一个就静默失效」。新增 G 系列 5 条 + K12/K25/K27/C01 后，
    # 扫描器能报、自检也能报，唯独注册表里没有它们（无 eval、无判据映射、
    # 不计入覆盖率）。改为从函数 docstring 自动发现：
    #   docstring 形如 `G01 打包范围过宽（...）` → id + 标题
    #   level 从函数体里第一次产出该 id 时用的等级取
    _pm = re.search(r'PROJECT_CHECKS\s*=\s*\[(.*?)\]', asrc, re.S)
    if _pm:
        for _fn in re.findall(r'_p_\w+', _pm.group(1)):
            # docstring 可能含引号（如 G09 的说明里引了 `'../runner.mjs'`），
            # 用 [^"]* 会匹配不到 → 该规则**静默不进注册表**（能报、自检也报，
            # 但无 eval、无判据映射、不计入覆盖率）。改用非贪婪 + DOTALL。
            _dm = re.search(
                r'def\s+' + _fn + r'\s*\([^)]*\):\s*\n\s*"{3}(.*?)"{3}',
                asrc, re.S)
            if not _dm:
                continue
            _doc = _dm.group(1).strip()
            _idm = re.match(r'([A-Z]\d{2})\s+(.*)', _doc, re.S)
            if not _idm:
                continue
            _pid, _title = _idm.group(1), _idm.group(2).strip().split('\n')[0]
            if _pid in aseen:
                continue
            aseen.add(_pid)
            _lm = re.search(r"\(\s*'" + _pid + r"'\s*,\s*'(P\d)'", asrc[_dm.end():])
            _lvl = _lm.group(1) if _lm else 'P2'
            out.append({'rule_id': 'APP-%s' % _pid, 'native_id': _pid,
                        'scanner': 'scan-app.py', 'level': _lvl, 'title': _title,
                        'family': _pid[0], 'scene': APP2SCENE.get(_pid, 's-build'),
                        'item': None, 'cwe': [], 'fix': ''})

    # scan-app 的 FILE_PATTERNS / PROJECT_CHECKS 无法用统一正则提取，按已知清单补齐
    # 合并 note：G01/K12/K25/K27 来自另一条工作线（判据缺口补齐批次），
    # 原在线上版本里被覆盖丢失过一次 —— 远端 registry 一度只剩 156 条、
    # APP-K 与 CC 全空。--check 现在会拿 PROJECT_CHECKS 与注册表做交叉比对，
    # 少一条就报，不会再静默。
    extra = {'C01': ('P2', '孤儿组件 / 死代码（无任何引用）', 's-contracts'),
             'G01': ('P1', '打包范围过宽 / 无 files 白名单', 's-build'),
             'K12': ('P1', '进程注册表有写入无 remove（进程结束条目残留）', 's-lifecycle'),
             'K25': ('P0', '定义了命令但 invoke_handler 里没有（承诺失效）', 's-contracts'),
             'K27': ('P1', '命令重复实现（同名 handler 多处定义）', 's-contracts'),
             'G09': ('P2', '导出后零引用（已实现未接线）', 's-contracts'),
             'G10': ('P0', 'CI 引用不存在的 npm script', 's-build'),
             'J13': ('P1', '同名常量清单重复定义且已分叉', 's-contracts'),
             'P01': ('P2', '忽略清单缺常见项', 's-build'),
             'P02': ('P2', '孤儿源文件（无任何引用）', 's-contracts'),
             'P03': ('P2', '有校验脚本但无 CI', 's-build'),
             'P04': ('P0', '多入口但安全策略只覆盖其一', 's-sandbox'),
             'P05': ('P1', '多份构建配置合并关系存疑', 's-build'),
             'R08': ('P2', '未被 mod 声明的孤儿 .rs 文件', 's-contracts'),
             'G04': ('P1', '有依赖声明但缺 lock 文件', 's-build'),
             'G05': ('P1', '占位资源未替换（脚手架默认值发布）', 's-build'),
             'G11': ('P1', '测试 import 扩展名写法与同目录不一致', 's-build'),
             'G13': ('P2', 'sourcemap / minify 不随 profile 变化', 's-build'),
             'G12': ('P1', '基础镜像用 latest 或无标签', 's-build')}
    for k, (lvl, title, scene) in extra.items():
        if k not in aseen:
            out.append({'rule_id': 'APP-%s' % k, 'native_id': k, 'scanner': 'scan-app.py',
                        'level': lvl, 'title': title, 'family': k[0], 'scene': scene,
                        'item': None, 'cwe': [], 'fix': ''})
    # ---------- cocos-audit.py ----------
    # 长期游离在体系之外：这个扫描器能报 11 类问题，但注册表里 0 条 cocos 规则。
    # 从它自己的 RULE_IDS 表提取（中文名 → ID），id 与级别都在它那里定义，
    # 这里只负责搬运——不另立一份清单，避免两处不同步。
    cpath = os.path.join(HERE, 'cocos-audit.py')
    if os.path.isfile(cpath):
        csrc = open(cpath, encoding='utf-8').read()
        _rm = re.search(r'RULE_IDS\s*=\s*\{(.*?)\}', csrc, re.S)
        _lm = re.search(r'RULE_LEVELS\s*=\s*\{(.*?)\}', csrc, re.S)
        if _rm:
            levels = dict(re.findall(r'"([A-Z]+-\d+)"\s*:\s*"(P\d)"',
                                     _lm.group(1) if _lm else ''))
            for name, pid in re.findall(r'"([^"]+)"\s*:\s*"?([A-Z]+-\d+)"?',
                                        _rm.group(1)):
                if not re.match(r'^[A-Z]+-\d+$', pid):
                    continue   # None（如「读取失败」）不是规则
                if pid in cseen:
                    continue
                cseen.add(pid)
                out.append({'rule_id': pid, 'native_id': pid,
                            'scanner': 'cocos-audit.py',
                            'level': levels.get(pid, 'P2'), 'title': name,
                            'family': 'CC', 'scene': 'p-cocos',
                            'languages': ['ts', 'js'],
                            'fixtures': {'tp': None, 'fp': None},
                            'eval': {'precision': 'unverified',
                                     'recall': 'unverified'}})

    # ---------- godot-audit.py ----------
    # 与 cocos 完全同型的幽灵包：34 条 GD 规则一条都不在注册表里 ——
    # 能报、有 45 条自检，但没有 eval、没有判据映射、不计入覆盖率、
    # --scanners 里也看不到它（CI 因此不会跑它的自检）。
    # 根因同前：各处名单按 `scan-` 前缀硬匹配，`*-audit.py` 漏掉。
    gpath = os.path.join(HERE, 'godot-audit.py')
    if os.path.isfile(gpath):
        gsrc = open(gpath, encoding='utf-8').read()
        gseen = set()
        # 规则元组形如 ("GD04", "P1", "旧式信号", "gd", r"...", "说明", "修法")
        # ⚠ 原来是 `GD\d{2}` —— 只认两位编号。
        #   GD 编号已排到 GD384，三位编号的规则（GD101–GD384 共 230 条）
        #   **从未进过注册表**，而 --check 只报"扫描器有、注册表没有"，
        #   看起来像"没跑 --sync"，实际是提取器根本取不到。
        #   ⛔ 这又是"只覆盖一种写法"：编号位数涨了，正则没跟着涨。
        # ⚠ GDS01–GDS08 是着色器规则的独立命名空间，同样要登记，
        #   否则 registry 里永远缺这 8 条（而 --check 只会说"扫描器有"）。
        for m in re.finditer(r'\(\s*"(GD(?:S)?\d{2,4})"\s*,\s*"(P\d)"\s*,\s*"([^"]+)"\s*,',
                             gsrc):
            _nat = m.group(1)
            gid = ('GDS-%s' % _nat[3:]) if _nat.startswith('GDS') \
                else ('GD-%s' % _nat[2:])
            if gid in gseen:
                continue
            gseen.add(gid)
            out.append({'rule_id': gid, 'native_id': m.group(1),
                        'scanner': 'godot-audit.py', 'level': m.group(2),
                        'title': m.group(3), 'family': 'GD', 'scene': 'p-godot',
                        'languages': ['gd', 'cs'],
                        'fixtures': {'tp': None, 'fp': None},
                        'eval': {'precision': 'unverified',
                                 'recall': 'unverified'}})

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
        names = os.listdir(d)
        # 两种形态：单文件 tp.<ext>（默认）与项目树 tp.d/（项目级规则需要多文件）。
        # 只认 startswith('tp.') 的话，tp.d/ 形态会被判成「没有样本」——
        # 项目级规则（J13/P01~P05/R08/G01~G12/K12/K25/K27/C01）与全部
        # cocos 规则都是 tp.d/，它们会被集体误报为未覆盖。
        tp = (next((f for f in names if f.startswith('tp.')), None)
              or ('tp.d' if 'tp.d' in names else None))
        fp = (next((f for f in names if f.startswith('fp.')), None)
              or ('fp.d' if 'fp.d' in names else None))
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
    # eval 继承：判据没变就保留上次实测结论，变了（sig 不同）才重置。
    # 不带 sig 的历史 eval 一律不继承 —— 无法确认实测时的规则是否还是这一版。
    old, old_map = {}, {}
    if os.path.isfile(REG):
        try:
            prev = json.load(open(REG, encoding='utf-8'))
            old = {r['rule_id']: r.get('eval') for r in prev.get('rules', [])}
            # item 映射同样要继承：它是 --map 的产物，不是扫描器能提取出来的。
            # 不继承的话跑一次 --sync 就把 106 条映射全冲掉，而 --sync 的输出
            # 看起来一切正常 —— 又一种「跑了但悄悄丢东西」。
            old_map = {r['rule_id']: (r.get('item'), r.get('item_src'))
                       for r in prev.get('rules', [])
                       if 'item' in r}
        except ValueError:
            old, old_map = {}, {}
    kept = map_kept = 0
    lost_map = []
    for r in rules:
        if r['rule_id'] in old_map:
            r['item'], r['item_src'] = old_map[r['rule_id']]
            # 只统计真正有映射的；item=null 是「确认无对应」，不算继承了一条映射，
            # 混在一起报会让「继承了 N 条」看起来比实际多
            if r['item']:
                map_kept += 1
            elif old_map[r['rule_id']][0]:
                # 上一版有映射、这一版没了 —— 典型「跑了但悄悄丢东西」。
                # 不加这道护栏，--sync 输出一切正常，等你用 item-index 才发现
                # 判据取不到，而那时已经说不清是哪次 sync 丢的。
                lost_map.append(r['rule_id'])
        ev = old.get(r['rule_id'])
        if isinstance(ev, dict) and ev.get('sig') == _rule_sig(r):
            r['eval'] = ev
            kept += 1
        else:
            e = r.get('eval') or {}
            e['sig'] = _rule_sig(r)
            e.setdefault('precision', 'unverified')
            e.setdefault('recall', 'unverified')
            e.setdefault('verified_at', None)
            r['eval'] = e
    reg = {'version': '1.0.0',
           'note': '由 scripts/rule-registry.py --sync 从扫描器提取生成。'
                   '不要手改条目（会被 --check 判为漂移）；改扫描器后重新 sync。',
           'rules': rules}
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    json.dump(reg, open(REG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('已同步 %d 条规则 → rules/registry.json'
          '（继承实测结论 %d 条 · 继承判据映射 %d 条）'
          % (len(rules), kept, map_kept))
    if lost_map:
        print('  ✗ 映射在同步中丢失：%s' % ', '.join(lost_map[:10]))
        print('    → 「跑了但悄悄丢东西」，请查 --map 后再 sync')
        return 1
    return 0


def check_dup_definitions():
    """同一条规则在扫描器源码里被定义多次 → 前面的定义静默失效。

    为什么必须查：scan-ts.py 装配时「按 id 去重，保留最后定义」（修正区
    覆盖 core34 的失效实现）。于是**改前面的定义完全不生效**——
    代码看起来改了、diff 也有，但行为纹丝不动，且不报任何错。

    实测：I01 / K02 各有两个定义，我第一次改判据改的是第一个，
    复测召回率仍是 0/8，白改。这是最难察觉的一类失效。
    """
    import re as _re
    out = []
    for scanner in sorted(glob.glob(os.path.join(HERE, 'scan-*.py'))):
        src = open(scanner, encoding='utf-8').read()
        m = _re.search(r'#\s*装配后处理：按 id 去重，保留最后定义', src)
        if not m:
            continue
        ids = _re.findall(r"@pattern\('([A-Za-z0-9_]+)'", src)
        for rid in sorted({i for i in ids if ids.count(i) > 1}):
            pos = [k for k, x in enumerate(ids) if x == rid]
            out.append('%s：%s 被定义 %d 次（行序 %s）→ 生效的是**最后**一个，'
                       '改前面的不生效'
                       % (os.path.basename(scanner), rid, len(pos),
                          ', '.join(str(x) for x in pos)))
    return out



def project_check_ids():
    """从 scan-app.py 的 PROJECT_CHECKS 函数 docstring 里取规则 ID。

    为什么需要：项目级检查是**函数**，ID 写在 docstring 首行
    （约定形如 G04 开头的一行短描述），extract() 的正则提取不到，
    只能靠 extra 手工登记。登记表散在两处，靠这个函数把
    「代码里的真实集合」拉出来做交叉验证。

    取不到就返回空集——宁可不报，也不要因为解析失败刷一堆假告警。
    """
    path = os.path.join(HERE, 'scan-app.py')
    if not os.path.isfile(path):
        return set()
    try:
        src = open(path, encoding='utf-8').read()
    except OSError:
        return set()
    ids = set()
    # 只在 PROJECT_CHECKS 列表**之前**的函数定义里找，避免误抓别处的 docstring
    head = src.split('PROJECT_CHECKS')[0]
    for m in re.finditer(r'^def\s+(_\w+)\([^)]*\):\s*\n\s*"""([A-Z]\d{2})\b',
                         head, re.M):
        ids.add(m.group(2))
    return ids


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

    # 重复定义：改前面的不生效，且没有任何报错
    for msg in check_dup_definitions():
        warns.append(msg)

    # 项目级规则漏登记：PROJECT_CHECKS 是函数，extract() 提取不到，
    # 只能靠 extra 手工登记。加规则时改了 scan-app.py 却忘了改这里，
    # 规则会「能跑、能报、但不在注册表里」——fixture 覆盖率、CWE、
    # SARIF 导出全都看不到它，且不报任何错。
    #
    # 比 native_id 而非 rule_id：docstring 里是裸 ID（R08），
    # 注册表里 rule_id 带 APP- 前缀（APP-R08）。比错了会全部误报成「未登记」。
    reg_native = {r.get('native_id') for r in reg['rules']
                  if r.get('scanner') == 'scan-app.py'}
    for rid in sorted(project_check_ids() - reg_native):
        warns.append('%s 在 scan-app.py 的 PROJECT_CHECKS 里，但注册表没有'
                     ' → 补 rule-registry.py 的 extra 后跑 --sync' % rid)

    # 判据映射覆盖率：没映射的规则在 item-index 里取不到人工判据。
    # 「未映射」与「确认无对应」是两回事（item=null vs 缺字段），
    # 这里分开报 —— 合并统计会让「还没做」看起来像「做了，没有」。
    try:
        _items = {i['id'] for i in
                  json.load(open(ITEMS, encoding='utf-8'))['items']}
    except (OSError, ValueError, KeyError):
        _items = set()
    by_rid = {r['rule_id']: r for r in reg['rules']}
    wrong = [('%s→%s(应为%s)' % (k, by_rid[k].get('item'), v))
             for k, v in sorted(KNOWN_MAP.items())
             if k in by_rid and by_rid[k].get('item') != v]
    if wrong:
        errs.append('已知映射被改坏（撞号回归锚点）：%s' % '; '.join(wrong[:6]))

    unmapped = [r['rule_id'] for r in reg['rules'] if 'item' not in r]
    dangling = [r['rule_id'] for r in reg['rules']
                if r.get('item') and _items and r['item'] not in _items]
    if dangling:
        errs.append('映射指向不存在的条目：%s → 跑 --map --apply'
                    % ', '.join(dangling[:8]))
    if unmapped:
        warns.append('未做判据映射 %d 条 → 跑 --map --apply（%s…）'
                     % (len(unmapped), ', '.join(unmapped[:5])))

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
    # 必须用 live（extract + attach_fixtures 实时算）而不是 reg（registry.json
    # 的静态字段）：sync 前 registry.json 里 fixtures 全是 null，用 reg 统计
    # 会稳定输出「有 TP fixture: 0 / 93」——而文件系统里 148 个目录都有 tp。
    # 自检自己报出一个与事实相反的覆盖率，比不报更糟：它会让人以为 fixture
    # 一条都没写，实际只差 3 条。
    nofix = [r['rule_id'] for r in live if not r['fixtures'].get('tp')]
    verified = len(live) - len(nofix)

    print('rule-registry · 检查')
    # 按扫描器分档统计：原来只写死了 scan-ts / scan-app 两个，
    # 新增语言包后总数会对不上（131 条里只报 89），掩盖了新规则是否真的入表
    from collections import Counter
    per = Counter(r['scanner'] for r in reg['rules'])
    print('规则总数: %d（%s）' % (
        len(reg['rules']),
        ' / '.join('%s %d' % (k.replace('.py', ''), v)
                   for k, v in sorted(per.items()))))
    if len(live) != len(reg['rules']):
        print('  ⚠ 扫描器实际有 %d 条，注册表只有 %d 条 → 跑 --sync'
              % (len(live), len(reg['rules'])))
    print('有 TP fixture: %d / %d（按扫描器实际规则计）'
          % (verified, len(live)))
    # eval 分布：全 unverified 说明这个字段没活起来（跑 --eval 回填）
    evc = Counter()
    for r in reg['rules']:
        e = r.get('eval') or {}
        evc[(e.get('precision', 'unverified'), e.get('recall', 'unverified'))] += 1
    print('eval 状态: %s' % ' · '.join(
        'recall=%s/precision=%s %d' % (rc, pr, n)
        for (pr, rc), n in sorted(evc.items(), key=lambda x: -x[1])))
    never = evc.get(('unverified', 'unverified'), 0)
    if never == len(reg['rules']):
        warns.append('eval 全部 unverified（等于没标）→ 跑 --eval 回填实测结论')
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
    """在临时模块结构上跑扫描器，返回 (ok, hits, err)；hits 只计**本规则**的命中。

    ok=False 表示扫描器**没跑起来**（超时 / 崩溃 / 无输出 / 输出非 JSON），
    hits 为 None。

    为什么拆成三态：原来失败与「真的 0 命中」都返回 None，上层统一按
    「无有效输出」跳过 —— 于是「规则失效」「扫描器坏了」「fixture 没写」
    三种情况被压成同一个数。这正是本技能最痛恨的静默失败，却出现在
    统计自身健康度的路径上（未覆盖 72 条里可能混着跑挂的）。

    为什么不再传 --pattern=：六个扫描器里只有 scan-ts 认这个参数，
    其余五个当未知 flag 忽略 → 实际跑的是全量扫描，只要**任何一条**
    规则命中就算通过。于是「TP 已验证」里混着从未被自己规则命中的假通过，
    FP 侧则被反过来要求全库零命中。改为跑全量后按 id 自行过滤，
    六个扫描器行为一致。
    """
    import subprocess
    # cocos-audit.py 用**位置参数**接路径（`cocos_audit.py <路径>`），
    # 不认 --src=。统一按 --src= 调它会让 argparse 报 unrecognized arguments
    # 直接退出，于是 11 条 cocos 规则全被算成「扫描器没跑起来」——
    # 又是一次「工具不支持 → 静默当没问题」。
    if scanner == 'cocos-audit.py':
        cmd = [sys.executable, os.path.join(HERE, scanner), src_root, '--json']
    else:
        cmd = [sys.executable, os.path.join(HERE, scanner),
               '--src=' + src_root, '--json']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        return False, None, '执行异常：%s' % e
    out = (r.stdout or '').strip()
    if not out:
        return False, None, 'stdout 为空（stderr：%s）' % (
            (r.stderr or '').strip()[:200] or '无')
    try:
        d = json.loads(out)
    except ValueError:
        return False, None, '输出非 JSON：%s' % out[:160]
    items = d.get('items', []) if isinstance(d, dict) else (
        d if isinstance(d, list) else [])
    hits = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        rid = it.get('id') or it.get('pattern') or it.get('rule_id')
        if rid == native_id:
            hits += 1
    return True, hits, ''


# 变体目录名：`<RULE_ID>-<变体名>`，且 <RULE_ID> 本身是已注册的规则号。
# 只在注册表里**查得到基规则**时才这么解析，避免把任何带横杠的目录都当变体。
def _variant_base(rid, reg):
    m = re.match(r'^(.*?)-([a-z][a-z0-9]*)$', rid)
    if not m:
        return None
    base = m.group(1)
    if any(r['rule_id'] == base for r in reg['rules']):
        return base
    return None


VARIANT_RX = re.compile(r'^(?P<base>[A-Z]{2,4}-[A-Z]?\d{1,2})-[a-z][a-z0-9]*$')


def run_all_fixtures(reg, verbose=True):
    """跑全部 fixture，返回 {rid: {'tp': bool|None, 'fp': bool|None, 'errors': [...]}}。

    tp=True  → TP 样本被命中（规则抓得到真问题）
    fp=True  → FP 样本未被命中（规则不过宽、不误伤）
    None     → 该项没有样本，或扫描器没跑起来；两者靠 errors 区分。
    """
    res = {}
    if not os.path.isdir(FIXDIR):
        return res
    for rid in sorted(os.listdir(FIXDIR)):
        d = os.path.join(FIXDIR, rid)
        if not os.path.isdir(d):
            continue
        names = os.listdir(d)
        # 必须按「tp / tp2 / tp3 …」识别，不能只认 startswith('tp.')：
        # 'tp2.ts' 不以 'tp.' 开头，用前缀判断会让第二组样本被静默跳过
        files = [f for f in names if re.fullmatch(r'(?:tp|fp)\d*\.[A-Za-z0-9.]+', f)]
        # 项目级规则（J13 / P01~P05 / R08）判的是「整棵工程」——忽略清单、CI 配置、
        # 多入口 HTML 的安全策略覆盖。单文件 fixture 表达不了，故支持 tp.d/ / fp.d/
        # 整树模式：目录内容原样铺到临时根，扫描器按平时的方式扫整个根。
        trees = [f for f in names if f in ('tp.d', 'fp.d')]
        if not files and not trees:
            continue
        meta = next((r for r in reg['rules'] if r['rule_id'] == rid), None)
        # 注册表里没有这条规则 → 这是**判据条目**的样本（如 PY-14/PY-15：
        # p-python.md 有判据、有样本，但 scan-py.py 没实现机扫规则）。
        # 不能当失败，也不能静默跳过：记下来统一报，让人一眼看出
        # 「这是人工判据」还是「规则删了样本没清」。
        # 变体目录：`TS-D02-dts` 是 TS-D02 的**额外样本**（同一规则、不同写法），
        # 不是独立规则。原先 native 取 rid.split('-',1)[-1] = 'D02-dts'，
        # 而扫描器输出的是 'D02' —— 永远匹配不上。
        # 对 fp 而言 hits 恒为 0 → rec['fp'] 恒为 True → **永远通过**。
        # 三个变体目录里的额外误报样本，其实一条都没在验证任何东西。
        if meta is None and VARIANT_RX.match(rid):
            base = VARIANT_RX.match(rid).group(1)
            meta = next((r for r in reg['rules'] if r['rule_id'] == base), None)
            if meta is None and verbose:
                print('  ! %s：变体目录找不到基规则 %s（样本不会生效）' % (rid, base))
        # 变体也没匹配上 → 注册表里没有这条规则。
        # 分两种，都必须显式列出，不能静默跳过：
        if meta is None and not VARIANT_RX.match(rid):
            SKIPPED_NO_RULE.add(rid)
            continue
        scanner = (meta or {}).get('scanner', 'scan-ts.py')
        native = (meta or {}).get('native_id', rid.split('-', 1)[-1])
        rec = {'tp': None, 'fp': None, 'errors': []}
        for kind in ('tp', 'fp'):
            treedir = os.path.join(d, kind + '.d')
            # 两种形态互斥：
            #   ① 整树  tp.d/（目录）—— 项目级规则需要多文件工程
            #   ② 多组单文件  tp.ts / tp2.ts … —— 同一规则的不同写法
            if os.path.isdir(treedir):
                tmp = tempfile.mkdtemp(prefix='fix-')
                try:
                    shutil.copytree(treedir, tmp, dirs_exist_ok=True)
                    ok, hits, err = _run_scanner(scanner, tmp, native)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
                if not ok:
                    rec['errors'].append('%s：扫描器执行失败（%s）' % (kind, err))
                    if verbose:
                        print('  ! %s %s：扫描器执行失败（%s）'
                              % (rid, kind, err[:110]))
                    continue
                if kind == 'tp':
                    rec['tp'] = hits > 0
                    if hits == 0 and verbose:
                        print('  \u2717 %s TP 未命中（规则可能失效）' % rid)
                else:
                    rec['fp'] = hits == 0
                    if hits and verbose:
                        print('  \u2717 %s FP 被命中（%d 处，规则可能过宽'
                              ' → 误报源）' % (rid, hits))
                continue

            samples = sorted(f for f in files
                             if re.fullmatch(kind + r'\d*\.[A-Za-z0-9.]+', f)
                             and os.path.isfile(os.path.join(d, f)))
            if not samples:
                continue
            results = []
            for src in samples:
                tmp = tempfile.mkdtemp(prefix='fix-')
                try:
                    # 扫描器按「一级子目录 = 模块」切分，fixture 要放进一个模块目录
                    # 部分规则要求特定目录结构（如 J08 要求文件在 plugins/ 下），
                    # fixture 可用 .subdir 文件指定存放子目录
                    _sd = 'mod'
                    _sdf = os.path.join(d, '.subdir')
                    if os.path.isfile(_sdf):
                        _sd = open(_sdf).read().strip() or 'mod'
                    mod = os.path.join(tmp, _sd)
                    os.makedirs(mod, exist_ok=True)
                    shutil.copy(os.path.join(d, src), os.path.join(mod, src))
                    ok, hits, err = _run_scanner(scanner, tmp, native)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
                if not ok:
                    rec['errors'].append('%s(%s)：扫描器执行失败（%s）'
                                         % (kind, src, err))
                    if verbose:
                        print('  ! %s %s(%s)：扫描器执行失败（%s）'
                              % (rid, kind, src, err[:110]))
                    continue
                if kind == 'tp':
                    results.append(hits > 0)
                    if hits == 0 and verbose:
                        print('  \u2717 %s TP 未命中（%s，规则可能失效）' % (rid, src))
                else:
                    results.append(hits == 0)
                    if hits and verbose:
                        print('  \u2717 %s FP 被命中（%s，%d 处，规则可能过宽'
                              ' → 误报源）' % (rid, src, hits))
            if not results:
                continue
            # 多组样本：全部通过才算通过，不能「有一个命中就算过」
            rec['tp' if kind == 'tp' else 'fp'] = all(results)
        res[rid] = rec
    return res


# ---- 机扫规则 → 人工判据 的显式映射 ----
#
# 为什么需要：两套编号体系独立演进，撞在了同一个字母上。
#   items.json  按 scene 编号：A=s-atomicity  N=s-numerics  D=s-structures …
#   scan-ts     按族   编号：A=数值族         C=原型污染族   T=循环族 …
# 于是 TS-A05（「>>> 0 把 NaN 变 0」）与 A-05（「调试/作弊/后门默认启用」）
# 归一化后都是 A05，按 ID 取判据会**静默给出完全无关的一条**——
# 实测 41/131 条错配。更麻烦的是 family 字母还会误导：
# TS-A05 的 family 是 A，而它的 scene 是 s-numerics，真判据在 N-05。
#
# 解法：把映射关系**显式写进 registry.json 的 item 字段**，不再靠 ID 推算。
# 取值三态，与 cwe 字段同一套哲学（区分「确认没有」与「还没查」）：
#   "N-05"  → 已映射
#   null    → 确认无对应判据
#   缺字段  → 尚未做过映射


def _map_tokens(t):
    return set(re.findall(r'[\u4e00-\u9fff]|[A-Za-z]{2,}', t or ''))


def _map_score(rule, item):
    """候选打分 0~1。名称为主，关键词/同场景/正文命中为辅。"""
    a, b = _map_tokens(rule.get('title')), _map_tokens(item.get('name'))
    s = (len(a & b) / len(a | b)) if (a and b) else 0.0
    ks = item.get('keywords') or []
    if ks:
        hit = sum(1 for k in ks
                  if k and k.lower() in (rule.get('title') or '').lower())
        s += min(0.20, hit * 0.07)
    if rule.get('scene') and rule['scene'] == item.get('scene'):
        s += 0.08
    body = item.get('body') or ''
    core = [w for w in a if len(w) >= 2]
    if core:
        bh = sum(1 for w in core if w in body)
        s += min(0.15, bh / max(1, len(core)) * 0.15)
    return min(1.0, s)


AUTO_ACCEPT = 0.50   # ≥ 此分自动采纳
AUTO_REVIEW = 0.32   # ≥ 此分记为待确认（保留候选，不写入）

# 人工确认表：自动打分低于阈值，但核对判据原文后确认语义对应的。
#
# 为什么需要这张表：措辞差异会让语义正确的映射只有 0.33 分。
# 例：TS-A05「>>> 0 / |0 把 NaN 静默变成 0」对 N-05「位运算把 NaN 静默归零」，
# 判据原文写的就是 `>>> 0` / `| 0`，完全同一条，但名称字面重合度只有 0.44。
# 自动阈值再调低就会引入真错配，所以低分档交人判断，结论沉淀在这里。
#
# 为什么写进代码而不是直接改 registry.json：重跑 --map 时人工结论不会被冲掉，
# 且每条都留了理由，半年后回看知道当初为什么这么定（对应 H016「先查溯源」）。
#
# 确认于 2026-09-15：逐条比对 items.json 的 body 判据原文后采纳。
MANUAL_MAP = {
    'APP-J04': ('K-32', 'K-32 判据含「无 allowlist 的 JSON 转对象」，'
                        'APP-J04 是存储反序列化无兜底，同一条'),
    'APP-P02': ('K-26', 'K-26 判据「.rs 文件是否都被 mod 声明」，'
                        'APP-P02 是孤儿源文件，同一条'),
    'APP-P03': ('G-03', 'G-03 判据「有 typecheck/test/lint 脚本但无 CI 引用」，'
                        '与 APP-P03 完全吻合'),
    'APP-R02': ('K-22', 'K-22 判据「一次锁中毒 = 应用直接崩」，'
                        'APP-R02 是 lock().unwrap() 配 panic=abort'),
    'APP-R05': ('S-05', 'S-05 判据「字符串比较未做 canonicalize」，'
                        '与 APP-R05 的可 ../ 绕过完全吻合'),
    'APP-R07': ('K-24', 'K-24 判据「阻塞式固定 sleep 轮询」，'
                        'APP-R07 前半段即 thread::sleep 轮询'),
    'TS-A05': ('N-05', 'N-05 判据原文就是 `>>> 0` / `| 0`，与 TS-A05 同一条；'
                       '此前按 ID 撞号错取到 A-05「调试/作弊后门」'),
    'TS-F01': ('C-12', 'C-12 特征明确列出 `register`/`import` 成对'
                       '（一个有校验一个没有），正是 TS-F01 的核心'),
    'TS-M02': ('A-04', 'A-04 判据「can*/has* 体内数值比较但无 isFinite」，'
                       '与 TS-M02 的安全判定依赖污染数值吻合'),
    # 架构可演进性：规则号取自判据号，且规则就是该判据的直接实现，
    # 属真正的语义同源（不是编号撞号）—— 显式声明，避免 --map 按字面打分漏掉。
    'AR-01': ('AR-01', 'AR-01 规则由 s-architecture 判据 AR-01 直接实现'
                       '（判定函数内 print / 非 CLI 层 SystemExit），同源'),
    'AR-03': ('AR-03', 'AR-03 规则由判据 AR-03 直接实现'
                       '（状态常量为仓库外绝对路径 / 目标常量硬编码），同源'),
    'AR-04': ('AR-04', 'AR-04 规则由判据 AR-04 直接实现'
                       '（退出点≥3 而数字退出码≤1 种），同源'),
    'AR-05': ('AR-05', 'AR-05 规则由判据 AR-05 直接实现'
                       '（无测试框架 + ALL PASS / mod.X= 打补丁），同源'),
    'TS-O03': ('A-09', 'A-09 判据「不直接 console.*，走 logger 注入」，'
                       '与 TS-O03 完全吻合'),
    # 第二批（2026-09-15）：未映射规则 ↔ 未映射判据 的双向配对。
    # 单向查会漏掉「两边都没映射、其实是一对」——只查「未映射判据能否配上某条规则」
    # 时，这些规则自身也未被映射，于是两边都被当成「无对应」，缺口被重复计了一次。
    'APP-R01': ('K-01', 'K-01 判据「是否用 take(cap) 流式读取，而非 fs::read 后截断」，'
                        '与 APP-R01 完全同一条（Rust 视角）'),
    'APP-R09': ('K-18', 'K-18 判据「token 为空时是否直接放行」，'
                        '与 APP-R09 空凭据即放行完全同一条'),
    'APP-P01': ('G-06', 'G-06 判据「忽略清单缺 node_modules/dist/target/__pycache__」，'
                        '与 APP-P01 完全同一条'),
    'TS-J01': ('A-01', 'A-01 特征「扣减与增加在相邻行且无 try」，'
                       '与 TS-J01 多步写不回滚同一条'),
    'TS-E02': ('L-09', 'L-09 特征「Set 存监听器 + filter 按函数值重建」，'
                       '与 TS-E02 按函数值去重的 Set 同一条'),
    'APP-J05': ('T-02', 'T-02 判据「注册时包箭头函数、解绑时传原始 fn」，'
                        '与 APP-J05 事件解绑引用不一致同一条'),
    'APP-R11': ('K-07', 'K-07 判据「是否 canonicalize / realpath 后比较」，'
                        '与 APP-R11 文件读取无路径约束同族'),
    'APP-J09': ('L-01', 'L-01「事件订阅无注销」已有 TS-X01 映射；'
                        'APP-J09「只注册不注销」是同一条的扩展视角（多对一）'),
    # 缺口补齐批次：规则号刻意取成判据号，语义分却只有 0.4x（标题是「绑定地址：
    # 0.0.0.0 对局域网开放」，判据名是「127.0.0.1 vs 0.0.0.0」，字面重合低）。
    # 曾想用「编号同源直映」自动处理，实测会把 TS-S01/TS-K01 也错配（见 cmd_map
    # ③ 处说明），故逐条显式声明。
    'APP-K10': ('K-10', 'K-10 判据「参数数组 vs 字符串拼接」，'
                        '与 APP-K10 完全同一条'),
    'APP-K17': ('K-17', 'K-17 判据「127.0.0.1 vs 0.0.0.0（后者对局域网开放）」，'
                        '与 APP-K17 完全同一条'),
}

# 回归锚点：这些映射**曾经被算错过**，且错得很隐蔽——
# 每次错都是「归一化后撞到另一个编号体系」，输出看着像一条正常判据。
# 锚在这里，谁改匹配逻辑改坏了就当场红，不用等人工审查时才发现判据取错。
KNOWN_MAP = {
    'TS-S01': 'A-05',   # 撞 S-01「隔离后能力静默失效」（应为「调试/作弊/后门默认启用」）
    'TS-K01': 'L-10',   # 撞 K-01「读入是否有界」（应为「状态字段只置 true 没有复位」）
    'TS-A05': 'N-05',   # 撞 A-05「调试/作弊/后门默认启用」（应为「位运算把 NaN 静默归零」）
    'TS-C01': 'D-01',   # 撞 C-01「孤儿组件/死代码」（应为「裸 Record 查表命中 prototype」）
    'TS-D01': 'C-05',   # 撞 D-01（应为「接口字段声明但从未被读取」）
    'TS-B10': 'B-10',
    'TS-L15': 'L-15',
    'TS-T05': 'T-05',
    'TS-D11': 'D-11',
    'APP-K03': 'K-03',
    'APP-K08': 'K-08',
    'APP-K10': 'K-10',
    'APP-K14': 'K-14',
    'APP-K15': 'K-15',
    'APP-K16': 'K-16',
    'APP-K17': 'K-17',
    'APP-K31': 'K-31',
    'APP-K34': 'K-34',
    'APP-G01': 'G-01',
    'APP-G04': 'G-04',
    'APP-G05': 'G-05',
    'APP-G10': 'G-10',
    'APP-G12': 'G-12',
    'APP-K12': 'K-12',
    'APP-K25': 'K-25',
    'APP-K27': 'K-27',
    'APP-C01': 'C-01',
    'CC-11': 'CC-02',
    'CC-12': 'CC-04',
    'CC-13': 'CC-01',
    'CC-14': 'CC-02',
    'CC-15': 'CC-02',
}

# 明确无对应：候选分最高的也明显不是同一条，别硬塞
MANUAL_NONE = {
    'APP-R03': '候选 L-15 是「缓存 Map 无上限」，K-13 是「权限声明」，'
               '都与「按声明长度分配缓冲」无关',
}


def cmd_map(apply=False):
    """生成 机扫规则 → items.json 判据 的显式映射，写入 registry.json 的 item 字段。

    为什么分两档：语言包（CPP/GO/JAVA/PY）两边编号同源，native_id 即 items 的 id，
    属**结构性映射**，无需猜；TS/APP 包编号体系不同源，只能靠语义匹配，
    所以高分自动采纳、低分**不写入**并保留候选，等人工确认——
    宁可留空让人看到「未映射」，也不塞一条可能错的。
    """
    reg = load()
    if reg is None:
        print('没有注册表')
        return 1
    try:
        items = json.load(open(ITEMS, encoding='utf-8'))['items']
    except (OSError, ValueError, KeyError) as e:
        print('读 items.json 失败：%s' % e)
        return 1
    by_id = {i['id']: i for i in items}
    high, review, none_, lang = [], [], [], 0
    for r in reg['rules']:
        nid = r.get('native_id', '')
        # ① 编号严格同源：native_id / rule_id 与 items 的某个 id **完全相同**。
        #
        # 为什么用严格相等而不是硬编码前缀列表：
        # 原先写死 `^(CPP|GO|JAVA|PY)-\\d`，新增 Rust 语言包后 RS-01~10
        # 一条都没映射上——扫描器在跑、规则在注册表里、--check 也报了，
        # 但 item-index 取不到它们的判据。又一处「名单漏了一个就静默失效」。
        #
        # 为什么**不能**归一化后比（这正是上一轮撤掉的方案）：
        # 归一化会让 TS-S01(native=S01) 撞上 S-01「隔离后能力静默失效」，
        # 而正确答案是 A-05「调试/作弊/后门默认启用」。
        # 格式对齐 ≠ 语义同源。严格相等才安全——实测 TS/APP 零误伤
        #（它们的 native_id 是 A05 / J01 这种紧凑写法，items 里不存在）。
        _same = None
        for _k in (nid, r['rule_id']):
            if _k in by_id:
                _same = _k
                break
        if _same:
            r['_item'], r['_src'] = _same, 'id'
            lang += 1
            continue
        # 进了语言包分支却找不到同 id 条目 → 记一笔，别沉默
        if re.match(r'^(CPP|GO|JAVA|PY|RS)-\d', r['rule_id']):
            r['_item'], r['_src'] = None, 'no-same-id'
            none_.append(r)
            continue
        # ② 人工确认表优先（不会被自动打分冲掉）。
        #
        # KNOWN_MAP 是**撞号回归锚点**：每一条都曾被打分算错过、人工核对后
        # 定下来的（如 CC-13 曾被映射到 GO-01）。它和 MANUAL_MAP 一样是人工结论，
        # 必须同样优先于打分——否则 --map --apply 会用打分结果把它们冲掉，
        # --check 随即报「已知映射被改坏」，两个命令互相打架。
        # 实测：合并 Rust 包 + 两侧分支合并后，6 条锚点被冲成 None/错值。
        if r['rule_id'] in KNOWN_MAP:
            r['_item'], r['_src'] = KNOWN_MAP[r['rule_id']], 'known'
            high.append(r)
            continue
        if r['rule_id'] in MANUAL_MAP:
            tgt, _why = MANUAL_MAP[r['rule_id']]
            r['_item'], r['_src'] = tgt, 'manual'
            high.append(r)
            continue
        if r['rule_id'] in MANUAL_NONE:
            r['_item'], r['_src'] = None, 'manual-none'
            none_.append(r)
            continue
        # ③ 语义匹配。
        #
        # 这里**曾经**加过一条「编号同源直映」：规则号取成判据号（K17 → K-17）
        # 就直映。实测是错的，而且错的正是本批次要修的那类撞号——
        #   TS-S01 native=S01 → S-01「隔离后能力静默失效」
        #                       （正确答案 A-05「调试/作弊/后门默认启用」）
        #   TS-K01 native=K01 → K-01「读入是否有界」
        #                       （正确答案 L-10「状态字段只置 true 没有复位」）
        # 归一化只是**格式**对齐，不代表语义同源。编号撞车时直映就是静默错配。
        # 真正的同源（缺口补齐批次）走 MANUAL_MAP 显式声明，带理由、可回溯。
        best, second, bs, ss = None, None, 0.0, 0.0
        for it in items:
            v = _map_score(r, it)
            if v > bs:
                best, second, bs, ss = it, best, v, bs
            elif v > ss:
                second, ss = it, v
        if bs >= AUTO_ACCEPT:
            r['_item'], r['_src'] = best['id'], 'auto:%.2f' % bs
            r['_margin'] = bs - ss
            high.append(r)
        elif bs >= AUTO_REVIEW:
            r['_item'], r['_src'] = None, 'review'
            r['_cand'] = (best['id'], bs, second['id'] if second else '-', ss)
            review.append(r)
        else:
            r['_item'], r['_src'] = None, 'none:%.2f' % bs
            none_.append(r)

    print('映射候选')
    print('=' * 60)
    print('  语言包 ID 直映      %3d 条' % lang)
    print('  语义匹配 高置信     %3d 条（≥%.2f，自动采纳）'
          % (len(high), AUTO_ACCEPT))
    print('  语义匹配 待确认     %3d 条（%.2f~%.2f，保留候选不写入）'
          % (len(review), AUTO_REVIEW, AUTO_ACCEPT))
    print('  无对应判据          %3d 条' % len(none_))

    if review:
        print('\n【待人工确认】候选分接近，写入风险大：')
        for r in review:
            c = r['_cand']
            print('  %-9s → %-7s %.2f（次选 %s %.2f）  %s'
                  % (r['rule_id'], c[0], c[1], c[2], c[3], r['title'][:34]))
    if none_:
        print('\n【无对应判据】机扫能报、items 里没有人工判据（正常，非缺陷）：')
        for r in none_[:12]:
            print('  %-9s %s' % (r['rule_id'], r['title'][:44]))
        if len(none_) > 12:
            print('  … 另有 %d 条' % (len(none_) - 12))

    margin_low = [r for r in high if r.get('_margin', 1) < 0.08]
    if margin_low:
        print('\n【高置信但次选接近】已写入，建议抽查：')
        for r in margin_low:
            print('  %-9s → %-7s (差距仅 %.2f)  %s'
                  % (r['rule_id'], r['_item'], r['_margin'], r['title'][:34]))

    if not apply:
        print('\n（预览模式。加 --apply 写入 registry.json）')
        return 0

    for r in reg['rules']:
        r.pop('_margin', None)
        r.pop('_cand', None)
        r['item'] = r.pop('_item', None)
        r['item_src'] = r.pop('_src', '')
    json.dump(reg, open(REG, 'w', encoding='utf-8'),
               ensure_ascii=False, indent=1)
    done = sum(1 for r in reg['rules'] if r.get('item'))
    print('\n已写入：%d/%d 条有显式映射' % (done, len(reg['rules'])))
    return 0

def _load_gaps():
    try:
        return json.load(open(GAPS, encoding='utf-8')).get('items', {})
    except (OSError, ValueError, AttributeError):
        return {}

def cmd_scanners():
    """列出注册表里出现过的全部扫描器。

    CI 里原本写死 `for s in scan-ts scan-app scan-py scan-go scan-java scan-cpp`——
    正是本仓库反复出现的「名单漏一个就静默失效」：新增 Rust 语言包后
    scan-rust.py 一条自检都没跑，而流水线照样绿。
    扫描器全集本就写在 registry 里，从这里推导就不会漏。
    """
    reg = load()
    if reg is None:
        print('没有注册表')
        return 1
    seen, out = set(), []
    for r in reg['rules']:
        sc = r.get('scanner')
        if sc and sc not in seen:
            seen.add(sc)
            out.append(sc)
    here = set(os.listdir(HERE)) if os.path.isdir(HERE) else set()
    for sc in sorted(out):
        mark = '' if sc in here else '   ← 文件不存在！'
        print('%s%s' % (sc, mark))
    missing = sorted(s for s in here
                     if s.startswith('scan-') and s.endswith('.py') and s not in seen)
    if missing:
        print('\n  ▲ 有扫描器文件但注册表里没有它的规则：%s' % ', '.join(missing))
        print('    → 跑 --sync 重新提取')
    return 0




def cmd_gaps():
    """判据缺口清单：items.json 里没有任何机扫规则对应的判据。

    为什么不直接报「N 条没覆盖」就完事：缺口有三种成因，混在一起报等于没说——
      xref   判据正文自己写了「与 X 同源，报一次即可」→ **根本不是缺口**
      manual 跨函数 / 时序 / 架构 / 需运行验证 → 机扫做不到，声明出来即可，
             否则每次看缺口都要重新纠结一遍「要不要给它写规则」
      todo   有明确文本特征 → 真的该写规则
    分类写在 rules/gaps.json（items.json 是生成物，不能手改）。
    """
    reg = load()
    if reg is None:
        print('没有注册表')
        return 1
    try:
        items = json.load(open(ITEMS, encoding='utf-8'))['items']
    except (OSError, ValueError, KeyError) as e:
        print('读 items.json 失败：%s' % e)
        return 1
    mapped = {r['item'] for r in reg['rules'] if r.get('item')}
    gaps = [i for i in items if i['id'] not in mapped]
    cls = _load_gaps()

    buckets = {'todo': [], 'manual': [], 'xref': [], '未分类': []}
    for it in gaps:
        k = cls.get(it['id'], {}).get('machine')
        buckets[k if k in buckets else '未分类'].append((it, cls.get(it['id'], {})))

    print('判据缺口')
    print('=' * 62)
    print('  items.json 判据总数   %3d' % len(items))
    print('  已有规则覆盖          %3d' % (len(items) - len(gaps)))
    print('  无规则对应            %3d' % len(gaps))
    print()
    print('  ├ 同源重复（非缺口）  %3d' % len(buckets['xref']))
    print('  ├ 需人工判断（非缺陷）%3d' % len(buckets['manual']))
    print('  ├ 可机扫·待写规则     %3d' % len(buckets['todo']))
    print('  └ 未分类              %3d' % len(buckets['未分类']))

    if buckets['未分类']:
        print('\n【未分类】先分类再谈补不补：')
        for it, _ in buckets['未分类']:
            print('  %-6s %s' % (it['id'], it['name'][:44]))

    if buckets['todo']:
        print('\n【可机扫 · 待写规则】按目标扫描器分组：')
        by = {}
        for it, c in buckets['todo']:
            by.setdefault(c.get('target_scanner', '?'), []).append((it, c))
        for sc in sorted(by):
            print('  %s（%d 条）' % (sc, len(by[sc])))
            for it, c in by[sc]:
                print('    %-6s %-28s %s' % (it['id'], it['name'][:26],
                                             c.get('why', '')[:36]))

    if buckets['manual']:
        print('\n【需人工判断】已声明，不必再纠结写不写规则（%d 条）：'
              % len(buckets['manual']))
        for it, c in buckets['manual'][:8]:
            print('  %-6s %-26s %s' % (it['id'], it['name'][:24],
                                       c.get('why', '')[:32]))
        if len(buckets['manual']) > 8:
            print('  … 另有 %d 条' % (len(buckets['manual']) - 8))

    # 只针对仍标着 todo 的：xref（与 X 同源）与 manual（机扫做不到）
    # 本来就可能有规则对应，算它们没意义；covered 是已处理的。
    # 原先 `k in mapped` 扫全表，把 xref/manual 里被映射的也算成陈旧，
    # 于是补完规则后这个提示反而不消失——提示本身失去了意义。
    stale = sorted(k for k, v in cls.items()
                   if v.get('machine') == 'todo' and k in mapped)
    if stale:
        print('\n  ! gaps.json 里 %d 条仍标 todo 但已被映射（补完规则后应改 covered）：%s'
              % (len(stale), ', '.join(stale[:8])))
    return 0



def _scan_hits(scanner, src_file):
    """跑扫描器并**返回完整命中分布** {rule_id: 次数}。

    与 _run_scanner 的区别：
      · _run_scanner 只回「本规则命中几次」（--test 用）
      · 这条回**全部**规则的分布（--cross 需要看「还命中了谁」）
    单文件按「放进一个模块目录」的方式喂给扫描器，与 --test 的做法一致。
    """
    import shutil
    import subprocess
    tmp = tempfile.mkdtemp(prefix='cross-')
    try:
        mod = os.path.join(tmp, 'mod')
        os.makedirs(mod, exist_ok=True)
        shutil.copy(src_file, mod)
        if scanner == 'cocos-audit.py':
            cmd = [sys.executable, os.path.join(HERE, scanner), tmp, '--json']
        else:
            cmd = [sys.executable, os.path.join(HERE, scanner),
                   '--src=' + tmp, '--json']
        # 不能 `except Exception: return None` 了事——这正是本仓库最痛恨的
        # 静默失败：第一版漏了 `import subprocess`，NameError 被吞成 None，
        # 于是每个样本都被当成「没跑起来」跳过，--cross 恒绿。
        # 变异测试（把 fp 改回带缺陷的版本）因此也不变红。
        # 跑不起来的要**说出来**，不计入「通过」。
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as e:
            print('  ! %s 执行异常：%s' % (scanner, e))
            return None
        if not (r.stdout or '').strip():
            print('  ! %s 无输出（stderr：%s）' % (scanner, (r.stderr or '')[:160]))
            return None
        try:
            d = json.loads(r.stdout or '[]')
        except ValueError:
            print('  ! %s 输出非 JSON：%s' % (scanner, (r.stdout or '')[:120]))
            return None
        items = d.get('items', []) if isinstance(d, dict) else d
        from collections import Counter
        c = Counter()
        for it in items:
            if isinstance(it, dict):
                rid = it.get('id') or it.get('pattern') or it.get('rule_id')
                if rid:
                    c[rid] += 1
        return c
    finally:
        shutil.rmtree(tmp, ignore_errors=True)



def cmd_comment_test():
    """注释化测试：把 tp 整段注释掉，必须零命中。

    抓的是一类很隐蔽的失效：**行扫描规则扫到了注释 / 文档字符串里的示例**。

    实测发现过程：用 scan-py 扫自己的 scripts/ 目录，53 条命中里混着
    K-44 命中「K-44 注释里写的 user.name=xxx 示例」、AR-05 命中
    「AR-05 文档字符串里的 ALL PASS 说明」—— 规则把**描述自己的文字**
    当成了被审代码。这类误报在 fixture 里测不出来（fixture 不会有
    「把规则说明抄进注释」这种形态），只有扫真实代码库才撞得到。

    做法：把每个 tp 的每一行加注释前缀再扫。若还有命中，说明该规则
    没做注释过滤。AST 驱动的规则天然不受影响（注释进不了 AST），
    所以只对行扫描规则有信号——这正是要抓的目标。
    """
    import shutil, tempfile
    reg = load()
    if reg is None:
        print('没有注册表')
        return 1
    meta = {r['rule_id']: r for r in reg['rules']}
    CM = {'.py': '# ', '.ts': '// ', '.js': '// ', '.tsx': '// ', '.jsx': '// ',
          '.gd': '# ', '.cs': '// '}
    SC = {'.py': 'scan-py.py', '.ts': 'scan-ts.py', '.js': 'scan-ts.py',
          '.tsx': 'scan-ts.py', '.jsx': 'scan-ts.py', '.gd': 'godot-audit.py',
          '.cs': 'godot-audit.py', '.rs': 'scan-rust.py', '.go': 'scan-go.py',
          '.java': 'scan-java.py', '.cpp': 'scan-cpp.py'}
    bad, tested = [], 0
    for rid in sorted(os.listdir(FIXDIR)):
        d = os.path.join(FIXDIR, rid)
        if not os.path.isdir(d):
            continue
        tps = [f for f in sorted(os.listdir(d))
               if re.fullmatch(r'tp\d*\.[A-Za-z0-9.]+', f)]
        tps = [f for f in tps if not f.endswith('.md')]
        if not tps:
            continue
        ext = os.path.splitext(tps[0])[1]
        if ext not in SC or ext not in CM:
            continue
        scanner = (meta.get(rid) or {}).get('scanner') or SC[ext]
        tmp = tempfile.mkdtemp()
        for f in tps:
            lines = open(os.path.join(d, f), encoding='utf-8').read().split('\n')
            pref = CM[ext]
            open(os.path.join(tmp, f), 'w', encoding='utf-8').write(
                '\n'.join(pref + l if l.strip() else l for l in lines))
        ok, hits, _err = _run_scanner(scanner, tmp, rid)
        shutil.rmtree(tmp, ignore_errors=True)
        tested += 1
        if hits:
            ids = sorted({str(h.get('id') or h.get('rule_id') or h.get('rule'))
                          for h in hits})
            bad.append((rid, ids))
    print('=' * 66)
    print('注释化测试（代码整段注释后应零命中）')
    print('=' * 66)
    print('  测试 TP 组数: %d' % tested)
    if bad:
        print()
        print('  ✗ 注释后仍命中 —— 规则没做注释过滤：')
        for rid, ids in bad:
            print('      %-12s %s' % (rid, ', '.join(ids)))
        print()
        print('  注释 / 文档字符串里描述规则的文字会被当成被审代码，')
        print('  扫真实代码库时表现为「报了一堆看不懂的命中」。')
        return 1
    print('  ✓ 全部 %d 组注释后零命中' % tested)
    return 0

def cmd_cross():
    """fixture 交叉审计：样本是否**真的在验证**它该验证的东西。

    --test 只查「tp 被自己命中 / fp 不被自己命中」，两个方向都有盲区：

      A. fp 被**别的**规则命中
         fp 是「正确写法」示例，会被人照抄。若它含真缺陷
         （如 RS-01 的 fp 自带路径穿越），文档价值直接变成负的。
      B. tp 没命中自己、却命中了别的
         该规则的「通过」是蹭来的，样本从没验证过它。

    两种都不影响 --test 的结论，所以长期没人发现——
    实测首次跑出 37 条 A（其中多条是「正确写法」自带的真漏洞）。
    """
    reg = load()
    if reg is None:
        print('没有注册表')
        return 1
    meta = {r['rule_id']: r for r in reg['rules']}
    bad_a, bad_b, bad_run = [], [], []
    for rid in sorted(os.listdir(FIXDIR)):
        if rid not in meta and not VARIANT_RX.match(rid):
            continue   # 人工判据条目（A-18 等）无对应机扫规则，同 --test
        d = os.path.join(FIXDIR, rid)
        if not os.path.isdir(d):
            continue
        m = meta.get(rid)
        scanner = (m or {}).get('scanner', 'scan-ts.py')
        native = (m or {}).get('native_id') or rid.split('-', 1)[-1]
        names = os.listdir(d)
        for kind in ('tp', 'fp'):
            samples = sorted(f for f in names
                             if re.fullmatch(kind + r'\d*\.[A-Za-z0-9.]+', f)
                             and os.path.isfile(os.path.join(d, f)))
            for smp in samples:
                hits = _scan_hits(scanner, os.path.join(d, smp))
                if hits is None:
                    bad_run.append('%s/%s' % (rid, smp))
                    continue
                own = hits.get(native, 0)
                others = {k: v for k, v in hits.items() if k != native}
                if kind == 'fp' and others:
                    bad_a.append((rid, smp, others))
                if kind == 'tp' and own == 0 and others:
                    bad_b.append((rid, smp, others))

    print('=' * 66)
    print('fixture 交叉审计')
    print('=' * 66)
    print()
    if bad_run:
        print('  ! %d 个样本没跑起来（**未计入**通过，别当成没问题）：%s'
              % (len(bad_run), ', '.join(bad_run[:6])))
        return 1
    if not bad_a and not bad_b:
        print('  ✓ fp 均未被任何规则命中（「正确写法」示例本身无缺陷）')
        print('  ✓ tp 均命中自己（没有蹭别条规则的通过）')
        return 0
    if bad_a:
        print('A. fp 被别的规则命中 —— 「正确写法」示例本身有缺陷：\n')
        for rid, smp, o in bad_a:
            print('   %-12s %-14s → %s' % (rid, smp, o))
        print('\n   → fp 会被人当参考照抄，含缺陷比没有更糟')
    if bad_b:
        print('\nB. tp 未命中自己、只命中别的 —— 通过是蹭来的：\n')
        for rid, smp, o in bad_b:
            print('   %-12s %-14s → %s' % (rid, smp, o))
        print('\n   → 这类样本从未验证过目标规则')
    return 1




# 「注册表里没有对应规则」的 fixture 目录。
# 必须显式列出：静默跳过会把两类真实欠账藏起来——
#   ① 判据条目（A-18 等）本就没有机扫规则（正常，需人工判据）
#   ② 规则改名/删除后 fixture 没清（真实遗留）
# 不区分的话，两者都表现为「没跑」，久了没人知道欠的是什么。
SKIPPED_NO_RULE = set()


def cmd_test():
    """跑 fixture：TP 必须命中、FP 必须不命中（实际执行扫描器，不是只看文件在不在）。"""
    if not os.path.isdir(FIXDIR):
        print('没有 fixtures 目录，跳过')
        return 0
    reg = load()
    if reg is None:
        print('没有注册表')
        return 1
    res = run_all_fixtures(reg)
    ok = fail = errs = 0
    for rid in sorted(res):
        r = res[rid]
        for kind in ('tp', 'fp'):
            v = r[kind]
            if v is None:
                continue
            ok += 1 if v else 0
            fail += 0 if v else 1
        errs += len(r['errors'])
    # 未覆盖要**按 rule_id 逐项核对**，不能用「规则数 − 目录数」相减。
    # 相减法会被变体目录骗到：TS-D02-dts/long/regex 三个额外样本目录
    # 会被当成 3 条独立规则计入 total，正好抵掉 CC-15/CC-18 两条真实缺口，
    # 于是报「未覆盖 0」——而实际有 2 条规则一条样本都没有。
    # 聚合数字代替逐项核对，正是本技能反复出现的失效形态。
    have_fx = set()
    if os.path.isdir(FIXDIR):
        for rid in os.listdir(FIXDIR):
            d = os.path.join(FIXDIR, rid)
            if not os.path.isdir(d):
                continue
            names = os.listdir(d)
            if (any(f.startswith('tp.') for f in names) or 'tp.d' in names
                    or any(f.startswith('fp.') for f in names)
                    or 'fp.d' in names):
                have_fx.add(rid)
                # 变体目录归到基规则名下
                vb = VARIANT_RX.match(rid)
                if vb and vb.group('base') not in have_fx:
                    have_fx.add(vb.group('base'))
    uncovered = sorted(r['rule_id'] for r in reg['rules']
                       if r['rule_id'] not in have_fx)
    print('\nfixture 实测：通过 %d · 失败 %d · 未覆盖规则 %d'
          % (ok, fail, len(uncovered)))
    if uncovered:
        print('  ▲ 无 tp 也无 fp 样本：%s' % ', '.join(uncovered[:12]))
        if len(uncovered) > 12:
            print('    …共 %d 条' % len(uncovered))
        print('    → 加规则请配样本，否则自检对它等于没跑')
    if errs:
        print('  ! 另有 %d 项因扫描器执行失败**未计入**（已排除，勿当作「无问题」）'
              % errs)
    # 跳过的目录必须显式列出：静默跳过等于把「判据条目没机扫规则」和
    # 「规则删了 fixture 没清」这两种真实欠账藏起来。
    if SKIPPED_NO_RULE:
        print('  - %d 个 fixture 目录在注册表里没有对应规则，已跳过机扫：'
              % len(SKIPPED_NO_RULE))
        print('    %s' % ' '.join(sorted(SKIPPED_NO_RULE)))
        # 区分「人工判据」与「改名残留」：前者正常，后者是真欠账。
        # 不区分的话两者都表现为「没跑」，久了没人知道欠的是什么。
        _idx = set()
        try:
            _d = json.load(open(os.path.join(SKILL, 'rules', 'items.json'),
                                encoding='utf-8'))
            _idx = {i['id'] for i in _d.get('items', [])}
        except (OSError, ValueError):
            pass
        legit = sorted(x for x in SKIPPED_NO_RULE if x in _idx)
        stale = sorted(x for x in SKIPPED_NO_RULE if x not in _idx)
        if legit:
            print('    人工判据（正常，需人看而非机扫）：%s' % ' '.join(legit[:20]))
            if len(legit) > 20:
                print('      …共 %d 个' % len(legit))
        if stale:
            print('    ▲ 判据库里也查不到（改名/删除后的残留，请清理）：%s'
                  % ' '.join(stale[:20]))
    return 1 if (fail or errs) else 0


def _rule_sig(r):
    """规则判据签名：判据变了，之前的实测结论就不该继承。"""
    return hashlib.md5(('%s|%s|%s' % (r.get('native_id'), r.get('level'),
                                      r.get('title'))).encode('utf-8')
                       ).hexdigest()[:8]


def _eval_of(rec):
    """fixture 结果 → eval 字段。

    recall    ← TP 命中能力（抓不抓得到真问题）
    precision ← FP 拒绝能力（会不会误伤）
    没有对应样本就是 unverified，绝不写成 pass。
    """
    ev = {'precision': 'unverified', 'recall': 'unverified'}
    if rec.get('tp') is not None:
        ev['recall'] = 'pass' if rec['tp'] else 'fail'
    if rec.get('fp') is not None:
        ev['precision'] = 'pass' if rec['fp'] else 'fail'
    ev['verified_at'] = datetime.date.today().isoformat()
    ev['sig'] = rec.get('sig')
    return ev


def cmd_eval():
    """跑 fixture 并把结论回填到注册表的 eval 字段。

    为什么需要：eval 默认全 unverified，131 条里没有一条能区分
    「实测有效」与「从没验证过」——字段形同虚设。跑完这一轮，
    哪条规则敢信就有据可查了。
    """
    reg = load()
    if reg is None:
        print('没有注册表，先跑 --sync')
        return 1
    res = run_all_fixtures(reg, verbose=False)
    n_pass = n_fail = n_unv = 0
    for r in reg['rules']:
        rid = r['rule_id']
        rec = res.get(rid)
        if rec is None:
            r['eval'] = {'precision': 'unverified', 'recall': 'unverified',
                         'verified_at': None, 'sig': _rule_sig(r)}
            n_unv += 1
            continue
        rec['sig'] = _rule_sig(r)
        ev = _eval_of(rec)
        r['eval'] = ev
        if 'unverified' in (ev['precision'], ev['recall']):
            n_unv += 1
        elif ev['precision'] == 'pass' and ev['recall'] == 'pass':
            n_pass += 1
        else:
            n_fail += 1
    json.dump(reg, open(REG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('eval 已回填 → rules/registry.json')
    print('  实测通过 %d · 实测有问题 %d · 仍为 unverified %d'
          % (n_pass, n_fail, n_unv))
    if n_fail:
        print('  ✗ 有规则实测不通过，别把 fail 当 unverified 用')
    return 1 if n_fail else 0


def main():
    if '--sync' in _flags:
        sys.exit(cmd_sync())
    if '--test' in _flags:
        sys.exit(cmd_test())
    if '--eval' in _flags:
        sys.exit(cmd_eval())
    if '--check' in _flags:
        sys.exit(cmd_check())
    if '--map' in _flags:
        sys.exit(cmd_map(apply='--apply' in _flags))
    if '--gaps' in _flags:
        sys.exit(cmd_gaps())
    if '--scanners' in _flags:
        sys.exit(cmd_scanners())
    if '--comment-test' in _flags:
        sys.exit(cmd_comment_test())
    if '--cross' in _flags:
        sys.exit(cmd_cross())

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
