#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描器「输入语料」守卫。

为什么需要
----------
上一轮的教训：verify.py 里残留迁移前的旧路径 `flow/godot`。
改名后该目录下是**功能点子目录、没有直接 .md**，
`os.listdir()` 过滤 `.md` 得到空列表 → 收集到 0 条 → **脚本正常退出、不报错**。
整套"待核对"机制空转了一整轮没人发现。

⛔ 失败模式是"返回 0 条"而不是"报错"，所以任何"能跑通"的检查都查不出来。

为什么不能断言「输出非空」
--------------------------
⚠ **输出为 0 往往是好状态**：
  check-symmetry 报 0 个断链 = 全部修好了；
  check-common-index 报 0 个问题 = 索引是干净的。
⛔ 若断言"输出 > 0"，则修完问题反而自检失败 —— 判据方向是反的。

✅ 真正的判据是「输入语料非空」：
  扫到 0 个文件、0 个概念、0 个 token，只有一个解释 —— **路径指错了层**。
  这个不变量在"结果完美"和"结果糟糕"时都必须成立。

ⓘ 文件名用下划线不用连字符：本模块要被各扫描器 `import corpus_guard`，
   而 `corpus-guard.py` 这种带连字符的名字**无法被 import**
   （Python 会把模块名当标识符）。⛔ 上一版就叫 corpus-guard.py，
   结果三个扫描器的 guard() 全部 import 失败、静默走 except 分支。

用法
----
各扫描器实现 `stats()` 返回输入计数，自检统一断言：

    import corpus_guard
    corpus_guard.check_all([verify, scan_gaps, check_symmetry, check_common_index])
"""
import os
import sys


class Fail(Exception):
    pass


def expect(label, n, minimum=1):
    """n < minimum → 抛 Fail。label 用于定位是哪个扫描器的哪项输入。"""
    if not isinstance(n, int) or n < minimum:
        raise Fail('%s：输入语料为 %r（应 ≥%d）'
                   % (label, n, minimum))


def expect_dir(label, path, suffix='.md', minimum=1):
    """目录存在 + 含预期类型文件数 ≥ minimum。

    ⚠ 目录不存在与"存在但没文件"要分开报：
       前者是路径写错，后者是路径指到了错误的层（上一轮正是后者）。
    """
    if not os.path.isdir(path):
        raise Fail('%s：目录不存在 %s' % (label, path))
    n = len([f for f in os.listdir(path) if f.endswith(suffix)])
    if n < minimum:
        raise Fail('%s：%s 下没有%s文件（目录存在但为空 → 路径极可能指错层）'
                   % (label, path, suffix))
    return n


def run(modules):
    """对一组已导入的扫描模块执行 stats() 并断言输入语料非空。

    返回 (通过数, 失败列表)。⛔ 不抛异常，让调用方统一报。
    """
    ok = 0
    fails = []
    for mod in modules:
        name = getattr(mod, '__name__', str(mod))
        fn = getattr(mod, 'stats', None)
        if fn is None:
            fails.append('%s：没有实现 stats()，无法核验输入语料' % name)
            continue
        try:
            st = fn()
        except Exception as e:      # ⓘ stats() 自身出错也要报出来
            fails.append('%s：stats() 执行失败（%s）' % (name, e))
            continue
        if not isinstance(st, dict) or not st:
            fails.append('%s：stats() 返回空，无法核验' % name)
            continue
        bad = [k for k, v in st.items()
               if not isinstance(v, int) or v < 1]
        if bad:
            fails.append('%s：输入语料为空 %s' % (name, {k: st[k] for k in bad}))
        else:
            ok += 1
    return ok, fails


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import importlib.util as _ilu
    here = os.path.dirname(os.path.abspath(__file__))
    mods = []
    # ⓘ 文件名带连字符，不能用 import_module，必须按文件路径加载
    for m in ('verify.py', 'scan-gaps.py', 'check-symmetry.py',
              'check-common-index.py'):
        path = os.path.join(here, m)
        try:
            spec = _ilu.spec_from_file_location(m[:-3], path)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mods.append(mod)
        except Exception as e:
            print('✗ 无法加载 %s（%s）' % (m, e))
    ok, fails = run(mods)
    for f in fails:
        print('✗', f)
    print('语料守卫：%d 通过 / %d 失败' % (ok, len(fails)))
    sys.exit(1 if fails else 0)
