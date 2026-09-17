#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mutate.py — 变异测试：验证「测试有没有能力发现问题」

为什么需要
----------
`测试全绿` 只能证明**代码与测试当前一致**，证明不了测试有能力发现问题。
本脚本把**真实修过的缺陷**逐个注入回去，看测试会不会变红：

    KILLED      测试抓到了 —— 该缺陷被守住了
    SURVIVED    测试没抓到 —— 盲区，需补测试
    NOT_APPLIED 变异没生效 —— **脚本配置问题，不是代码问题**

三个必须做对的点（都是实战踩出来的）
-----------------------------------
1. **SURVIVED 与 NOT_APPLIED 必须分开**
   空变异（old 串没对上，代码压根没改）会让测试继续绿，
   被误判成「测试有盲区」。假信号比没信号更糟 ——
   会让人以为防护真有洞，去补不存在的测试。
   实测：一次报告了 5 个「漏网」，其中 2 个是空变异。

2. **测试套件自动发现，不手写列表**
   手写列表漏套件的后果同样是假信号 ——
   实测漏了一个套件，3 个变异被误报成盲区，实际全被那个套件抓到了。

3. **单实例锁用 PID 文件，不用 flock**
   flock 由内核在 fd 关闭时释放。进程被 timeout / SIGKILL 后 fd 不关，
   锁不释放 → 后续所有运行**永久卡死**（实测：遍历 /proc 找不到持锁进程，
   flock 仍返回 EAGAIN）。PID 文件能自愈：进程不存在就当锁已释放。

用法
----
    python3 mutate.py --src=<目标源码> --mutations=<定义.json> [--only=id1,id2]
    python3 mutate.py --src=<目标源码> --mutations=<定义.json> --check  # 只校验锚点
    python3 mutate.py --mutations=<定义.json> --list

定义文件格式（JSON 数组，字段见 README 段）：
    [{"id": "...", "desc": "...", "old": "...", "new": "..."}, ...]

只出候选，不是结论 —— SURVIVED 要人工判断是真盲区还是测试本来就不该管。
"""
import argparse

import contextlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exitcode import help_text,  ENV, USAGE, die   # 码表见 exitcode.py（AR-04）

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK_PATH = "/tmp/mutate.lock"
# 测试通过的标志串：与 scan-*.py 的 --self-test 判定风格保持一致
PASS_MARKS = ("ALL PASS", "总判定: ALL PASS")


def discover_tests(root="."):
    """自动发现测试套件（test_*.py）。

    不手写列表：手写会漏后加的套件，漏了就产生「假盲区」信号。
    """
    return sorted(f for f in os.listdir(root)
                  if f.startswith("test_") and f.endswith(".py"))


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                     # 存在但无权发信号 → 仍算活着
    return True


@contextlib.contextmanager
def single_instance_lock():
    """单实例锁（PID 标记文件，不是 flock —— 理由见模块 docstring）。

    测试套件常共用固定路径（如 /dev/shm 下的仓库与状态文件）。
    两个实例同时跑会互删对方的 fixture，表现为随机失败、基线不绿，
    极易误判成「代码 flaky」。
    """
    try:
        raw = open(LOCK_PATH).read().strip()
    except FileNotFoundError:
        raw = ""
    if raw.isdigit() and _pid_alive(int(raw)):
        # audit: ignore —— 单实例锁冲突时终止是 CLI 的职责；锁失败继续跑会互相删 fixture
        # 锁冲突是**环境/并发状态**，不是工具 bug：等一会儿重试即可，
        # 与「代码有问题」完全不同。用 ENV(3) 区分开（AR-04）。
        die(ENV,
            f"另一个 mutate.py 正在运行（PID {raw}，锁 {LOCK_PATH}）。\n"
            f"  测试套件共用固定路径，并发跑会互相删对方的 fixture，\n"
            f"  结果不可信。请等它结束；确认是僵死进程后可手动删除锁文件。"
        )
    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))
    try:
        yield
    finally:
        try:
            if open(LOCK_PATH).read().strip() == str(os.getpid()):
                os.unlink(LOCK_PATH)
        except (FileNotFoundError, ValueError):
            pass


def apply_mutation(src, mut):
    """返回 (新源码, old 的匹配处数)。匹配处数 != 1 就是空变异。"""
    n = src.count(mut["old"])
    if n != 1:
        return None, n
    return src.replace(mut["old"], mut["new"], 1), 1


def run_suite(script, target, timeout=180, root="."):
    """跑一个测试套件，返回 (是否通过, 输出)。"""
    try:
        p = subprocess.run([sys.executable, script, target],
                           cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    out = (p.stdout or "") + (p.stderr or "")
    return any(m in out for m in PASS_MARKS), out


def check_anchors(src, muts):
    """只校验锚点：每条 old 必须恰好匹配 1 处。

    代码改动后锚点会失效/变多处 —— 每次改完代码都应跑一遍，
    否则「KILLED」可能只是因为变异压根没生效。
    """
    bad = [(m["id"], src.count(m["old"])) for m in muts if src.count(m["old"]) != 1]
    # audit: ignore —— --check 模式就是只打印锚点报告，输出即它的职责
    # audit: ignore —— --check 模式的报告输出，输出即它的职责
    print(f"锚点检查：{len(muts)} 条")
    if bad:
        for mid, n in bad:
            # audit: ignore —— --check 模式的报告输出，输出即它的职责
            print(f"  ✗ {mid:<28} 匹配 {n} 处（应恰好 1 处）")
        return 1
    # audit: ignore —— --check 模式的逐条报告输出，输出即它的职责
    # audit: ignore —— --check 模式的报告输出，输出即它的职责
    print("  ✓ 全部唯一命中")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="变异测试：注入真实修过的缺陷，验证测试能否发现", epilog=help_text())
    ap.add_argument("--src", help="被变异的目标源码文件")
    ap.add_argument("--mutations", required=True, help="变异定义 JSON 文件")
    ap.add_argument("--tests-root", default=".", help="测试套件所在目录（默认当前）")
    ap.add_argument("--check", action="store_true", help="只校验锚点，不跑测试")
    ap.add_argument("--only", help="只跑指定变异（逗号分隔 id）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--keep", action="store_true", help="保留变异后的源码文件")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    with open(args.mutations, encoding="utf-8") as f:
        muts = json.load(f)
    for m in muts:                      # 定义文件自检
        if not all(k in m for k in ("id", "desc", "old", "new")):
            raise SystemExit(f"变异定义缺字段: {m.get('id', m)}")

    if args.list:
        for m in muts:
            print(f"  {m['id']:<28} {m['desc']}")
        return 0

    if not args.src:
        # 缺必填参数 = 用法错误，用 USAGE(2) 与真出错分开（AR-04）
        die(USAGE, "需要 --src=<目标源码>（--list / --check 除外）")

    src = open(args.src, encoding="utf-8").read()
    target = os.path.abspath(args.src)
    if args.check:
        return check_anchors(src, muts)

    tests = discover_tests(args.tests_root)
    if not tests:
        raise SystemExit(f"{args.tests_root} 下没有 test_*.py —— 没有测试可验证，"
                         f"变异测试无意义。")
    print(f"目标      : {target}")
    print(f"变异定义  : {args.mutations}（{len(muts)} 条）")
    print(f"测试套件  : {len(tests)} 个（自动发现）")
    for t in tests:
        print(f"   - {t}")
    print()

    with single_instance_lock():
        # 基线：未变异时必须全绿，否则后面所有结论都不可信
        print("=== 基线（未变异）===")
        base_ok = all(run_suite(t, target, args.timeout, args.tests_root)[0]
                      is True for t in tests)
        for t in tests:
            ok, _ = run_suite(t, target, args.timeout, args.tests_root)
            print(f"  {'PASS' if ok else 'FAIL'}  {t}")
        if not base_ok:
            print("\n基线不绿 —— 先修测试，变异结果无意义。")
            return 1
        print("  基线全绿 ✓\n")

        todo = muts
        if args.only:
            want = set(args.only.split(","))
            todo = [m for m in muts if m["id"] in want]

        results = []
        for m in todo:
            mutated, n = apply_mutation(src, m)
            if mutated is None:
                results.append((m, "NOT_APPLIED", []))
                print(f"  ⚠️  {m['id']:<28} NOT_APPLIED（old 匹配 {n} 处，应恰好 1）")
                continue

            tmp = os.path.join(args.tests_root, f"_mut_{m['id']}.py")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(mutated)

            killed_by = []
            for t in tests:
                ok, _ = run_suite(t, os.path.abspath(tmp), args.timeout, args.tests_root)
                if not ok:
                    killed_by.append(t)
                    break               # 一个套件抓到就算 KILLED
            verdict = "KILLED" if killed_by else "SURVIVED"
            results.append((m, verdict, killed_by))
            extra = f"（{killed_by[0]} 抓到）" if killed_by else "（盲区！）"
            print(f"  {'✓' if killed_by else '✗'} {m['id']:<28} {verdict}{extra}")

            if not args.keep:
                os.unlink(tmp)

    killed = [r for r in results if r[1] == "KILLED"]
    survived = [r for r in results if r[1] == "SURVIVED"]
    empty = [r for r in results if r[1] == "NOT_APPLIED"]

    print("\n" + "=" * 62)
    print(f"变异总数    : {len(results)}")
    print(f"  KILLED    : {len(killed)}  （测试守住了）")
    print(f"  SURVIVED  : {len(survived)}  （盲区，需补测试）")
    print(f"  NOT_APPLIED: {len(empty)}  （变异没生效，是配置问题不是代码问题）")
    if killed or survived:
        score = 100.0 * len(killed) / (len(killed) + len(survived))
        print(f"\n变异得分    : {score:.0f}%  （KILLED / (KILLED+SURVIVED)）")

    if empty:
        print("\n--- NOT_APPLIED：old 串没对上，改的是 mutate 定义不是代码 ---")
        for m, _, _ in empty:
            print(f"  {m['id']}: {m['desc']}")
    if survived:
        print("\n--- SURVIVED：真盲区，需要补测试 ---")
        for m, _, _ in survived:
            print(f"  {m['id']}: {m['desc']}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
