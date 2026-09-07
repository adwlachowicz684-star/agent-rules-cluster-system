#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自进化整合助手 (consolidate.py)

职责：机械活交给脚本，判断活留给 AI/用户。
  - 解析 SKILLS/*.md 的表格条目与 pending/draft.md 的草稿
  - 用 bigram Jaccard 做语义粗筛，输出「重复 / 相关 / 新增」三类候选
  - 统计命中率、文件膨胀情况，给出修剪建议

不会自动改写任何文件 —— 最终决策必须由 AI 或用户做出。
用法：
    python scripts/consolidate.py              # 出报告
    python scripts/consolidate.py --root ..    # 指定 skill 根目录
"""

import re
import sys
import argparse
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from env import overlap as env_overlap, detect as env_detect
except Exception:
    env_overlap = lambda a, b: True
    env_detect = lambda: {}

DUP_THRESHOLD = 0.30   # 超过此相似度视为「疑似重复」，应强化而非新增
REL_THRESHOLD = 0.05   # 宽松判据：仅用于提示人工看一眼，宁可多报
MIN_SHARED = 5         # 共同 bigram 最少个数：低于此值一律判为不相关，
                       # 防命令类短条目因共享 python3/SKILLS 等高频词而误报
BLOAT_LIMIT = 40       # 单文件条目数上限
DEAD_HITS = 0          # 命中次数低于此值视为僵尸条目


# 无区分度的噪音 token：命令库里人人都有，不能作为相似证据
STOP = {"md", "py", "l1", "l2", "l3", "id", "in", "out", "the",
        "0", "1", "2", "3", "-m", "f", "d", "c", "rg"}


def bigrams(text: str) -> set:
    """中英混合特征集。

    中文取字符二元组（"修改配置" → 修改/改配/配置），
    英文/路径/命令按整体 token 取（"python3" 只算一个特征，
    不会因为两条命令都用了 python3 就判相似）。
    """
    feats = set()
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_./-]*", text):
        t = tok.lower()
        if t not in STOP:
            feats.add(t)
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(seg) < 2:
            feats.add(seg)
        else:
            feats.update(seg[i:i + 2] for i in range(len(seg) - 1))
    return feats


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def related_score(a: set, b: set) -> float:
    """宽松相关度：只看 jaccard，不设绝对量门槛。

    「重复」判错代价高（会漏掉该新增的条目），所以 similarity 严格；
    「相关」只是提示人工看一眼，判错代价低，所以这里宁可多报。
    """
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b) if inter >= 2 else 0.0


def similarity(a: set, b: set, min_shared: int = MIN_SHARED) -> float:
    """混合评分：overlap 为主 + jaccard 为辅。

    中文短文本下 jaccard 会因长度差被稀释（实测「同一件事的详写与简写」
    jaccard 仅 0.12），故以 overlap 为主，识别「一条是另一条的简写」。
    """
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter < min_shared:      # 绝对量不够，比例再高也是巧合
        return 0.0
    return 0.65 * (inter / min(len(a), len(b))) + 0.35 * (inter / len(a | b))



def _draft_env(text: str) -> str:
    """从草稿行里提取环境线索（如 [py3.8] / [win] 标记或显式约束）。"""
    m = re.search(r"\[(?:env|环境)\s*[:：]?\s*([^\]]+)\]", text, re.I)
    if m:
        return m.group(1).strip()
    for kw, spec in (("mac", "os:darwin"), ("macos", "os:darwin"),
                     ("win", "os:windows"), ("windows", "os:windows"),
                     ("linux", "os:linux")):
        if kw in text.lower():
            return spec
    m = re.search(r"py(?:thon)?\s*(?:>=|<=|==|>|<)\s*[\d.]+", text, re.I)
    return m.group(0) if m else ""


def scan_facts(items: list[tuple[str, str]], root: Path) -> list[tuple[str, str, str]]:
    """扫描疑似项目事实：路径 / 具体文件名 / 一次性日期。

    只挑可疑项交人工判断，不做自动删除——「consolidate.py」这类
    skill 内部文件名和「NAME.zip」这类占位符不算事实，直接放行。
    """
    # 占位符：模板里的通用名，不是真实文件
    placeholders = {"name", "dir", "path", "file", "id", "in", "out",
                    "x", "foo", "bar", "example", "test", "old", "new"}
    # skill 自身的文件名，属于内部引用而非项目事实
    internal = {p.name.lower() for p in root.rglob("*") if p.is_file()}

    patterns = [
        (r"/(?:etc|usr|var|home|tmp|opt)/[\w./-]+", "绝对路径"),
        (r"[\w-]+\.(?:conf|ya?ml|toml|ini|csv|xlsx|docx|pptx|log)\b", "具体文件名"),
        (r"\b\d{4}-\d{2}-\d{2}\b", "具体日期"),
        (r"[A-Z]:\\\w", "Windows 路径"),
    ]

    hits = []
    for where, text in items:
        for pat, label in patterns:
            m = re.search(pat, text)
            if not m:
                continue
            token = m.group().strip("/").lower()
            stem = re.split(r"[./\\]", token)[0]
            if stem in placeholders:          # NAME.zip / in.json 之类
                break
            if Path(token).name.lower() in internal:   # skill 内部文件
                break
            hits.append((where, label, m.group()))
            break
    return hits


def parse_table(path: Path) -> list[dict]:
    """解析 markdown 表格，返回条目字典列表（跳过 HTML 注释块内的示例行）。"""
    if not path.exists():
        return []
    entries = []
    header = None
    in_comment = False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        # 维护 HTML 注释状态，注释块内的行一律跳过
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            continue
        if not line.startswith("|"):
            continue
        # 命令里的转义管道 \| 要先保护，否则 split 会把一条命令切成两列
        safe = line.replace("\\|", "\x00")
        cells = [c.strip().replace("\x00", "|") for c in safe.strip("|").split("|")]
        if re.fullmatch(r"[-: ]+", "".join(cells)):      # 分隔行
            continue
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells))
        row["_id"] = row.get("ID", "?").strip()
        row["_env"] = (row.get("适用环境") or "").strip()
        row["_text"] = " ".join(
            v for k, v in row.items() if k not in ("ID", "命中"))
        row["_bg"] = bigrams(row["_text"])
        entries.append(row)
    return entries


def parse_drafts(path: Path) -> list[str]:
    """解析草稿：提取非注释、非标题、非空的有效行。"""
    if not path.exists():
        return []
    out = []
    in_comment = False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--"):
            if "-->" not in s:
                in_comment = True
            continue
        if not s or s.startswith(("#", "-->", ">")):
            continue
        if s.startswith("|") or re.fullmatch(r"[-: |]+", s):
            continue
        out.append(s.lstrip("-*0123456789. "))
    return out


def report(skills_dir: Path, draft_path: Path, root: Path) -> None:
    # 扫描实际存在的技能文件，按用途给中文名
    name_map = {
        "_hot.md": "热区铁律",
        "_preferences.md": "用户偏好",
        "_commands.md": "命令库",
    }
    libs = {}
    for f in sorted(skills_dir.rglob("*.md")):
        rel = str(f.relative_to(skills_dir))
        # 领域包 / 冷藏包是完整文档，内部表格是流程说明不是条目，
        # 只按文件计数，不逐行解析
        if rel.startswith("domains") or rel.startswith("archive"):
            continue
        libs[rel] = name_map.get(f.name, f.stem)

    print("=" * 62)
    print("自进化整合报告")
    print("=" * 62)

    # ---- 1. 技能库现状 ----
    print("\n【1】技能库现状")
    all_entries = {}
    total = 0
    for fname, label in libs.items():
        entries = parse_table(skills_dir / fname)
        all_entries[fname] = entries
        total += len(entries)
        flag = "  ⚠ 超限，需合并同类项" if len(entries) > BLOAT_LIMIT else ""
        print(f"  {label:<10} {fname:<18} {len(entries):>3} 条{flag}")

    # 领域包按文件统计（文档型，不逐条解析）
    doms = sorted(list((skills_dir / "domains").rglob("*.md")) +
                  list((skills_dir / "archive").rglob("*.md")))
    if doms:
        print()
        for f in doms:
            n = len(f.read_text(encoding="utf-8").splitlines())
            where = "冷藏" if "archive" in f.parts else "冷区"
            meta = {}
            m = re.search(r"^keywords:\s*\[(.*?)\]",
                          f.read_text(encoding="utf-8"), re.M)
            kw = f"  关键词：{m.group(1)[:40]}" if m else ""
            print(f"  【{where}】{f.name:<26} {n:>4} 行{kw}")

    zombies = []
    for fname, entries in all_entries.items():
        for e in entries:
            hits = e.get("命中", "0")
            m = re.search(r"\d+", hits or "0")
            if m and int(m.group()) <= DEAD_HITS:
                zombies.append((fname, e["_id"]))
    if zombies and total >= 10:
        print(f"\n  ℹ️ {len(zombies)} 条命中为 0：{', '.join(f'{f}#{i}' for f, i in zombies[:6])}"
              f"{' …' if len(zombies) > 6 else ''}")
        print("    → 长期 0 命中只是说明低频，不代表无用：冷藏保留，不删除")
        print("    → 见 python3 scripts/index.py --stats 的分层建议")

    # ---- 2. 草稿分类 ----
    drafts = parse_drafts(draft_path)
    print(f"\n【2】待整合草稿：{len(drafts)} 条")
    if not drafts:
        print("  （草稿为空，无需整合）")
        print("\n" + "=" * 62)
        return

    dbgs = [bigrams(d) for d in drafts]
    dup, related, fresh, variants = [], [], [], []

    # 草稿 ↔ 技能库：找最相似的已有条目
    # 草稿 ↔ 草稿：同一次会话里最容易把一件事记两遍
    inner_pairs = []
    for i in range(len(drafts)):
        for j in range(i + 1, len(drafts)):
            s = similarity(dbgs[i], dbgs[j], min_shared=2) or related_score(dbgs[i], dbgs[j])
            if s >= REL_THRESHOLD:
                inner_pairs.append((i, j, s))

    for idx, d in enumerate(drafts):
        # 严格分与宽松分各自取最匹配的条目（两者的冠军往往不是同一条）
        best, best_score, best_where = None, 0.0, None
        rbest, rel_score, rwhere = None, 0.0, None
        for fname, entries in all_entries.items():
            for e in entries:
                sc = similarity(dbgs[idx], e["_bg"])
                if sc > best_score:
                    best, best_score, best_where = e, sc, fname
                rs = related_score(dbgs[idx], e["_bg"])
                if rs > rel_score:
                    rbest, rel_score, rwhere = e, rs, fname
        if best_score >= DUP_THRESHOLD and not env_overlap(
                _draft_env(d), best.get("_env", "")):
            # 相似但适用环境不重叠 → 版本分化，不是冲突，两条都留
            variants.append((d, best, best_score, best_where))
        elif best_score >= DUP_THRESHOLD:
            dup.append((d, best, best_score, best_where))
        elif rel_score >= REL_THRESHOLD and rbest is not None:
            related.append((d, rbest, rel_score, rwhere))
        else:
            fresh.append(d)

    if inner_pairs:
        print(f"\n  ▸ 草稿之间重复 {len(inner_pairs)} 组 → 同一件事在本轮记了两遍，先合并再入库")
        for i, j, s in inner_pairs:
            print(f"    [{s:.2f}] 「{drafts[i][:32]}」")
            print(f"          ↔ 「{drafts[j][:32]}」")

    if variants:
        print(f"\n  ▸ 版本分化 {len(variants)} 条 → **不是冲突，不要合并或删除**")
        for d, e, sc, w in variants:
            print(f"    [{sc:.2f}] 草稿：{d[:38]}")
            print(f"            已有：{w}#{e['_id']}（适用 {e.get('_env') or '通用'}）")
            print(f"            → 两条都留，用 applies_to 区分适用场景")
    print(f"\n  ▸ 疑似重复 {len(dup)} 条 → 建议只「命中 +1」，勿重复新增")
    for d, e, s, w in dup:
        print(f"    [{s:.2f}] 草稿：{d[:40]}")
        print(f"            撞车：{w}#{e['_id']} → {e['_text'][:52]}")

    print(f"\n  ▸ 疑似相关 {len(related)} 条 → 人工判断是否该合并")
    for d, e, s, w in related:
        print(f"    [{s:.2f}] 草稿：{d[:40]}")
        print(f"            相近：{w}#{e['_id']} → {e['_text'][:52]}")

    print(f"\n  ▸ 可新增 {len(fresh)} 条 → 过四道门槛后归位")
    for d in fresh:
        print(f"    · {d[:70]}")

    # ---- 2.5 事实污染扫描 ----
    # 技能库里混进项目事实（路径/文件名/一次性数据）会稀释命中率。
    # 扫「草稿 + 已入库条目」两边：草稿是入口，拦在这里成本最低。
    fact_hits = scan_facts(
        [(f"SKILLS/{f}#{e['_id']}", e["_text"]) for f, es in all_entries.items() for e in es]
        + [(f"草稿{i + 1}", d) for i, d in enumerate(drafts)],
        root,
    )
    if fact_hits:
        print(f"\n  ⚠ 事实污染扫描：{len(fact_hits)} 条疑似项目事实（第零道闸应拦截）")
        for where, label, hit in fact_hits[:10]:
            print(f"    · {where}  [{label}] {hit}")
        print("    → 能抽象成通用做法就改写，不能就删除；事实留在对话上下文里")

    # ---- 3. 跨库重复 ----
    flat = [(f, e) for f, es in all_entries.items() for e in es]
    cross = []
    for (f1, e1), (f2, e2) in combinations(flat, 2):
        s = similarity(e1["_bg"], e2["_bg"])
        if s >= DUP_THRESHOLD and env_overlap(e1.get("_env", ""), e2.get("_env", "")):
            cross.append((f1, e1["_id"], f2, e2["_id"], s))
    if cross:
        print(f"\n【3】跨库重复 {len(cross)} 组 → 同一件事记了两遍，建议合并")
        for f1, i1, f2, i2, s in cross[:6]:
            print(f"    [{s:.2f}] {f1}#{i1}  ↔  {f2}#{i2}")

    # ---- 4. 门槛提醒 ----
    print("\n【4】写入前逐条自问（任一不过则丢弃）")
    print("    第零道闸（先分诊）")
    print("      ☐ 这条描述的是「怎么做」还是「是什么」？是「是什么」→ 直接丢弃")
    print("      ☐ 换个项目、换个话题，这条还成立吗？不成立 → 项目事实，丢弃")
    print("    四道门槛")
    for q in ["可迁移：换个项目还成立吗？",
              "已抽象：这是模式还是个案？",
              "可执行：能照着做，不是「要认真」？",
              "已验证：真跑通过，不是想象？"]:
        print(f"      ☐ {q}")

    print("\n【5】整合收尾")
    for step in ["归位：判断放 _hot / domains / _commands / _preferences",
                 "重建索引：python3 scripts/index.py（必做，否则定向加载找不到）",
                 "分层复核：python3 scripts/index.py --stats",
                 "归档草稿：bash scripts/archive.sh",
                 "写入前让用户过目（L1 变动必须告知）",
                 "自检：常驻开销是否稳定、是否只写正确路径、有无混入事实"]:
        print(f"    ☐ {step}")

    print("\n" + "=" * 62)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="skill 根目录")
    args = ap.parse_args()
    root = Path(args.root)
    skills_dir, draft_path = root / "SKILLS", root / "pending" / "draft.md"
    if not skills_dir.is_dir():
        sys.exit(f"找不到技能库目录：{skills_dir}")
    report(skills_dir, draft_path, root)


if __name__ == "__main__":
    main()
