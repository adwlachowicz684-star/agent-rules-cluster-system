#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流程层代码块自包含检查（check-code-blocks.py）

查什么：
    flow/godot/**/*.md 里的 ```gdscript 代码块，用到的**裸常量**
    （如 JUMP_VELOCITY / MAX_BATCH）有没有"出处"。

为什么查：
    流程文档是逐步叠加的，作者常把常量声明写在"Step 1 的变量块"或
    "§3 参考实现"里，后面每个 Step 的片段直接引用。
    ⛔ 读者单独复制某一段 → 未声明标识符，跑不起来 —— 而 SKILL.md
       核心原则第 1 条正是"给能跑的完整代码，不给片段"。

判据（二选一即合规）：
    (a) 代码块**内部**有该常量的声明（const / var / @export var / enum 成员）
    (b) 代码块内的注释**点名**了该常量（如 "# 承接 Step 1：JUMP_VELOCITY"）
        ⓘ (b) 不是放水：它要求把依赖写清楚，读者知道要先声明什么。

不查的：
    - 带 `.` 的 API 成员（Control.PRESET_FULL_RECT、FileAccess.READ）
    - Godot 内置全局常量/枚举（KEY_*、ERR_*、PROCESS_MODE_*、INF …）
    - 注释行与字符串里出现的词

用法：
    python3 scripts/check-code-blocks.py [--json]
退出码：0 无问题 / 1 有缺口
"""

import os
import re
import sys
import glob
import json as _json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
FLOW = os.path.join(ROOT, 'references', 'flow')

# Godot 内置：全局常量、枚举成员、内建类名。不需要读者自己声明。
BUILTIN = {
    'KEY_SPACE', 'KEY_A', 'KEY_D', 'KEY_J', 'KEY_W', 'KEY_S', 'KEY_LEFT',
    'KEY_RIGHT', 'KEY_UP', 'KEY_DOWN', 'KEY_ESC', 'KEY_ENTER',
    'INF', 'NAN', 'PI', 'TAU', 'OK', 'FAILED',
    'PROCESS_MODE_ALWAYS', 'PROCESS_MODE_INHERIT', 'PROCESS_MODE_PAUSABLE',
    'PROCESS_MODE_DISABLED', 'PROCESS_MODE_WHEN_PAUSED',
    'ERR_INVALID_DATA', 'ERR_ALREADY_IN_USE', 'ERR_INSUFFICIENT_SPACE',
    'ERR_FILE_NOT_FOUND', 'ERR_CANT_OPEN', 'ERR_PARSE_ERROR',
    'HORIZONTAL_ALIGNMENT_CENTER', 'HORIZONTAL_ALIGNMENT_LEFT',
    'HORIZONTAL_ALIGNMENT_RIGHT', 'VERTICAL_ALIGNMENT_CENTER',
    'ATTENUATION_INVERSE_DISTANCE', 'ATTENUATION_INVERSE_SQUARE_DISTANCE',
    'ATTENUATION_LOGARITHMIC', 'ATTENUATION_DISABLED',
    'JSON', 'XML', 'CSV', 'UTF', 'BOM', 'HMAC', 'SHA', 'AES', 'PCK', 'ZIP',
    'RPC', 'FSM', 'LOD', 'BGM', 'SFX', 'HUD', 'API', 'URL',
}

# 裸常量：前面不能是 . 或单词字符（排除 Control.PRESET_X 这类成员访问）
USE = re.compile(r'(?<![\.\w])([A-Z][A-Z0-9_]{2,})\b')
DEC = re.compile(r'^\s*(?:const|var|@export\s+var|@onready\s+var)\s+([A-Z][A-Z0-9_]{2,})\b', re.M)
ENUM = re.compile(r'enum\s*(?:\w+)?\s*\{([^}]*)\}', re.S)


def strip_noise(blk):
    """去掉注释与字符串字面量，只留代码本体。"""
    out = []
    for line in blk.split('\n'):
        s = line.split('#')[0]
        s = re.sub(r'"[^"]*"', '""', s)
        out.append(s)
    return '\n'.join(out)


def count_blocks():
    """⛔ 自检必须取到样本：扫描路径失效时 scan() 恒返回空 → 假性全绿。"""
    n = 0
    for f in sorted(glob.glob(os.path.join(FLOW, '**', '*.md'), recursive=True)):
        if os.path.basename(f).startswith('_'):
            continue
        n += len(re.findall(r'```gdscript\n(.*?)```',
                            open(f, encoding='utf-8').read(), re.S))
    return n


def scan():
    """返回 [(文件, 块序号, [缺失常量...]), ...]"""
    bad = []
    for f in sorted(glob.glob(os.path.join(FLOW, '**', '*.md'), recursive=True)):
        if os.path.basename(f).startswith('_'):
            continue
        txt = open(f, encoding='utf-8').read()
        for i, blk in enumerate(re.findall(r'```gdscript\n(.*?)```', txt, re.S)):
            code = strip_noise(blk)
            decl = set(DEC.findall(code))
            for e in ENUM.findall(code):
                decl |= set(re.findall(r'([A-Z][A-Z0-9_]{2,})', e))
            miss = sorted(set(USE.findall(code)) - decl - BUILTIN)
            if not miss:
                continue
            # (b) 注释里点名了 → 已声明依赖，合规
            comments = '\n'.join(
                l for l in blk.split('\n') if l.lstrip().startswith('#'))
            miss = [m for m in miss if m not in comments]
            if miss:
                bad.append((os.path.relpath(f, ROOT), i, miss))
    return bad


def main():
    bad = scan()
    if '--json' in sys.argv:
        print(_json.dumps({'missing': len(bad), 'detail': bad}, ensure_ascii=False))
        return 1 if bad else 0
    if bad:
        print('代码块自包含检查：%d 个块存在无出处常量\n' % len(bad))
        for f, i, m in bad:
            print('  ✗ %s 块#%d: %s' % (f, i, ', '.join(m)))
        print('\n修法：块内补 const 声明，或在块内注释点名来源（如「# 承接 Step 1：X」）')
    else:
        print('代码块自包含检查：全部 gdscript 块的常量都有出处 ✓')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
