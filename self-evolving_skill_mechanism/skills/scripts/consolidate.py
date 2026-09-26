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
import time
import sys
import argparse
from exitcode import OK, ERR, USAGE, ENV, BLOCKED  # 码表：0/1/2/3/4
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
            # ⛔ 早先一律丢弃 `<!--`，而 draft 模板**规定的捕获格式就是**
            #    `<!-- [A] 场景 → 正确做法 -->`
            #    ⇒ 按模板写的捕获 100% 被丢弃。**archive.sh 同病**（已修）。
            #    实测（主链路第一次真跑）：6 条真捕获，归档丢光、整合也读不到。
            # ⇒ 捕获注释（`<!-- [A]`~`[G]`）= 内容；其余注释才是注释。
            _m = re.match(r"^<!--\s*\[([A-G][0-9]?)\](.*?)-->\s*$", s)
            if _m:
                out.append(_m.group(2).strip().lstrip("-*0123456789. "))
                continue
            if "-->" not in s:
                in_comment = True
            continue
        if not s or s.startswith(("#", "-->", ">")):
            continue
        if s.startswith("|") or re.fullmatch(r"[-: |]+", s):
            continue
        out.append(s.lstrip("-*0123456789. "))
    return out


# ---- 驳回清单（负面门槛）----
# 四道门槛是「什么该入库」，驳回清单是「什么不该」。只有正面清单的后果是：
# 一条草稿只要"说得通"就被放进去，库里慢慢堆满听起来对但没用的条目。
#
# 对应的判据来自审查技能里的「驳回清单」——那里最高频的误报来源是
# 「没读注释就报问题」，搬到这里就是「没查溯源就改旧规则」。
REJECT_RULES = [
    # (检测函数, 驳回理由, 补救建议)
    ("intent", "可能是既有设计意图",
     "先查溯源（note.py --show <ID>）确认它当初为什么这么写，再决定改不改"),
    ("consequence", "说不出后果",
     "补上「不这么做会怎样」；补不出来说明它不构成技能，丢弃"),
    ("style", "风格偏好",
     "命名 / 格式 / 架构口味不构成技能，丢弃"),
    ("scope", "趁机顺手改无关内容",
     "本轮范围外的改动不做；单独记一条草稿下轮处理"),
]


def check_reject(text: str) -> list[tuple[str, str]]:
    """对一条草稿跑驳回清单，返回 [(理由, 建议)]。

    只做保守的关键词粗筛，宁可漏报不可误杀——
    最终判断留给人工（本脚本的定位就是「机械活给脚本，判断活给 AI」）。
    """
    hits = []
    t = text.lower()

    # 设计意图：提到「改成/不要/去掉/删掉」+ 指向已有做法 → 可能是要推翻既有设计
    if re.search(r'(改成|改为|换成|不要|去掉|删掉|不应该|不该)', text) and \
            re.search(r'(之前|原来|现有|已有|现在)', text):
        hits.append(("可能是既有设计意图", REJECT_RULES[0][2]))

    # 后果：只有动词没有后果描述
    if re.search(r'^(应该|要|需要|建议|最好)', text) and len(text) < 12:
        hits.append(("说不出后果", REJECT_RULES[1][2]))

    # 风格偏好
    if re.search(r'(命名|格式|排版|风格|统一用|改成.*名|大小写|缩进)', text) and \
            not re.search(r'(命令|脚本|检查|grep|rg|python)', text):
        hits.append(("风格偏好", REJECT_RULES[2][2]))

    # 超出范围
    if re.search(r'(顺便|顺手|一起改|一并|统一改)', text):
        hits.append(("趁机顺手改无关内容", REJECT_RULES[3][2]))
    return hits


def check_trio(text: str) -> list[str]:
    """入库三件套：来源 / 证据 / 后果。

    对应审查技能的「行号 + 证据 + 后果，三件套缺一不可」。
    技能库版本：
      来源 — 哪次任务、什么信号（note.py 的 --src）
      证据 — 实测输出，或可验证的推导链
      后果 — 不这么做会怎样
    缺任一条都标出来，让整合时补，而不是默默入库。
    """
    miss = []
    if not re.search(r'\[(env|src|来源|信号)[:：]', text) and \
            not re.search(r'(来源|捕获自|来自)', text):
        miss.append("来源（哪次任务 / 什么信号）")
    if not re.search(r'(实测|跑过|验证|输出|结果|报错|退出码)', text):
        miss.append("证据（实测输出或可验证推导链）")
    if not re.search(r'(否则|会|导致|后果|不然|造成)', text):
        miss.append("后果（不这么做会怎样）")
    return miss


def load_reference_corpus(root: Path) -> list[dict]:
    """reference/ 下已入库的知识文档，按标题块拆分作为查重语料。

    ### ⛔ 为什么需要（实测动机）

    主链路第一次真跑时，整合器把
    「同一脚本内连续两次 `write(s.replace(...))`，s 没重新赋值」
    报成 **「可新增」**——而它**早就写在**
    `reference/audit/self-verification-silent.md` 第十七条「第 4 次」里。

    ⇒ 查重只扫 `SKILLS/*.md` 的**条目表**，`reference/` 下 8000+ 行
    已入库知识**完全不参与查重**。
    **同一个东西会进库两遍，而整合器说"不重复"。**

    ⓘ 这是第十八条「查不到 ≠ 没有」的变体：
    失败模式是"返回 0 条重复"而不是报错。

    ### ⛔ 只用于严格档（DUP），不用于宽松档（REL）

    `reference/` 有 8000+ 行、词汇面极广。宽松阈值（0.05）下
    **任何草稿都会与某块有交集** → 全部被判「疑似相关」→ 信号被噪声淹没。
    ⛔ **误报的检查会被关掉**（falsepos 第十四条）。

    ⇒ 语料纳入，但**只喂给严格判据**。
    """
    ref = root / "reference"
    if not ref.is_dir():
        return []
    out = []
    for f in sorted(ref.rglob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        head, buf = "(开头)", []
        for ln in text.split("\n"):
            if ln.startswith("#"):
                if buf:
                    t = " ".join(buf).strip()
                    if len(t) >= 12:
                        out.append({"_id": "", "_text": t[:300], "_bg": bigrams(t),
                                    "_env": "", "_where": "%s#%s" % (
                                        f.relative_to(root).as_posix(), head)})
                head = ln.lstrip("#").strip() or "(开头)"
                buf = []
            else:
                buf.append(ln)
        if buf:
            t = " ".join(buf).strip()
            if len(t) >= 12:
                out.append({"_id": "", "_text": t[:300], "_bg": bigrams(t),
                            "_env": "", "_where": "%s#%s" % (
                                f.relative_to(root).as_posix(), head)})
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
        # 注意：不能就此 return。第【3】跨库重复检查**不依赖草稿**——
        # 它查的是库里已有条目之间的重复。早先这里直接 return，
        # 导致「没草稿时跑 consolidate.py」永远看不到库内已有的重复，
        # 而输出是正常的「无需整合」，看起来一切良好。
        # 定期查库内重复是常规维护动作，不该被草稿状态挡住。
        print("  （草稿为空，无需整合）")
        print("  ℹ️ 仍继续检查库内已有条目（跨库重复不依赖草稿）")

    dbgs = [bigrams(d) for d in drafts]
    # ⛔ reference/ 已入库知识必须参与**严格档**查重（详见 load_reference_corpus）
    ref_corpus = load_reference_corpus(root)
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
        # 严格档也比对 reference/（⛔ 只扫 SKILLS/ 会漏掉已入库的知识）。
        # ⛔ 不喂给宽松档：8000+ 行语料会让任何草稿都"疑似相关"。
        for re_ in ref_corpus:
            sc = similarity(dbgs[idx], re_["_bg"])
            if sc > best_score:
                best, best_score, best_where = re_, sc, re_["_where"]
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

    # ---- 2.6 驳回清单 ----
    # 四道门槛是正面清单（什么该入），这里是负面清单（什么不该入）。
    # 只有正面清单时，"说得通"的废话会被一路放行。
    reject_hits = [(d, check_reject(d)) for d in drafts]
    reject_hits = [(d, r) for d, r in reject_hits if r]
    if reject_hits:
        print(f"\n  ⛔ 驳回清单：{len(reject_hits)} 条疑似不该入库 → 逐条确认后再决定")
        for d, rs in reject_hits:
            print(f"    · {d[:56]}")
            for reason, advice in rs:
                print(f"        ↳ {reason} → {advice}")

    # ---- 2.7 三件套 ----
    trio_miss = [(d, check_trio(d)) for d in drafts]
    trio_miss = [(d, m) for d, m in trio_miss if m]
    if trio_miss:
        print(f"\n  ⚠ 三件套不全：{len(trio_miss)} 条 → 补齐再入库，别默默放进去")
        for d, m in trio_miss:
            print(f"    · {d[:56]}")
            print(f"        缺：{'、'.join(m)}")
        print("    → 判据：说不出「不这么做会怎样」的，通常不是真技能")

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


def cmd_self_test():
    """给「过闸逻辑」本身配正反样本。

    为什么需要：本技能在 reference/audit/self-verification.md 里写明
    「检测类规则必须配 tp/fp 双样本，只写 tp 精度永远无法验证」。
    而引擎自己的三道闸（驳回清单 / 三件套 / 事实扫描）**一条样本都没有**——
    协议要求别人做的，自己没做。判据一旦被改坏，只能等真整合时才发现。

    这里是纯函数级验证，不需要 domains 数据，也不依赖 draft.md 有内容。
    """
    ok = fail = 0

    def chk(cond, msg):
        nonlocal ok, fail
        print(('  \u2713 ' if cond else '  \u2717 ') + msg)
        if cond:
            ok += 1
        else:
            fail += 1

    # ---- check_reject：该驳回的必须驳回 ----
    for text, why in [
        ("把之前的检查改成脚本", "推翻既有设计意图"),
        ("应该统一", "说不出后果"),
        ("顺便改一下配置", "顺手改无关内容"),
        ("缩进用两个空格", "风格偏好"),
    ]:
        chk(bool(check_reject(text)), '驳回清单能拦：%s（%s）' % (text[:12], why))

    # ---- check_reject：不该误杀 ----
    good = "接口超时时先重试一次再报错，否则网络抖动会导致整体失败"
    chk(not check_reject(good), '正常技能条目不被驳回（不是所有条目都该拦）')

    # ---- check_trio：缺项要报 ----
    miss = check_trio("要小心处理边界")
    chk(len(miss) == 3, '三件套能查出全缺（来源/证据/后果各一项）→ %d 项' % len(miss))

    full = ("实测 lint.py 报出 3 项死链；来源：本次改造；"
            "不跑则死链发现不了，会导致照文档敲 command not found")
    chk(not check_trio(full), '三件套齐全时不误报')

    partial = "实测跑过，来源：上线检查"
    chk(len(check_trio(partial)) == 1 and '后果' in check_trio(partial)[0],
        '只缺后果时报出**具体缺哪项**，不是笼统提示')

    # ---- scan_facts：事实要挑出，占位符/内部文件要放行 ----
    root = Path(__file__).resolve().parent.parent
    hits = scan_facts([("draft", "配置在 /etc/nginx.conf")], root)
    chk(bool(hits) and hits[0][1] == "绝对路径", '项目事实能挑出（绝对路径）')

    chk(not scan_facts([("draft", "打包成 NAME.zip")], root),
        '占位符放行（NAME.zip 不是真实文件）')
    chk(not scan_facts([("draft", "见 scripts/consolidate.py")], root),
        'skill 内部文件名放行（不是项目事实）')
    chk(bool(scan_facts([("draft", "截止 2026-09-15")], root)),
        '一次性日期能挑出（换项目就不成立）')

    print()
    print('自检：%d 通过 / %d 失败' % (ok, fail))
    if not fail:
        print('结论：过闸逻辑工作正常')
    # 自检失败 = 工具自身的过闸逻辑有问题 → ERR(1)，不是内容问题。
    return ERR if fail else OK



def cmd_self_test() -> int:
    """正反样本：证明主链路两个断点真的被守住了。"""
    import tempfile
    ok = True

    def chk(cond, label):
        nonlocal ok
        print(('  ✓ ' if cond else '  ✗ ') + label)
        if not cond:
            ok = False

    print('=' * 62)
    print('consolidate 自检（主链路断点守门）')
    print('=' * 62)

    # ---- 断点 1：`<!-- [A] 场景 → 正确做法 -->` 必须能被解析 ----
    with tempfile.NamedTemporaryFile('w', suffix='.md', delete=False,
                                     encoding='utf-8') as f:
        f.write('# 待整合草稿\n\n<!-- [信号类型 A-F] 场景 → 正确做法 -->\n'
                '<!-- [A] 某场景 → 正确做法 -->\n')
        dp = Path(f.name)
    got = parse_drafts(dp)
    chk(any('某场景' in g for g in got),
        '捕获注释 `<!-- [A] ... -->` 能被解析 —— ⛔ 不解析则按模板写的捕获 100% 读不到')
    chk(not any('信号类型' in g for g in got),
        '模板占位行 `<!-- [信号类型 A-F] -->` 不算内容，不误报')
    dp.unlink(missing_ok=True)

    # ---- 断点 2：reference/ 必须参与严格档查重 ----
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ref = root / 'reference' / 'audit'
        ref.mkdir(parents=True, exist_ok=True)
        (ref / 'x.md').write_text(
            '# 某标题\n同一脚本内连续两次 write 覆盖，第二次把第一次冲掉了，'
            '这是改了但没落盘的典型形态\n', encoding='utf-8')
        # ⛔ 必须测 **report() 的实际判定**，不能直接调 similarity：
        #    第一版用例直接算 similarity，绕过了 report 里那段循环
        #    ⇒ 把循环变异掉，用例照样绿（SURVIVED）。
        #    ⚠ 与 silent 第一条同族：断言要针对**被改的那个地方**。
        (root / 'SKILLS').mkdir(parents=True, exist_ok=True)
        (root / 'pending').mkdir(parents=True, exist_ok=True)
        (root / 'pending' / 'draft.md').write_text(
            '# 待整合草稿\n\n<!-- [信号类型 A-F] 场景 → 正确做法 -->\n'
            '<!-- [A] 同一脚本内连续两次 write 覆盖，第二次把第一次冲掉了，'
            '这是改了但没落盘的典型形态 -->\n', encoding='utf-8')
        import io as _io
        import contextlib as _cl
        _buf = _io.StringIO()
        with _cl.redirect_stdout(_buf):
            report(root / 'SKILLS', root / 'pending' / 'draft.md', root)
        _out = _buf.getvalue()
        chk('撞车' in _out and 'reference/' in _out,
            'report() 把已入库知识判为「撞车」而非「可新增」—— '
            '⛔ 只扫 SKILLS/ 会让同一个东西进库两遍')
        chk('撞车' in _out,
            '⚠ 断言针对 report() 的实际输出，⛔ 不是直接调 similarity'
            '（第一版绕过了被变异的循环 → SURVIVED）')

    print()
    print('自检：%s' % ('全部通过' if ok else '有失败'))
    return OK if ok else ERR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="skill 根目录")
    ap.add_argument("--self-test", action="store_true",
                    help="用正反样本验证过闸逻辑真的能查出来")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(cmd_self_test())
    root = Path(args.root)
    skills_dir, draft_path = root / "SKILLS", root / "pending" / "draft.md"
    if not skills_dir.is_dir():
        sys.stderr.write("找不到技能库目录：%s\n" % skills_dir)
        sys.exit(ENV)
    report(skills_dir, draft_path, root)
    # ⛔ FL-05 清单第 1 项「归档前必须先整合」此前**没有任何强制机制**——
    #    清单写了，但没人拦。实测我自己就跳过了一次（先归档后整合）。
    #    ⇒ 整合后记录草稿指纹；archive.sh 归档前比对，不匹配就拦下。
    #    ⛔ 只在文档里写「必须先整合」是不够的：**清单不会自己执行**。
    _stamp = root / "pending" / ".last_consolidated"
    try:
        import hashlib
        _fp = hashlib.sha1(draft_path.read_bytes()).hexdigest()[:16] \
            if draft_path.exists() else "empty"
        _stamp.write_text("%s %s\n" % (
            _fp, time.strftime("%Y-%m-%d %H:%M:%S")), encoding="utf-8")
    except Exception:
        pass


if __name__ == "__main__":
    main()
