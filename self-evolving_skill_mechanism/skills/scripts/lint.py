#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规范检查 (lint.py)

检查文件体积、frontmatter 完整性、ID 唯一性、verified 标注覆盖。
**单文件过大是隐性风险**：加载时吃掉上下文，且说明该拆没拆。

用法：
    python3 scripts/lint.py                 全量检查
    python3 scripts/lint.py --json          输出 JSON
    python3 scripts/lint.py --config X.yaml 指定配置

阈值见 config.yaml 的 size_limits。
"""

import re
import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from domain import load_config, domain_dir, CONFIG  # noqa: E402

DEFAULTS = {
    "SKILL.md": 200,
    "reference": 400,
    "skills": 500,
    "rules": 50,
    "agents": 100,
    "_hot.md": 40,
    "_preferences.md": 40,
    "_commands.md": 120,
    "assets": 300,
}

REQUIRED_FM = ["id", "name", "keywords", "trigger"]

HINTS = {
    "rules": "rules 每次必读，超过 50 行说明混进了流程 → 移到 skills/",
    "agents": "按场景拆成多个角色文件",
    "skills": "按子任务拆包，用 related 互链",
    "reference": "按主题拆成多个文件",
    "assets": "按年/季度拆分归档",
}


def n_lines(p):
    try:
        return len(p.read_text(encoding="utf-8").splitlines())
    except Exception:
        return 0


def check_size(cfg, limits):
    issues = []

    def chk(path, label, key, hint=""):
        if not path.exists():
            return
        n = n_lines(path)
        lim = int(limits.get(key, DEFAULTS.get(key, 400)))
        if n > lim:
            issues.append({"level": "warn", "file": label, "lines": n,
                           "limit": lim, "hint": hint or HINTS.get(key, "拆分")})

    chk(ROOT / "SKILL.md", "SKILL.md", "SKILL.md", "细节下沉到 reference/")
    for name in ("_hot.md", "_preferences.md", "_commands.md"):
        chk(ROOT / "SKILLS" / name, "SKILLS/" + name, name,
            "拆分为多个文件或归档低频条目")
    for f in sorted((ROOT / "reference").glob("*.md")):
        chk(f, "reference/" + f.name, "reference")

    ad = ROOT / "assets"
    if ad.exists():
        for f in sorted(ad.glob("*.md")):
            chk(f, "assets/" + f.name, "assets")

    for key in cfg.get("domains", {}):
        d = domain_dir(cfg, key)
        for sub in ("rules", "agents", "skills", "assets"):
            sd = d / sub
            if not sd.exists():
                continue
            lim = int(limits.get(sub, DEFAULTS.get(sub, 400)))
            for f in sorted(sd.rglob("*.md")):
                n = n_lines(f)
                if n > lim:
                    issues.append({
                        "level": "warn",
                        "file": "%s/%s/%s" % (d.name, sub, f.name),
                        "lines": n, "limit": lim,
                        "hint": HINTS.get(sub, "拆分归档")})
    return issues


def check_frontmatter(cfg):
    issues, seen = [], {}
    targets = []
    for key in cfg.get("domains", {}):
        sd = domain_dir(cfg, key) / "skills"
        if sd.exists():
            targets += [f for f in sd.rglob("*.md") if not f.name.startswith("_")]

    for f in targets:
        text = f.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
        if not m:
            issues.append({"level": "error", "file": str(f),
                           "issue": "缺少 frontmatter",
                           "hint": "至少 id / name / keywords / trigger"})
            continue
        fm = {}
        for line in m.group(1).splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()

        miss = [k for k in REQUIRED_FM if not fm.get(k)]
        if miss:
            issues.append({"level": "warn", "file": str(f),
                           "issue": "缺字段 " + str(miss),
                           "hint": "keywords 决定召回，trigger 决定何时加载"})

        sid = fm.get("id", "?")
        if sid in seen:
            issues.append({"level": "error", "file": str(f),
                           "issue": "ID 与 " + seen[sid] + " 重复",
                           "hint": "ID 必须全局唯一"})
        else:
            seen[sid] = str(f)

        if not fm.get("verified"):
            issues.append({"level": "info", "file": str(f),
                           "issue": "未标注 verified",
                           "hint": "执行验证过就标 verified: yes，仅作回溯参考"})
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--config", default=str(CONFIG))
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    limits = cfg.get("size_limits", {})
    issues = check_size(cfg, limits) + check_frontmatter(cfg)

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
        return

    if not issues:
        print("✓ 规范检查通过")
        return

    errs = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    infos = [i for i in issues if i["level"] == "info"]

    print("=" * 56)
    print("规范检查")
    print("=" * 56)
    if errs:
        print("\n【错误】%d 项 → 必须修" % len(errs))
        for i in errs:
            print("  ✗ " + i["file"])
            print("    " + i["issue"] + " → " + i["hint"])
    if warns:
        print("\n【体积预警】%d 项" % len(warns))
        for i in warns:
            bar = "#" * min(30, i["lines"] // 20)
            print("  ! %s  %d/%d 行 %s" % (i["file"], i["lines"], i["limit"], bar))
            print("    -> " + i["hint"])
    if infos:
        print("\n【提示】%d 项" % len(infos))
        for i in infos[:10]:
            print("  - %s: %s" % (Path(i["file"]).name, i["issue"]))
        if len(infos) > 10:
            print("  … 另有 %d 项" % (len(infos) - 10))
    print("\n合计：%d 错误 · %d 预警 · %d 提示" % (len(errs), len(warns), len(infos)))
    if errs:
        sys.exit(1)


if __name__ == "__main__":
    main()
