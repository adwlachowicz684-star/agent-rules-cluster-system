#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
变更溯源 (note.py)

往 assets/ 追加一行记录：改了什么、为什么改、来源是什么。
**只写一行**——目的是回溯时能看懂，不是写文档。

用法：
    python3 scripts/note.py "C047" "版本分化" "macOS sed -i 需空参数"
    python3 scripts/note.py "R003" "补充" "漏了违约金条款" --domain legal
    python3 scripts/note.py --show                  查看引擎记录
    python3 scripts/note.py --show --domain legal   查看某大类记录
    python3 scripts/note.py --types                 列出全部类型
"""

import sys
import argparse
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from domain import load_config, domain_dir, CONFIG  # noqa: E402

TYPES = ["新增", "补充", "修正", "更新", "参考", "合并", "拆分", "冷藏"]

HEADER = """# 变更溯源（{title}）

> 技能条目会越来越多，半年后看到一条规则，没人记得它怎么来的、为什么这么写。
> 这里用一行回答这两个问题。**只写一行**，不写长篇。

| 日期 | 对象 | 类型 | 来源/原因 |
|------|------|------|-----------|
"""


def target_file(cfg, domain=None):
    if domain:
        if domain not in cfg.get("domains", {}):
            sys.exit("未注册的大类：%s" % domain)
        f = domain_dir(cfg, domain) / "assets" / "changelog.md"
        title = cfg["domains"][domain].get("name", domain)
    else:
        f = ROOT / "assets" / "changelog.md"
        title = "引擎"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(HEADER.format(title=title), encoding="utf-8")
    return f


def append(f, obj, kind, reason, src=""):
    line = "| %s | %s | %s | %s |" % (date.today().isoformat(), obj, kind, reason)
    if src:
        line = line[:-1] + " （来源：%s） |" % src
    text = f.read_text(encoding="utf-8")
    if line in text:
        print("已存在相同记录，跳过")
        return
    if not text.endswith("\n"):
        text += "\n"
    f.write_text(text + line + "\n", encoding="utf-8")
    print("已记录 → %s" % f)
    print("  " + line)


def show(f, last=30):
    if not f.exists():
        print("（暂无记录）%s" % f)
        return
    text = f.read_text(encoding="utf-8")
    print(text.split("| 日期 | 对象 | 类型 | 来源/原因 |")[0].strip())
    print()
    lines = [l for l in text.splitlines()
             if l.startswith("|") and "---" not in l and "日期" not in l]
    for l in lines[-last:]:
        print(l)
    if len(lines) > last:
        print("\n… 共 %d 条，显示最近 %d 条" % (len(lines), last))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("obj", nargs="?", help="改动对象（技能 ID / 文件名）")
    ap.add_argument("kind", nargs="?", help="类型：" + "/".join(TYPES))
    ap.add_argument("reason", nargs="?", help="来源或原因，一句话")
    ap.add_argument("--src", default="", help="来源标注（URL / 文档名）")
    ap.add_argument("--domain", default="", help="记录到某大类的 assets/")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--types", action="store_true")
    ap.add_argument("--last", type=int, default=30)
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args()

    if args.types:
        desc = ["首次创建", "出错或遗漏后补上（最常见）", "原来写的就是错的",
                "版本过期、环境变化", "来源文章/文档/对话",
                "多条并成一条", "一条拆成多条", "长期未用，冷藏保留"]
        for t, d in zip(TYPES, desc):
            print("  %-4s %s" % (t, d))
        return

    cfg = load_config(Path(args.config))
    f = target_file(cfg, args.domain or None)

    if args.show:
        show(f, args.last)
        return

    if not (args.obj and args.kind and args.reason):
        ap.print_help()
        sys.exit("\n示例：python3 scripts/note.py C047 版本分化 'macOS sed 需空参数'")

    if args.kind not in TYPES:
        sys.exit("未知类型：%s\n可用：%s" % (args.kind, "/".join(TYPES)))

    append(f, args.obj, args.kind, args.reason, args.src)


if __name__ == "__main__":
    main()
