#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
route.py —— 代码审查场景路由（精确辅助，非结论）

做什么：按**确定性信号**扫一遍仓库，输出「可能命中哪些风险场景 + 证据」。
不做什么：不替你下结论。输出必须经人工审核——可以剔、可以补、可以改优先级。

为什么要有它：AI 靠"这项目像有插件"是猜，脚本扫到 plugins/ 是事实。
脚本按目录/文件/正则机械扫一遍不会漏，人负责判断这些信号对不对。

信号分三级：
    [结构]  目录/文件/构建配置      —— 几乎不会错，直接采信
    [特征]  正则命中代码            —— 有命中即相关，但要看密度
    [文档]  README / 配置里的关键词  —— 弱信号，仅作提示

用法：
    python3 route.py --src=<根>
    python3 route.py --src=<根> --json
    python3 route.py --src=<根> --all          # 列出全部场景（含未命中）
    python3 route.py --src=<根> --min-hits=2   # 提高命中门槛（默认 1）
    python3 route.py --src=<根> --batch=6      # 每批加载数（默认 4）

输出示例：
    sandbox   [结构] plugins/(8) src-tauri/
              [特征] createObjectURL×3
    boundary  [特征] postMessage×12 addEventListener('message')×5
    ---
    命中 7 个 —— 全部都要审，分 2 批加载（每批 ≤4）

设计要点：**不设命中上限**。截断会漏检——大项目命中 10+ 是正常的。
改为分批：一批审完再加载下一批，既不漏又能保证每批读得深。
"""

import os
import re
import sys
import json

_args = [a for a in sys.argv[1:] if not a.startswith('--')]
_flags = [a for a in sys.argv[1:] if a.startswith('--')]

ROOT = None
for f in _flags:
    if f.startswith('--src='):
        ROOT = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
if ROOT is None:
    ROOT = os.path.abspath('.')
AS_JSON = '--json' in _flags
SHOW_ALL = '--all' in _flags
MIN_HITS = 1
BATCH = 4
for f in _flags:
    if f.startswith('--min-hits='):
        MIN_HITS = int(f.split('=', 1)[1])
    if f.startswith('--batch='):
        BATCH = int(f.split('=', 1)[1])

SKIP_DIRS = {'node_modules', 'dist', 'build', 'target', 'vendor', 'third_party',
             '.git', '.idea', '.vscode', '__pycache__', 'coverage', 'audit',
             '.next', '.cache', 'bin', 'obj'}
SOURCE_EXT = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rs', '.py',
              '.go', '.cpp', '.cc', '.c', '.h', '.java', '.kt', '.cs')
MAX_BYTES = 600 * 1024
SCAN_LIMIT = 400          # 超过这个文件数就抽样，避免大仓库卡住

# ---------------------------------------------------------------- 场景定义
# signals: (信号类型, 判据, 展示名)
SCENES = [
    ('s-numerics', '数值与边界', 'P0 密度最高的一类，TS/JS 库几乎必中',
     [('dir', None, None),
      ('rx', r'\b(?:clamp|clamp01|Math\.max|Math\.min)\s*\(', 'clamp'),
      ('rx', r'\bfor\s*\(\s*let\s+i\s*=\s*\w+\s*;\s*i\s*<\s*[A-Za-z_]', '循环上界非字面量'),
      ('rx', r'\bwhile\s*\(', 'while'),
      ('rx', r'Number\.isFinite|isNaN', '有限性校验'),
      ('rx', r'(?:Math\.)?(?:PI|sin|cos|atan2|sqrt|pow|hypot)\b', '浮点运算'),
      ('rx', r'>>>\s*0|\|\s*0\b', '位运算取整'),
      ('rx', r'(?:/\s*\w+\s*|\*\s*\w+)\s*[;,)]', '除法/乘法')]),
    ('s-structures', '数据结构与内存', 'TypedArray / 对象池 / 分桶 / 裸对象查表',
     [('rx', r'new\s+(?:Float\d+Array|Uint\d+Array|Int\d+Array|ArrayBuffer)\s*\(', 'TypedArray'),
      ('rx', r'\b(?:prewarm|acquire|release)\s*\(|objectPool|ObjectPool', '对象池'),
      ('rx', r'new\s+Map\s*\(\s*\)', '分桶 Map'),
      ('rx', r'\b\w+\s*\[\s*\w*\s*\]\s*[+\-]?=', '裸对象查表'),
      ('rx', r'\.(?:split|join)\s*\(\s*[\'"]\.', '路径/复合 key'),
      ('rx', r'Object\.assign\s*\(|\.\.\.\w+', '对象合并')]),
    ('s-lifecycle', '生命周期与资源', '订阅 / 定时器 / 句柄 / 每帧回调',
     [('rx', r'addEventListener\s*\(|\.on\s*\(\s*[\'"]|subscribe\s*\(', '订阅'),
      ('rx', r'setInterval\s*\(|setTimeout\s*\(|schedule\s*\(', '定时器'),
      ('rx', r'createObjectURL\s*\(', 'objectURL'),
      ('rx', r'\b(?:update|tick|lateUpdate|onFrame)\s*\(', '每帧回调'),
      ('rx', r'\b(?:dispose|destroy|release|close|disconnect)\s*\(', '释放')]),
    ('s-contracts', '契约与承诺', '对外 API / 接口声明 / 文档承诺',
     [('file', 'README.md', 'README'),
      ('rx', r'\bexport\s+(?:interface|type|class|function|const)', '对外导出'),
      ('rx', r'@param|@returns|\* @', 'JSDoc'),
      ('dir', 'docs', 'docs 目录')]),
    ('s-state', '状态与配置', 'store / 序列化 / 快照',
     [('rx', r'localStorage|sessionStorage|JSON\.parse\s*\(', '持久化'),
      ('rx', r'\b(?:store|state|config|settings)\b', '状态字段'),
      ('rx', r'\b(?:store|Store|persist|hydrate)\s*[.(\[]', 'store 对象')]),
    ('s-atomicity', '原子性与安全判定', '多步写 / 批处理 / 权限判定',
     [('rx', r'\b(?:can|is|should|check|has)\w+\s*\([^)]*\)\s*(?::\s*boolean)?\s*\{', '判定函数'),
      ('rx', r'catch\s*\(\s*\w*\s*\)\s*\{\s*\}', '空 catch'),
      ('rx', r'\b(?:buy|sell|craft|transfer|deduct|add)\w*\s*\(', '交易类'),
      ('rx', r'(?:enabled|debug|cheat|devMode)\s*[:=]\s*true', '调试默认开')]),
    ('s-boundary', '跨边界通信', 'postMessage / IPC / 桥接 / iframe',
     [('rx', r'postMessage\s*\(', 'postMessage'),
      ('rx', r'addEventListener\s*\(\s*[\'"]message[\'"]', 'message 监听'),
      ('rx', r'\biframe\b|contentWindow|contentDocument', 'iframe'),
      ('rx', r'\b(?:invoke|listen|emit)\s*\(\s*[\'"]', 'IPC'),
      ('rx', r'\bbridge\b|__TAURI|__ELECTRON', '桥接')]),
    ('s-sandbox', '沙箱与权限', '插件 / 扩展 / 隔离 / CSP / 凭据',
     [('dir', 'plugins', 'plugins/'),
      ('dir', 'extensions', 'extensions/'),
      ('rx', r'Content-Security-Policy', 'CSP'),
      ('rx', r'sandbox\s*=|allow-scripts', 'sandbox 属性'),
      ('rx', r'\b(?:token|secret|password|credential|encrypt|decrypt)\b', '凭据'),
      ('rx', r'\b(?:isolat|隔离)\w*', '隔离')]),
    ('s-backend', '原生后端', 'Rust / C++ / Go、fs、进程、本地服务',
     [('dir', 'src-tauri', 'src-tauri/'),
      ('file', 'Cargo.toml', 'Cargo.toml'),
      ('rx', r'Command::new\s*\(|std::process', '进程执行'),
      ('rx', r'std::fs::|fs::read|std::fs::File', '文件操作'),
      ('rx', r'TcpListener|thread::spawn|tokio', '网络/线程')]),
    ('s-build', '构建与交付', '构建 / 打包 / CI / 依赖',
     [('file', 'package.json', 'package.json'),
      ('file', 'vite.config.*', 'vite 配置'),
      ('dir', '.github', 'CI'),
      ('file', '.gitignore', '忽略清单'),
      ('rx', r'frontendDist|\bfiles\s*:\s*\[', '打包范围')]),
    ('p-cocos', 'Cocos 平台', 'Cocos Creator 项目',
     [('file', 'cc.config.json', 'cc.config'),
      ('file', 'project.json', 'cocos project'),
      ('dir', 'assets', 'assets/'),
      ('rx', r"from\s+['\"]cc['\"]|cc\.Class|_decorator", 'cc 导入')]),
]

# 结构信号：目录/文件存在即命中（最强）
STRUCT_DIRS = {'plugins': 's-sandbox', 'extensions': 's-sandbox',
               'src-tauri': 's-backend', 'docs': 's-contracts',
               '.github': 's-build', 'assets': 'p-cocos'}
STRUCT_FILES = {'Cargo.toml': 's-backend', 'README.md': 's-contracts',
                'package.json': 's-build', '.gitignore': 's-build',
                'cc.config.json': 'p-cocos'}


def walk_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn.startswith('.'):
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > MAX_BYTES:
                    continue
            except OSError:
                continue
            if p.endswith(SOURCE_EXT) or fn in STRUCT_FILES or fn.endswith('.json'):
                out.append(p)
    return out


def route(root):
    files = walk_files(root)
    sampled = files
    if len(files) > SCAN_LIMIT:
        step = len(files) // SCAN_LIMIT
        sampled = files[::step][:SCAN_LIMIT]

    text = []
    for p in sampled:
        try:
            text.append(open(p, encoding='utf-8', errors='replace').read())
        except OSError:
            pass
    blob = '\n'.join(text)

    # 结构信号（目录名 / 文件名）
    top_dirs = set()
    for p in files:
        rel = os.path.relpath(p, root).replace('\\', '/')
        parts = rel.split('/')
        if len(parts) > 1:
            top_dirs.add(parts[0])
    top_files = {os.path.basename(p) for p in files}

    result = {}
    for sid, name, desc, signals in SCENES:
        ev_struct, ev_feat, ev_doc = [], [], []
        for kind, pat_or_name, label in signals:
            if kind == 'dir':
                if pat_or_name and pat_or_name in top_dirs:
                    n = len([p for p in files
                             if os.path.relpath(p, root).replace('\\', '/').startswith(pat_or_name + '/')])
                    ev_struct.append('%s/ (%d)' % (pat_or_name, n))
                elif pat_or_name is None:
                    continue
                elif pat_or_name in top_dirs:
                    ev_struct.append('%s/' % pat_or_name)
            elif kind == 'file':
                if pat_or_name in top_files:
                    ev_struct.append(pat_or_name)
                elif pat_or_name.startswith('*') and any(f.endswith(pat_or_name[1:]) for f in top_files):
                    ev_feat.append('%s（普遍存在，弱信号）' % pat_or_name)
            elif kind == 'rx':
                n = len(re.findall(pat_or_name, blob))
                if n:
                    ev_feat.append('%s×%d' % (label, n))
        if ev_struct or ev_feat or ev_doc:
            result[sid] = {'name': name, 'desc': desc,
                           'struct': ev_struct, 'feat': ev_feat, 'doc': ev_doc}
    return files, sampled, result


# 结构信号分级：目录/构建配置是强信号，README 这类几乎每个项目都有的是弱信号
STRONG_STRUCT = {'plugins/', 'extensions/', 'src-tauri/', 'Cargo.toml', 'cc.config.json'}

def score(item):
    """排序用。

    为什么**不**按特征命中总数排：`\b(?:store|state|config)\b` 这类宽泛正则
    在任何项目都能命中几百次，会把真正的项目特征（plugins/、src-tauri/）压下去。
    所以：结构信号 >> 特征种类数 >> 特征命中数（且对数压缩）。
    """
    st = sum(1000 if any(x.startswith(k) for k in STRONG_STRUCT) else 100
             for x in item['struct'])
    kinds = len(item['feat'])                                  # 命中几种不同特征
    n = sum(int(m.group(1)) for f in item['feat']
            for m in [re.search(r'\u00d7(\d+)', f)] if m)
    return st + kinds * 30 + int(10 * (1 + (n / 100.0 if n else 0)) ** 0.5)


def main():
    files, sampled, hits = route(ROOT)
    ranked = sorted(hits.items(), key=lambda kv: -score(kv[1]))
    ranked = [(k, v) for k, v in ranked if score(v) >= MIN_HITS or v['struct']]

    if AS_JSON:
        print(json.dumps([{'scene': k, 'name': v['name'], 'struct': v['struct'],
                           'feat': v['feat'], 'score': score(v)}
                          for k, v in ranked], ensure_ascii=False, indent=1))
        return

    print('route · 代码审查场景路由')
    print('根: %s   扫描文件: %d%s' % (ROOT, len(sampled),
                                    '（抽样，共 %d）' % len(files) if len(files) > len(sampled) else ''))
    print()
    if not ranked:
        print('未命中任何场景。跑 --all 看判据，或手工指定场景。')
        return
    for sid, v in ranked:
        print('%-14s %s' % (sid, v['name']))
        if v['struct']:
            print('   [结构] %s' % ' · '.join(v['struct'][:5]))
        if v['feat']:
            print('   [特征] %s' % ' · '.join(v['feat'][:6]))
    print()
    print('─' * 56)
    print('命中 %d 个 —— **全部都要审**，不设上限（截断会漏检）' % len(ranked))
    if len(ranked) <= BATCH:
        print('一批加载：%s' % ', '.join(k for k, _ in ranked))
    else:
        n = (len(ranked) + BATCH - 1) // BATCH
        print('分 %d 批加载（每批 ≤%d，避免一次读太多导致都读不深）：' % (n, BATCH))
        for i in range(n):
            chunk = ranked[i * BATCH:(i + 1) * BATCH]
            print('   第 %d 批  %s' % (i + 1, ', '.join(k for k, _ in chunk)))
        print('每批审完再加载下一批；审的过程中发现新特征 → 回头补加载（增量路由）')
    print()
    print('⚠ 脚本只按信号机械扫描，输出的是候选。必须人工审核：')
    print('   · 可能漏（相关代码在没扫到的路径）→ 手动补')
    print('   · 可能多（只审前端却探测到 src-tauri/）→ 手动剔')
    print('   · 不设命中上限：大项目命中 10+ 是正常的，分批审完，不要截断')


if __name__ == '__main__':
    main()
