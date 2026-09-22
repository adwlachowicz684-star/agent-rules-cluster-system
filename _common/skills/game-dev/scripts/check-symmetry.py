#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
howto ↔ audit 对称性扫描（ⓘ 只作参考，不强求一对一）。

背景：audit 是「不能怎么做」，howto 是「怎么做」。
若 audit 里出现了一个技术点，而 howto 里从头到尾没提过它，
这条审核项就无处可依 —— 审核时无法确认为什么不能这么做，
改的时候也不知道该怎么做。这类断链会随文档增多而累积。

⚠ 边界（重要）：
  - **不要求一对一**：全局性内容（如"参数类型不符"）横跨所有域，
    ⛔ 不可能每个功能里单独写一份。这类内容放 `common/audit/global.md`，
    通过锚点被多个域引用，**不强求 howto/godot 里也有一份**。
  - **多对多**：一个全局块可被多个域引用，一个域也可引用多个块。
    判定"已覆盖"时，指向的 common 块内容也算覆盖。
  - 因此本扫描只是**提示**，用于发现"确实漏了"的项，
    ⛔ 不是"必须清零"的硬性约束。

判据：从 audit 表格的「实际」列抽取技术标识（类名 / API / 常量 / 属性名），
      在对应 howto 全文里查找。未命中 = 不对称。
"""
import os, re, sys, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'references')
HOWTO = os.path.join(ROOT, 'howto', 'godot')
AUDIT = os.path.join(ROOT, 'audit', 'godot')

# 技术标识：类名(大驼峰)、snake_case API、SCREAMING_CASE 常量、带点的属性
# ⚠ 不能用 \b：下划线是单词字符，`focus_neighbor_*` 里的 token 后面跟 `_` 时
#    \b 无法成立，会导致整个 token 提取不到（漏报）。改用显式的前后断言。
TOKEN = re.compile(r'(?<![A-Za-z0-9_])([A-Z][A-Za-z0-9]*(?:3D|2D)?|_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+|[A-Z][A-Z0-9_]{3,}|[a-z][a-z0-9]*\.[a-z_][a-z0-9_]*)(?![A-Za-z0-9_])')

# 过滤噪声：通用词、中文里常见的英文、表格格式词
NOISE = {
    'Area3D', 'Node', 'Node3D', 'Godot', 'CPU', 'GPU', 'UI', 'ID', 'NPC',
    'RTS', 'MMO', 'DLC', 'API', 'SDK', 'JSON', 'XML', 'HTML', 'URL',
    'PROCESS_MODE_PAUSABLE', 'PROCESS_MODE_ALWAYS', 'PROCESS_MODE_DISABLED',
    'PROCESS_MODE_INHERIT', 'PROCESS_MODE_WHEN_PAUSED',
    # 通用词：出现在审核项里不代表该文档需要专门讲它
    'HTTP', 'HTTPS', 'FROM', 'WHERE', 'SELECT', 'DELETE', 'UPDATE',
    'Tooltip', 'RigidBody3D', 'RigidBody2D', 'CharacterBody3D', 'Area2D',
    'NavigationAgent2D', 'NavigationAgent3D', 'Tween', 'Timer',
    'RandomNumberGenerator',
}

# 只认「看起来像技术标识」的：含下划线(API名) 或 大驼峰类名 或 含点属性
def is_tech(tok: str) -> bool:
    if tok in NOISE:
        return False
    if re.fullmatch(r'GD\d+', tok):        # 规则编号，不是技术标识
        return False
    if re.fullmatch(r'[A-Z][A-Z0-9_]{3,}', tok) and '_' not in tok and '.' not in tok:
        # 全大写枚举常量：保留（是有意义的状态名），但排除过短的
        pass
    if '.' in tok:                      # 属性 / 方法调用
        return len(tok) > 3
    if '_' in tok:                      # snake_case API
        return len(tok) > 5
    if re.fullmatch(r'[A-Z][A-Z0-9_]{3,}', tok):   # 常量
        if tok in {'READY', 'PAUSED', 'STEP', 'JOINT'}:   # 过于通用，误伤大
            return False
        return True
    if re.fullmatch(r'[A-Z][A-Za-z0-9]*(?:3D|2D)?', tok):   # 类名
        return len(tok) >= 5
    return False


def common_pool():
    """全局层（common/）里讲过的技术点。

    ⓘ 为什么算覆盖：全局块是"不可能每个域单独写"的内容，
      通过锚点被多个域引用。若要求每个域都自带一份，
      就退化成几十处重复，改一处要改几十处。
    """
    pool = set()
    for sub in ('howto', 'audit'):
        d = os.path.join(ROOT, 'common', sub)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.endswith('.md'):
                pool |= set(TOKEN.findall(
                    open(os.path.join(d, f), encoding='utf-8').read()))
    return pool


COMMON = None


def howto_tokens(name: str):
    p = os.path.join(HOWTO, name)
    if not os.path.isfile(p):
        return None
    return set(TOKEN.findall(open(p, encoding='utf-8').read()))


def stats():
    """输入语料计数。

    ⚠ 注意：这里**不**统计"断链数"—— 断链为 0 是好状态，
       ⛔ 断言输出非空会导致"修完问题反而失败"。只断言输入。
    """
    def _n(d):
        return len([f for f in os.listdir(d) if f.endswith('.md')]) \
            if os.path.isdir(d) else 0
    aud = _n(AUDIT)
    # 提取到的技术点总数：扫描器若失效（正则/路径），这里会是 0
    toks = 0
    for fn in sorted(os.listdir(AUDIT)) if os.path.isdir(AUDIT) else []:
        if not fn.endswith('.md'):
            continue
        txt = open(os.path.join(AUDIT, fn), encoding='utf-8', errors='replace').read()
        toks += len([t for t in TOKEN.findall(txt) if is_tech(t)])
    return {'audit_docs': aud, 'howto_docs': _n(HOWTO),
            'tech_tokens': toks}


def scan():
    global COMMON
    if COMMON is None:
        COMMON = common_pool()
    out = []
    for fn in sorted(os.listdir(AUDIT)):
        if not fn.endswith('.md'):
            continue
        ht = howto_tokens(fn)
        if ht is None:
            continue            # howto 不存在 = 镜像缺失，由别的自检管
        txt = open(os.path.join(AUDIT, fn), encoding='utf-8').read()
        # 只看表格行（以 | 开头），取「实际」列（最后一列）
        miss = {}
        for line in txt.split('\n'):
            line = line.strip()
            if not line.startswith('|') or line.startswith('|--') or '---' in line[:6]:
                continue
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) < 3:
                continue
            # ⓘ 扫整行而不是只扫最后一列：技术点同样常出现在「本能以为」列
            #   （如 `| 用 Tween 绑自身 | ... |`），只看末列会漏。
            actual = ' '.join(cells[1:])       # 去掉序号列
            # ⓘ 豁免一：带 GD 规则编号的行由**自动审查规则**覆盖
            #   （godot-audit.py 会直接扫代码报错），不依赖 howto 也讲一遍。
            if re.search(r'\bGD\d+', actual):
                continue
            # ⓘ 豁免二：index.md 的「常见漏写速查」是**跨所有域的全局表**，
            #   它不属于任何单一 howto 域 —— 强制对称会永远报红。
            #   这正是"全局层内容不必一对一"的情况（见 common/index.md）。
            if fn == 'index.md':
                continue
            if '实际' in actual and '本能' in actual:
                continue        # 表头
            # 若该行已给出指向，就到目标文件里找，不再算断链
            refs = re.findall(r'→\s*`([A-Za-z0-9_-]+\.md)`', actual)
            extra = set()
            for r in refs:
                rp = os.path.join(HOWTO, r)
                if os.path.isfile(rp):
                    extra |= set(TOKEN.findall(open(rp, encoding='utf-8').read()))
            pool = ht | extra | COMMON
            line_toks = [t for t in TOKEN.findall(actual) if is_tech(t)]
            for tok in TOKEN.findall(actual):
                if not is_tech(tok):
                    continue
                # ⓘ 类名的 3D/2D 后缀是常见写法差异，不算断链（CPUParticles ↔ CPUParticles3D）
                if tok in pool:
                    continue
                # 命名差异：token 是 pool 中某项的子串（combo_scaling ↔ combo scaling 之外的
                # 前后缀写法），且够长才认，避免短词误杀
                if len(tok) >= 6 and any(tok in t or t in tok for t in pool if len(t) >= 6):
                    continue
                # 同行里另一个 token 已覆盖 → 讲的是同一话题（distance_to ↔ distance_squared_to）
                if any(other in pool and (tok in other or other in tok) for other in line_toks if len(other) >= 6):
                    continue
                if any(tok + suf in pool for suf in ('2D', '3D')):
                    continue
                if any(tok.endswith(suf) and tok[:-2] in pool for suf in ('2D', '3D')):
                    continue
                # 下划线 ↔ 空格 的写法差异也不算（combo_scaling ↔ combo scaling）
                if tok.replace('_', ' ') in ' '.join(pool):
                    continue
                miss.setdefault(tok, actual[:60])
        if miss:
            out.append({'file': fn, 'miss': miss})
    return out


def guard():
    """ⓘ 独立运行时也自检输入语料。"""
    try:
        import corpus_guard
        _, fails = corpus_guard.run([sys.modules[__name__]])
        for f in fails:
            print('✗ ' + f, file=sys.stderr)
        return not fails
    except Exception as e:
        # ⚠ 必须 **fail-closed**：守卫自身出错时拒绝放行。
        #   上一版写的 `return True` 等于"守卫坏了 = 检查通过"，
        #   ⛔ 这正是本模块要消灭的那类静默放行 —— 在自己身上又犯了一次。
        print('⛔ 语料守卫不可用，拒绝放行（%s）' % e, file=sys.stderr)
        return False


if __name__ == '__main__':
    if not guard():
        sys.exit(2)
    res = scan()
    if '--json' in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(0)
    total = sum(len(r['miss']) for r in res)
    print('howto ↔ audit 不对称扫描：%d 个文件存在 audit 有、howto 无的技术点，共 %d 个\n' % (len(res), total))
    for r in sorted(res, key=lambda x: -len(x['miss'])):
        print('■ %s  (%d)' % (r['file'], len(r['miss'])))
        for tok, ctx in sorted(r['miss'].items()):
            print('   %-34s  %s' % (tok, ctx))
