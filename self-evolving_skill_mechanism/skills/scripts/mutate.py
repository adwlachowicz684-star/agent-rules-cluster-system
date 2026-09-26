#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mutate.py —— 变异测试（反哺自 code-audit 的 scripts/mutate.py）

为什么需要
----------
自检用例是**手写的**，它只能证明「我写的这个样例能被查出」，
证明不了「历史上真实发生过的那个缺陷能被查出」。

这两者的差距就是盲区。实测差距有多大：
本文件沉淀的 5 条变异全部来自**真实修过的缺陷**，
其中 EV-M04 至今仍是 SURVIVED —— 手写用例漏了它。

做法：把真实修过的缺陷**注入回去**（old → new），跑测试套件，
看它变红（KILLED）还是仍绿（SURVIVED）。

三种结果（**必须分开**，见下）
----------------------------
    KILLED       测试抓到了 → 该缺陷被守住了
    SURVIVED     测试没抓到 → **盲区**，需补测试
    NOT_APPLIED  变异没生效 → **配置问题，不是代码问题**

⛔ **SURVIVED 与 NOT_APPLIED 必须分开**
   混在一起会让「脚本配置错了」被当成「代码有盲区」——
   前者改配置，后者补测试，处理的完全不同。
   更糟的是：NOT_APPLIED 时测试当然绿，会被误报成 KILLED，
   **于是「KILLED」可能只是因为变异压根没生效**。

用法
----
    python3 scripts/mutate.py --mutations=assets/mutations.json
    python3 scripts/mutate.py --mutations=assets/mutations.json --id=EV-M01
    python3 scripts/mutate.py --mutations=assets/mutations.json --json
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exitcode import OK, ERR, USAGE, ENV, BLOCKED, die, help_text  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DEFAULT_MUTATIONS = os.path.join(ROOT, 'assets', 'mutations.json')
# 测试套件：引擎侧就是 lint.py 的自检
TEST_CMD = [sys.executable, os.path.join(ROOT, 'scripts', 'lint.py'), '--self-test']


def run_tests(cmd=None):
    """跑测试套件，返回 (是否通过, 输出)。"""
    r = subprocess.run(cmd or TEST_CMD, capture_output=True, text=True, cwd=ROOT)
    return (r.returncode == 0), (r.stdout or '') + (r.stderr or '')


# ⛔ 哪些文件被默认测试套件（lint.py --self-test）实际覆盖到
#    —— 判定依据是「lint.py 会不会 import / 执行它」，不是「它在不在 scripts/ 下」
COVERED_BY_DEFAULT = {'scripts/lint.py'}


def covered_by(mut: dict) -> bool:
    """这条变异的 target 有没有测试套件守着。

    ### ⛔ 实测（主链路真跑后的回放）

    四个断点沉淀成 EV-M28~M31 后**全部 SURVIVED**。
    第一反应是"用例不够"，逐条查才发现：

    ```
    mutate.py 的 TEST_CMD = lint.py --self-test
    EV-M28~M31 的 target = consolidate.py / domain.py / archive.sh
    ```

    ⇒ ⛔ **测试套件压根不执行那几个文件** —— 改坏了也不会有任何用例变红。
    SURVIVED 看起来是"用例不够"，实际是"**测试没跑到**"。

    ⓘ 与 NOT_APPLIED 的区别：
    - NOT_APPLIED = 变异没应用上（old 片段对不上）
    - **本状态 = 变异应用上了，但测试不覆盖**（伪装成 SURVIVED）
    """
    t = (mut.get('target') or '').replace('\\', '/')
    if mut.get('test_cmd'):
        return True
    return t in COVERED_BY_DEFAULT


def apply_mutation(path, old, new):
    """把 old 替换成 new。返回 True 表示真的替换了。"""
    with open(path, encoding='utf-8') as f:
        src = f.read()
    if old not in src:
        return False
    with open(path, 'w', encoding='utf-8') as f:
        f.write(src.replace(old, new, 1))
    return True


def check_residue(muts):
    """⛔ 回放前先扫：有没有上次回放残留的变异还留在磁盘上。

    ### ⚠ 实测（连续 3 次）

    回放中途异常退出 → finally 没跑到 / 分支提前 continue
    → 磁盘上留一个**被改坏的文件** → 下次跑别的命令才暴露，
    且报错信息与变异完全无关。三次分别污染了 consolidate.py（2 次）、
    domain.py、archive.sh。

    ⇒ 变异是"临时改坏再还原"，任何中断都会留下半截状态。
    """
    hits = []
    for m in muts:
        tgt = os.path.join(ROOT, m.get("target", ""))
        if not os.path.isfile(tgt):
            continue
        try:
            with open(tgt, encoding="utf-8") as _f:
                src = _f.read()
        except Exception:
            continue
        nv = (m.get("new") or "").strip()
        # ⛔ 短片段（如 EV-M01 的 `        return`）在真库里必然存在，
        #    直接做字符串包含会**误报并阻塞整轮回放**（实测误报 1/31）。
        #    ⇒ 只查**带变异标记**或**足够长**的 new。
        if not nv:
            continue
        if "变异" not in nv and len(nv) < 20:
            continue
        if nv in src:
            hits.append((m["id"], m.get("target")))
    return hits


def main():
    ap = argparse.ArgumentParser(epilog=help_text())
    ap.add_argument('--mutations', default=DEFAULT_MUTATIONS,
                    help='变异定义 JSON 文件')
    ap.add_argument('--id', default='', help='只跑某一条（默认全部）')
    ap.add_argument('--json', action='store_true', help='机器可读')
    args = ap.parse_args()

    if not os.path.isfile(args.mutations):
        die(ENV, '找不到变异定义：%s' % args.mutations)
    with open(args.mutations, encoding='utf-8') as f:
        muts = json.load(f)

    if args.id:
        muts = [m for m in muts if m.get('id') == args.id]
        if not muts:
            die(USAGE, '没有 id 为 %s 的变异' % args.id)

    res = check_residue(muts)
    if res:
        die(ERR, '⛔ 磁盘上有残留变异，先还原再跑：\n'
                 + '\n'.join('  %s  %s' % (i, t) for i, t in res))

    results = []
    for m in muts:
        tgt = os.path.join(ROOT, m.get('target', ''))
        if not os.path.isfile(tgt):
            results.append({'id': m['id'], 'result': 'NOT_APPLIED',
                            'reason': '目标文件不存在：%s' % m.get('target')})
            continue
        if not covered_by(m):
            results.append({'id': m['id'], 'result': 'NOT_COVERED',
                            'reason': '测试套件不覆盖 %s（默认只跑 lint.py --self-test）'
                                      % m.get('target')})
            continue

        with open(tgt, encoding='utf-8') as f:
            original = f.read()

        if not apply_mutation(tgt, m['old'], m['new']):
            results.append({'id': m['id'], 'result': 'NOT_APPLIED',
                            'reason': 'old 片段在当前文件里找不到——'
                                      '代码改过了，变异定义需要更新'})
            continue

        _cmd = None
        if m.get('test_cmd'):
            _cmd = [c.replace('{root}', ROOT) for c in m['test_cmd']]
            if _cmd and _cmd[0].startswith('python'):
                _cmd[0] = sys.executable
        try:
            passed, out = run_tests(_cmd)
        finally:
            # ⛔ 无论测试跑没跑完都必须还原——否则留一个被改坏的文件在磁盘上
            with open(tgt, 'w', encoding='utf-8') as f:
                f.write(original)

        result = 'SURVIVED' if passed else 'KILLED'
        expect = m.get('expect', 'KILLED')
        results.append({
            'id': m['id'], 'result': result, 'expect': expect,
            'match': result == expect,
            'desc': m.get('desc', ''), 'why': m.get('why', ''),
        })

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        sys.exit(OK)

    print('=' * 60)
    print('变异测试（历史缺陷回放）')
    print('=' * 60)
    nk = ns = nn = nc = 0
    for r in results:
        if r['result'] == 'KILLED':
            nk += 1
            mark = '✓'
        elif r['result'] == 'SURVIVED':
            ns += 1
            mark = '✗' if r.get('expect') == 'KILLED' else '!'
        elif r['result'] == 'NOT_COVERED':
            nc += 1
            mark = '∅'
        else:
            nn += 1
            mark = '?'
        line = '  %s %-8s %s' % (mark, r['id'], r['result'])
        if r['result'] in ('NOT_APPLIED', 'NOT_COVERED'):
            line += ' —— %s' % r.get('reason', '')
            line += '\n      %s' % r.get('desc', '')
        else:
            if not r.get('match') and 'expect' in r:
                line += '（期望 %s）' % r['expect']
            line += '\n      %s' % r.get('desc', '')
        print(line)

    # ⚠ **扫描范围无条件先说清楚**（第二条：在空集上跑出来的通过没有意义）。
    #    实测：mutations.json 为空时输出「KILLED 0 · SURVIVED 0」，
    #    看起来是"没问题"，实际是**配置空了 / 路径指错了**。
    #    ⛔ 失败模式是"返回 0 条"而不是"报错"，任何能跑通的检查都查不出来。
    print()
    print('扫描范围：变异定义 %d 条（来源 %s）'
          % (len(muts), args.mutations))
    if not muts:
        print('  ⛔ 0 条 = 空集上跑的通过没有意义 —— 检查路径或配置')
    print()
    print('合计：KILLED %d（已守住）· SURVIVED %d · NOT_APPLIED %d · NOT_COVERED %d'
          % (nk, ns, nn, nc))
    if nc:
        print()
        print('  ⛔ NOT_COVERED = 测试套件**不执行**该 target —— 伪装成 SURVIVED。')
        print('     判据：报 SURVIVED 前先确认测试真的会跑到那个文件。')
    if ns:
        print()
        print('  SURVIVED = 测试没抓到 = **盲区**。')
        print('  两类成因，处理方式不同：')
        print('    ① 真盲区 → 补自检用例')
        print('    ② 测试本来就不该管 → 改变异定义的 expect 并写明理由')
        print('  ⛔ 不能因为「看着绿」就删掉变异定义——那等于抹掉历史。')
    if nn:
        print()
        print('  NOT_APPLIED = 变异没生效 = **配置问题**，不是代码问题。')
        print('  多半是代码改过了，old 片段对不上 → 更新变异定义。')
        print('  ⛔ 它和测试通过是两回事，不要当成「守住了」。')

    sys.exit(OK if ns == 0 else BLOCKED)


if __name__ == '__main__':
    main()
