#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技能集群索引器 (index.py)

扫描「大类根目录」下所有大类的 skills/，生成全局 INDEX.md，
并提供定向检索、命中计数、冷藏回热、跨大类写入。

用法：
    python3 scripts/index.py                        重建全局索引
    python3 scripts/index.py --find 合同 审查        定向检索（计数+回热）
    python3 scripts/index.py --find 打包 --domain legal   限定大类检索
    python3 scripts/index.py --add X.md --domain legal    写入指定大类
    python3 scripts/index.py --list                 列出全部（按大类分组）
    python3 scripts/index.py --stats                统计与分层建议

设计前提：
  - 技能只增不减，命中数决定加载优先级，不决定存亡
  - 技能物理分散在各人类 skills/ 下，逻辑上由全局 INDEX 统一检索
  - 写入一律落到大类根目录的真实路径（不走 junction 虚拟路径）
"""

import re
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from domain import load_config, domain_root, domain_dir, CONFIG  # noqa: E402

# 分层阈值（天）
COLD_AFTER = 30
ARCHIVE_AFTER = 90


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
        meta[k] = v
    return meta


def scan(cfg: dict, only: str = None) -> list[dict]:
    """扫描全部大类的 skills/，返回条目列表。"""
    items = []
    seen = set()          # 跨大类共享：软链接会让同一技能出现在多个人类下
    for key, meta in cfg.get("domains", {}).items():
        if only and key != only:
            continue
        skills = domain_dir(cfg, key) / "skills"
        if not skills.exists():
            continue
        for f in sorted(skills.rglob("*.md")):
            if f.name.startswith("_"):
                continue
            # 软链接会让同一技能在多个大类下重复出现，
            # 按真实路径去重，否则命中计数重复累加、索引出现同 ID 多条
            try:
                real = f.resolve()
            except Exception:
                real = f
            if real in seen:
                continue
            seen.add(real)
            fm = parse_frontmatter(f)
            items.append({
                "id": fm.get("id", "?"),
                "name": fm.get("name", f.stem),
                "domain": key,
                "domain_name": meta.get("name", key),
                "tier": fm.get("tier", "cold"),
                "keywords": fm.get("keywords", []) if isinstance(fm.get("keywords"), list) else [],
                "trigger": fm.get("trigger", ""),
                "hits": int(fm.get("hits", 0) or 0),
                "last_used": fm.get("last_used", ""),
                "related": fm.get("related", []) if isinstance(fm.get("related"), list) else [],
                "path": str(real),
                "_file": real,
                "_alias_of": "" if real == f else str(f),
            })
    return items


def days_since(d: str) -> int:
    try:
        return (date.today() - datetime.strptime(d, "%Y-%m-%d").date()).days
    except Exception:
        return 9999


def _set_fm_field(text: str, key: str, value) -> str:
    """设置 frontmatter 字段：存在则替换，不存在则在 frontmatter 内补上。

    不能只用 re.sub —— 字段不存在时它静默无操作，
    会导致「提示已计数 +1」但实际什么都没写（曾经的真实 bug）。
    """
    if re.search(r"^%s:" % re.escape(key), text, flags=re.M):
        return re.sub(r"^%s:.*$" % re.escape(key), f"{key}: {value}",
                      text, count=1, flags=re.M)
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return text          # 无 frontmatter，交给调用方判断
    return f"---\n{m.group(1)}\n{key}: {value}\n---\n" + text[m.end():]


def bump(item: dict) -> bool:
    """命中 +1。返回是否真的写成功——失败要让调用方知道，别假装成功。"""
    f = item["_file"]
    text = f.read_text(encoding="utf-8")
    orig = text

    text = _set_fm_field(text, "hits", item["hits"] + 1)
    text = _set_fm_field(text, "last_used", date.today().isoformat())

    if item["tier"] == "archive":
        text = _set_fm_field(text, "tier", "cold")
        print(f"  ↻ {item['id']} 已从冷藏回热")

    if text == orig:
        print(f"  ⚠ {item['id']} 计数写入失败：frontmatter 缺失或格式异常，"
              f"请检查文件头部 --- 区块")
        return False
    f.write_text(text, encoding="utf-8")
    return True


def write_index(cfg: dict, items: list[dict]) -> None:
    """生成全局 INDEX.md，按大类分组。"""
    root = domain_root(cfg)
    out = root / "INDEX.md"
    common = cfg.get("common", "_common")

    groups = {}
    for i in items:
        groups.setdefault(i["domain"], []).append(i)

    lines = [
        "# 技能总索引（全局）",
        "",
        "> **定向加载第一步：读这个文件。** 按 keywords / trigger 匹配，命中后加载 `path`。",
        "> 本文件由 `python3 scripts/index.py` 自动生成，位于大类根目录，勿手改。",
        "",
        f"大类根目录：`{root}`",
        f"技能总数：{len(items)}",
        "",
        "## 加载顺序",
        "",
        "1. 先看**当前项目接入的大类**（`python3 scripts/domain.py --detect`）",
        "2. 该大类没命中 → 查 `_common` 通用大类",
        "3. 都没有 → 不加载，直接开工；学到的流程收工后入库",
        "",
    ]

    order = [common] + [k for k in cfg.get("domains", {}) if k != common]
    for key in order:
        if key not in groups:
            continue
        meta = cfg.get("domains", {}).get(key, {})
        title = meta.get("name", key)
        tag = "【通用】" if key == common else ""
        lines += [f"## {tag}{title}（`{key}`）", "",
                  "| ID | 名称 | 关键词 | 触发场景 | 层 | 命中 |",
                  "|----|------|--------|---------|-----|------|"]
        for i in sorted(groups[key], key=lambda x: -x["hits"]):
            kw = ", ".join(i["keywords"][:5])
            mark = {"hot": "🔥", "cold": "❄️", "archive": "🧊"}.get(i["tier"], "")
            lines.append(f"| {i['id']} | {i['name']} | {kw} | {i['trigger'][:30]} "
                         f"| {mark} | {i['hits']} |")
        lines.append("")

    lines += [
        "## 大类与路径",
        "",
        "| 大类 | 真实路径 |",
        "|---|---|",
    ]
    for key in order:
        if key in groups or key in cfg.get("domains", {}):
            lines.append(f"| {cfg['domains'][key].get('name', key)} "
                         f"| `{domain_dir(cfg, key) / 'skills'}` |")
    lines += ["", "> 项目通过 junction 接入某大类后，AI 仍可用绝对路径访问本索引与其他大类。", ""]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"全局索引已生成：{out}（{len(items)} 项）")

    # 二级索引：每个大类一份，任务开始时只扫本类这份（约 30 行）
    # 全局索引只在跨类检索时读，避免库变大后索引吃掉上下文
    for key in groups:
        _write_domain_index(cfg, key, items)


def _write_domain_index(cfg: dict, key: str, items: list[dict]) -> None:
    """生成单个大类的索引：任务开始时读这个，不读全局。"""
    d = domain_dir(cfg, key)
    meta = cfg.get("domains", {}).get(key, {})
    common = cfg.get("common", "_common")

    own = [i for i in items if i["domain"] == key]
    # 通用技能通过 _common 链接可见，附在末尾供快速查阅
    common_items = [i for i in items if i["domain"] == common] if key != common else []

    lines = [
        f"# {meta.get('name', key)} — 技能索引",
        "",
        f"> 本类 {len(own)} 个｜通用 {len(common_items)} 个",
        "> 自动生成，勿手改。全局索引见 `../INDEX.md`（仅跨类检索时读）。",
        "",
        "## 本类技能",
        "",
        "| ID | 名称 | 关键词 | 触发场景 | 层 | 命中 |",
        "|----|------|--------|---------|-----|------|",
    ]
    if own:
        for i in sorted(own, key=lambda x: -x["hits"]):
            mark = {"hot": "🔥", "cold": "❄️", "archive": "🧊"}.get(i["tier"], "")
            lines.append(f"| {i['id']} | {i['name']} | {', '.join(i['keywords'][:5])} "
                         f"| {i['trigger'][:30]} | {mark} | {i['hits']} |")
    else:
        lines.append("| （暂无） | | | | | |")

    if common_items:
        lines += ["", f"## 通用技能（来自 `{common}`，通过链接可见）", "",
                  "| ID | 名称 | 触发场景 |", "|----|------|---------|"]
        for i in sorted(common_items, key=lambda x: -x["hits"]):
            lines.append(f"| {i['id']} | {i['name']} | {i['trigger'][:40]} |")

    # 领域规则与角色：让读者知道这类目录下还有什么
    for sub, label in (("rules", "领域规则"), ("agents", "角色定义")):
        sd = d / sub
        fs = [f for f in sd.glob("*.md")] if sd.exists() else []
        if fs:
            lines += ["", f"## {label}（`{sub}/`）", ""]
            for f in fs:
                lines.append(f"- `{f.name}`")

    lines += ["", "> 加载顺序：本类 → 通用 → 都没有则不加载，直接开工。", ""]
    (d / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  └ 二级索引：{d.name}/INDEX.md（{len(own)} 项）")


def cmd_add(cfg: dict, src: str, domain: str) -> None:
    """把技能文件写入指定大类的 skills/。"""
    if domain not in cfg.get("domains", {}):
        sys.exit(f"未注册的大类：{domain}\n已注册：{', '.join(cfg.get('domains', {}))}")
    src = Path(src).expanduser().resolve()
    if not src.exists():
        sys.exit(f"文件不存在：{src}")
    dest_dir = domain_dir(cfg, domain) / "skills"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        print(f"⚠ 已存在同名文件：{dest}")
        print("  → 这是补充而非新建：应编辑已有文件，追加到对应段落，不要覆盖")
        return
    shutil.copy2(src, dest)
    print(f"✓ 已写入：{dest}")
    print("  → 记得重建索引：python3 scripts/index.py")


def find(cfg: dict, terms: list[str], only: str = None) -> list[dict]:
    items = scan(cfg, only)

    # 兼容 `--find "cocos 脚本审核"` 这种带引号整串传入：
    # 不二次切分的话，整串做子串匹配必然失败（多词检索一直是失效的）
    expanded: list[str] = []
    for t in terms:
        expanded += [x for x in re.split(r"[\s,，、;；]+", t) if x]
    terms = expanded or terms

    scored = []
    for i in items:
        hay = " ".join([i["id"], i["name"], i["trigger"], " ".join(i["keywords"])]).lower()
        s = 0
        for t in terms:
            tl = t.lower()
            if tl in hay:
                s += 1                      # 正向：查询词出现在技能描述里
            elif len(tl) >= 4:
                # 反向：关键词出现在整句查询里（中文无空格分词难）
                # 用 sum 而非 any —— 命中 5 个词理应比命中 1 个词排得更前
                s += sum(1 for kw in i["keywords"]
                         if len(kw) >= 2 and kw.lower() in tl)
        if s:
            scored.append((s, i))
    scored.sort(key=lambda x: (-x[0], -x[1]["hits"]))
    if not scored:
        print(f"未命中：{' '.join(terms)}" + (f"（限定大类 {only}）" if only else ""))
        print("→ 库里还没有这个技能，收工后走捕获流程入库")
        return []
    print(f"命中 {len(scored)} 项：\n")
    for s, i in scored:
        mark = {"hot": "🔥", "cold": "❄️", "archive": "🧊"}.get(i["tier"], "")
        print(f"  {mark} [{i['id']}] {i['name']}  （{i['domain_name']}，匹配 {s}）")
        print(f"      {i['path']}")
    print()
    ok = 0
    for _, i in scored[:3]:
        if bump(i):
            ok += 1
    # 按实际成功数汇报，别把失败也报成成功
    if ok:
        print(f"已为 {ok} 项计数 +1")
    else:
        print("⚠ 没有任何条目完成计数 —— 检查源文件 frontmatter 是否规范")
    return [i for _, i in scored]


def cmd_list(cfg: dict) -> None:
    items = scan(cfg)
    groups = {}
    for i in items:
        groups.setdefault(i["domain_name"], []).append(i)
    for name in sorted(groups):
        print(f"\n【{name}】")
        for i in sorted(groups[name], key=lambda x: -x["hits"]):
            print(f"  [{i['id']}] {i['tier']:8} 命中{i['hits']:>3}  {i['name']}")


def cmd_stats(cfg: dict) -> None:
    items = scan(cfg)
    print("=" * 58)
    print("技能集群统计")
    print("=" * 58)
    print(f"\n技能总数：{len(items)}   累计命中：{sum(i['hits'] for i in items)}")
    groups = {}
    for i in items:
        groups.setdefault(i["domain_name"], []).append(i)
    for name in sorted(groups):
        n = len(groups[name])
        h = sum(i["hits"] for i in groups[name])
        print(f"  {name:<10} {n:>3} 个   命中 {h:>3}")
    print("\n【分层建议】（只建议，不自动改；冷藏≠删除）")
    sug = []
    for i in items:
        d = days_since(i["last_used"])
        if d >= ARCHIVE_AFTER and i["tier"] != "archive":
            sug.append((i, f"闲置 {d} 天 → 建议冷藏"))
        elif d >= COLD_AFTER and i["tier"] == "hot":
            sug.append((i, f"闲置 {d} 天 → hot → cold"))
        elif i["hits"] >= 10 and i["tier"] != "hot":
            sug.append((i, f"命中 {i['hits']} → 建议升 hot"))
    for i, s in sug or []:
        print(f"  · [{i['id']}] {i['name']}（{i['domain_name']}）：{s}")
    if not sug:
        print("  （暂无）")



def cmd_check(cfg):
    """防漂移：索引里记录的 vs 磁盘上实际存在的。

    为什么需要：索引是**产物**，文件是**源**。改了文件忘了重建索引，
    定向加载就会指向不存在的包、或漏掉新写的包——而它不会报错，
    只是"没命中"，看起来跟"库里没有这个技能"一模一样。
    """
    issues = []
    items = scan(cfg)
    root = domain_root(cfg)

    by_id = {}
    for it in items:
        if it["id"] in by_id:
            issues.append({"level": "error", "issue":
                           "ID 重复：%s（%s / %s）" % (it["id"], by_id[it["id"]], it["path"])})
        else:
            by_id[it["id"]] = it["path"]

    # 索引文件里写了、但磁盘上没有的条目（悬空引用）
    for key in cfg.get("domains", {}):
        idx = domain_dir(cfg, key) / "INDEX.md"
        if not idx.exists():
            continue
        try:
            text = idx.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in re.finditer(r'`?([A-Z]\d{2,4})`?', text):
            rid = m.group(1)
            if rid not in by_id:
                issues.append({"level": "warn", "issue":
                               "%s 索引引用了 %s，但磁盘上没有该技能包" % (idx.name, rid)})

    # 无 keywords / 无 trigger → 永远召不回
    for it in items:
        if not it.get("keywords"):
            issues.append({"level": "warn", "issue":
                           "%s 缺 keywords → 检索召回不到" % it["path"]})
        if not it.get("trigger"):
            issues.append({"level": "warn", "issue":
                           "%s 缺 trigger → 不知道何时加载" % it["path"]})

    print("index · 防漂移检查")
    print("扫描到 %d 个技能包" % len(items))
    errs = [i for i in issues if i["level"] == "error"]
    for i in issues:
        print(("  ✗ " if i["level"] == "error" else "  ! ") + i["issue"])

    # 0 命中不等于没问题：最常见的原因是 domains 还没实例化，
    # 或 config.yaml 的 root 与实际目录不一致。直接报「一致」会让人以为库是好的。
    if not items:
        print()
        print("  ⚠ 一个包都没扫到——**这不等于没问题**。逐项排查：")
        print("    1) 大类目录建了没：python3 scripts/domain.py --list")
        print("       没有就初始化：python3 scripts/domain.py --init")
        print("    2) config.yaml 的 root 指向了别处（当前：%s）" % root)
        print("    3) 文件放在了 skills/ 之外，或以 _ 开头被跳过")
        print("   扫不到时 --find 也永远为空，看起来跟「库里没有」一模一样。")

    print("结论：%s" % ("一致。" if not issues and items
                        else ("未扫到任何包，先确认大类目录" if not items
                              else "%d 错误 / %d 预警 → 跑 index.py 重建" % (
                                  len(errs), len(issues) - len(errs)))))
    return 1 if errs else 0


def cmd_self_test():
    """验证检索 / 计数 / 回热 / 防漂移四条主链路真的能跑。

    为什么需要：这套机制最坏的失效是"看起来在跑"——
    --find 永远返回空、--check 永远说一致，而实际一个包都没扫到
    （domains 未实例化、路径拼错、ID 前缀不匹配都会造成这个假象）。
    """
    import tempfile
    import shutil
    ok = fail = 0

    def chk(cond, msg):
        nonlocal ok, fail
        print(("  ✓ " if cond else "  ✗ ") + msg)
        if cond:
            ok += 1
        else:
            fail += 1

    tmp = tempfile.mkdtemp()
    try:
        cfg = {"domains": {"dev": {"name": "开发"}}, "root": tmp,
               "subdirs": ["agents", "skills", "rules"], "common": "_common"}
        sd = domain_dir(cfg, "dev") / "skills"
        sd.mkdir(parents=True)
        (sd / "pack.md").write_text("""---
id: D900
name: 交付打包
keywords: [交付, 打包, zip]
trigger: 产物多于一个
tier: cold
---
# 交付打包
""", encoding="utf-8")

        items = scan(cfg)
        chk(len(items) == 1, "能扫到技能包（%d 个）" % len(items))
        chk(items and items[0]["id"] == "D900", "frontmatter 的 id 能解析")

        # 关键词召回：同义词要能命中
        hits = [i for i in items if "打包" in " ".join(i.get("keywords", []))]
        chk(bool(hits), "keywords 同义词可召回")

        # 缺字段必须被防漂移查出来
        (sd / "bad.md").write_text("""---
id: D900
name: 重复ID
---
""", encoding="utf-8")
        code = cmd_check(cfg)
        chk(code == 1, "重复 ID 被判为错误（退出码 1）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("自检：%d 通过 / %d 失败" % (ok, fail))
    if not fail:
        print("结论：索引主链路工作正常")
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", nargs="+", metavar="关键词")
    ap.add_argument("--domain", metavar="大类KEY", help="限定大类（检索/写入）")
    ap.add_argument("--add", metavar="文件", help="写入指定大类（配合 --domain）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--check", action="store_true", help="防漂移检查（索引 vs 磁盘）")
    ap.add_argument("--self-test", action="store_true", help="验证主链路真的能跑")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    items = scan(cfg)

    if args.self_test:
        sys.exit(cmd_self_test())
    if args.check:
        sys.exit(cmd_check(cfg))
    if args.add:
        if not args.domain:
            sys.exit("--add 必须配合 --domain <大类KEY>")
        cmd_add(cfg, args.add, args.domain)
        items = scan(cfg)
        write_index(cfg, items)
    elif args.find:
        find(cfg, args.find, args.domain)
        write_index(cfg, scan(cfg))
    elif args.list:
        cmd_list(cfg)
    elif args.stats:
        cmd_stats(cfg)
    else:
        write_index(cfg, items)


if __name__ == "__main__":
    main()
