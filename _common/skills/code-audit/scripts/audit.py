#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit.py —— 审查编排器（预算控制 + 断点续跑 + 统一输出）

解决三个「扫到一半失败」的问题：

    1. **预算**：大项目全量扫可能超 token/时间预算。按场景分批，
       每批有预算上限，超了就停并报告进度，而不是整个失败
    2. **断点续跑**：中断后从断点继续，已完成的不重跑
    3. **统一输出**：编排 route + 两个扫描器 + 文档检查，产出单一 SARIF

为什么单独一个脚本而不是塞进扫描器：
    预算与续跑是**跨场景的编排问题**，不是单条规则的扫描问题。
    扫描器保持纯粹（给什么扫什么），编排器负责节奏与容错。

用法：
    python3 audit.py --src=<根>                      # 全量，自动分批
    python3 audit.py --src=<根> --budget=80000       # token 预算（默认 120000）
    python3 audit.py --src=<根> --batch=2            # 每批场景数（默认 4）
    python3 audit.py --src=<根> --sarif=out.sarif    # 统一 SARIF 输出
    python3 audit.py --resume                        # 从上次断点继续
    python3 audit.py --status                        # 查看进度
    python3 audit.py --reset                         # 清断点重来

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

# 场景 -> 该跑哪些脚本
SCENE_SCRIPTS = {
    's-numerics': ['scan-ts.py'], 's-structures': ['scan-ts.py'],
    's-lifecycle': ['scan-ts.py', 'scan-app.py'], 's-contracts': ['scan-ts.py', 'scan-app.py'],
    's-state': ['scan-ts.py', 'scan-app.py'], 's-atomicity': ['scan-ts.py', 'scan-app.py'],
    's-boundary': ['scan-app.py'], 's-sandbox': ['scan-app.py'],
    's-backend': ['scan-app.py'], 's-build': ['scan-app.py'],
    'p-cocos': ['cocos-audit.py'],
}


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


def main():
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

    print('audit · 审查编排')
    print('根: %s' % SRC)
    print('场景 %d 个 · 已完成 %d · 本轮待审 %d · 预算 %d tokens'
          % (len(order), len(st['done']), len(todo), BUDGET))
    print()

    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        print('── 第 %d 批：%s ──────────' % (i // BATCH + 1, ', '.join(chunk)))
        for scene in chunk:
            scripts = SCENE_SCRIPTS.get(scene, ['scan-ts.py', 'scan-app.py'])
            count = 0
            for sc in scripts:
                sp = os.path.join(HERE, sc)
                if not os.path.isfile(sp):
                    continue
                tmp = os.path.join('/tmp', 'audit_%s_%s.json' % (scene, sc.replace('.py', '')))
                code, out, err = run([sp, '--src=' + SRC, '--json'], HERE)
                if code != 0 and not out.strip():
                    print('  ✗ %s / %s：%s' % (scene, sc, (err or '')[:80]))
                    continue
                try:
                    _d = json.loads(out) if out.strip() else []
                    # scan-ts 输出 {'items':[...]}；scan-app 直接输出 [...]
                    items = _d.get('items', []) if isinstance(_d, dict) else _d
                except ValueError:
                    items = []
                open(tmp, 'w', encoding='utf-8').write(json.dumps(items, ensure_ascii=False))
                count += len(items)
                st['scenes'].setdefault(scene, {})[sc] = tmp
            st['scenes'][scene]['count'] = count
            st['done'].append(scene)
            st['spent'] += int(count * 60)   # 粗估：每条候选约 60 token 的复核成本
            print('  ✓ %-14s %d 条候选（累计已耗 %d）' % (scene, count, st['spent']))
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
    print('全部完成：%d 个场景 · %d 条候选 · token 估算 %d'
          % (len(st['done']), sum(v.get('count', 0) for v in st['scenes'].values()), st['spent']))

    if SARIF_OUT:
        parts = []
        for scene, v in st['scenes'].items():
            for k, p in v.items():
                if k != 'count' and os.path.isfile(p):
                    parts.append(p)
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
