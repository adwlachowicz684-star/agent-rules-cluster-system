#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit.py —— 审查编排器（预算控制 + 断点续跑 + 统一输出）

解决三个「扫到一半失败」的问题：

    1. **预算**：大项目全量扫可能超 token/时间预算。按场景分批，
       每批有预算上限，超了就停并报告进度，而不是整个失败
    2. **断点续跑**：中断后从断点继续，已完成的不重跑
    3. **统一输出**：编排 route + 两个扫描器 + 文档检查，产出单一 SARIF
4. **判据落盘**（--items）：跑完扫描后，按场景挑出该核对的判据条目，
   写到 `<根>/.audit-items/<scene>.md`。

   为什么需要：路由的最小粒度是文件，命中一个场景就整篇读 references，
   而实际相关的往往只有几条目。落盘后逐个读小文件即可，
   实测省 67%~91%。

   挑选逻辑：扫描器命中的规则（精准）→ 路由命中的特征名（起步）。
   两者都没有 → **默认跳过**（判据服务于候选核对，无候选就不落），
   除非加 `--items-all` 落到该场景 P0 起步集。

为什么单独一个脚本而不是塞进扫描器：
    预算与续跑是**跨场景的编排问题**，不是单条规则的扫描问题。
    扫描器保持纯粹（给什么扫什么），编排器负责节奏与容错。

用法：
    python3 audit.py --src=<根>                      # 全量，自动分批
    python3 audit.py --src=<根> --budget=80000       # token 预算（默认 120000）
    python3 audit.py --src=<根> --batch=2            # 每批场景数（默认 4）
    python3 audit.py --src=<根> --sarif=out.sarif    # 统一 SARIF 输出
    python3 audit.py --src=<根> --items              # 判据落盘（<根>/.audit-items/）
    python3 audit.py --src=<根> --items --items-all   # 无候选的场景也落 P0 起步集
    python3 audit.py --resume                        # 从上次断点继续
    python3 audit.py --status                        # 查看进度
    python3 audit.py --src=<根> --items --item-level=P0   # 只要 P0 判据
    python3 audit.py --src=<根> --no-gitignore       # 别动被审查项目的 .gitignore
    python3 audit.py --reset                         # 清断点重来

关于 .gitignore：
    审查产物（.audit-state.json / .audit-items/）落在**被审查项目里**，
    会弄脏对方的 git status。所以检测到 git 仓库时会自动追加两行
    .gitignore（幂等，带注释标注来源，可随时删）。
    不想让它动就用 --no-gitignore；不是 git 仓库则什么都不做。

退出码：
    0  全部完成
    1  有 P0 未确认（CI 可据此阻断）
    2  预算耗尽（未完成，可 --resume）
    3  执行错误
"""

import os
import sys
import json
import time
import subprocess
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
STATE = '.audit-state.json'

_flags = [a for a in sys.argv[1:] if a.startswith('--')]
SRC = None
BUDGET = 120000
BATCH = 4
SARIF_OUT = None
for f in _flags:
    if f.startswith('--src='):
        SRC = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
    elif f.startswith('--budget='):
        BUDGET = int(f.split('=', 1)[1])
    elif f.startswith('--batch='):
        BATCH = int(f.split('=', 1)[1])
    elif f.startswith('--sarif='):
        SARIF_OUT = f.split('=', 1)[1]
if SRC is None:
    SRC = os.path.abspath('.')

RESUME = '--resume' in _flags
STATUS = '--status' in _flags
RESET = '--reset' in _flags
ITEMS = '--items' in _flags
ITEM_ALL = '--items-all' in _flags
ITEM_LEVEL = ''
ITEM_LIMIT = 0
# 默认开启：不往被审查项目写 .gitignore，审查产物会污染它的 git status
NO_GITIGNORE = '--no-gitignore' in _flags
for _f in _flags:
    if _f.startswith('--item-level='):
        ITEM_LEVEL = _f.split('=', 1)[1].strip()
    elif _f.startswith('--item-limit='):
        try:
            ITEM_LIMIT = int(_f.split('=', 1)[1])
        except ValueError:
            ITEM_LIMIT = 0

# 场景 -> 该跑哪些脚本
SCENE_SCRIPTS = {
    's-numerics': ['scan-ts.py'], 's-structures': ['scan-ts.py'],
    's-lifecycle': ['scan-ts.py', 'scan-app.py'], 's-contracts': ['scan-ts.py', 'scan-app.py'],
    's-state': ['scan-ts.py', 'scan-app.py'], 's-atomicity': ['scan-ts.py', 'scan-app.py'],
    's-boundary': ['scan-app.py'], 's-sandbox': ['scan-app.py'],
    's-backend': ['scan-app.py'], 's-build': ['scan-app.py'],
    'p-cocos': ['cocos-audit.py'],
    'p-godot': ['godot-audit.py'],
    # 语言包：早先漏了，导致四语言项目里 p-python/p-go/p-java/p-cpp
    # 永远 0 条候选——因为压根没跑对应扫描器
    'p-python': ['scan-py.py'], 'p-go': ['scan-go.py'],
    'p-java': ['scan-java.py'], 'p-cpp': ['scan-cpp.py'],
    'p-rust': ['scan-rust.py'],
    # 架构可演进性：AR-01/03/04/05 四条机扫规则都在 scan-py.py 里
    # （AR-02 是人工判据，无机扫）。漏掉这一行 = 编排器永远不跑 scan-py，
    # 该场景恒定 0 条候选 —— 与「SCENE_SCRIPTS 漏语言包」是同一个失效模式。
    's-architecture': ['scan-py.py'],
}

# 主循环要跑的扫描器。语言扫描器对 TS 项目输出 0 条，多跑只是白费时间，
# 所以按源码实际语言挑——用 route.py 命中的语言包来决定。
# 从 SCENE_SCRIPTS 推导，不硬编码名单。
#
# 为什么：硬编码名单是「名单漏一个就静默失效」的第三处
# （前两处是 CI 的扫描器列表、SCENE_SCRIPTS 自己漏语言包）。
# 早先这里只写了 7 个 scan-*.py，于是 SCENE_SCRIPTS 里配好的
# cocos-audit.py / godot-audit.py **永远不会被调用**——
# 编排器输出"0 条候选，无候选，跳过"，看起来像代码没问题，
# 实际是扫描器压根没跑。
ALL_SCANNERS = tuple(sorted({s for v in SCENE_SCRIPTS.values() for s in v}))

# 扫描器 → 场景 的反查表。**只收录「只服务一个场景」的扫描器**。
#
# 为什么：引擎专项扫描器（cocos-audit.py / godot-audit.py）的规则
# 不在 registry.json 里（它们是引擎专有的，不进通用规则表），
# 于是分组时 scene_of 查不到 → 全部掉进 s-contracts 兜底，
# 而真正该看它们的 p-cocos / p-godot 场景显示"0 条候选，跳过"。
# 扫描器明明跑了、候选明明有，报告里却看不到——又一种静默丢失。
_SCENES_OF = {}
for _s, _scs in SCENE_SCRIPTS.items():
    for _x in _scs:
        _SCENES_OF.setdefault(_x, []).append(_s)
SOLE_SCANNER_SCENE = {k: v[0] for k, v in _SCENES_OF.items() if len(v) == 1}

# 语言 ID 前缀 → 语言包场景（分组用，见下方 grouped 逻辑）
LANG_SCENE = {'PY': 'p-python', 'GO': 'p-go',
              'JAVA': 'p-java', 'CPP': 'p-cpp', 'RS': 'p-rust'}


def _items_index():
    """读判据索引。没有就返回 None（不报错——缺索引不该让编排失败）。

    为什么用 importlib 而不是 import：脚本名带连字符（`item-index.py`），
    Python 无法直接 `import item-index`，只能按文件路径加载。
    """
    try:
        import importlib.util
        path = os.path.join(HERE, 'item-index.py')
        if not os.path.isfile(path):
            return None
        spec = importlib.util.spec_from_file_location('_item_index', path)
        II = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(II)
        d = II.load()
        if not d or not d.get('items'):
            d = II.build()
        return (II, d) if d and d.get('items') else None
    except Exception:
        return None


def _pick_items(II, d, scene, hit_ids=None, feats=None):
    """挑出该场景要加载的判据条目。

    两条路径：
      · hit_ids —— 扫描器命中的规则（精准）。有就用它，最省
      · feats   —— 路由命中的特征名（起步）。没扫描命中时兜底
    两者都没有 → 该场景的 P0 起步集。
    """
    idx = {i['id']: i for i in d['items']}
    by_norm = {}
    for k in idx:
        n = II.norm_id(k)
        if n:
            by_norm.setdefault(n, k)

    picked = []
    if hit_ids:
        for h in hit_ids:
            k = by_norm.get(II.norm_id(h) or '')
            if k and idx[k] not in picked:
                picked.append(idx[k])
    if not picked and feats:
        keys = [f.split('×')[0].strip().lower() for f in feats if f]
        keys = [k for k in keys if k]
        scored = []
        for i in d['items']:
            if i['scene'] != scene:
                continue
            parts = [i['name']]
            for fk in ('判据', '特征', '典型', '正确'):
                for v in (i.get('fields') or {}).get(fk, []):
                    parts.append(v if isinstance(v, str) else ' '.join(v))
            hay = ' '.join(parts).lower()
            sc = sum(1 for k in keys if k and k in hay)
            if sc:
                scored.append((sc, i))
        if scored:
            scored.sort(key=lambda t: (-t[0], t[1]['level'], t[1]['id']))
            picked = [i for _, i in scored]
    if not picked:
        # 既无扫描命中、特征也对不上 → 默认**不落**。
        # 判据是用来核对候选的；一个扫描器跑过却零命中的场景，
        # 再落一整包 P0 起步集纯属浪费（实测四语言项目里
        # s-numerics 落 13 条/1257 tokens，而真正有用的只有 560）。
        # 确实要人工兜底时用 --items-all。
        if not ITEM_ALL:
            return []
        picked = [i for i in d['items']
                  if i['scene'] == scene and i['level'] == 'P0']
    if ITEM_LEVEL:
        picked = [i for i in picked if i['level'] == ITEM_LEVEL]
    picked.sort(key=lambda i: (i['level'], i['id']))
    return picked[:ITEM_LIMIT] if ITEM_LIMIT else picked


def _write_items_md(II, d, scene, items, feats):
    """把挑出的判据渲染成 Markdown 落盘。

    为什么不打到 stdout：audit 自己就输出扫描进度/批次/预算，
    再把判据正文打出来，它的输出本身先爆了。落盘给路径，按需读。
    """
    out = ['# %s · 待核对判据（%d 条）' % (scene, len(items))]
    if feats:
        out.append('')
        out.append('> 路由命中特征：%s' % ' · '.join(feats[:6]))
    out.append('')
    body = II.render(items, II.related_sections(d, [i['id'] for i in items]))
    out.append(body)
    return '\n'.join(out)


# ---- 产物不污染被审查项目 ----
# 本脚本把 .audit-state.json / .audit-items/ 写在**被审查项目的根**里
# （产物跟着项目走，便于查看与断点续跑）。副作用是这些文件会出现在
# 对方的 `git status` 里——那是人家的仓库，不该被审查工具弄脏。
#
# 方案：检测到是 git 仓库就自动往 .gitignore 追加两行。
# 为什么是追加而不是改产物位置：产物落在项目里更顺手（一眼能看到、
# 换机器也能接着跑），而 .gitignore 追加两行是最小侵入。
GITIGNORE_MARK = '# code-audit 审查产物（由 audit.py 自动追加，可删）'
GITIGNORE_ENTRIES = ['.audit-state.json', '.audit-items/']


def git_toplevel(path):
    """返回 path 所属 git 仓库的根；不是 git 仓库则返回 None。"""
    try:
        r = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                           cwd=path, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return os.path.abspath(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def ensure_gitignore(root, rel_entries):
    """把审查产物加进被审查项目的 .gitignore（幂等）。

    几个刻意的处理：
      · **相对仓库根写路径**。SRC 可能是子目录，而 .gitignore 在仓库根，
        直接写 `.audit-items/` 会失效（gitignore 含 `/` 时锚定到文件所在目录）
      · **幂等**。按行精确比对，重复跑不会堆一坨
      · **失败不致命**。只读仓库、无权限都只是 warning，不影响审查
      · **可关**。--no-gitignore
    """
    if NO_GITIGNORE:
        return None
    top = git_toplevel(root)
    if not top:
        return None

    # 产物相对仓库根的路径（SRC 可能就是根，也可能是子目录）
    try:
        rel = os.path.relpath(root, top)
    except ValueError:
        return None
    prefix = '' if rel in ('.', '') else rel.replace(os.sep, '/').rstrip('/') + '/'
    wanted = ['%s%s' % (prefix, e) for e in rel_entries]

    gi = os.path.join(top, '.gitignore')
    lines = []
    if os.path.isfile(gi):
        try:
            lines = open(gi, encoding='utf-8').read().splitlines()
        except (OSError, UnicodeDecodeError):
            return None  # 读不了就别碰它

    existing = {l.strip() for l in lines}
    add = [w for w in wanted if w not in existing]
    if not add:
        return None  # 已经有了，什么都不做

    try:
        with open(gi, 'a', encoding='utf-8') as f:
            if lines and lines[-1].strip():
                f.write('\n')
            f.write(GITIGNORE_MARK + '\n')
            for w in add:
                f.write(w + '\n')
    except OSError as e:
        print('  [warn] 写 .gitignore 失败（不影响审查）: %s' % e, file=sys.stderr)
        return None
    return wanted


def state_path():
    return os.path.join(SRC, STATE)


def load_state():
    p = state_path()
    if os.path.isfile(p):
        try:
            return json.load(open(p, encoding='utf-8'))
        except (OSError, ValueError):
            pass
    return {'scenes': {}, 'done': [], 'spent': 0, 'started': time.time()}


def save_state(st):
    json.dump(st, open(state_path(), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def run(cmd, root):
    try:
        r = subprocess.run([sys.executable] + cmd, cwd=root,
                           capture_output=True, text=True, timeout=900)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 124, '', '超时'
    except Exception as e:
        return 3, '', str(e)


def _scene_map():
    # 从 rules/registry.json 读「规则 ID -> 场景」映射
    reg = os.path.join(SKILL, 'rules', 'registry.json')
    if not os.path.isfile(reg):
        return {}
    try:
        return dict((r['rule_id'], r['scene'])
                    for r in json.load(open(reg, encoding='utf-8'))['rules'])
    except (OSError, ValueError, KeyError):
        return {}


def route_scenes():
    """调 route.py --json 拿场景排序。"""
    code, out, err = run([os.path.join(HERE, 'route.py'), '--src=' + SRC, '--json'], HERE)
    if code != 0 or not out.strip():
        print('路由失败：%s' % (err or '无输出'))
        return []
    try:
        return json.loads(out)
    except ValueError:
        return []


def cmd_status():
    st = load_state()
    if not st['done']:
        print('无进行中的任务')
        return 0
    print('进度：%d/%d 场景已完成 · 已耗 token 估算 %d' % (
        len(st['done']), len(st.get('scenes') or st['done']), st['spent']))
    for s in st['done']:
        print('  ✓ %s（%d 条）' % (s, (st['scenes'].get(s) or {}).get('count', 0)))
    pend = [s for s in (st.get('pending') or []) if s not in st['done']]
    for s in pend:
        print('  · %s（待审）' % s)
    if st.get('exhausted'):
        print('\n⚠ 上次预算耗尽，用 --resume 继续')
    return 0


def cmd_reset():
    p = state_path()
    if os.path.isfile(p):
        os.remove(p)
        print('已清除断点')
    return 0


def cmd_self_test():
    """编排器判据落盘的自检。

    为什么单独测：接入过程中踩了三个坑，全部表现为**静默丢失**——
    不报错、输出看着正常，但候选或判据就是少了。
    不写断言根本发现不了。
    """
    ok = fail = 0

    def chk(cond, msg):
        nonlocal ok, fail
        print(('  ✓ ' if cond else '  ✗ ') + msg)
        if cond:
            ok += 1
        else:
            fail += 1

    chk(os.path.isfile(os.path.join(HERE, 'item-index.py')),
        'item-index.py 存在')
    IDX = _items_index()
    chk(IDX is not None, '判据索引可加载' + ('' if IDX else '（先跑 item-index.py --sync）'))
    if not IDX:
        print()
        print('自检：%d 通过 / %d 失败' % (ok, fail))
        return 1

    II, d = IDX
    idx = {i['id']: i for i in d['items']}

    # 1) 语言包规则必须归到语言包场景，不能按 registry 的 scene 分走
    chk(all(k in idx for k in ('PY-05', 'PY-06', 'PY-01')),
        'PY-01/05/06 都在索引里')
    lang = dict(LANG_SCENE)
    chk(lang.get('PY') == 'p-python' and lang.get('JAVA') == 'p-java',
        '语言前缀→场景映射完整（%d 种）' % len(lang))

    # 2) 精准路径：给命中 ID 就只返回对应条目
    picked = _pick_items(II, d, 'p-python', ['PY-01', 'PY-05'])
    ids = sorted(i['id'] for i in picked)
    chk(ids == ['PY-01', 'PY-05'],
        '精准路径只取命中的（得到 %s）' % ','.join(ids))

    # 3) 无命中、无特征 → 默认跳过（不落一整包 P0）
    global ITEM_ALL
    _old = ITEM_ALL
    ITEM_ALL = False
    empty = _pick_items(II, d, 's-numerics', [], [])
    chk(empty == [], '无候选且无特征 → 默认不落（得到 %d 条）' % len(empty))
    ITEM_ALL = True
    fallback = _pick_items(II, d, 's-numerics', [], [])
    chk(len(fallback) > 0, '--items-all 时落 P0 起步集（%d 条）' % len(fallback))
    ITEM_ALL = _old

    # 4) 表格格式的判据也能被索引（s-backend 是表格，曾整篇漏掉）
    be = [i for i in d['items'] if i['scene'] == 's-backend']
    chk(len(be) > 0, 's-backend（表格格式）已进索引（%d 条）' % len(be))

    # 5) 渲染出的 Markdown 非空且带误报段
    md = _write_items_md(II, d, 'p-python',
                         [idx['PY-01']], ['clamp×3'])
    chk('PY-01' in md and len(md) > 100,
        '渲染结果含条目正文（%d 字符）' % len(md))

    # 6) .gitignore 自动追加：四种情形都不能出错
    import tempfile
    def _mkgit(sub=''):
        """建一个 git 仓库；给了 sub 就**返回子目录**（仓库根是它的父目录）。

        早先写成在 sub 里 git init，那 sub 自己就是根了，
        子目录场景等于没测到。"
        """
        top = tempfile.mkdtemp()
        subprocess.run(['git', 'init', '-q'], cwd=top, capture_output=True)
        if sub:
            d = os.path.join(top, sub)
            os.makedirs(d)
            return d
        return top

    saved_flag = globals().get('NO_GITIGNORE')
    try:
        globals()['NO_GITIGNORE'] = False
        d1 = _mkgit()
        a1 = ensure_gitignore(d1, GITIGNORE_ENTRIES)
        chk(a1 == ['.audit-state.json', '.audit-items/'],
            'git 仓库根：写入两条（%s）' % a1)
        a2 = ensure_gitignore(d1, GITIGNORE_ENTRIES)
        chk(a2 is None, '幂等：第二次不重复追加')

        d2 = _mkgit('sub')
        a3 = ensure_gitignore(d2, GITIGNORE_ENTRIES)
        chk(a3 == ['sub/.audit-state.json', 'sub/.audit-items/'],
            '子目录：路径相对仓库根（%s）' % a3)

        d3 = tempfile.mkdtemp()   # 非 git 目录
        chk(ensure_gitignore(d3, GITIGNORE_ENTRIES) is None,
            '非 git 目录：不写、不崩')

        globals()['NO_GITIGNORE'] = True
        d4 = _mkgit()
        chk(ensure_gitignore(d4, GITIGNORE_ENTRIES) is None,
            '--no-gitignore：不写（产物仍可见，由用户自行处理）')
    finally:
        globals()['NO_GITIGNORE'] = saved_flag

    print()
    print('自检：%d 通过 / %d 失败' % (ok, fail))
    if not fail:
        print('结论：编排器判据落盘工作正常')
    return 1 if fail else 0


def main():
    if '--self-test' in _flags:
        sys.exit(cmd_self_test())
    if STATUS:
        sys.exit(cmd_status())
    if RESET:
        sys.exit(cmd_reset())

    scenes = route_scenes()
    if not scenes:
        print('未命中任何场景')
        return 3
    order = [s['scene'] for s in scenes]

    st = load_state() if RESUME else {'scenes': {}, 'done': [], 'spent': 0,
                                      'started': time.time(), 'pending': order}
    if not RESUME:
        st['pending'] = order
    todo = [s for s in order if s not in st['done']]
    if not todo:
        print('全部场景已完成。--reset 可重来。')
        return 0

    # 产物会落在被审查项目里 → 先让它的 .gitignore 接住，
    # 否则人家的 git status 里会冒出 .audit-state.json / .audit-items/
    _added = ensure_gitignore(SRC, GITIGNORE_ENTRIES)

    print('audit · 审查编排')
    print('根: %s' % SRC)
    if _added:
        print('已把审查产物加入 .gitignore: %s' % ' · '.join(_added))
    print('场景 %d 个 · 已完成 %d · 本轮待审 %d · 预算 %d tokens'
          % (len(order), len(st['done']), len(todo), BUDGET))
    print()

    # 关键：扫描器**每个只跑一次全量**，再按场景分组。
    # 旧版是「每个场景跑一次全量扫描器」——同一份结果被计入 N 次
    # （实测 nexus-panel：111 条 TS 候选被算成 666 条，虚增 6 倍），
    # 既浪费时间又让预算估算失真。分批控制的是**人工阅读节奏**，不是重复扫描。
    scene_of = _scene_map()

    if 'scan_cache' not in st:
        st['scan_cache'] = {}
    cache = st['scan_cache']

    # 只跑「命中场景真正需要」的扫描器：
    # 全跑 6 个在纯 TS 项目上白费 4 次；全不跑则语言包永远 0 条。
    need = set()
    for _sc in todo:
        need.update(SCENE_SCRIPTS.get(_sc, []))
    if not need:
        need = {'scan-ts.py', 'scan-app.py'}
    for sc in [x for x in ALL_SCANNERS if x in need]:
        sp = os.path.join(HERE, sc)
        if not os.path.isfile(sp):
            continue
        if sc in cache and cache[sc] and os.path.isfile(cache[sc]):
            continue
        print('── 扫描：%s ──────────' % sc)
        code, out, err = run([sp, '--src=' + SRC, '--json'], HERE)
        if code != 0 and not out.strip():
            print('  x %s：%s' % (sc, (err or '')[:80]))
            cache[sc] = None
            continue
        try:
            _d = json.loads(out) if out.strip() else []
            items = _d.get('items', []) if isinstance(_d, dict) else _d
        except ValueError:
            items = []
        tmp = os.path.join('/tmp', 'audit_%s.json' % sc.replace('.py', ''))
        open(tmp, 'w', encoding='utf-8').write(json.dumps(items, ensure_ascii=False))
        cache[sc] = tmp
        print('  %d 条候选' % len(items))
    save_state(st)

    # 按场景分组（用 registry 的 scene 字段）
    grouped = {}
    for sc, path in cache.items():
        if not path or not os.path.isfile(path):
            continue
        for it in json.load(open(path, encoding='utf-8')):
            native = it.get('id') or it.get('pattern') or ''
            # 语言扫描器输出的已是统一 ID（PY-01 / GO-04），不能再加前缀，
            # 否则变成 TS-PY-01，scene_of 查不到 → 全部归到 s-contracts
            if re.match(r'^(TS|APP|PY|GO|JAVA|CPP)-', native):
                rid = native
            else:
                rid = ('APP-' if 'app' in sc else 'TS-') + native
            # 补 scanner 字段：sarif.py 靠它决定 APP-/TS- 前缀，
            # 不补就会全部退化成 TS-*（实测 R06 被误标成 TS-R06）
            it.setdefault('scanner', sc)

            # 语言包规则按**ID 前缀**归到语言包场景，不用 registry 的 scene。
            #
            # 为什么：registry 把 PY-05（不安全反序列化）标成 s-backend、
            # PY-06 标成 s-sandbox。若按 registry 分组，这两条候选会被分到
            # 别的场景——而那个场景可能压根没被路由命中，
            # 于是**候选静默丢失**（实测四语言项目：PY-05 一条都没进报告）。
            #
            # 判据写在 p-python.md 里，审 Python 就该在 p-python 看到它。
            # registry 的 scene 用于风险面统计，不用于分组。
            m = re.match(r'^(PY|GO|JAVA|CPP)-', rid)
            if m:
                scene = LANG_SCENE[m.group(1)]
            elif sc in SOLE_SCANNER_SCENE:
                # 专用扫描器（引擎包等）：候选直接归它的场景。
                # 见 SOLE_SCANNER_SCENE 处的说明。
                scene = SOLE_SCANNER_SCENE[sc]
            else:
                scene = scene_of.get(rid, 's-contracts')
            grouped.setdefault(scene, []).append(it)

    # 判据索引（--items 时才需要）。缺失不致命，只是不落盘。
    IDX = None
    feat_of = {}
    if ITEMS:
        IDX = _items_index()
        if not IDX:
            print('⚠ 判据索引缺失（跑 scripts/item-index.py --sync 生成），跳过判据落盘')
        for sc in scenes:
            feat_of[sc['scene']] = sc.get('feat') or []

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        print()
        print('── 第 %d 批：%s ──────────' % (i // BATCH + 1, ', '.join(chunk)))
        for scene in chunk:
            items = grouped.get(scene, [])
            tmp = os.path.join('/tmp', 'audit_scene_%s.json' % scene)
            open(tmp, 'w', encoding='utf-8').write(json.dumps(items, ensure_ascii=False))
            st['scenes'].setdefault(scene, {})['items'] = tmp
            n = len(items)
            st['scenes'][scene]['count'] = n
            st['done'].append(scene)
            st['spent'] += int(n * 60)

            # 判据落盘：把「这个场景该读哪几条」固化下来，省得人工翻 references
            itok = 0
            if ITEMS and IDX:
                II, d = IDX
                feats = feat_of.get(scene, [])
                hit_ids = [str(it.get('id') or it.get('pattern') or '')
                           for it in items]
                picked = _pick_items(II, d, scene, hit_ids, feats)
                if picked:
                    odir = os.path.join(SRC, '.audit-items')
                    os.makedirs(odir, exist_ok=True)
                    op = os.path.join(odir, '%s.md' % scene)
                    open(op, 'w', encoding='utf-8').write(
                        _write_items_md(II, d, scene, picked, feats))
                    itok = sum(i['tokens'] for i in picked)
                    st['scenes'][scene]['item_file'] = op
                    st['scenes'][scene]['item_count'] = len(picked)
                    st['scenes'][scene]['item_tokens'] = itok
                    # 判据正文才是真正占上下文的部分，必须计入预算，
                    # 否则预算模型只算候选数、严重低估实际开销
                    st['spent'] += itok
                    st['item_tokens'] = st.get('item_tokens', 0) + itok

            note = ''
            if itok:
                note = ' · 判据 %d 条/%d tokens' % (
                    st['scenes'][scene].get('item_count', 0), itok)
            elif ITEMS and IDX:
                # 文案不能写「无候选」：此时候选可能很多（如 p-godot 14 条），
                # 只是该场景的判据条目没有被 items.json 收录（引擎包用表格
                # 写规则，不是 `### ID (P级)` 条目格式，索引取不到）。
                # 写成「无候选」会让人以为扫描器没跑。
                note = ' · 该场景无已索引判据条目，跳过落盘（候选仍照常报）'
            print('  ✓ %-14s %d 条候选%s（累计已耗 %d）'
                  % (scene, n, note, st['spent']))
            save_state(st)

            if st['spent'] >= BUDGET:
                st['exhausted'] = True
                save_state(st)
                print()
                print('⚠ 预算耗尽（%d/%d）。已审 %d/%d 场景，用 --resume 继续。'
                      % (st['spent'], BUDGET, len(st['done']), len(order)))
                return 2

    st['exhausted'] = False
    save_state(st)
    print()
    print('全部完成：%d 个场景 · %d 条候选（去重后）· token 估算 %d'
          % (len(st['done']), sum(v.get('count', 0) for v in st['scenes'].values()), st['spent']))
    if ITEMS and st.get('item_tokens'):
        files = [v['item_file'] for v in st['scenes'].values() if v.get('item_file')]
        print()
        print('判据已落盘：%d 个文件 · %d 条 · %d tokens'
              % (len(files),
                 sum(v.get('item_count', 0) for v in st['scenes'].values()),
                 st['item_tokens']))
        for f in files:
            print('  %s' % f)
        print()
        print('逐个读这些文件核对候选；不要整篇读 references/。')

    if SARIF_OUT:
        # 各场景的候选已按规则归属分组，互不重叠，直接合并
        parts = [v['items'] for v in st['scenes'].values()
                 if v.get('items') and os.path.isfile(v['items'])]
        if parts:
            cmd = [os.path.join(HERE, 'sarif.py')] + parts + \
                  ['--root=' + SRC, '--out=' + SARIF_OUT]
            code, out, err = run(cmd, HERE)
            print(out.strip() or err.strip())

    p0 = sum(1 for v in st['scenes'].values() if v.get('count', 0) > 0)
    print('\n提示：候选 ≠ 结论。逐条过 references/pattern-detection 的「确认」栏。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
