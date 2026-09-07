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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", nargs="+", metavar="关键词")
    ap.add_argument("--domain", metavar="大类KEY", help="限定大类（检索/写入）")
    ap.add_argument("--add", metavar="文件", help="写入指定大类（配合 --domain）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    items = scan(cfg)

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
