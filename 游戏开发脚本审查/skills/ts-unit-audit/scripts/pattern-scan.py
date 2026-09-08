#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pattern-scan.py —— TypeScript / JavaScript 库缺陷模式自动扫描

模式库来源：对 240+ 条真实 P0/P1 缺陷（多轮人工审核，覆盖 119 个单元）聚类所得。
目的：把历史教训变成可执行的检查，在人工精审前先机器过一遍。

用法：
    python3 pattern-scan.py --src=<源码根>                  # 扫全部模块
    python3 pattern-scan.py --src=<根> moduleA moduleB      # 只扫指定模块
    python3 pattern-scan.py --src=<根> --p0                 # 只显示致命级
    python3 pattern-scan.py --src=<根> --pattern=A01        # 只扫某条模式
    python3 pattern-scan.py --src=<根> --json               # 机器可读
    python3 pattern-scan.py --src=<根> --flat               # 扁平结构
    python3 pattern-scan.py --self-test                     # 注入故障自检

--src 指向「模块根目录」：其下每个一级子目录视为一个模块。
若源码是扁平结构（根下直接是文件），用 --flat。

--self-test 构造含已知缺陷的临时代码，验证每条模式能否检出。
永远返回 0 命中的检查等于没有检查，改模式后应跑一次自检。
"""

import re
import os
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

if SRC is None:
    for cand in ('src', '.'):
        if os.path.isdir(cand):
            SRC = os.path.abspath(cand)
            break

if '--self-test' not in _flags:
    if SRC is None or not os.path.isdir(SRC):
        print('找不到源码目录，请用 --src=<路径> 指定')
        sys.exit(1)

FLAT = '--flat' in _flags
SKIP_DIRS = {'tests', 'test', 'examples', 'example', 'scripts', 'typings',
             'node_modules', '.build', 'build', 'dist', 'audit', 'docs',
             '__tests__', '__pycache__', '.git'}
SKIP_PREFIX = ('.', '_')
SOURCE_EXT = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs')

BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)
LINE_COMMENT = re.compile(r'^\s*//.*$', re.M)


def _strip_line_comments(src):
    """剥离开注解（含**行尾**注释），替换成等长空格。

    为什么不能用 `^\s*//.*$` 只剥整行注释：
    代码后跟的注释同样会参与模式匹配。实测 `const a = 1; // clamp(opts.x, 0, 1)`
    会让 A03 把注释里的 clamp 当成真代码报出来。

    为什么不用简单的 `//.*`：会误伤两处——
      · URL 协议 `https://example.com` 里的 `//`
      · 字符串里的 `"//path/to"`
    所以用「前一个字符不是 `:`」+「该行此前引号数为偶数」两个条件排除。
    跨行模板字符串内的 `//` 不在处理范围（罕见，且代价高于收益）。
    """
    out = []
    for line in src.split('\n'):
        i = 0
        n = len(line)
        while i < n - 1:
            if line[i] == '/' and line[i + 1] == '/':
                prev = line[i - 1] if i > 0 else ''
                head = line[:i]
                # 引号计数需排除转义引号
                unescaped_q = head.replace('\\"', '').replace("\\'", '')
                q_even = (unescaped_q.count('"') + unescaped_q.count("'")) % 2 == 0
                if prev != ':' and q_even:
                    line = line[:i] + ' ' * (n - i)
                    break
                i += 2
                continue
            i += 1
        out.append(line)
    return '\n'.join(out)


def strip_comments(src):
    """把注释替换成**等长空白**。

    为什么是"替换成空格"而不是"删掉"：
    注释参与匹配会误报（注释里写的 `clamp(opts.x)` 也会被当成真代码），
    但直接删除会让后续所有行号整体前移——实测 93% 的文件受影响，
    最大偏移 85 行，报告出来的行号全部不可信。
    替换成等长空格可以做到：行数不变、列位置不变、注释内容不再参与匹配。
    """
    def _blank(m):
        return ''.join(ch if ch == '\n' else ' ' for ch in m.group(0))
    src = BLOCK_COMMENT.sub(_blank, src)
    return _strip_line_comments(src)


def _read_files(dirpath):
    files = {}
    for fn in sorted(os.listdir(dirpath)):
        if fn.endswith(SOURCE_EXT):
            files[fn] = strip_comments(
                open(os.path.join(dirpath, fn), encoding='utf-8',
                     errors='ignore').read())
    return files


def load_plugins(only=None):
    """返回 {模块名: {文件名: 清洗后源码}}"""
    out = {}
    if FLAT:
        files = _read_files(SRC)
        if files:
            out[os.path.basename(SRC.rstrip('/')) or 'root'] = files
        return out
    for d in sorted(os.listdir(SRC)):
        p = os.path.join(SRC, d)
        if not os.path.isdir(p) or d in SKIP_DIRS or d.startswith(SKIP_PREFIX):
            continue
        if only and d not in only:
            continue
        files = _read_files(p)
        if files:
            out[d] = files
    return out


# ============================================================
# 模式库
# 每条：id, 等级, 名称, 说明, 检测函数(module, files) -> [(file, line, snippet)]
# ============================================================

PATTERNS = []


def pattern(pid, level, name, desc):
    def deco(fn):
        PATTERNS.append({'id': pid, 'level': level, 'name': name,
                         'desc': desc, 'fn': fn})
        return fn
    return deco


def iter_lines(files):
    for fn, src in files.items():
        for i, ln in enumerate(src.split('\n'), 1):
            yield fn, i, ln


def _body_of(src, m, limit=4000):
    """取函数体（从 m.end() 开始的第一个完整 {} 块）"""
    depth, j = 0, len(src)
    for k in range(m.end() - 1, min(len(src), m.end() + limit)):
        if src[k] == '{':
            depth += 1
        elif src[k] == '}':
            depth -= 1
            if depth == 0:
                return src[m.end():k]
    return src[m.end():m.end() + min(2000, limit)]

# ---------- A 族：NaN 穿透与守卫失效 ----------

@pattern('A01', 'P0', '守卫用 <=0/<0 挡不住 NaN',
         'NaN 参与所有比较恒为 false，守卫失效。应写 !(x>0) 或 Number.isFinite')
def a01(plugin, files):
    hits = []
    # if (x <= 0) / if (x < 0) / while (i < n) 类数值守卫
    for fn, i, ln in iter_lines(files):
        for m in re.finditer(r'\b(?:if|while)\s*\(\s*(?:!?\s*)?([A-Za-z_$][\w.$]*)\s*'
                             r'(<=|<|>=|>)\s*([0-9.]+)\s*\)', ln):
            var, op, num = m.groups()
            # 排除明显是下标/长度的（这些是整数循环，不是数值守卫）
            if re.search(r'length|size|count|index|idx|\bi\b$|\bj\b$', var, re.I):
                continue
            hits.append((fn, i, ln.strip()[:90]))
            break
    return hits


@pattern('A02', 'P0', '?? 默认值未收口（只挡 undefined，不挡 NaN/Infinity）',
         '配置字段用 opts.x ?? d 而非 clampNum/numOr，NaN 长驱直入')
def a02(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'\?\?\s', ln) and not re.search(r'clampNum|numOr|Math\.max\(', ln):
            # 排除字符串/布尔默认值
            if re.search(r"''|\"\"|true|false|'[^']*'|\{\}|\[\]", ln):
                continue
            hits.append((fn, i, ln.strip()[:90]))
    return hits


@pattern('A03', 'P0', 'clamp/clamp01 对 NaN 原样返回 → 穿透',
         '_core 的 clamp 用比较实现，NaN 两个分支都 false 直接穿透')
def a03(plugin, files):
    hits = []
    for fn, src in files.items():
        # 只报裸 clamp / clamp01 —— 它们用比较实现，NaN 两个分支都 false → 原样穿透
        # **clampNum / numOr 不算问题**：内部走 numOr(v, NaN) + isNaN → fallback，
        # 非有限值有兜底，不会穿透。把它们算进来会淹没真问题。
        for m in re.finditer(r'\bclamp(01)?\s*\(\s*([^,()]+),', src):
            arg = m.group(2).strip()
            line = src[:m.start()].count('\n') + 1
            # 若参数直接来自外部字段（.xx / opts. / ctx.）且附近无 isFinite
            if re.search(r'(opts|cfg|config|ctx|d|def|data)\.', arg):
                near = '\n'.join(src.split('\n')[max(0, line - 6):line])
                if 'isFinite' not in near and 'numOr' not in near:
                    hits.append((fn, line, f'clamp({arg}, ...)'))
    return hits


@pattern('A04', 'P0', '状态字段被 NaN 污染后不可逆（累加/EMA 类）',
         '如 _smoothPerf/_progress/余额：一次 NaN 后每帧 lerp(NaN,..)=NaN，永不恢复')
def a04(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'this\.(_\w+)\s*(?:-=|\+=|=\s*lerp|=\s*this\.\1\s*\*)', src):
            field = m.group(1)
            line = src[:m.start()].count('\n') + 1
            ctx = '\n'.join(src.split('\n')[max(0, line - 8):line + 3])
            if 'isFinite' in ctx:
                continue
            hits.append((fn, line, f'this.{field} 累加/EMA 无有限性守卫'))
    return hits


@pattern('A05', 'P1', '>>> 0 / |0 把 NaN 静默变成 0',
         '位运算对 NaN 得 0，seed 类参数静默退化（所有随机地图变成同一张）')
def a05(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'>>+\s*0|\|\s*0(?![.\d])', ln):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- B 族：循环/递归不收敛 ----------

@pattern('B01', 'P0', '循环上界来自入参且未收口（Infinity/NaN → 死循环）',
         'octaves/samples/maxRadius 等来自配置，未 clamp 会挂死主线程')
def b01(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\bfor\s*\(\s*let\s+\w+\s*=\s*[^;]+;\s*\w+\s*<\s*'
                             r'([A-Za-z_$][\w.$]*)\s*;', src):
            bound = m.group(1)
            if re.search(r'^\d+$', bound):
                continue
            line = src[:m.start()].count('\n') + 1
            ctx = '\n'.join(src.split('\n')[max(0, line - 10):line])
            if re.search(r'clamp|Math\.min|isFinite', ctx):
                continue
            hits.append((fn, line, f'for (...; i < {bound}; ...)'))
    return hits


@pattern('B02', 'P0', 'while 循环的退出条件可能被 NaN/Infinity 绕过',
         'radius *= 2 且退出条件 radius >= maxRadius，maxRadius=Infinity 时永不退出')
def b02(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\bwhile\s*\(([^)]{3,80})\)', src):
            cond = m.group(1)
            line = src[:m.start()].count('\n') + 1
            body_start = m.end()
            body = src[body_start:body_start + 400]
            # 有自增/倍增但退出条件依赖外部上界
            if re.search(r'\*=\s*2|\+\+|\+=', body):
                if re.search(r'Infinity|maxRadius|maxStep|limit', cond + body):
                    hits.append((fn, line, f'while ({cond.strip()})'))
    return hits


@pattern('B03', 'P0', '递归无访问集/深度上限（互相引用 → 栈溢出）',
         '子表互引用、嵌套材料树等场景')
def b03(plugin, files):
    hits = []
    for fn, src in files.items():
        # 找 self.method( 形式的自递归
        for m in re.finditer(r'this\.(\w+)\s*\(', src):
            name = m.group(1)
            # 该函数定义体内是否再次调用自己
            dm = re.search(r'^\s*(?:private\s+|public\s+)?' + re.escape(name) +
                           r'\s*\([^)]*\)[^{]*\{', src, re.M)
            if not dm:
                continue
            depth, j = 0, dm.end() - 1
            for k in range(dm.end() - 1, min(len(src), dm.end() + 4000)):
                if src[k] == '{':
                    depth += 1
                elif src[k] == '}':
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
            body = src[dm.end():j]
            if re.search(r'this\.' + re.escape(name) + r'\s*\(', body):
                line = src[:m.start()].count('\n') + 1
                if not re.search(r'visiting|visited|seen|depth|guard', body):
                    hits.append((fn, line, f'this.{name}() 自递归，无访问集/深度上限'))
                break
    return hits


# ---------- C 族：原型链污染 ----------

@pattern('C01', 'P0', '裸 Record 查表命中 Object.prototype',
         'TABLE[k] 或 k in TABLE，k 来自外部输入时会取到 toString/constructor 等')
def c01(plugin, files):
    hits = []
    for fn, src in files.items():
        # const X: Record<...> = { ... }  或  const X = { ... } 后跟 [k] 索引
        tables = re.findall(r'const\s+([A-Z][A-Z_0-9]*)\s*(?::\s*Record<[^>]*>)?\s*=\s*\{', src)
        for t in tables:
            for m in re.finditer(re.escape(t) + r'\s*\[\s*([A-Za-z_$][\w.$]*)\s*\]', src):
                line = src[:m.start()].count('\n') + 1
                near = '\n'.join(src.split('\n')[max(0, line - 4):line + 1])
                if 'hasOwnProperty' in near or 'Object.create(null)' in near:
                    continue
                hits.append((fn, line, f'{t}[{m.group(1)}]'))
        for t in tables:
            for m in re.finditer(r'\b([A-Za-z_$][\w.$]*)\s+in\s+' + re.escape(t) + r'\b', src):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, f'{m.group(1)} in {t}'))
    return hits


@pattern('C02', 'P1', '用 {} 字面量累加计数（key 为 __proto__ 时丢失）',
         'tally/rarity 等按 id 累加的场景')
def c02(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'(?:const|let)\s+(\w+)\s*(?::\s*Record<[^>]*>)?\s*=\s*\{\s*\}', src):
            name = m.group(1)
            if re.search(re.escape(name) + r'\s*\[[^\]]+\]\s*(?:\+=|\+\+|=\s*\(?' +
                         re.escape(name) + r'\[)', src):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, f'{name} = {{}} 后按外部 key 累加'))
    return hits


@pattern('C03', 'P1', 'Object.assign / spread 合并外部对象（触发 __proto__ setter）',
         'addLocale/importState 直接 assign 外部 JSON')
def c03(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'Object\.assign\s*\(', ln) or re.search(r'\.\.\.(\w+)\s*[,)]', ln):
            if re.search(r'JSON|import|table|data|json|state', ln, re.I):
                hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- D 族：死契约（声明但从未实现） ----------

@pattern('D01', 'P0', '接口字段声明但从未被赋值/读取（死契约）',
         'PlaceResult.missing / StepContext.elapsed / capacity / offsetRotation')
def d01(plugin, files):
    hits = []
    src_all = '\n'.join(files.values())
    for fn, src in files.items():
        # 接口里的可选字段
        for m in re.finditer(r'^\s*(?:readonly\s+)?(\w+)\??\s*:\s*[^;]+;\s*(?://.*)?$',
                             src, re.M):
            f = m.group(1)
            if f.startswith('_') or len(f) < 3:
                continue
            if re.search(r'\b' + re.escape(f) + r'\b', src_all):
                pass
            # 统计全插件出现次数（声明处算 1 次）
            n = len(re.findall(r'\b' + re.escape(f) + r'\b', src_all))
            if n <= 1:
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, f'字段 `{f}` 全插件仅出现 {n} 次（很可能声明未实现）'))
    return hits


@pattern('D02', 'P0', '参数声明但函数体内从未使用（承诺无效）',
         'register(type, fn, overwrite=false) 的 overwrite 完全无效')
def d02(plugin, files):
    hits = []
    for fn, src in files.items():
        # 只匹配行首的函数/方法定义，避免把调用点误当定义
        for m in re.finditer(r'^[ \t]*(?:export\s+)?(?:private\s+|public\s+|protected\s+)?'
                             r'(?:static\s+)?(?:async\s+)?(\w+)\s*\('
                             r'([^()]{0,300})\)\s*(?::\s*[^{;=>]+)?\{\s*$', src, re.M):
            fname = m.group(1)
            # 排除控制流关键字（它们的"参数"是条件表达式，天然不在体内出现）
            if fname in {'if', 'for', 'while', 'switch', 'catch', 'return',
                         'function', 'constructor', 'get', 'set'}:
                continue
            params = m.group(2)
            if not params.strip() or '=>' in params:
                continue
            depth, j = 0, len(src)
            for k in range(m.end() - 1, min(len(src), m.end() + 6000)):
                if src[k] == '{':
                    depth += 1
                elif src[k] == '}':
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
            body = src[m.end():j]
            # 先抹掉泛型尖括号内容，避免 Record<a,b> 的逗号被当分隔符
            flat = re.sub(r'<[^<>]*>', '', params)
            for seg in flat.split(','):
                seg = seg.split('=')[0].strip().lstrip('.').strip()
                pm = re.match(r'^([a-zA-Z_$][\w$]*)\s*\??', seg)
                if not pm:
                    continue
                pn = pm.group(1)
                if len(pn) < 4 or pn in {'this', 'type', 'name', 'opts', 'args'}:
                    continue
                if not re.search(r'\b' + re.escape(pn) + r'\b', body):
                    line = src[:m.start()].count('\n') + 1
                    hits.append((fn, line, f'参数 `{pn}` 在函数体内未被使用'))
    return hits


# ---------- E 族：遍历中修改集合 ----------

@pattern('E01', 'P0', 'forEach 遍历监听器数组 + 回调可能取消订阅',
         'splice 后下标前移，下一个订阅者被静默跳过')
def e01(plugin, files):
    hits = []
    SUB = re.compile(r'listener|handler|subscrib|subs|callback|observer|watcher|'
                     r'emitter|hook|consumer', re.I)
    for fn, i, ln in iter_lines(files):
        m = re.search(r'([A-Za-z_$][\w.$]*)\.forEach\s*\(', ln)
        if m and SUB.search(m.group(1)):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


@pattern('E02', 'P1', '按函数值去重的 Set 配合"每注册一条"的数组',
         'signal 的同类问题：一次取消把所有同名注册项全删')
def e02(plugin, files):
    hits = []
    for fn, src in files.items():
        if re.search(r'Set<[^>]*>\s*\(\s*\)', src) and re.search(r'\.filter\s*\(\s*\(?\w+\)?\s*=>\s*!', src):
            if re.search(r'has\(l\.fn\)|\.fn\)|indexOf', src):
                line = src[:src.find('.filter')].count('\n') + 1
                hits.append((fn, line, '按函数值去重的收尾 filter'))
    return hits


# ---------- F 族：import* 绕过校验 ----------

@pattern('F01', 'P0', 'import/importState 直接写内部容器，绕过 register/set 的校验',
         'buff/achievement/settings/quest/leaderboard 都栽在这里')
def f01(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\b(import|importState|importEntries|load|deserialize)'
                             r'\s*\([^)]*\)\s*(?::\s*[^{]+)?\{', src):
            depth, j = 0, len(src)
            for k in range(m.end() - 1, min(len(src), m.end() + 4000)):
                if src[k] == '{':
                    depth += 1
                elif src[k] == '}':
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
            body = src[m.end():j]
            writes = re.findall(r'this\.(_\w+)\.(?:set|push|add)\(', body)
            if writes:
                guarded = bool(re.search(r'isFinite|clamp|numOr|validate|register\(|this\.set\(', body))
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line,
                             f'{m.group(1)}() 直接写 {", ".join(sorted(set(writes))[:3])}'
                             f'{"（有校验）" if guarded else "——无校验"}'))
    return hits


# ---------- G 族：单监听器 ----------

@pattern('G01', 'P1', 'onXxx 直接赋值（第二个订阅者顶掉第一个）',
         'i18n.onChange / buff.onChange / condition.onComplete')
def g01(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        m = re.search(r'this\.(_?on[A-Z]\w*)\s*=\s*(?:fn|cb|handler|listener|undefined|null)\s*;', ln)
        if m:
            hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- H 族：不对称校验 ----------

@pattern('H01', 'P1', '成对 API 的校验不对称（一个校验一个不校验）',
         'setStat vs addStat / addKey vs evaluate / set vs snapTo / preview vs upgrade')
def h01(plugin, files):
    hits = []
    PAIRS = [('set', 'add'), ('register', 'import'), ('preview', 'upgrade'),
             ('addKey', 'evaluate'), ('set', 'snapTo'), ('compute', 'evaluate')]
    for fn, src in files.items():
        for a, b in PAIRS:
            ra = re.search(r'\b' + a + r'[A-Z]?\w*\s*\([^)]*\)\s*(?::\s*[^{]+)?\{', src)
            rb = re.search(r'\b' + b + r'[A-Z]?\w*\s*\([^)]*\)\s*(?::\s*[^{]+)?\{', src)
            if not (ra and rb):
                continue
            def body_of(m):
                depth, j = 0, len(src)
                for k in range(m.end() - 1, min(len(src), m.end() + 4000)):
                    if src[k] == '{':
                        depth += 1
                    elif src[k] == '}':
                        depth -= 1
                        if depth == 0:
                            return src[m.end():k]
                return src[m.end():m.end() + 2000]
            ba, bb = body_of(ra), body_of(rb)
            ga = bool(re.search(r'isFinite|throw|clamp', ba))
            gb = bool(re.search(r'isFinite|throw|clamp', bb))
            if ga != gb:
                line = src[:ra.start()].count('\n') + 1
                hits.append((fn, line,
                             f'`{a}` {"有" if ga else "无"}校验 / `{b}` {"有" if gb else "无"}校验'))
    return hits


# ---------- I 族：容量/性能 ----------

@pattern('I01', 'P1', '容量类字段无上限（无限增长）',
         'historyLimit / _log / _seen / _cache / capacity')
def i01(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'this\.(_\w*(?:log|history|seen|cache|records|entries|samples)\w*)'
                             r'\s*(?::[^=;]+)?=', src):
            f = m.group(1)
            line = src[:m.start()].count('\n') + 1
            # 全文找该字段的裁剪
            if re.search(re.escape(f) + r'\.(?:shift|splice|length\s*=\s*0|clear)\s*\(', src):
                continue
            if re.search(r'clampNum|Math\.min\(', src):
                continue
            hits.append((fn, line, f'{f} 无裁剪/上限'))
    return hits


@pattern('I02', 'P1', 'O(n²)：filter/map 内调用全量扫描方法',
         'reddot activePaths / spatial _findEntry')
def i02(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'\.filter\s*\(|\.map\s*\(', ln):
            if re.search(r'this\.get\(|this\.query|indexOf|includes', ln):
                hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- J 族：非原子 ----------

@pattern('J01', 'P0', '连续多个写操作，中间可能抛错且不回滚',
         'currency.exchange 先扣后加 / command.transact')
def j01(plugin, files):
    hits = []
    for fn, src in files.items():
        # 找含 spend/remove/add 连续调用的函数
        for m in re.finditer(r'\b\w*(?:spend|consume|deduct|remove|sub)\w*\s*\([^)]*\)', src):
            line = src[:m.start()].count('\n') + 1
            seg = '\n'.join(src.split('\n')[line - 1:line + 4])
            if re.search(r'\b\w*(?:add|grant|credit|give)\w*\s*\(', seg):
                if not re.search(r'try\s*\{', seg):
                    hits.append((fn, line, '扣减 + 增加连续执行，无 try/回滚'))
                    break
    return hits


@pattern('J02', 'P1', '空 catch 吞异常',
         'command.rollback / diag-pack / runscope.getOr')
def j02(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'catch\s*\([^)]*\)\s*\{\s*\}', src, re.S):
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, '空 catch 块'))
    return hits


# ---------- K 族：状态不复位 / 清理不彻底 ----------

@pattern('K01', 'P1', '状态字段只有置 true 没有复位 false',
         'affix.lastRerollDegraded 只置 true 从不复位')
def k01(plugin, files):
    hits = []
    for fn, src in files.items():
        assigns = re.findall(r'this\.(_\w+)\s*=\s*(true|false)\s*;', src)
        c = {}
        for f, v in assigns:
            c.setdefault(f, set()).add(v)
        for f, vs in c.items():
            if vs == {'true'}:
                line = src[:src.find('this.' + f + ' = true')].count('\n') + 1
                hits.append((fn, line, f'this.{f} 只被置 true，从不复位'))
    return hits


@pattern('K02', 'P1', 'clear/reset 遗漏部分容器（清理不彻底）',
         'save.clearAll 漏 __tmp / spatial 空桶不回收')
def k02(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\b(clear|clearAll|reset)\s*\(\s*\)\s*(?::\s*[^{]+)?\{', src):
            depth, j = 0, len(src)
            for k in range(m.end() - 1, min(len(src), m.end() + 3000)):
                if src[k] == '{':
                    depth += 1
                elif src[k] == '}':
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
            body = src[m.end():j]
            cleared = set(re.findall(r'this\.(_\w+)\.(?:clear|length\s*=\s*0)\s*\(\s*\)', body))
            cleared |= set(re.findall(r'this\.(_\w+)\.clear\s*\(', body))
            allc = set(re.findall(r'private\s+(?:readonly\s+)?(_\w+)\s*(?::[^=;]+)?=', src))
            allc |= set(re.findall(r'this\.(_\w+)\s*=\s*(?:new\s+(?:Map|Set|Array)|\[\]|\{\})', src))
            miss = allc - cleared
            miss = {x for x in miss if re.search(r'map|set|arr|list|log|hist|cache|'
                                                 r'record|entry|item|node|slot|bucket', x, re.I)}
            if miss and len(miss) < len(allc):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, f'{m.group(1)}() 未清理: {", ".join(sorted(miss))}'))
    return hits


# ---------- L 族：空块 / 半成品校验 ----------

@pattern('L01', 'P0', '空 if 块（校验写了一半）',
         'logger 的 Silent 判断、blessing、room-graph')
def l01(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\bif\s*\(([^)]{3,120})\)\s*\{\s*\}', src, re.S):
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, f'空 if 块: if ({m.group(1).strip()[:60]}) {{}}'))
    return hits


@pattern('L02', 'P1', '三元表达式两支返回同一个值',
         'condition 的 `return actual === 0 ? 1 : 1`')
def l02(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        m = re.search(r'\?\s*([^:?;]{1,40})\s*:\s*\1\s*[;)]', ln)
        if m and not re.search(r'^\s*(//|\*)', ln.strip()):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- M 族：fail-open（安全/经济链路） ----------

@pattern('M01', 'P0', 'fail-open：校验缺失时默认放行/通过',
         'skill-variant 未注入 evaluator → 静默放行；anticheat NaN → action=none 放过')
def m01(plugin, files):
    hits = []
    for fn, src in files.items():
        # if (!x) return true;  /  return true; 在校验函数末尾
        for m in re.finditer(r'\b(can|is|should|check|validate|verify|allow)\w*\s*\('
                             r'[^)]*\)\s*(?::\s*boolean)?\s*\{', src, re.I):
            depth, j = 0, len(src)
            for k in range(m.end() - 1, min(len(src), m.end() + 2500)):
                if src[k] == '{':
                    depth += 1
                elif src[k] == '}':
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
            body = src[m.end():j]
            if re.search(r'if\s*\(\s*!\s*\w+\s*\)\s*return\s*true\s*;', body):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, f'{m.group(0)[:50]} 内含 `if (!x) return true`'))
    return hits


@pattern('M02', 'P0', '安全/经济判定依赖可能污染的数值',
         'meta NaN → 零成本解锁；quest NaN → 瞬间完成可领奖')
def m02(plugin, files):
    hits = []
    KEY = re.compile(r'unlock|afford|canBuy|canCraft|complete|claim|reward|ban|'
                     r'cheat|violation|purchase', re.I)
    for fn, src in files.items():
        for m in re.finditer(r'\b(\w*(?:can|is|has|should)\w*)\s*\([^)]*\)\s*(?::\s*boolean)?\s*\{', src):
            if not KEY.search(m.group(1)):
                continue
            depth, j = 0, len(src)
            for k in range(m.end() - 1, min(len(src), m.end() + 2000)):
                if src[k] == '{':
                    depth += 1
                elif src[k] == '}':
                    depth -= 1
                    if depth == 0:
                        j = k
                        break
            body = src[m.end():j]
            if re.search(r'[<>]=?\s*\w+', body) and not re.search(r'isFinite|numOr', body):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, f'{m.group(1)}() 数值比较无有限性守卫'))
    return hits


# ---------- N 族：时间与随机源 ----------

@pattern('N01', 'P1', '硬编码 Date.now / performance.now（时间源不可注入）',
         'Scheduler 吞掉 TimeScale 的注入能力；回放/单测不可控')
def n01(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'\bDate\.now\s*\(\s*\)|performance\.now\s*\(\s*\)', ln):
            if re.search(r'=\s*Date\.now|now\s*=\s*|now\?|now:', ln):
                continue  # 有注入口
            hits.append((fn, i, ln.strip()[:90]))
    return hits


@pattern('N02', 'P1', '裸 Math.random（破坏可复现）',
         'perception 抖动 / steering wander / crash 采样')
def n02(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if 'Math.random' in ln:
            hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- O 族：其他确定性问题 ----------

@pattern('O01', 'P1', '32 位移位溢出（1 << 31/32）',
         'binary 的 uint(31)/uint(32) 范围算成负数')
def o01(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'1\s*<<\s*(\d+)', ln):
            for m in re.finditer(r'1\s*<<\s*(\d+)', ln):
                if int(m.group(1)) >= 31:
                    hits.append((fn, i, ln.strip()[:90]))
                    break
    return hits


@pattern('O02', 'P1', '除法分母来自变量且无零/NaN 防护',
         'minimap scale=0 / affix 除零')
def o02(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'/\s*([A-Za-z_$][\w.$]*)\s*[;),]', src):
            v = m.group(1)
            if re.search(r'\b(scale|total|count|len|length|sum|weight|duration|'
                         r'amount|divisor|n)\b', v):
                line = src[:m.start()].count('\n') + 1
                ctx = '\n'.join(src.split('\n')[max(0, line - 5):line + 1])
                if re.search(r'===?\s*0|<\s*1e-|Math\.max\(|isFinite', ctx):
                    continue
                hits.append((fn, line, f'/ {v} 无零防护'))
                break
    return hits


@pattern('O03', 'P1', 'console.* 直接输出（应走 logger 注入）',
         'write() 失败只 console.error；库内污染宿主日志格式')
def o03(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'console\.(log|warn|error|info)', ln):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


@pattern('O04', 'P1', '返回内部可变引用（调用方持有的会被后续帧改写）',
         'joystick-mover evaluate() / ModifierSet.dump()')
def o04(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'return\s+this\.(_\w+)\s*;', src):
            f = m.group(1)
            line = src[:m.start()].count('\n') + 1
            if re.search(r'return\s+this\.' + re.escape(f) + r'\s*(?:\.slice|\.map|'
                         r'\.filter|as\s+readonly|\?\?\s*\[\])', src):
                continue
            hits.append((fn, line, f'return this.{f}; 返回内部引用'))
    return hits
# ============================================================
# 修正区：以下 6 条是 core34 的已知失效实现，后置重新注册以覆盖
# 装配后按 id 去重（保留最后定义）
# ============================================================

@pattern('B03', 'P0', '递归无访问集/深度上限（互相引用 → 栈溢出）',
         '子表互引用、嵌套材料树等场景')
def b03(plugin, files):
    hits = []
    for fn, src in files.items():
        # ① 普通函数自递归
        for dm in re.finditer(r'\bfunction\s+(\w+)\s*\(([^)]{0,300})\)', src):
            name = dm.group(1)
            body = _body_of(src, dm)
            if not re.search(r'\b' + re.escape(name) + r'\s*\(', body):
                continue
            if re.search(r'visiting|visited|seen|depth|guard|memo', body):
                continue
            line = src[:dm.start()].count('\n') + 1
            hits.append((fn, line, f'{name}() 自递归，无访问集/深度上限'))
        # ② this.method( 形式的方法自递归
        for m in re.finditer(r'this\.(\w+)\s*\(', src):
            name = m.group(1)
            dm = re.search(r'^\s*(?:private\s+|public\s+)?' + re.escape(name) +
                           r'\s*\([^)]*\)[^{]*\{', src, re.M)
            if not dm:
                continue
            body = _body_of(src, dm)
            if re.search(r'this\.' + re.escape(name) + r'\s*\(', body):
                line = src[:m.start()].count('\n') + 1
                if not re.search(r'visiting|visited|seen|depth|guard', body):
                    hits.append((fn, line, f'this.{name}() 自递归，无访问集/深度上限'))
                break
    return hits


@pattern('D02', 'P0', '参数声明但函数体内从未使用（承诺无效）',
         'register(overwrite) / configure 参数被忽略')
def d02(plugin, files):
    hits = []
    for fn, src in files.items():
        # 三种形态都覆盖：类方法 name( / 独立函数 function name( / 箭头方法 name = (
        for m in re.finditer(r'^[ \t]*(?:export\s+)?(?:default\s+)?'
                             r'(?:private\s+|public\s+|protected\s+)?'
                             r'(?:static\s+)?(?:async\s+)?(?:function\s+)?(\w+)\s*'
                             r'(?:=\s*)?\('
                             r'([^()]{0,300})\)\s*(?::\s*[^{;=>]+)?\{', src, re.M):
            fname = m.group(1)
            if fname in {'if', 'for', 'while', 'switch', 'catch', 'return',
                         'function', 'constructor', 'get', 'set'}:
                continue
            params = m.group(2)
            if not params.strip() or '=>' in params:
                continue
            body = _body_of(src, m)
            flat = re.sub(r'<[^<>]*>', '', params)
            for seg in flat.split(','):
                seg = seg.split('=')[0].strip().lstrip('.').strip()
                pm = re.match(r'^([a-zA-Z_$][\w$]*)\s*\??', seg)
                if not pm:
                    continue
                pn = pm.group(1)
                if len(pn) < 4 or pn in {'this', 'type', 'name', 'opts', 'args'}:
                    continue
                if not re.search(r'\b' + re.escape(pn) + r'\b', body):
                    line = src[:m.start()].count('\n') + 1
                    hits.append((fn, line, f'参数 `{pn}` 在函数体内未被使用'))
    return hits


@pattern('E02', 'P1', '按函数值去重的 Set 配合"每注册一条"的数组',
         '同一函数注册多次时，一次取消会把所有同名注册项全删')
def e02(plugin, files):
    hits = []
    for fn, src in files.items():
        # Set 构造可能是 new Set() 也可能 new Set([...])，不能只认空括号
        if not re.search(r'\bnew\s+Set\s*(?:<[^>]*>)?\s*\(|Set<[^>]*>\s*\(', src):
            continue
        m = re.search(r'\.filter\s*\(', src)
        if not m:
            continue
        if not re.search(r'handler|listener|callback|subscrib|on[A-Z]|'
                         r'_\w*(?:set|handler|listener)\w*\s*(?:=|\.)', src, re.I):
            continue
        line = src[:m.start()].count('\n') + 1
        hits.append((fn, line, '按函数值去重的收尾 filter：同一函数注册多次会被一起删掉'))
    return hits


@pattern('I01', 'P1', '容量类字段无上限（无限增长）',
         '各类 log / history / cache / seen 容器')
def i01(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'this\.(_\w*(?:log|history|seen|cache|records|entries|samples)\w*)'
                             r'\s*(?::[^=;]+)?=', src):
            f = m.group(1)
            line = src[:m.start()].count('\n') + 1
            if re.search(re.escape(f) + r'\.(?:shift|splice|length\s*=\s*0|clear)\s*\(', src):
                continue
            if re.search(r'clampNum|Math\.min\(', src):
                continue
            hits.append((fn, line, f'{f} 无裁剪/上限'))
        # 兜底：无显式声明但存在无界写入
        for m in re.finditer(r'this\.(_\w*(?:log|history|seen|cache|records|entries|samples)\w*)'
                             r'\s*\.\s*(?:push|add|unshift)\s*\(', src):
            f = m.group(1)
            if re.search(re.escape(f) + r'\.(?:shift|splice|length\s*=\s*0|clear)\s*\(', src):
                continue
            if re.search(r'clampNum|Math\.min\(', src):
                continue
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, f'{f} 持续写入且无裁剪/上限'))
            break
    return hits


@pattern('K02', 'P1', 'clear/reset 遗漏部分容器（清理不彻底）',
         'crash / diagpack / skill-caster 的 reset')
def k02(plugin, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\b(clear|clearAll|reset)\s*\(\s*\)\s*(?::\s*[^{]+)?\{', src):
            body = _body_of(src, m)
            # 清理写法有三种：.clear() / .length = 0 / = [] ，不能只认带括号的
            cleared = set(re.findall(r'this\.(_\w+)\.clear\s*\(', body))
            cleared |= set(re.findall(r'this\.(_\w+)\.length\s*=\s*0', body))
            cleared |= set(re.findall(r'this\.(_\w+)\s*=\s*(?:\[\]|new\s+Map\s*\(|new\s+Set\s*\()', body))
            allc = set(re.findall(r'private\s+(?:readonly\s+)?(_\w+)\s*(?::[^=;]+)?=', src))
            allc |= set(re.findall(r'this\.(_\w+)\s*=\s*(?:new\s+(?:Map|Set|Array)|\[\]|\{\})', src))
            miss = allc - cleared
            miss = {x for x in miss if re.search(r'map|set|arr|list|log|hist|cache|'
                                                 r'record|entry|item|node|slot|bucket', x, re.I)}
            if miss and len(miss) < len(allc):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, f'{m.group(1)}() 未清理: {", ".join(sorted(miss))}'))
    return hits


@pattern('N01', 'P1', '硬编码 Date.now / performance.now（时间源不可注入）',
         '时间源不可注入会导致单测必须真 sleep、无法确定性回放')
def n01(plugin, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'\bDate\.now\s*\(\s*\)|performance\.now\s*\(\s*\)', ln):
            # 只在确实是「注入口」时跳过：箭头函数 / 函数类型声明
            # `const now = Date.now();` 不是注入口，它就是硬编码取值
            if re.search(r'now\s*\??\s*:\s*\(\s*\)\s*=>|now\s*=\s*\(\s*\)\s*=>|'
                         r'=>\s*Date\.now|=>\s*performance\.now|'
                         r'now\s*\?\?\s*\(\s*\)\s*=>|readonly\s+now\s*\?\s*:', ln):
                continue
            hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- P 族：值域与类型收口（深层） ----------

@pattern('P01', 'P0', '数值收口函数缺 typeof 校验',
         'clampNum/numOr 必须 typeof v === "number"；否则 null / "" 静默变 0 或下界')
def p01(module, files):
    hits = []
    NAMES = r'clampNum|numOr|toNum|safeNum|asNumber|toNumber|needCount|needInt'
    for fn, src in files.items():
        for m in re.finditer(r'\bfunction\s+(' + NAMES + r')\s*\(', src):
            body = _body_of(src, m)
            if not re.search(r"typeof\s+\w+\s*===?\s*['\"]number['\"]", body):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, '%s() 内无 typeof === "number" 校验' % m.group(1)))
    return hits


@pattern('P02', 'P0', 'Infinity 被用作哨兵值，与合法极值冲突',
         '空集/无效值必须用 length===0 或 null 表示；±Infinity 是合法数值，当哨兵会误判')
def p02(module, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'=\s*-?Infinity\s*[;,)]', ln) or re.search(r'[!=]==\s*-?Infinity', ln):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


@pattern('P03', 'P0', 'Math.max/min 当收口守卫（对 NaN / Infinity 无效）',
         'Math.max(1,NaN)=NaN、Math.max(1,Infinity)=Infinity；必须用 clampNum 或显式有限性判定')
def p03(module, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'Math\.(max|min)\s*\(\s*\d+\s*,\s*([A-Za-z_$][\w.$]*)\s*\)', ln):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


@pattern('P04', 'P1', 'slice / splice 的负数参数陷阱',
         'slice(0, n) 当 n 为负会变成「去掉末尾 n 个」；数量参数必须先转为有限非负整数')
def p04(module, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'\.(slice|splice)\s*\(\s*[^)]*[A-Za-z_$][\w.$]*\s*[,)]', ln):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


@pattern('P05', 'P0', '数值 op 未校验操作数类型（+ 变字符串拼接）',
         'add/mul 类操作必须要求两个操作数同为有限 number，否则 "10"+"5"="105"')
def p05(module, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r"case\s+['\"](add|mul|inc|sub|dec|append)['\"]\s*:", src):
            line = src[:m.start()].count('\n') + 1
            seg = '\n'.join(src.split('\n')[line - 1:line + 6])
            if re.search(r'value\s*\)|\+\s*(?:p\.)?value|\*=\s*(?:p\.)?value', seg):
                if not re.search(r"typeof\s+\S+\s*===?\s*['\"]number['\"]|Number\.isFinite", seg):
                    hits.append((fn, line, "case '%s' 的操作数无类型校验" % m.group(1)))
    return hits


# ---------- Q 族：内存分配与数据结构 ----------

@pattern('Q01', 'P0', 'TypedArray / 大数组尺寸来自未校验变量',
         '尺寸必须有限正整数且有总量上限，否则底层 RangeError 或瞬时 OOM，且错误不指向配置字段')
def q01(module, files):
    hits = []
    TYPES = (r'Array|Uint8Array|Uint16Array|Uint32Array|Int8Array|Int16Array|'
             r'Int32Array|Float32Array|Float64Array|ArrayBuffer|Uint8ClampedArray|BigInt64Array')
    for fn, src in files.items():
        for m in re.finditer(r'new\s+(?:' + TYPES + r')\s*\(\s*([^)]{1,60}?)\)', src):
            arg = m.group(1).strip()
            if re.match(r'^\d+$', arg):
                continue
            line = src[:m.start()].count('\n') + 1
            ctx = '\n'.join(src.split('\n')[max(0, line - 8):line + 1])
            if re.search(r'clampNum|Math\.min|isFinite|needCount|Math\.floor', ctx):
                continue
            typename = m.group(0).split('(')[0].replace('new', '').strip()
            hits.append((fn, line, 'new %s(%s) 尺寸未收口' % (typename, arg[:28])))
    return hits


@pattern('Q02', 'P1', '惰性删除结构的 size / isEmpty 与 pop 语义不一致',
         '标记删除后 size 必须反映有效条目；否则以 isEmpty 驱动的循环会空转')
def q02(module, files):
    hits = []
    for fn, src in files.items():
        if not re.search(r'LazyHeap|tombstone|_removed|_dead|_alive', src):
            continue
        has_size = re.search(r'get\s+(?:size|isEmpty|length)\s*\(', src)
        has_remove = re.search(r'\bremove\s*\(\s*\w+\s*\)', src)
        if has_size and has_remove:
            line = src[:has_size.start()].count('\n') + 1
            hits.append((fn, line, '惰性删除 + size/isEmpty：需确认统计有效条目'))
    return hits


@pattern('Q03', 'P0', '分桶 / 空间索引删除后不回收空桶',
         'Map<key,Set> 删除元素后若 bucket.size === 0 必须删除 Map key，否则长期内存泄漏')
def q03(module, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'new\s+Map\s*(?:<[^>]*>)?\s*\(\s*\)', src):
            head = src[max(0, m.start() - 160):m.start()].strip()
            fm = re.search(r'([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*$', head)
            if not fm:
                continue
            f = fm.group(1)
            if not re.search(re.escape(f) + r'\s*\.\s*delete\s*\(', src):
                continue
            if re.search(r'\.size\s*===?\s*0', src):
                continue
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, '%s 是分桶 Map，有 delete 但未见空桶回收' % f))
    return hits


@pattern('Q04', 'P0', '对象池缺归属校验 / prewarm 无界',
         'put/release 必须拒绝非本池借出的对象；active 不得为负；prewarm 必须有限整数上限')
def q04(module, files):
    hits = []
    for fn, src in files.items():
        if not re.search(r'\bclass\s+\w*Pool\b|\bprewarm\s*\(', src):
            continue
        for m in re.finditer(r'\bprewarm\s*\([^)]*\)\s*(?::[^{]+)?\{', src):
            body = _body_of(src, m, 1500)
            if not re.search(r'clampNum|Math\.min|isFinite|needCount|limit|Math\.max', body):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, 'prewarm() 无上界收口'))
        for m in re.finditer(r'(?:this\.)?_?(?:active|used|_out|borrowed|_borrowed)\s*--', src):
            line = src[:m.start()].count('\n') + 1
            ctx = '\n'.join(src.split('\n')[max(0, line - 4):line + 2])
            if re.search(r'Math\.max\(\s*0', ctx):
                continue
            hits.append((fn, line, 'active/used 递减无下限保护（可为负）'))
    return hits


@pattern('Q05', 'P1', 'spread 展开不定参数（大量参数 → RangeError）',
         'min/max/sum 等可变参数函数必须循环归约；深度很浅但参数很多照样爆栈')
def q05(module, files):
    hits = []
    for fn, i, ln in iter_lines(files):
        if re.search(r'Math\.(max|min)\s*\(\s*\.\.\.', ln):
            hits.append((fn, i, ln.strip()[:90]))
    return hits


# ---------- R 族：路径、序列化与 key 编码 ----------

@pattern('R01', 'P0', '按路径写入未过滤危险段（原型污染）',
         '解析路径后必须拒绝 __proto__ / prototype / constructor 段，且只在自有容器上写入')
def r01(module, files):
    """路径解析有两种写法都要覆盖：
       ① str.split('.')  ② 正则 /([^.[\\]]+)|\[(\d+)\]/g 逐段提取
       只扫 split 会漏掉用正则的实现。
    """
    hits = []
    for fn, src in files.items():
        if re.search(r"['\"]__proto__['\"]\s*[,)\]]|"
                     r"['\"]__proto__['\"]\s*===|"
                     r"__proto__\s*\)|includes\(\s*['\"]__proto__", src):
            continue
        found = None
        m = re.search(r'(\w+)\.split\s*\(\s*[\'\"]([.\\/\[\]])', src)
        if m:
            found = ('%s.split("%s")' % (m.group(1), m.group(2)), m.start())
        else:
            m2 = re.search(r'function\s+(parsePath|parseKey|pathTokens|tokenizePath|'
                           r'splitPath|toTokens)\s*\(', src)
            if m2:
                found = ('%s() 路径解析' % m2.group(1), m2.start())
            else:
                m3 = re.search(r'\[\^?\.\[\\\\\]\]\+', src)
                if m3:
                    found = ('正则路径解析', m3.start())
        if not found:
            continue
        if not re.search(r'\bapplyPatch|setPath|\bpatch\b|\bpath\b', src, re.I):
            continue
        line = src[:found[1]].count('\n') + 1
        hits.append((fn, line, '%s，未见危险段过滤' % found[0]))
    return hits


@pattern('R02', 'P0', '批量删除未降序（索引前移导致删错）',
         '同一父数组删除多个索引必须按索引降序 splice；按深度排序不足以处理同层多删')
def r02(module, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\.splice\s*\(', src):
            line = src[:m.start()].count('\n') + 1
            ctx = '\n'.join(src.split('\n')[max(0, line - 10):line + 3])
            if re.search(r'sort|reverse|降序|descending', ctx, re.I):
                continue
            if not re.search(r'\bfor\s*\(|\.forEach\s*\(', ctx):
                continue
            hits.append((fn, line, '循环内 splice，需确认是否降序删除'))
            break
    return hits


@pattern('R03', 'P0', '路径协议不可逆（无法表达含分隔符的键）',
         '路径必须用 JSON Pointer / token 数组等可逆协议；点分拼接会让 {"a.b":1} 变成 {a:{b:1}}')
def r03(module, files):
    hits = []
    for fn, src in files.items():
        has_split = re.search(r"\.split\s*\(\s*['\"][.\/]", src)
        has_join = re.search(r"\.join\s*\(\s*['\"][.\/]", src)
        has_regex = re.search(r'function\s+(parsePath|parseKey|pathTokens|tokenizePath|'
                              r'splitPath|toTokens)\s*\(', src)
        has_patch = re.search(r'\bapplyPatch|createPatch|\bpatch\b', src, re.I)
        if has_patch and (has_regex or (has_split and has_join)):
            anchor = has_regex or has_split
            line = src[:anchor.start()].count('\n') + 1
            hits.append((fn, line, '存在路径解析 + patch，需确认协议可逆（含点号/方括号的键）'))
    return hits


@pattern('R04', 'P0', '复合 key 未编码（分隔符碰撞）',
         'makeKey 必须对 id / 键 / 值做长度前缀或转义；拼接会让不同组合生成同一 key')
def r04(module, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\.join\s*\(\s*[\'\"]([,|=:;\/|#&])[\'\"]\s*\)', src):
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, 'join("%s") 复合 key 拼接，需确认转义' % m.group(1)))
        for m in re.finditer(r'`\$\{[^}]+\}[,|=:|]\$\{', src):
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, '模板字符串复合 key，需确认转义'))
    return hits


# ---------- S 族：安全默认值 ----------

@pattern('S01', 'P0', '调试 / 作弊 / 后门功能默认启用',
         'enabled / debug / cheat / devMode 类开关默认必须为 false，由宿主显式开启')
def s01(module, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(
                r'\b(enabled|debug|cheat|devMode|allowUnsafe|unsafe|openAll|godMode)'
                r'\s*(?:\?\.)?\s*(?:=\s*|:\s*|\?\?\s*)(true)\b', src):
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, '%s 默认 true（应为 false）' % m.group(1)))
        for m in re.finditer(r'\b(enabled|debug|cheat|devMode)\s*\?\?\s*true', src):
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, '%s ?? true（默认值应为 false）' % m.group(1)))
    return hits


# ---------- T 族：角度 / 周期归一化 ----------

@pattern('T01', 'P0', 'while 循环做角度 / 周期归一化',
         '角度归一化必须常数时间取模；while 减 2π/360 遇 Infinity 永不退出')
def t01(module, files):
    hits = []
    for fn, src in files.items():
        # 循环体可能是 { ... } 也可能是单语句（无大括号），两种都要覆盖
        for m in re.finditer(r'\bwhile\s*\(([^)]{3,90})\)\s*(?:\{|(?=[A-Za-z_$+\-]))', src):
            body = src[m.end():m.end() + 300]
            if re.search(r'[-+]=\s*(?:360|2\s*\*\s*Math\.PI|Math\.PI\s*\*\s*2|TAU)', body) \
               or re.search(r'[-+]\s*(?:360|2\s*\*\s*Math\.PI|Math\.PI\s*\*\s*2|TAU)', body):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, 'while (%s) 角度/周期归一化循环' % m.group(1).strip()[:46]))
    return hits


@pattern('T02', 'P0', '循环变量可为 ±Infinity（自增后仍为 ±Infinity）',
         '-Infinity + 1 仍为 -Infinity；循环上/下界非有限时条件永不满足')
def t02(module, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(r'\bfor\s*\(\s*let\s+(\w+)\s*=\s*([^;]{1,40});\s*'
                             r'\1\s*(<=|<|>=|>)\s*([^;]{1,40});', src):
            start_v, bound = m.group(2), m.group(4)
            if re.match(r'^-?\d', start_v.strip()) and re.match(r'^-?\d', bound.strip()):
                continue
            line = src[:m.start()].count('\n') + 1
            ctx = '\n'.join(src.split('\n')[max(0, line - 10):line + 1])
            if re.search(r'isFinite|clampNum|Math\.min\(|Math\.max\(', ctx):
                continue
            hits.append((fn, line, 'for (%s = %s; ...; %s) 边界未收口'
                         % (m.group(1), start_v.strip()[:18], bound.strip()[:18])))
    return hits


# ---------- U 族：展示层掩盖 ----------

@pattern('U01', 'P1', '展示层把非有限值掩盖成 0',
         'display/format/render 不得用 || 0 / ?? 0 掩盖 NaN，否则故障被完全隐藏')
def u01(module, files):
    hits = []
    for fn, src in files.items():
        for m in re.finditer(
                r'\b(?:display|format|toDisplay|render|toText|label|toFixed|pretty)\w*'
                r'\s*\([^)]*\)\s*(?::[^{]+)?\{', src):
            body = _body_of(src, m, 1200)
            if re.search(r'\|\|\s*0|\?\?\s*0', body):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, '展示函数用 || 0 / ?? 0，可能掩盖 NaN'))
    return hits


# ---------- W 族：交易与批量数量 ----------

@pattern('W01', 'P0', '交易 / 批量数量未校验有限正整数',
         'buy/sell/craft/pull 的 count/quantity 必须有限、> 0 且为整数，否则负数可反向增钱')
def w01(module, files):
    hits = []
    FNS = r'buy|sell|trade|craft|pullN|pull|roll|simulate|spawn|prewarm|exchange|consume|grant'
    QTY = r'count|quantity|amount|times|pulls|samples|n\b|num\b|size\b'
    for fn, src in files.items():
        for m in re.finditer(r'\b(?:' + FNS + r')\s*\(([^)]{0,220})\)\s*(?::[^{]+)?\{', src):
            params = m.group(1)
            pm = re.search(r'\b(' + QTY + r')\s*[:?]', params)
            if not pm:
                continue
            body = _body_of(src, m, 3000)
            integer = re.search(r'Number\.isInteger|%\s*1|Math\.floor|Math\.trunc|Math\.round', body)
            positive = re.search(r'>\s*0|<\s*=\s*0|<\s*1|isFinite', body)
            if not (integer and positive):
                line = src[:m.start()].count('\n') + 1
                hits.append((fn, line, '%s() 的 %s 未校验有限正整数'
                             % (m.group(0).split('(')[0].strip(), pm.group(1))))
    return hits


# ============================================================
# 装配后处理：按 id 去重，保留最后定义（修正区覆盖 core34 的失效实现）
# ============================================================


# ---------- X 族：成对 API 配对（获取 ↔ 释放） ----------
# 来源：cocos_audit.py 的 PAIRS / LOAD_PAT / TWEEN_FOREVER
# 抽象：任何「注册-注销」「获取-归还」的成对契约，缺一侧即泄漏
# 判据：这类泄漏随运行时长累积，测试期看不出，上线后 OOM

@pattern('X01', 'P0', '事件订阅无对应注销（监听泄漏）',
         '注册了 on/addEventListener/subscribe，全文未见 off/removeEventListener/unsubscribe')
def x01(module, files):
    hits = []
    REG = r'\.\s*(?:on|addEventListener|addListener|subscribe)\s*\('
    # 清理可能是 .off( 调用，也可能是 off( 方法定义 —— 两种都要认
    CLEAN = (r'(?:\.\s*|\b)(?:off|targetOff|removeEventListener|removeListener|'
             r'unsubscribe|removeAllListeners|dispose)\s*\(')
    for fn, src in files.items():
        regs = list(re.finditer(REG, src))
        if not regs:
            continue
        if re.search(CLEAN, src):
            continue
        line = src[:regs[0].start()].count('\n') + 1
        hits.append((fn, line, '注册了 %d 处监听，未见任何注销调用' % len(regs)))
    return hits


@pattern('X02', 'P0', '定时器注册无清理（定时任务泄漏）',
         'schedule/setInterval/setTimeout 全文未见 unschedule/clearInterval/clearTimeout')
def x02(module, files):
    hits = []
    PAIRS = [
        (r'\b(?:schedule|scheduleOnce)\s*\(',
         r'(?:\.\s*|\b)unschedule(?:All)?(?:Callbacks)?\s*\(', 'schedule 无 unschedule'),
        (r'\bsetInterval\s*\(', r'\bclearInterval\s*\(', 'setInterval 无 clearInterval'),
        (r'\bsetTimeout\s*\(', r'\bclearTimeout\s*\(', 'setTimeout 无 clearTimeout'),
    ]
    for fn, src in files.items():
        for reg, clean, msg in PAIRS:
            regs = list(re.finditer(reg, src))
            if not regs:
                continue
            if re.search(clean, src):
                continue
            line = src[:regs[0].start()].count('\n') + 1
            hits.append((fn, line, '%s（%d 处注册）' % (msg, len(regs))))
    return hits


@pattern('X03', 'P0', '资源/句柄获取后无释放（资源泄漏）',
         'load/open/acquire 类调用全文未见 decRef/release/close/dispose')
def x03(module, files):
    hits = []
    REG = (r'\b(?:resources\.load|assetManager\.load|bundle\.load|loader\.loadRes|'
           r'open|acquire|loadAsset|createTexture)\s*\(')
    CLEAN = (r'(?:\.\s*|\b)(?:decRef|addRef|releaseAsset|releaseAll|release|close|dispose|'
             r'free|destroy)\s*\(')
    for fn, src in files.items():
        regs = list(re.finditer(REG, src))
        if not regs:
            continue
        if re.search(CLEAN, src):
            continue
        line = src[:regs[0].start()].count('\n') + 1
        hits.append((fn, line, '获取了资源/句柄（%d 处），未见释放调用' % len(regs)))
    return hits


@pattern('X04', 'P0', '循环/常驻动画无停止调用（切场景后驻留）',
         'repeatForever/setLoop/loop=true 全文未见 stop/clear 类调用')
def x04(module, files):
    hits = []
    REG = (r'\brepeatForever\s*\(|\bsetLoop\s*\(\s*true|\bloop\s*[:=]\s*true|'
           r'\bplayForever\s*\(')
    CLEAN = (r'(?:\.\s*|\b)(?:stop|clear|pause|cancel)\s*\(|'
             r'\bstopAll(?:ByTarget|ByTag)?\s*\(|\bcancelAnimationFrame\s*\(')
    for fn, src in files.items():
        regs = list(re.finditer(REG, src))
        if not regs:
            continue
        if re.search(CLEAN, src):
            continue
        line = src[:regs[0].start()].count('\n') + 1
        hits.append((fn, line, '启动了循环动画/任务，未见停止调用'))
    return hits


@pattern('X05', 'P1', '成对方法只出现一侧（获取无归还）',
         'lock/unlock、acquire/release、open/close 等成对方法缺一侧')
def x05(module, files):
    hits = []
    PAIRS = [
        (r'\block\s*\(', r'(?:\.\s*|\b)unlock\s*\(', 'lock 无 unlock'),
        (r'\bacquire\s*\(', r'(?:\.\s*|\b)release\s*\(', 'acquire 无 release'),
        (r'\bopen\s*\(', r'(?:\.\s*|\b)close\s*\(', 'open 无 close'),
    ]
    for fn, src in files.items():
        for reg, clean, msg in PAIRS:
            if not re.search(reg, src):
                continue
            if re.search(clean, src):
                continue
            m = re.search(reg, src)
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, msg))
    return hits


@pattern('X06', 'P1', '匿名回调注册（无法精确注销）',
         'on(ev, () => {...}) 之后 off 需同一函数引用，匿名函数导致写了也 off 不掉')
def x06(module, files):
    hits = []
    ANON = (r'\.\s*(?:on|addEventListener|addListener|subscribe|once)\s*\('
            r'[^;]{0,140}?(?:\(\s*\)\s*=>|function\s*\(|=>\s*\{)')
    for fn, src in files.items():
        m = re.search(ANON, src)
        if m:
            line = src[:m.start()].count('\n') + 1
            hits.append((fn, line, '匿名回调注册，后续无法精确 off'))
    return hits


# ---------- Y 族：热路径与高频回调 ----------
# 来源：cocos_audit.py 的 UPDATE_BAN
# 抽象：每帧/高频回调内的昂贵操作会随帧率线性放大

@pattern('Y01', 'P1', '每帧回调内的昂贵操作（应缓存到初始化）',
         'update/tick/lateUpdate 内 find/getComponent/instantiate/destroy 等每帧开销')
def y01(module, files):
    hits = []
    HOT = (r'\b(?:update|lateUpdate|tick|fixedUpdate|onTick)\s*\(\s*(?:[^)]{0,40})?\)'
           r'\s*(?::[^{]+)?\{')
    BAN = [
        (r'\b(?:find|getChildByName|getChildByPath)\s*\(', '查找节点'),
        (r'\bgetComponent\s*\(', '获取组件'),
        (r'\binstantiate\s*\(', '实例化节点'),
        (r'\bdestroy\s*\(', '销毁节点'),
        (r'\bnew\s+[A-Z]\w*', '新建对象'),
        (r'\bJSON\.(?:parse|stringify)\s*\(', 'JSON 序列化'),
        (r'\b\w+\.sort\s*\(', '排序'),
        (r'\bObject\.(?:keys|values|entries)\s*\(', '遍历分配'),
    ]
    for fn, src in files.items():
        for hm in re.finditer(HOT, src):
            body = _body_of(src, hm, 6000)
            if not body:
                continue
            start_line = src[:hm.start()].count('\n') + 1
            for pat, what in BAN:
                bm = re.search(pat, body)
                if not bm:
                    continue
                off = body[:bm.start()].count('\n')
                hits.append((fn, start_line + off,
                             '每帧回调内%s → 应缓存到初始化' % what))
    return hits


@pattern('Y02', 'P1', '每帧回调内分配对象（GC 压力）',
         'update 内创建数组/对象字面量/闭包，每帧产生垃圾')
def y02(module, files):
    hits = []
    HOT = (r'\b(?:update|lateUpdate|tick|fixedUpdate|onTick)\s*\(\s*(?:[^)]{0,40})?\)'
           r'\s*(?::[^{]+)?\{')
    ALLOC = [
        (r'=\s*\[\s*\]', '空数组'),
        (r'=\s*\{\s*\}', '空对象'),
        (r'\.\s*(?:map|filter|slice|concat)\s*\(', '数组变换'),
        (r'\(\s*\)\s*=>', '闭包'),
    ]
    for fn, src in files.items():
        for hm in re.finditer(HOT, src):
            body = _body_of(src, hm, 6000)
            if not body:
                continue
            start_line = src[:hm.start()].count('\n') + 1
            for pat, what in ALLOC:
                bm = re.search(pat, body)
                if not bm:
                    continue
                off = body[:bm.start()].count('\n')
                hits.append((fn, start_line + off, '每帧分配%s → 复用外部对象' % what))
                break
    return hits


_dedup = {}
for _p in PATTERNS:
    _dedup[_p['id']] = _p
PATTERNS[:] = list(_dedup.values())


# ============================================================
# 自检：注入已知缺陷，验证每条模式能否检出
# 永远返回 0 命中的检查等于没有检查
# ============================================================

SELF_TEST_CASES = {
    'A01': 'if (x <= 0) throw new Error("bad");',
    'A02': 'const n = opts.count ?? 4;',
    'A03': 'const v = clamp(opts.ratio, 0, 1);',
    'A04': 'this._smooth = lerp(this._smooth, sample, 0.1);',
    'A05': 'const seed = opts.seed >>> 0;',
    'B01': 'for (let i = 0; i < opts.octaves; i++) { total += 1; }',
    'B02': 'while (radius < maxRadius) { radius *= 2; }',
    'B03': 'function roll(id) { return roll(sub[id]); }',
    'C01': 'const TABLE = { a: 1 };\nfunction get(k) { return TABLE[k]; }',
    'C02': 'const tally = {};\ntally[k] = (tally[k] || 0) + 1;',
    'C03': 'Object.assign(target, JSON.parse(raw));',
    'D02': ('function register(type, fn, overwrite = false) {\n'
            '  map.set(type, fn);\n'
            '}'),
    'E01': 'this._listeners.forEach(fn => fn(result));',
    'F01': ('function importState(list) {\n'
            '  for (const i of list) this._map.set(i.id, i);\n'
            '}'),
    'G01': 'this._onChange = fn;',
    'I01': ('private readonly _log = [];\n'
            'this._log.push(entry);'),
    'J01': 'this._spend(from, n);\nthis._add(to, got);',
    'J02': 'try { risky(); } catch (e) { }',
    'K01': 'this._degraded = true;',
    'L01': 'if (this._onConflict === "error") { }',
    'L02': 'return x === 0 ? 1 : 1;',
    'M01': 'function canDo(x) { if (!evaluator) return true; }',
    'N01': 'const now = Date.now();',
    'N02': 'const r = Math.random();',
    'O01': 'const max = (1 << 31) - 1;',
    'O02': 'const ratio = value / total;',
    'O03': 'console.error("failed");',
    'O04': 'return this._items;',
    'P01': 'function clampNum(v, min, max, def) { return Math.min(Math.max(v, min), max); }',
    'P02': 'let best = -Infinity;',
    'P03': 'const n = Math.max(1, opts.count);',
    'P04': 'return list.slice(0, n);',
    'P05': "case 'add': return oldVal + p.value;",
    'Q01': 'const buf = new Float32Array(size);',
    'Q03': 'const cell = new Map();\ncell.delete(id);',
    'Q05': 'const m = Math.max(...values);',
    'R01': 'const parts = path.split(".");\napplyPatch(root, parts, v);',
    'R02': 'for (const i of indices) { arr.splice(i, 1); }',
    'R04': 'const key = [a, b].join("|");',
    'S01': 'this._enabled = opts.enabled ?? true;',
    'T01': 'while (diff > 180) diff -= 360;',
    'T02': 'for (let i = from; i < limit; i++) { s += i; }',
    'U01': 'function display(v) { return v || 0; }',
    'W01': ('function buy(id: string, quantity: number) {\n'
            '  const t = price * quantity;\n'
            '}'),
    'X01': ('onLoad() {\n'
            '  this.node.on(Node.EventType.TOUCH_START, this.onTouch, this);\n'
            '}\n'
            'private onTouch() { }'),
    'X02': ('onLoad() {\n'
            '  this.schedule(this.tick, 1);\n'
            '}\n'
            'private tick() { }'),
    'X03': ('onLoad() {\n'
            "  resources.load('bg/spriteFrame', SpriteFrame, (e, sp) => { this.sp = sp; });\n"
            '}'),
    'X04': ('onLoad() {\n'
            '  tween(this.node).repeatForever(tween().to(1, { angle: 360 })).start();\n'
            '}'),
    'X05': 'lock(mutex);\ndoWork();',
    'X06': "this.node.on('evt', () => { this.hp -= 1; });",
    'Y01': ('update(dt: number) {\n'
            '  const n = find("Canvas/Player");\n'
            '}'),
    'Y02': ('update(dt: number) {\n'
            '  const list = [];\n'
            '  for (const x of this.items) list.push(x);\n'
            '}'),
}

# 需要多行上下文才能触发的模式（单句不足以命中）
SELF_TEST_CONTEXT_CASES = {
    'D01': ('export interface PlaceResult {\n'
            '  ok: boolean;\n'
            '  missing: string[];\n'
            '}\n'
            'function place(): PlaceResult {\n'
            '  return { ok: true };\n'
            '}'),
    'E02': ('on(fn) { this._set.add(fn); return () => this._set.delete(fn); }\n'
            'off(fn) { this._set = new Set([...this._set].filter(x => x !== fn)); }'),
    'H01': ('setStat(k, v) {\n'
            '  if (!Number.isFinite(v)) throw new Error("bad");\n'
            '  this._m.set(k, v);\n'
            '}\n'
            'addStat(k, v) { this._m.set(k, this._m.get(k) + v); }'),
    'I02': ('active() {\n'
            '  return this._all.filter(x => this.get(x) !== null);\n'
            '}'),
    'K02': ('class C {\n'
            '  private readonly _items = [];\n'
            '  private readonly _cache = new Map();\n'
            '  clear() { this._items.length = 0; }\n'
            '}'),
    'M02': ('canUnlock(id) {\n'
            '  return this._balance >= cost;\n'
            '}'),
    'Q02': ('class LazyHeap {\n'
            '  get size() { return this._heap.length; }\n'
            '  remove(h) { h.removed = true; }\n'
            '}'),
    'Q04': ('class Pool {\n'
            '  prewarm(n) { for (let i = 0; i < n; i++) this._idle.push(this._create()); }\n'
            '  release(o) { this._active--; }\n'
            '}'),
    'R03': ('function parsePath(p) { return p.split("."); }\n'
            'function applyPatch(base, patch) { const parts = parsePath(patch.path); }'),
}


def _run_one_pattern(p, src):
    files = {'case.ts': strip_comments(src)}
    return p['fn']('selftest', files)


def self_test_infra():
    """元检查：扫描器基础设施本身是否可信。

    为什么需要这一层：
    模式自检只验证"这条模式能不能检出"，但**行号对不对**、**注释有没有被
    误当代码**这类问题出在公共基建上，模式自检一条都抓不到。
    实测教训：strip_comments 曾把块注释替换成等量换行，导致 93% 的
    文件行号前移（最大偏移 85 行），报告出来的行号全部不可信——
    而当时 61/61 模式自检全绿，完全没报警。
    """
    cases = [
        ('块注释', 'const a = 1;\n/* 注释\n   第二行\n   第三行 */\nconst b = 2;\n'),
        ('行注释', 'const a = 1; // 这里有 clamp(opts.x, 0, 1)\nconst b = 2;\n'),
        ('混合',   '/* 头 */\nconst a = 1; // 尾注\n/* 中\n段 */\nconst b = 2;\n'),
        ('无注释', 'const a = 1;\nconst b = 2;\n'),
        ('注释在行中', 'const a = 1 /* 内联 */ + 2;\n'),
    ]
    bad = []
    for name, src in cases:
        out = strip_comments(src)
        if len(out.split('\n')) != len(src.split('\n')):
            bad.append('%s: 行数 %d → %d' % (
                name, len(src.split('\n')), len(out.split('\n'))))
        # 注释内容不得残留
        for kw in ('clamp(opts.x', '这里有', '注释', '内联', '第二行', '尾注', '段'):
            if kw in out:
                bad.append('%s: 注释内容残留 "%s"' % (name, kw))
    print('=' * 70)
    print('基础设施自检（strip_comments）')
    print('=' * 70)
    if bad:
        print('  ✗ 发现问题：')
        for b in bad:
            print('    %s' % b)
        print('\n  行号错位会让整份报告不可用，必须先修这里。')
        return 1
    print('  ✓ 行数守恒（%d 个用例）' % len(cases))
    print('  ✓ 注释内容已剔除，不参与匹配')
    return 0


def self_test():
    if self_test_infra():
        return 1
    print()
    tmp = tempfile.mkdtemp(prefix='pattern-selftest-')
    mod = os.path.join(tmp, 'selftest')
    os.makedirs(mod)
    try:
        passed, failed, skipped = [], [], []
        for p in PATTERNS:
            pid = p['id']
            if pid in SELF_TEST_CONTEXT_CASES and SELF_TEST_CONTEXT_CASES[pid]:
                src = SELF_TEST_CONTEXT_CASES[pid]
                shown = src.replace('\n', ' ')[:50]
            elif pid in SELF_TEST_CASES:
                snippet = SELF_TEST_CASES[pid]
                src = 'export function f() {\n  %s\n}\n' % snippet
                shown = snippet[:50]
            else:
                skipped.append(pid)
                continue
            open(os.path.join(mod, 'case.ts'), 'w', encoding='utf-8').write(src)
            try:
                hits = _run_one_pattern(p, src)
            except Exception as e:
                failed.append((pid, '异常: %s' % e))
                continue
            if hits:
                passed.append(pid)
            else:
                failed.append((pid, '未检出: %s' % shown))
        print('=' * 70)
        print('模式自检 · 共 %d 条' % len(PATTERNS))
        print('=' * 70)
        print('  检出成功: %d' % len(passed))
        print('  未检出  : %d' % len(failed))
        print('  跳过    : %d' % len(skipped))
        if failed:
            print('\n  未检出的模式（需修复检查逻辑）：')
            for pid, why in failed:
                print('    %-4s %s' % (pid, why))
        if skipped:
            print('\n  跳过（无测试用例）：%s' % ' '.join(skipped))
        print('\n' + '=' * 70)
        print('结论：%s' % ('全部可检出的模式均通过' if not failed
                            else '%d 条模式失效，需修复' % len(failed)))
        print('=' * 70)
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================

def main():
    if '--self-test' in _flags:
        sys.exit(self_test())

    only = set(_args) if _args else None
    flags = set(_flags)
    lv_filter = 'P0' if '--p0' in flags else None
    pf = next((f.split('=')[1] for f in flags if f.startswith('--pattern=')), None)

    plugins = load_plugins(only)
    if not plugins:
        print('未找到可扫描的模块目录（SRC=%s）' % SRC)
        print('提示：扁平结构请加 --flat；子目录结构请确认 --src 指向模块根。')
        return

    total = 0
    by_pattern = {}
    rows = []

    for mod, files in plugins.items():
        for p in PATTERNS:
            if pf and p['id'] != pf:
                continue
            if lv_filter and p['level'] != lv_filter:
                continue
            try:
                hits = p['fn'](mod, files)
            except Exception as e:
                print('[warn] 模式 %s 在 %s 上异常: %s' % (p['id'], mod, e),
                      file=sys.stderr)
                continue
            for fn, line, snip in hits:
                rows.append((mod, p, fn, line, snip))
                by_pattern[p['id']] = by_pattern.get(p['id'], 0) + 1
                total += 1

    if '--json' in flags:
        json.dump({
            'src': SRC,
            'modules': len(plugins),
            'total': total,
            'by_pattern': by_pattern,
            'items': [{'module': m, 'pattern': p['id'], 'level': p['level'],
                       'name': p['name'], 'file': fn, 'line': ln, 'snippet': s}
                      for m, p, fn, ln, s in rows],
        }, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return

    print('=' * 78)
    print('缺陷模式扫描 · %d 个模块 · %d 条模式 · src=%s'
          % (len(plugins), len(PATTERNS), SRC))
    print('=' * 78)

    print('\n【模式命中排行】')
    for pid, n in sorted(by_pattern.items(), key=lambda x: -x[1]):
        meta = next(p for p in PATTERNS if p['id'] == pid)
        print('  %-4s %-3s %-40s %4d' % (pid, meta['level'], meta['name'][:40], n))

    print('\n【明细】')
    cur = None
    for mod, p, fn, line, snip in sorted(rows, key=lambda r: (r[1]['id'], r[0])):
        key = p['id']
        if key != cur:
            cur = key
            print('\n-- %s - %s (%s) --' % (p['id'], p['name'], p['level']))
            print('   %s' % p['desc'])
        print('   %-18s %-30s:%-5d %s' % (mod, fn, line, snip))

    print('\n' + '=' * 78)
    print('合计 %d 处候选。注意：这是**候选**，需人工确认是否为真问题。' % total)
    print('扫描器会有漏报与误报，它只用来缩小人工精审的范围。')
    print('改过模式逻辑后，跑 --self-test 验证模式本身没有失效。')
    print('=' * 78)


if __name__ == '__main__':
    main()
