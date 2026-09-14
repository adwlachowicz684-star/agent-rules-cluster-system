#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tool-scan.py —— 工具型应用缺陷模式扫描（52 条中的 28 条可机扫）

模式库来源：对 Nexus Panel（Tauri 2 + 双栈插件面板，5.26 万行）全量审查聚类。
目的：把「整机审查该查什么」变成可执行的检查，在人工精审前先机器过一遍。

用法：
    python3 tool-scan.py --src=<源码根>                 # 扫全部模块
    python3 tool-scan.py --src=<根> js plugins src      # 只扫指定模块
    python3 tool-scan.py --src=<根> --p0                # 只显示致命级
    python3 tool-scan.py --src=<根> --pattern=D01       # 按族或按 ID 过滤
    python3 tool-scan.py --src=<根> --json              # 机器可读
    python3 tool-scan.py --src=<根> --flat              # 扁平结构（不分模块）
    python3 tool-scan.py --self-test                    # 注入故障自检（28/28）

产出的是**候选**，不是结论。每条都要经 references/pattern-detection.md 的
「确认」一栏过滤：先读上方注释（排除设计意图），再想清后果。
"""

import os
import re
import sys
import json
import shutil
import tempfile

_args = [a for a in sys.argv[1:] if not a.startswith('--')]
_flags = [a for a in sys.argv[1:] if a.startswith('--')]

SRC = None
for f in _flags:
    if f.startswith('--src='):
        SRC = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
PAT_FILTER = None
for f in _flags:
    if f.startswith('--pattern='):
        PAT_FILTER = f.split('=', 1)[1].upper()

if '--self-test' not in _flags:
    if SRC is None:
        for cand in ('src', '.'):
            if os.path.isdir(cand):
                SRC = os.path.abspath(cand)
                break
    if SRC is None or not os.path.isdir(SRC):
        print('找不到源码目录，请用 --src=<路径> 指定')
        sys.exit(1)

FLAT = '--flat' in _flags
P0_ONLY = '--p0' in _flags
AS_JSON = '--json' in _flags

SKIP_DIRS = {'node_modules', 'dist', 'build', 'target', 'vendor', 'third_party',
             '.git', '.idea', '.vscode', '__pycache__', 'coverage', 'audit',
             'docs', 'examples', 'bin', 'obj', '.next', '.cache'}
SKIP_SUFFIX = ('.min.js', '.bundle.js', '.map', '.lock')
SOURCE_EXT = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rs', '.html')
MAX_FILE_BYTES = 600 * 1024
PLUGIN_DIR_HINTS = ('plugins', 'extensions', 'addons', 'modules', 'widgets')

# ---------------------------------------------------------------- 注释剥离
def strip_comments(src):
    """剥离 // 与 /* */，保持行数与每行长度守恒（行号才不会错位）。

    必须能识别字符串：否则 "https://x" 会被当成注释切掉，
    也会让模式在字符串里误命中。
    """
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith('/*', i):
            j = src.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append('\n' * src.count('\n', i, j))
            i = j
        elif src.startswith('//', i):
            j = src.find('\n', i)
            j = n if j < 0 else j
            out.append(' ' * (j - i))
            i = j
        elif src[i] in '"\'`':
            q, k = src[i], i + 1
            while k < n:
                if src[k] == '\\':
                    k += 2
                    continue
                if src[k] == q:
                    k += 1
                    break
                if src[k] == '\n' and q != '`':
                    break
                k += 1
            out.append(src[i:k])
            i = k
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


# ---------------------------------------------------------------- 模式定义
# LINE: (id, level, name, langs, regex, guard)  guard = {'absent':rx} | {'present':rx}
LINE_PATTERNS = [
    ('J01', 'P1', 'message 监听未校验来源', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'),
     r'addEventListener\(\s*[\'"]message[\'"]',
     {'absent': r'\b(?:e|ev|evt|event|d)\.(?:source|origin)', 'window': 40}),
    ('J02', 'P1', '动态成员调用（桥接/分发无白名单）', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs', 'rs'),
     r'\b(?:mod|module|ns|api|obj|target|handlers|exports)\s*\[\s*[A-Za-z_$][\w$]*\s*\]\s*\(', None),
    ('J03', 'P1', "postMessage 目标 origin 通配", ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'),
     r'postMessage\s*\([^;]{0,200}?,\s*[\'"]\*[\'"]\s*\)', None),
    ('J04', 'P2', '存储反序列化无兜底', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'),
     r'JSON\.parse\(\s*(?:localStorage|window\.localStorage|raw|saved|stored|text)\b', None),
    ('J06', 'P2', '能力探测一次性缓存降级', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'),
     r'if\s*\(\s*(\w+)\s*!==\s*undefined\s*\)\s*return\s*\1', None),
    ('R01', 'P1', '整文件读入后才截断（上限形同虚设）', ('rs',),
     r'\b(?:std::fs::read|fs::read|read_to_string)\s*\(',
     {'present': r'\.\s*min\s*\(', 'window': 25}),
    ('R02', 'P1', 'lock().unwrap()（配 panic=abort 即崩溃）', ('rs',),
     r'\.lock\(\)\s*\.\s*unwrap\(\)', None),
    ('R03', 'P0', '按声明长度分配缓冲（无上限）', ('rs',),
     r'vec!\[[^\]]{0,40};\s*\w*(?:len|size|length)\w*\s*\]', None),
    ('R05', 'P1', '路径黑名单字符串比较（可 ../ 绕过）', ('rs',),
     r'(?:FORBIDDEN|BLOCKED|DENY|BLACK)[A-Z_]*\s*:\s*&\[', {'absent': r'canonicalize', 'window': 10 ** 6}),
    ('R06', 'P0', '命令执行（shell 解析 / 可执行文件来自变量）', ('rs',),
     r'Command::new\(\s*(?:"cmd"|"sh"|"bash"|"powershell"|[a-z_][\w.]*)\s*\)', None),
    ('R07', 'P1', 'thread::sleep 轮询 / 连接循环内 spawn', ('rs',),
     r'thread::(?:sleep|spawn)\s*\(', None),
    ('R09', 'P0', '空凭据即放行', ('rs', 'ts', 'tsx', 'js', 'jsx'),
     r'if\s+\w*(?:token|secret|pass|key|auth|pwd)\w*\.is_empty\(\)\s*\{\s*return\s+true', None),
    ('R10', 'P2', 'rename 无跨设备回退', ('rs',),
     r'::rename\s*\(', None),
]
COMPILED_LINE = [(p[0], p[1], p[2], p[3], re.compile(p[4]),
                  ({k: (re.compile(v) if k != 'window' else v)
                    for k, v in p[5].items()} if p[5] else None))
                 for p in LINE_PATTERNS]

# FILE: (id, level, name, langs, fn(path, text, stripped) -> [Finding])
def _f_j05(path, text, st):
    """注册与注销的 handler 引用不一致"""
    out = []
    adds = re.findall(r'addEventListener\s*\(\s*([^,]{1,60}?)\s*,\s*([^,)]{1,60})', st)
    removes = re.findall(r'removeEventListener\s*\(\s*([^,]{1,60}?)\s*,\s*([^,)]{1,60})', st)
    add_map = {}
    for ev, h in adds:
        add_map.setdefault(ev.strip(), set()).add(h.strip())
    for ev, h in removes:
        h, ev = h.strip(), ev.strip()
        if ev not in add_map:
            continue
        if re.fullmatch(r'[A-Za-z_$][\w.$]*', h) and h not in add_map[ev]:
            if any(not re.fullmatch(r'[A-Za-z_$][\w.$]*', a) for a in add_map[ev]):
                out.append((0, 'addEventListener 与 removeEventListener 的 handler 引用不一致：%s' % h))
    return out

def _f_j07(path, text, st):
    if not any('/%s/' % d in path.replace('\\', '/') for d in PLUGIN_DIR_HINTS):
        return []
    out = []
    for m in re.finditer(r"from\s+['\"]@tauri-apps/|__TAURI_INTERNALS__|window\.parent\s*[.\[]|parent\.document", st):
        out.append((st[:m.start()].count('\n') + 1, m.group(0)[:60]))
    return out

def _f_j08(path, text, st):
    if not any('/%s/' % d in path.replace('\\', '/') for d in PLUGIN_DIR_HINTS):
        return []
    return [(st[:m.start()].count('\n') + 1, m.group(0))
            for m in re.finditer(r'window\.__[A-Z][A-Z0-9_]*', st)]

def _f_j09(path, text, st):
    has_add = re.search(r'addEventListener\s*\(', st)
    if not has_add:
        return []
    if not re.search(r'removeEventListener\s*\(', st):
        return [(st[:has_add.start()].count('\n') + 1, '只注册不注销（无 removeEventListener）')]
    return []

def _f_j10(path, text, st):
    m = re.search(r'setInterval\s*\(', st)
    if m and not re.search(r'clearInterval\s*\(', st):
        return [(st[:m.start()].count('\n') + 1, 'setInterval 无 clearInterval')]
    return []

def _f_j11(path, text, st):
    m = re.search(r'createObjectURL\s*\(', st)
    if m and not re.search(r'revokeObjectURL\s*\(', st):
        return [(st[:m.start()].count('\n') + 1, 'createObjectURL 无 revokeObjectURL')]
    return []

def _f_j12(path, text, st):
    out = []
    for m in re.finditer(r'\.innerHTML\s*=\s*[^;\n]*(\$\{|[\'"]\s*\+|\+\s*[A-Za-z_$])', st):
        out.append((st[:m.start()].count('\n') + 1, 'innerHTML 拼接变量'))
    return out

def _f_r04(path, text, st):
    if re.search(r'\.is_dir\(\)', st) and re.search(r'fs::(?:copy|create_dir_all)', st) \
            and not re.search(r'symlink_metadata', st):
        m = re.search(r'\.is_dir\(\)', st)
        return [(st[:m.start()].count('\n') + 1, '递归遍历/拷贝未识别符号链接')]
    return []

FILE_PATTERNS = [
    ('J05', 'P2', '事件解绑引用可能不一致', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), _f_j05),
    ('J07', 'P1', '扩展层直连底层 API（隔离后静默失效）', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), _f_j07),
    ('J08', 'P1', '扩展读取宿主全局单例（沙箱内取不到）', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), _f_j08),
    ('J09', 'P1', '只注册不注销', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), _f_j09),
    ('J10', 'P1', 'setInterval 无清理', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), _f_j10),
    ('J11', 'P2', 'objectURL 未释放', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), _f_j11),
    ('J12', 'P1', 'innerHTML 拼接变量', ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), _f_j12),
    ('R04', 'P1', '递归遍历未识别符号链接', ('rs',), _f_r04),
]


# ---------------------------------------------------------------- 项目级检查
def _p_duplicate_consts(files_by_ext, root, all_text):
    """J13 同名常量清单重复定义"""
    out = []
    seen = {}
    for path in files_by_ext.get(('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs'), []):
        try:
            t = open(path, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        seg = os.path.relpath(path, root).replace('\\', '/').split('/')
        # plugins/<id>/... 这类要按二级目录划区，否则不同插件的同名常量会互相误判
        area = '/'.join(seg[:2]) if (len(seg) > 1 and seg[0] in
                                     ('plugins', 'extensions', 'packages', 'apps', 'src')) else seg[0]
        for m in re.finditer(r'export\s+const\s+([A-Z][A-Z0-9_]{2,})\s*=\s*([^;]{0,600})', t):
            val = re.sub(r'\s+', '', m.group(2))
            seen.setdefault((area, m.group(1)), {}).setdefault(val, []).append(path)
    for (area, name), variants in seen.items():
        # 同一区域内出现 ≥2 种不同取值 = 真分叉（不同插件各自定义同名常量是常态，不算）
        if len(variants) < 2:
            continue
        for val, paths in variants.items():
            for pth in sorted(set(paths)):
                out.append(('J13', 'P1', '同名常量清单在同区域内多处定义且内容已分叉：%s' % name, pth, 1))
    return out

def _p_rust_orphan(files_by_ext, root, all_text):
    """R08 未被 mod 声明的 .rs 文件"""
    rs = files_by_ext.get(('rs',), [])
    if not rs:
        return []
    by_path = {os.path.abspath(p): p for p in rs}
    roots = [p for p in rs if os.path.basename(p) in ('main.rs', 'lib.rs')]
    if not roots:
        return []
    seen, stack = set(), [os.path.abspath(p) for p in roots]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_path:
            continue
        seen.add(cur)
        try:
            t = open(cur, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        base = os.path.dirname(cur)
        for m in re.finditer(r'(?:pub\s+)?mod\s+([a-z_][a-z0-9_]*)\s*;', t):
            for cand in (os.path.join(base, m.group(1) + '.rs'),
                         os.path.join(base, m.group(1), 'mod.rs')):
                if os.path.isfile(cand):
                    stack.append(os.path.abspath(cand))
    out = []
    for p in rs:
        ap = os.path.abspath(p)
        # build.rs 是 Cargo 约定的构建脚本，本就不该被 mod 声明
        if ap not in seen and os.path.basename(p) != 'build.rs':
            out.append(('R08', 'P2', '未被 mod 声明的孤儿 .rs 文件', p, 1))
    return out

def _p_js_orphan(files_by_ext, root, all_text):
    """P02 疑似孤儿源文件（无任何 import / 入口引用）"""
    exts = ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs')
    files = files_by_ext.get(exts, [])
    out = []
    for p in files:
        fn = os.path.basename(p)
        base = os.path.splitext(fn)[0]
        if base in ('index', 'main', 'App', 'mod'):
            continue
        if len(base) < 4:
            continue
        # 测试 / 探针 / 类型声明 / 配置：本就无人 import，不是孤儿
        if re.search(r'(?:\.d\.ts$|\.test\.|\.spec\.|^test|^probe|\.mjs$)', fn):
            continue
        if re.search(r'(?:^|/)(?:tests?|__tests__|audit|mocks?)/', os.path.relpath(p, root)):
            continue
        if re.search(r'(?:^|/)[\w.-]*config[\w.-]*\.(?:ts|js|mjs|json)$', fn) or fn.startswith('tsconfig'):
            continue
        # 只数**别的文件**里的引用次数（含自身会把「仅被引用 1 次」误判成孤儿）
        n = sum(len(re.findall(re.escape(base), t))
                for q, t in TEXT_BY_FILE.items() if q != p)
        if n == 0:
            out.append(('P02', 'P2', '疑似孤儿源文件（无任何 import / 入口引用）', p, 1))
    return out

def _p_ignore(files_by_ext, root, all_text):
    """P01 忽略清单缺常见项"""
    out = []
    for name in ('.gitignore', '.tauraignore', '.npmignore', '.dockerignore'):
        fp = os.path.join(root, name)
        if not os.path.isfile(fp):
            continue
        t = open(fp, encoding='utf-8', errors='replace').read()
        miss = [d for d in ('node_modules', 'dist', 'target', '__pycache__', '.DS_Store')
                if d not in t]
        if miss:
            out.append(('P01', 'P2', '%s 缺忽略项：%s' % (name, ', '.join(miss)), fp, 1))
    return out

def _p_ci(files_by_ext, root, all_text):
    """P03 有 lint/test 脚本但无 CI"""
    pkg = os.path.join(root, 'package.json')
    if not os.path.isfile(pkg):
        return []
    try:
        d = json.load(open(pkg, encoding='utf-8'))
    except (OSError, ValueError):
        return []
    scripts = d.get('scripts', {}) or {}
    has_check = [k for k in scripts if re.search(r'test|lint|typecheck|check', k, re.I)]
    ci_dirs = [os.path.join(root, '.github', 'workflows'),
               os.path.join(root, '.gitlab-ci.yml'), os.path.join(root, 'Jenkinsfile')]
    if has_check and not any(os.path.exists(c) for c in ci_dirs):
        return [('P03', 'P2', '存在 %d 个校验脚本但无 CI 配置（%s）'
                 % (len(has_check), ', '.join(has_check[:4])), pkg, 1)]
    return []

def _p_csp(files_by_ext, root, all_text):
    """P04 多个 HTML 入口但 CSP 只覆盖其一"""
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if os.path.relpath(dirpath, root) not in ('.', ''):
            continue
        for fn in filenames:
            if fn.endswith('.html'):
                entries.append(os.path.join(dirpath, fn))
    if len(entries) < 2:
        return []
    has, lack = [], []
    for e in entries:
        t = open(e, encoding='utf-8', errors='replace').read()
        (has if 'Content-Security-Policy' in t else lack).append(e)
    if has and lack:
        return [('P04', 'P0', '共 %d 个入口 HTML，其中 %d 个无 CSP：%s'
                 % (len(entries), len(lack), ', '.join(os.path.basename(x) for x in lack)),
                 os.path.dirname(lack[0]) or root, 1)]
    return []

def _p_multiconf(files_by_ext, root, all_text):
    """P05 多份构建配置（合并语义待确认）"""
    pkg = os.path.join(root, 'package.json')
    if not os.path.isfile(pkg):
        return []
    t = open(pkg, encoding='utf-8', errors='replace').read()
    hits = re.findall(r'--config\s+([^\s"\']+)', t)
    if hits:
        return [('P05', 'P1', '构建使用了额外配置 %s（合并而非替换，安全项覆盖关系需确认）'
                 % ', '.join(sorted(set(hits))), pkg, 1)]
    return []

PROJECT_CHECKS = [_p_duplicate_consts, _p_rust_orphan, _p_js_orphan,
                  _p_ignore, _p_ci, _p_csp, _p_multiconf]


# ---------------------------------------------------------------- 扫描
def lang_of(path):
    ext = os.path.splitext(path)[1].lower()
    return ext[1:] if ext else ''

def module_of(path):
    rel = os.path.relpath(path, SRC)
    parts = rel.replace('\\', '/').split('/')
    return parts[0] if len(parts) > 1 else '(root)'

def collect(root, only=None):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn.endswith(SKIP_SUFFIX) or fn.startswith('.'):
                continue
            if not fn.lower().endswith(SOURCE_EXT):
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if only and module_of(p) not in only:
                continue
            out.append(p)
    return sorted(out)

def scan(root, only=None):
    files = collect(root, only)
    findings = []
    JS_EXT = ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs')
    joined = {JS_EXT: [], ('rs',): []}
    for p in files:
        lg = lang_of(p)
        if lg in JS_EXT:
            joined[JS_EXT].append(p)
        elif lg == 'rs':
            joined[('rs',)].append(p)

    for p in files:
        lg = lang_of(p)
        try:
            raw = open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        st = strip_comments(raw) if lg in ('ts', 'tsx', 'js', 'jsx', 'mjs', 'cjs', 'rs') else raw
        lines = st.split('\n')
        for pid, lvl, name, langs, rx, guard in COMPILED_LINE:
            if lg not in langs or (PAT_FILTER and not (pid.startswith(PAT_FILTER) or PAT_FILTER in pid)):
                continue
            for m in rx.finditer(st):
                ln = st[:m.start()].count('\n') + 1
                if guard:
                    w = guard.get('window', 20)
                    ctx = '\n'.join(lines[max(0, ln - w): ln + w])
                    if 'absent' in guard and guard['absent'].search(ctx):
                        continue
                    if 'present' in guard and not guard['present'].search(ctx):
                        continue
                findings.append((pid, lvl, name, p, ln, m.group(0)[:70].replace('\n', ' ')))
        for pid, lvl, name, langs, fn in FILE_PATTERNS:
            if lg not in langs or (PAT_FILTER and not (pid.startswith(PAT_FILTER) or PAT_FILTER in pid)):
                continue
            for ln, snip in fn(p, raw, st):
                findings.append((pid, lvl, name, p, ln, snip[:70]))

    TEXT_BY_FILE = {}
    for p in files:
        try:
            if os.path.getsize(p) < 200 * 1024:
                TEXT_BY_FILE[p] = open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            pass
    globals()['TEXT_BY_FILE'] = TEXT_BY_FILE
    all_text = '\n'.join(TEXT_BY_FILE.values())
    for chk in PROJECT_CHECKS:
        for pid, lvl, name, pth, ln in chk(joined, root, all_text):
            if PAT_FILTER and not pid.startswith(PAT_FILTER):
                continue
            findings.append((pid, lvl, name, pth, ln, ''))
    return files, findings


def render(root, files, findings):
    if P0_ONLY:
        findings = [f for f in findings if f[1] == 'P0']
    findings.sort(key=lambda f: (f[1], f[0], f[3]))
    mods = sorted({module_of(p) for p in files})
    print('tool-scan · 工具型应用缺陷模式扫描')
    print('源码根: %s' % root)
    print('模块: %d   文件: %d   命中候选: %d' % (len(mods), len(files), len(findings)))
    if not findings:
        print('\n（无命中。若可疑，先跑 --self-test 确认模式未失效）')
        return
    print('\n按模式聚合：')
    agg = {}
    for f in findings:
        agg.setdefault((f[1], f[0], f[2]), []).append(f)
    for (lvl, pid, name), items in sorted(agg.items()):
        print('  [%s] %s %s — %d 处' % (lvl, pid, name, len(items)))
    print('\n明细：')
    cur = None
    for pid, lvl, name, p, ln, snip in findings:
        m = '(root)' if FLAT else module_of(p)
        if m != cur:
            print('\n── %s ──────────────' % m)
            cur = m
        rel = os.path.relpath(p, root)
        print('  [%s] %s  %s:%s' % (lvl, pid, rel, ln))
        if snip:
            print('        %s' % snip)
    print('\n候选 ≠ 结论。逐条过 references/pattern-detection.md 的「确认」栏：')
    print('  1) 读上方注释（排除设计意图） 2) 想清后果 3) 批量族抽样后合并报')


# ---------------------------------------------------------------- 自检
SELF_FILES = {
    'index.html': '<html><head><meta http-equiv="Content-Security-Policy" content="default-src \'self\'"></head><body></body></html>',
    'index.react.html': '<html><body><div id="root"></div></body></html>',
    '.gitignore': 'nothing\n',
    'package.json': json.dumps({'scripts': {'test': 'node t.js', 'typecheck': 'tsc'},
                                'tauri:dev': 'tauri dev --config src-tauri/tauri.vite.conf.json'}),
    'js/a.js': "export const THEME_VARS = ['--bg'];\n"
               "window.addEventListener('message', (e) => { const d = e.data; });\n"
               "const r = JSON.parse(localStorage.getItem('k'));\n"
               "if (_cache !== undefined) return _cache;\n"
               "setInterval(() => {}, 100);\n"
               "el.innerHTML = '<b>' + name + '</b>';\n"
               "window.addEventListener('keydown', (e) => {});\n"
               "const u = URL.createObjectURL(blob);\n"
               "parent.postMessage({a:1}, '*');\n"
               "mod[method](args);\n",
    'js/b.js': "export const THEME_VARS = ['--bg','--text'];\n"
               "window.addEventListener('evt', (e) => fn(e));\n"
               "window.removeEventListener('evt', fn);\n",
    'plugins/foo/x.ts': "import { invoke } from '@tauri-apps/api/core';\n"
                        "const p = window.__NEXUS__?.getPlugins?.();\n",
    'plugins/foo/OrphanPanel.tsx': "export default function OrphanPanel() { return null; }\n",
    'src-tauri/src/main.rs': "fn main() { let a = 1; }\nmod fpx;\n",
    'src-tauri/src/dead.rs': "pub fn never_called() {}\n",
    'src-tauri/src/serv.rs': "let mut buf = vec![0u8; content_len];\n"
                             "if token.is_empty() { return true; }\n"
                             "let m = state.0.lock().unwrap();\n"
                             "let b = std::fs::read(p)?;\nlet t = &b[..b.len().min(cap)];\n"
                             "std::fs::rename(a, b)?;\n"
                             "Command::new(exe).args(args).spawn();\n"
                             "thread::sleep(Duration::from_millis(100));\n"
                             "thread::spawn(move || {});\n"
                             "const FORBIDDEN_DELETE: &[&str] = &[\"/etc\"];\n"
                             "fn copy_all(s: &Path) { if s.is_dir() { std::fs::copy(s, d)?; } }\n",
}

def self_test():
    # 行数守恒
    sample = "let a = 1; // 注释\n/* 块\n注释 */\nlet s = \"https://x//y\";\n"
    assert strip_comments(sample).count('\n') == sample.count('\n'), '行数不守恒'
    assert 'https://x//y' in strip_comments(sample), '字符串内的 // 被误剥'
    print('✓ 行数守恒 + 字符串保护')

    tmp = tempfile.mkdtemp(prefix='tool-scan-self-')
    try:
        for rel, content in SELF_FILES.items():
            fp = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, 'w', encoding='utf-8').write(content)
        global SRC
        SRC = tmp
        files, findings = scan(tmp, None)
        hit = {f[0] for f in findings}
        expect = ['J01', 'J02', 'J03', 'J04', 'J05', 'J06', 'J07', 'J08', 'J09',
                  'J10', 'J11', 'J12', 'J13',
                  'R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10',
                  'P01', 'P02', 'P03', 'P04', 'P05']
        miss = [e for e in expect if e not in hit]
        for e in expect:
            print('  %s %s' % ('✓' if e in hit else '✗', e))
        if miss:
            print('\n未检出：%s（%d/%d）' % (', '.join(miss), len(expect) - len(miss), len(expect)))
            return 1
        print('\n自检通过：%d/%d 条模式均可检出' % (len(expect), len(expect)))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if '--self-test' in _flags:
        sys.exit(self_test())
    files, findings = scan(SRC, set(_args) if _args else None)
    if AS_JSON:
        print(json.dumps([{'id': f[0], 'level': f[1], 'name': f[2],
                           'file': os.path.relpath(f[3], SRC), 'line': f[4],
                           'snippet': f[5]} for f in findings],
                         ensure_ascii=False, indent=1))
    else:
        render(SRC, files, findings)


if __name__ == '__main__':
    main()
