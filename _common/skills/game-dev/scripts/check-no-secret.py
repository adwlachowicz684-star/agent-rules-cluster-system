#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库内禁止出现明文凭据。

⚠ 为什么查这个：token 曾硬编码在 5 个脚本里，其中 4 个在 arcs3 之外、
  1 个（历史上）.tools 在库内 —— ⛔ 一旦被推送就是公开泄露。
  统一改走 gh_auth 之后，需要一条**防止回潮**的检查：
  有人（包括我）图省事把 token 粘回脚本里时，这里要报出来。

检查范围：arcs3/ 全部文本文件。
"""
import os
import re
import sys

# ⓘ 按脚本位置推导仓库根，⛔ 不用绝对路径：脚本在库内，
#   换机器/换克隆位置都能跑（绝对路径会静默检查一个不存在的目录 → 永远 0 处）。
ROOT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..'))
# ⓘ GitHub 各代 token 前缀；也扫"像 token 的长串"以防漏掉新格式
PATS = [
    ('GitHub PAT', re.compile(r'github_pat_[A-Za-z0-9_]{20,}')),
    ('ghp/gho/ghu/ghs/ghr', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}')),
    ('40 位十六进制', re.compile(r'\b[0-9a-f]{40}\b')),
]
SKIP_DIR = {'.git', '__pycache__', 'node_modules'}
SKIP_EXT = {'.png', '.jpg', '.zip', '.pyc', '.ttf', '.ogg', '.wav'}


def main():
    bad = []
    for d, ds, fs in os.walk(ROOT):
        ds[:] = [x for x in ds if x not in SKIP_DIR]
        for f in fs:
            if os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            p = os.path.join(d, f)
            try:
                t = open(p, encoding='utf-8').read()
            except (OSError, UnicodeDecodeError):
                continue
            for name, rx in PATS:
                m = rx.search(t)
                if m:
                    bad.append('%s：%s（%s…）'
                               % (os.path.relpath(p, ROOT), name, m.group(0)[:12]))
                    break
    if bad:
        print('✗ 仓库内发现明文凭据 %d 处：' % len(bad))
        for x in bad[:10]:
            print('   ', x)
        print('\n  → 改用 gh_auth.get_token()（环境变量或 /data/workspace/.git_token）')
        return 1
    print('凭据扫描：arcs3 内无明文 token（0 处）')

    # ⚠ 凭据文件权限：它在库外不会被推送，但 777 在多用户/多进程环境是真实泄露面。
    #   ⓘ 沙盒文件系统上 chmod 600 可能不生效（实测改完仍是 777），
    #     所以这里**告警而不判失败** —— 否则在某些环境会永久报红掩盖真问题。
    cred = os.path.join(os.path.dirname(ROOT), '.git_token')
    if os.path.exists(cred):
        mode = os.stat(cred).st_mode & 0o777
        if mode & 0o077:
            print('⚠ 凭据文件权限过宽：%s 当前 %o（期望 600）；'
                  '沙盒可能不允许 chmod，仅提示' % (cred, mode))
    return 0


if __name__ == '__main__':
    sys.exit(main())
