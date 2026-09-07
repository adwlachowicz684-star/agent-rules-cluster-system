#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结构变更管理 (structure.py)

当现有类目归不精准时，AI 应主动提出新建或调整目录结构，
用户确认后执行。本脚本负责：健康检测 → 生成提案 → 安全执行 → 回滚。

用法：
    python3 scripts/structure.py --check              检测结构问题，生成提案
    python3 scripts/structure.py --show               查看当前提案
    python3 scripts/structure.py --apply              预览并执行（需确认）
    python3 scripts/structure.py --apply --yes        跳过确认执行
    python3 scripts/structure.py --undo               回滚上一次变更
    python3 scripts/structure.py --log                查看变更历史

设计原则：
  - AI 只能「提案」，不能自行改结构；执行必须用户确认
  - 执行前 dry-run 预览 + 自动备份，任何一步失败可回滚
  - 不删除任何文件：移动 = 复制 + 保留原处别名（除非用户明确要求删除）
"""

import os
import re
import sys
import json
import shutil
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from domain import load_config, domain_root, domain_dir, CONFIG  # noqa: E402

PROPOSAL = ROOT / "pending" / "structure-proposal.md"
LOG = ROOT / "pending" / "structure-log.json"
BACKUP = ROOT / "pending" / "_backup"


# ---------- 健康检测 ----------

def scan_skills(cfg: dict) -> dict:
    """扫描各大类技能，返回 {key: [Path]}（已按真实路径去重）。"""
    out, seen = {}, set()
    for key in cfg.get("domains", {}):
        d = domain_dir(cfg, key) / "skills"
        if not d.exists():
            continue
        files = []
        for f in sorted(d.rglob("*.md")):
            if f.name.startswith("_"):
                continue
            try:
                real = f.resolve()
            except Exception:
                real = f
            if real in seen:
                continue
            seen.add(real)
            files.append(f)
        out[key] = files
    return out


def check(cfg: dict) -> list[dict]:
    """检测结构健康问题，返回问题列表。"""
    issues = []
    skills = scan_skills(cfg)

    for key, files in skills.items():
        name = cfg["domains"][key].get("name", key)

        # 1. 大类技能过多 → 建议拆子类
        if len(files) > 40:
            issues.append({
                "type": "oversized_domain",
                "domain": key,
                "detail": f"{name} 有 {len(files)} 个技能，超过 40 个",
                "suggest": f"在大类下建二级子目录（如 skills/合同/ skills/诉讼/），或拆出新大类",
                "action": "new-subdir",
            })

        # 2. 单个技能包过长 → 建议拆包
        for f in files:
            n = len(f.read_text(encoding="utf-8").splitlines())
            if n > 200:
                issues.append({
                    "type": "oversized_skill",
                    "domain": key,
                    "detail": f"{f.name} 有 {n} 行，超过 200 行",
                    "suggest": "按子任务拆成多个包，用 related 互链",
                    "action": "split-skill",
                })

    # 3. 空大类只作提示，不进提案 —— 预留位置是正常状态，
    #    报警反而会淹没真正需要处理的「大而不当」问题
    empty = [cfg["domains"][k].get("name", k)
             for k in cfg.get("domains", {})
             if k != cfg.get("common") and not skills.get(k)]
    if empty:
        print(f"ⓘ {len(empty)} 个大类暂无技能（预留位置，正常）：{'、'.join(empty[:6])}"
              f"{' …' if len(empty) > 6 else ''}\n")
    return issues


def check_route_ambiguity(cfg: dict, text: str) -> dict:
    """判定技能描述在现有大类下的归属质量。

    返回是否「现有结构不精准」——这是触发新建/调整的核心信号。

    关键：靠泛词（流程/输出/文件）命中 _common **不算真正归属**。
    否则任何描述都会被"装得下"，永远发现不了缺失的大类。
    """
    common = cfg.get("common", "_common")
    generic = set(cfg.get("generic_words", []) or
                  ["通用", "流程", "输出", "文件", "交付", "打包", "沟通", "搜索", "写作"])

    scored = []
    for key, meta in cfg.get("domains", {}).items():
        kws = meta.get("keywords", [])
        hit = [k for k in kws if k in text]
        # 实质命中：排除泛词。通用类靠泛词撑起来的分数不作数
        solid = [k for k in hit if k not in generic] if key == common else hit
        if hit:
            scored.append({"score": len(solid), "raw": len(hit),
                           "key": key, "meta": meta, "hit": hit, "solid": solid})

    # 排序：实质分优先；等分时非通用类优先（通用类兜底，不该抢）
    scored.sort(key=lambda x: (-x["score"], x["key"] == common, -x["raw"]))

    if not scored or scored[0]["score"] == 0:
        return {"fits": False, "reason": "no_match",
                "suggest": ("现有大类的专业关键词一个都没命中"
                            f"（仅靠泛词命中 {common}）→ 建议新建大类"),
                "action": "new-domain"}

    top = scored[0]
    if len(scored) >= 2 and scored[1]["score"] == top["score"] and top["score"] >= 2:
        return {"fits": False, "reason": "ambiguous",
                "suggest": (f"「{top['meta'].get('name')}」与"
                            f"「{scored[1]['meta'].get('name')}」得分持平 → "
                            f"可能缺一个中间大类，或该技能应拆成两部分各自归属"),
                "action": "new-domain"}

    if top["score"] == 1:
        # 命中核心词 → 归属明确，不必确认
        core = top["meta"].get("core", []) or []
        if any(k in core for k in top["solid"]):
            return {"fits": True, "reason": "core_hit",
                    "suggest": f"归 {top['meta'].get('name', top['key'])}"
                               f"（命中核心词「{top['solid'][0]}」）",
                    "action": "none"}
        return {"fits": False, "reason": "weak_match",
                "suggest": (f"仅命中边缘词「{top['solid'][0]}」→ "
                            f"勉强归 {top['meta'].get('name')}，建议确认；"
                            f"若这是新方向，考虑新建大类"),
                "action": "confirm"}

    return {"fits": True, "reason": "ok",
            "suggest": f"归 {top['meta'].get('name', top['key'])}（命中 {', '.join(top['solid'])}）",
            "action": "none"}


# ---------- 提案 ----------

def write_proposal(items: list[dict], reason: str = "") -> None:
    """生成人类可读的提案文件，交给用户确认。"""
    lines = [
        "# 结构变更提案（待确认）",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> **本提案不会自动执行**，需你确认后运行：",
        f"> `python3 scripts/structure.py --apply`",
        "",
        "## 变更理由",
        "",
        reason or "（由 --check 自动检测得到）",
        "",
        "## 变更清单",
        "",
        "| # | 动作 | 目标 | 说明 |",
        "|---|------|------|------|",
    ]
    for i, it in enumerate(items, 1):
        lines.append(f"| {i} | {it.get('action')} | {it.get('target', '-')} "
                     f"| {it.get('desc', '')} |")
    lines += [
        "",
        "## 影响预览",
        "",
    ]
    for i, it in enumerate(items, 1):
        lines.append(f"**{i}. [{it.get('action')}] {it.get('target', '')}**")
        lines.append("")
        for k, v in it.items():
            if k in ("action", "target", "desc"):
                continue
            lines.append(f"- `{k}`：{v}")
        lines.append("")
    lines += [
        "---",
        "",
        "## 确认方式",
        "",
        "```bash",
        "python3 scripts/structure.py --apply        # 预览并逐项确认",
        "python3 scripts/structure.py --apply --yes  # 全部执行（先自动备份）",
        "python3 scripts/structure.py --undo         # 反悔，回滚上一次变更",
        "```",
        "",
    ]
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    PROPOSAL.write_text("\n".join(lines), encoding="utf-8")
    print(f"提案已生成：{PROPOSAL}")
    print(f"共 {len(items)} 项变更，请确认后执行 --apply")


def build_from_issues(issues: list[dict]) -> None:
    """把检测到的问题转成提案项。"""
    items = []
    for it in issues:
        items.append({
            "action": it["action"],
            "target": it.get("domain", ""),
            "desc": it["detail"],
            "suggest": it["suggest"],
        })
    if items:
        write_proposal(items, "自动健康检测（--check）发现以下结构问题")
    else:
        print("✓ 结构健康，无需变更")


# ---------- 执行 ----------

def load_proposal() -> list[dict]:
    """解析提案：表格给出概览，「影响预览」段给出执行所需的完整参数。

    两段都要读——只解析表格会丢掉 key / keywords 等字段，
    导致 new-domain 之类的动作无法执行。
    """
    if not PROPOSAL.exists():
        sys.exit("没有待执行的提案，先运行 --check 或手工构造")
    text = PROPOSAL.read_text(encoding="utf-8")
    items = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\| (\d+) \| (\S+) \| ([^|]*) \| ([^|]*) \|", line)
        if m:
            cur = {"action": m.group(2).strip(),
                   "target": m.group(3).strip(),
                   "desc": m.group(4).strip()}
            items.append(cur)
            continue
        # 影响预览段：**N. [action] target** 后的 - `k`：v
        if re.match(r"^\*\*\d+\. \[", line):
            idx = int(re.search(r"^\*\*(\d+)\.", line).group(1))
            if idx <= len(items):
                cur = items[idx - 1]
            continue
        if cur is not None:
            kv = re.match(r"^-\s+`([^`]+)`\s*[:：]\s*(.*)$", line)
            if kv:
                v = kv.group(2).strip()
                if v.startswith("[") and v.endswith("]"):
                    v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
                cur[kv.group(1)] = v
    return items


def backup(paths: list[Path]) -> Path:
    """备份受影响文件，返回备份目录。

    同时写 `_map.json` 记录「备份名 → 原绝对路径」，
    否则 undo 时无从知道该恢复到哪里（尤其新建类的目录是全新的）。
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP / stamp
    dest.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for i, p in enumerate(paths):
        p = Path(p)
        rel = f"{i:02d}_{p.name}"
        try:
            if not p.exists():
                # 本次将要新建 → 记录为待删除项，回滚时删掉它
                mapping[rel] = {"orig": str(p), "existed": False}
                continue
            if p.is_file():
                shutil.copy2(p, dest / rel)
            else:
                shutil.copytree(p, dest / rel, dirs_exist_ok=True)
            mapping[rel] = {"orig": str(p.resolve()), "existed": True}
        except Exception as e:
            print(f"  ⚠ 备份失败 {p}: {e}")
    (dest / "_map.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def apply_item(cfg: dict, item: dict, dry: bool = False) -> list[Path]:
    """执行单项变更，返回受影响路径（供备份）。"""
    act, target = item.get("action"), item.get("target", "")
    affected = []

    if act == "new-domain":
        # 新建大类：建目录 + rules/agents 模板 + 通用链接 + 注册 config
        name = item.get("name", target)
        key = item.get("key", "")
        if not key:
            print(f"  ⚠ 跳过：new-domain 缺少 key")
            return affected
        d = domain_root(cfg) / name
        affected.append(d)
        if not dry:
            for sub in cfg.get("subdirs", ["agents", "skills", "rules"]):
                (d / sub).mkdir(parents=True, exist_ok=True)
            (d / "rules" / "_domain.md").write_text(
                f"# {name} — 领域规则\n\n## 输出约束\n\n-\n", encoding="utf-8")
            (d / "agents" / "_role.md").write_text(
                f"# {name} — 角色定义\n\n## 身份\n\n-\n", encoding="utf-8")
            # 通用链接：进任何大类都要能看到通用技能
            common_real = domain_root(cfg) / cfg.get("common", "_common")
            if common_real.exists():
                link = d / cfg.get("common", "_common")
                if not link.exists():
                    try:
                        link.symlink_to(common_real, target_is_directory=True)
                    except Exception:
                        pass
            # 必须写回「本次 --config 指定的文件」，否则测试时
            # 会把新大类注册到引擎自带 config，污染正式配置
            reg = Path(cfg.get("__path__") or CONFIG)
            affected.append(reg)
            _register_domain(reg, key, name, item.get("keywords", []),
                             item.get("desc2") or item.get("desc", ""),
                             item.get("core"))
            print(f"  ✓ 已建大类 {name}（{key}）并注册到 config.yaml")

    elif act == "new-subdir":
        d = domain_dir(cfg, target) / "skills" / item.get("name", "")
        affected.append(d)
        if not dry:
            d.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ 已建子目录 {d}")

    elif act == "move-skill":
        src = Path(item.get("src", ""))
        dst_dir = domain_dir(cfg, target) / "skills"
        dst = dst_dir / src.name
        affected += [src, dst]
        if not dry:
            dst_dir.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                print(f"  ⚠ 目标已存在，跳过：{dst}")
            else:
                shutil.copy2(src, dst)
                print(f"  ✓ 已移动 {src.name} → {target}")

    elif act == "rename":
        old = Path(item.get("src", ""))
        new = old.parent / item.get("name", "")
        affected += [old, new]
        if not dry:
            if old.exists():
                old.rename(new)
                print(f"  ✓ 已重命名 {old.name} → {new.name}")

    else:
        print(f"  ⓘ 动作 {act} 需人工处理：{item.get('desc', '')}")
    return affected


def _register_domain(cfg_path: Path, key: str, name: str,
                     keywords: list, desc: str, item_core=None) -> None:
    """把新大类追加到 config.yaml 的 domains 段（保留原格式与注释）。"""
    text = cfg_path.read_text(encoding="utf-8")
    if f"\n  {key}:" in text:
        print(f"  ⓘ {key} 已注册，跳过")
        return
    kw = ", ".join(keywords) if keywords else "通用"
    core = item_core if isinstance(item_core, list) else (
        [x.strip() for x in str(item_core).split(",") if x.strip()] if item_core else [])
    block = f"\n  {key}:\n    name: {name}\n    desc: {desc or name}\n"
    if core:
        block += f"    core: [{', '.join(core)}]\n"
    block += f"    keywords: [{kw}]\n"
    lines = text.splitlines(keepends=True)
    # 插到 domains 段最后一个条目之后
    idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^  [a-z_]+:", ln):
            idx = i
    if idx is None:
        sys.exit("config.yaml 里找不到 domains 段")
    # 找到该条目块的结束（下一个顶格键或文件尾）
    end = idx + 1
    while end < len(lines) and not re.match(r"^[a-zA-Z#]", lines[end]):
        end += 1
    lines.insert(end, block)
    cfg_path.write_text("".join(lines), encoding="utf-8")
    print(f"  ✓ config.yaml 已注册 {key}")


def apply(cfg: dict, auto_yes: bool = False) -> None:
    items = load_proposal()
    print(f"待执行 {len(items)} 项变更：\n")
    for i, it in enumerate(items, 1):
        print(f"  {i}. [{it['action']}] {it.get('target', '')} — {it.get('desc', '')}")
    print()

    affected = []
    for it in items:
        affected += apply_item(cfg, it, dry=True)

    if not auto_yes:
        ans = input("\n确认执行？(y/n) ").strip().lower()
        if ans != "y":
            print("已取消")
            return
    if affected:
        # 不要在这里过滤 exists()：新建项正是"回滚时该删除"的对象，
        # 过滤掉会导致新建的大类无法回滚。由 backup 自行判断 existed。
        dest = backup([Path(p) for p in affected])
        print(f"\n已备份到：{dest}")

    done = []
    for it in items:
        apply_item(cfg, it, dry=False)
        done.append(it)
    if done:
        _log(done)
        print(f"\n完成 {len(done)} 项。反悔可执行 --undo")
        print("记得重建索引：python3 scripts/index.py")


def _log(items: list[dict]) -> None:
    history = []
    if LOG.exists():
        try:
            history = json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append({"time": datetime.now().isoformat(timespec="seconds"),
                    "items": items})
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def undo(auto_yes: bool = False) -> None:
    """回滚：从最新备份真正恢复。

    备份时记录了「备份名 → 原路径」映射（_map.json），
    所以能精确还原：文件复制回去，备份里没有的（新建的）则删除。
    """
    if not BACKUP.exists() or not any(BACKUP.iterdir()):
        sys.exit("没有可回滚的备份")
    stamps = sorted(p.name for p in BACKUP.iterdir())
    stamp = stamps[-1]
    src = BACKUP / stamp
    map_file = src / "_map.json"
    if not map_file.exists():
        sys.exit(f"备份 {stamp} 缺少 _map.json，无法定位原路径，请手动恢复")

    mapping = json.loads(map_file.read_text(encoding="utf-8"))
    print(f"回滚到备份：{stamp}\n")
    print("将执行：")
    for rel, info in mapping.items():
        orig, existed = info["orig"], info["existed"]
        verb = "恢复" if existed else "删除（本次新建）"
        print(f"  ↩ {verb} → {orig}")

    if not auto_yes:
        ans = input("\n确认回滚？(y/n) ").strip().lower()
        if ans != "y":
            print("已取消")
            return

    for rel, info in mapping.items():
        orig, existed = Path(info["orig"]), info["existed"]
        b = src / rel
        try:
            if not existed:
                # 本次新建的 → 删除（仅删除空目录或备份时确实不存在的）
                if orig.is_dir():
                    shutil.rmtree(orig, ignore_errors=True)
                    print(f"  ✓ 已删除新建目录 {orig}")
                elif orig.exists():
                    orig.unlink()
                    print(f"  ✓ 已删除新建文件 {orig}")
                continue
            if b.is_dir():
                if orig.exists():
                    shutil.rmtree(orig)
                shutil.copytree(b, orig)
            else:
                orig.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(b, orig)
            print(f"  ✓ 已恢复 {orig}")
        except Exception as e:
            print(f"  ✗ 失败 {orig}: {e}")

    shutil.rmtree(src)
    print(f"\n回滚完成，已清理备份 {stamp}")
    print("提醒：回滚只还原被备份的文件，新建的目录需手动清理")
    print("      重建索引：python3 scripts/index.py")


def propose_new_domain(name: str, key: str, keywords: list, desc: str = "", core: list = None) -> None:
    """生成「新建大类」提案。

    触发场景：--route-check 判定 no_match / ambiguous / weak_match，
    说明现有类目装不下，AI 应主动提议新建。
    """
    write_proposal([{
        "action": "new-domain",
        "target": name,
        "desc": f"新建大类「{name}」",
        "key": key,
        "name": name,
        "keywords": keywords,
        "core": core or [],
        "desc2": desc or f"{name}相关技能",
    }], reason=(f"现有大类中找不到「{name}」的合适位置。"
                f"新建后该方向技能可独立归类、独立维护。"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="检测结构问题并生成提案")
    ap.add_argument("--route-check", metavar="描述", help="判定归属是否精准")
    ap.add_argument("--propose-new", metavar="类名", help="提议新建大类（配 --key）")
    ap.add_argument("--key", metavar="英文key", help="新大类的英文 key")
    ap.add_argument("--kw", metavar="关键词", help="新大类关键词，逗号分隔")
    ap.add_argument("--desc", metavar="描述", default="", help="新大类描述")
    ap.add_argument("--core", metavar="核心词", default="", help="核心词，逗号分隔（命中即确认归属）")
    ap.add_argument("--show", action="store_true", help="查看当前提案")
    ap.add_argument("--apply", action="store_true", help="执行提案")
    ap.add_argument("--yes", action="store_true", help="跳过确认")
    ap.add_argument("--undo", action="store_true", help="回滚")
    ap.add_argument("--log", action="store_true", help="查看变更历史")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args()

    cfg = load_config(Path(args.config))

    if args.propose_new:
        if not args.key:
            sys.exit("--propose-new 必须配 --key <英文key>")
        kws = [x.strip() for x in (args.kw or "").split(",") if x.strip()]
        if not kws:
            sys.exit("--propose-new 必须配 --kw 关键词（逗号分隔）")
        core = [x.strip() for x in (args.core or "").split(",") if x.strip()]
        propose_new_domain(args.propose_new, args.key, kws, args.desc, core)
    elif args.check:
        build_from_issues(check(cfg))
    elif args.route_check:
        r = check_route_ambiguity(cfg, args.route_check)
        print(f"描述：{args.route_check}")
        print(f"现有结构是否装得下：{'是' if r['fits'] else '否'}（{r['reason']}）")
        print(f"建议：{r['suggest']}")
        if not r["fits"]:
            print(f"\n→ 应提出结构变更：{r['action']}")
    elif args.show:
        print(PROPOSAL.read_text(encoding="utf-8") if PROPOSAL.exists() else "（无提案）")
    elif args.apply:
        apply(cfg, args.yes)
    elif args.undo:
        undo(args.yes)
    elif args.log:
        print(LOG.read_text(encoding="utf-8") if LOG.exists() else "（无变更记录）")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
