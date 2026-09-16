# -*- coding: utf-8 -*-
"""验证 --resolve 的自指缺陷修复。

缺陷：resolve() 用全文匹配 `b"<<<<<<<" in data` 判断冲突标记，
而 push_api.py 自己的源码里就写着这个字面量（它要检查它），
于是 `push_api.py --resolve push_api.py` 永远报「仍有冲突标记」，
冲突无法解决，只能绕开脚本手写 API 提交。

修复：新增 `_has_conflict_marker()`，只认行首且要求成对。

未修复时 ① ⑤ 会红；修复后全绿。
"""
import importlib.util, os, sys

SRC = os.environ.get("PA", "/data/workspace/arcs_new/工具审查/scripts/push_api.py")
spec = importlib.util.spec_from_file_location("pa", SRC)
pa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pa)

R = []


def check(name, cond, detail=""):
    R.append((name, cond))
    print("  %s %-56s %s" % ("✓" if cond else "✗", name, detail if not cond else ""))


print("=" * 72)
print("A. 真实冲突标记必须被拦住（不能修过头）")
print("=" * 72)

check("标准冲突块（<<<<<<< HEAD … >>>>>>>）",
      pa._has_conflict_marker(b"line1\n<<<<<<< HEAD\nmine\n=======\ntheirs\n>>>>>>> main\nline2\n") is True)
check("只删了开头（残留 >>>>>>>）",
      pa._has_conflict_marker(b"a\n>>>>>>> main\n") is False,
      "不成对，不算冲突块")
check("CRLF 冲突块",
      pa._has_conflict_marker(b"a\r\n<<<<<<< HEAD\r\nx\r\n=======\r\ny\r\n>>>>>>> main\r\n") is True)
check("无标记的正常文件",
      pa._has_conflict_marker(b"print(1)\n") is False)

print()
print("=" * 72)
print("B. 内容里的字面量不能被误判（这正是本次缺陷）")
print("=" * 72)

# push_api.py 自身的源码：含该字面量但不在行首
self_src = open(SRC, "rb").read()
print("  （被测文件自身 %d 字节，含 b'<<<<<<<' %d 处）"
      % (len(self_src), self_src.count(b"<<<<<<<")))
check("① push_api.py 自身不被判为有冲突（核心用例）",
      pa._has_conflict_marker(self_src) is False)

check("② 行内的字面量（源码写法）",
      pa._has_conflict_marker(b'    if b"<<<<<<<" in data:\n        pass\n') is False)
check("③ Markdown 行首 setext 标题 =======",
      pa._has_conflict_marker(b"Title\n=======\n\ntext\n") is False)
check("④ 文档里单独示意 <<<<<<<（无配对）",
      pa._has_conflict_marker("# 冲突标记形如：\n<<<<<<< HEAD\n".encode("utf-8")) is False)
check("⑤ 注释里同时出现两种字面量但都不在行首",
      pa._has_conflict_marker("# 检查 <<<<<<< 与 >>>>>>> 是否残留\n".encode("utf-8")) is False)
check("⑥ 中文行首紧跟标记（真实冲突的中文场景）",
      pa._has_conflict_marker("<<<<<<< 本地改动\n你好\n=======\n世界\n>>>>>>> 远端\n".encode("utf-8")) is True)

print()
print("=" * 72)
bad = [n for n, c in R if not c]
if bad:
    print("结果：%d/%d 通过，%d 项未通过" % (len(R) - len(bad), len(R), len(bad)))
    sys.exit(1)
print("结果：全部 %d 项通过" % len(R))
