#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 md 正文里反引号包裹的文件引用是否真实存在。

⚠ 为什么查这个：接缝表与正文里大量写 `` `xxx.md` ``，这些是**普通文本**，
  ⛔ 不是【读】反引号锚点，所以断链检查**完全看不到它们**。

  实测后果：铺 vehicle / gem 两域时凭印象写文件名，写出 20 处断链
  （`physics-materials.md` / `netsync.md` / `save.md` / `inventory.md`
  全是想当然的拼法，实际文件是 physics.md / netsync-advanced.md /
  save-migration.md / flow 层功能点），
  ⛔ 而自检全程报「对称性 0 断链」—— 因为压根没检查这一类。

  ⚠ 这是「只查了一部分」的又一处：改了引用写法，检查没跟着改。

检查范围：flow/godot、howto/godot、audit/godot 下的全部 md。
"""
import os
import re
import sys

# ⓘ 按脚本位置推导，⛔ 不用绝对路径（换机器会静默检查不存在的目录 → 永远 0 处）
HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.abspath(os.path.join(HERE, '..', 'references'))

PAT = re.compile(r'`([A-Za-z0-9_\-/\.]+\.md)`')


def resolve(ref, src_dir):
    """把引用解析成磁盘路径；返回 None 表示无法解析。

    ⚠ 基准有两种，⛔ 不能统一按 references 根算：
      - 以 ../ 开头的**相对路径** → 基准是**引用所在文件的目录**
        （实测 audit/godot/index.md 引用 ../../../../code-audit/... 是跨 skill
        引用，从文件目录算 4 级正好到 skills/；按 references 根算会假阳性）
      - 其余显式路径（howto/godot/x.md、flow/godot/x/y.md）→ 基准是 references/
    """
    if ref.startswith('../'):
        return os.path.abspath(os.path.join(src_dir, ref))
    if '/' in ref:
        # 显式路径：howto/godot/x.md、audit/godot/x.md、flow/godot/x/y.md
        return os.path.join(REF, ref)
    # 纯文件名：howto 优先，其次 audit
    for sub in ('howto/godot', 'audit/godot'):
        p = os.path.join(REF, sub, ref)
        if os.path.exists(p):
            return p
    return os.path.join(REF, 'howto/godot', ref)


def scan():
    """返回 (total, bad)；bad 是 {引用: [文件]}。

    ⓘ 自检据此断言 total > 0 —— 防「扫描路径失效却静默返回 0 处」，
      那正是 verify.py 栽过的失败模式（检查没跑起来，却显示通过）。
    """
    if not os.path.isdir(REF):
        raise RuntimeError('references 目录不存在：%s' % REF)
    files = []
    # ⓘ craft 必须一起扫：新增层若不在扫描范围内，它内部的引用
    #   **完全不被检查** —— 而自检仍报「0 断链」（只查了一部分的又一例）。
    for sub in ('flow/godot', 'howto/godot', 'audit/godot', 'craft/godot'):
        d = os.path.join(REF, sub)
        for dd, _, fs in os.walk(d):
            for f in fs:
                if f.endswith('.md'):
                    files.append(os.path.join(dd, f))
    if not files:
        raise RuntimeError('未取到任何 md 文件（扫描路径失效）')

    bad = {}
    total = 0
    for f in files:
        try:
            t = open(f, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        for m in PAT.findall(t):
            total += 1
            p = resolve(m, os.path.dirname(f))
            if p is None or not os.path.exists(p):
                bad.setdefault(m, []).append(os.path.relpath(f, REF))
    return total, bad


def main():
    total, bad = scan()
    n = sum(len(v) for v in bad.values())
    if n:
        print('✗ md 正文引用断链 %d 处（共检查 %d 处引用）：' % (n, total))
        for k in sorted(bad):
            v = bad[k]
            print('   `%s`  (%d 处)  例: %s' % (k, len(v), v[0]))
        print('\n  → 改文件/改目录时同步改引用；纯文件名按 howto→audit 顺序解析')
        return 1
    print('md 引用校验：%d 处反引号文件引用，0 断链' % total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
