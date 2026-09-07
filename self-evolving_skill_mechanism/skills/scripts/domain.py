#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大类路由管理器 (domain.py)

配套机制：项目文件夹通过 junction / 软链接接入某个大类文件夹，
大类文件夹内含 agents / skills / rules 三个子目录。
本脚本负责：大类初始化、链接创建、归属判定、路径解析、技能写入定位。

用法：
    python3 scripts/domain.py --init                     初始化大类根目录
    python3 scripts/domain.py --list                     列出全部大类
    python3 scripts/domain.py --detect                   探测当前项目接入的大类
    python3 scripts/domain.py --route "合同审查流程"      推荐技能归属
    python3 scripts/domain.py --link legal <项目路径>     把项目接入某个大类
    python3 scripts/domain.py --add-common               各大类内建 _common 链接
    python3 scripts/domain.py --where legal              输出该大类的 skills 真实路径

设计要点：
  - 写入一律落到「大类根目录」的真实路径，不写 junction 虚拟路径，
    避免项目删除或链接切换后技能丢失
  - 归属判定不全自动：推荐 + 确认，归错类比不归更糟
"""

import os
import re
import sys
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
IS_WIN = os.name == "nt"


# ---------- 配置 ----------

def load_config(path: Path = CONFIG) -> dict:
    """极简 YAML 解析（只支持本文件用到的结构，避免引入依赖）。

    加了孤儿行检测：缩进 4 的字段若前面没有 key（通常是删 key 时漏删内容），
    会被静默归给上一个大类，导致「金融被改名成区块链」这类隐蔽错误。
    宁可报错，也不要静默产生错误结果。
    """
    if not path.exists():
        sys.exit(f"找不到配置文件：{path}")
    cfg, section, cur = {}, None, None
    cfg["__path__"] = str(path)   # 供写回时定位，避免硬编码引擎自带配置
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#")[0].rstrip()
        if not line.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        s = line.strip()
        if indent == 0 and s.endswith(":"):
            section = s[:-1]
            cfg[section] = {}
            cur = None
        elif indent == 0 and ":" in s:
            k, v = s.split(":", 1)
            cfg[k.strip()] = _scalar(v.strip())
            cur = None
        elif indent == 2 and section and s.endswith(":"):
            cur = s[:-1]
            cfg[section][cur] = {}
        elif indent == 2 and section and ":" in s:
            k, v = s.split(":", 1)
            cfg[section][k.strip()] = _scalar(v.strip())
        elif indent == 4 and ":" in s:
            if cur is None:
                sys.exit(
                    f"配置错误：{path}:{lineno} 「{s}」缩进为 4 但前面没有大类 key。\n"
                    f"  多半是删除某个大类时只删了 `  key:` 行、漏删了下面的内容。\n"
                    f"  请补齐 key 行，或删掉这段孤儿字段。"
                )
            k, v = s.split(":", 1)
            k = k.strip()
            # 同一大类内字段名重复 → 多半是孤儿块混进来了
            # （删 key 时漏删内容，属性被静默并入上一个人类的后果）
            if k in cfg[section][cur]:
                sys.exit(
                    f"配置错误：{path}:{lineno} 大类「{cur}」中字段 `{k}` 重复定义。\n"
                    f"  常见原因：删除某个人类时只删了 `  key:` 行，下面的内容成了孤儿块，\n"
                    f"  被静默并入上一个人类（表现为某个人类被改名为别的名字）。\n"
                    f"  请检查 `{section}` 段，补齐缺失的 key 行或删掉孤儿字段。"
                )
            cfg[section][cur][k] = _scalar(v.strip())
    return cfg


def _scalar(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
    return v


def domain_root(cfg: dict) -> Path:
    return Path(os.path.expanduser(cfg.get("root", "~/.ai/domains")))


def domain_dir(cfg: dict, key: str) -> Path:
    """大类的真实目录名：优先用 name（中文），否则用 key。"""
    meta = cfg.get("domains", {}).get(key, {})
    return domain_root(cfg) / meta.get("name", key)


# ---------- 初始化 ----------

def make_link(link_path: Path, target: Path) -> bool:
    """跨平台创建目录链接：Windows 用 junction，其余用 symlink。"""
    try:
        if link_path.exists() or link_path.is_symlink():
            return True
        if IS_WIN:
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
                           check=True, capture_output=True)
        else:
            link_path.symlink_to(target, target_is_directory=True)
        return True
    except Exception as e:
        print(f"  ✗ 创建链接失败 {link_path}: {e}")
        return False


RULES_TEMPLATE = """# {name} — 领域规则（每次任务前必读）

> 这里写**硬约束**：不能做什么、必须做什么。
> 与 skills/ 的区别：rules 是"每次都要看、但只有几行"的约束，
> skills 是"用得上才看、但很长"的流程。**不要在这里写流程。**

## 输出约束

-

## 禁止事项

-

## 必须确认的事项

-

## 术语与口径

| 术语 | 本协议中的含义 |
|---|---|
"""

AGENTS_TEMPLATE = """# {name} — 角色定义

> 你在这个领域里是谁。按需加载（涉及该领域专业输出时）。

## 身份

-

## 语气与风格

-

## 判断倾向

-

## 边界

遇到下列情况应提示用户而非自行判断：

-
"""

COMMON_RULES = """# 通用规则（每次任务前必读）

- 只陈述有证据支持的内容，不补全、不猜测
- 引用外部信息标注来源，不把检索内容当既知事实
- 生成代码后实际运行验证，不凭"看起来对"交付
- 产物 ≥5 个或为整个目录 → 打包 zip，只返单个路径
- 修改已有文件前先 read 原文件
"""


def cmd_init(cfg: dict) -> None:
    root = domain_root(cfg)
    subdirs = cfg.get("subdirs", ["agents", "skills", "rules"])
    print(f"初始化大类根目录：{root}\n")
    root.mkdir(parents=True, exist_ok=True)
    for key, meta in cfg.get("domains", {}).items():
        d = root / meta.get("name", key)
        for sub in subdirs:
            (d / sub).mkdir(parents=True, exist_ok=True)
        # 领域规则与角色模板：空着就没人填，给个骨架
        rules_f = d / "rules" / "_domain.md"
        if not rules_f.exists():
            rules_f.write_text(RULES_TEMPLATE.format(name=meta.get("name", key)),
                               encoding="utf-8")
        agents_f = d / "agents" / "_role.md"
        if not agents_f.exists():
            agents_f.write_text(AGENTS_TEMPLATE.format(name=meta.get("name", key)),
                                encoding="utf-8")
        # assets/：变更溯源。每个大类都要有，否则改了技能没地方记原因
        (d / "assets").mkdir(parents=True, exist_ok=True)
        mark = "（通用）" if key == cfg.get("common") else ""
        print(f"  ✓ {d.name}{mark}  {'/'.join(subdirs)} + assets/")

    # 通用大类预置一份真实可用的通用规则
    cr = domain_dir(cfg, cfg.get("common", "_common")) / "rules" / "_common.md"
    if not cr.exists():
        cr.write_text(COMMON_RULES, encoding="utf-8")
        print(f"  ✓ {cfg.get('common')}/rules/_common.md 已预置")

    print(f"\n各大类内建 {cfg.get('common')} 链接：")
    cmd_add_common(cfg, quiet=True)
    print("\n下一步：python3 scripts/domain.py --link <大类key> <项目路径>")


def cmd_add_common(cfg: dict, quiet: bool = False) -> None:
    """每个大类内建 _common 链接，使进入任意大类都能访问通用技能。"""
    root, common = domain_root(cfg), cfg.get("common", "_common")
    common_real = root / common
    if not common_real.exists():
        common_real.mkdir(parents=True, exist_ok=True)
    for key, meta in cfg.get("domains", {}).items():
        if key == common:
            continue
        d = root / meta.get("name", key)
        for sub in cfg.get("subdirs", ["agents", "skills", "rules"]):
            (d / sub).mkdir(parents=True, exist_ok=True)
        link = d / common
        if make_link(link, common_real) and not quiet:
            print(f"  ✓ {d.name}/{common} → {common_real}")


# ---------- 探测与路由 ----------

def cmd_detect(cfg: dict, start: Path = None) -> None:
    """从当前目录向上找 junction，解析出接入的大类。"""
    link_name = cfg.get("link_name", ".ai")
    p = Path(start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        link = d / link_name
        if link.is_symlink() or (IS_WIN and link.exists()):
            try:
                real = link.resolve()
            except Exception:
                real = link
            name = real.name
            key = _key_by_name(cfg, name)
            local = p / cfg.get("local_name", ".ai-local")
            print(f"当前项目：{p}")
            print(f"接入链接：{link}")
            print(f"指向大类：{name}" + (f"  (key={key})" if key else "  ⚠ 未注册"))
            print(f"skills 真实路径：{real / 'skills'}")
            print(f"本地覆盖层：{local}"
                  + ("（存在，优先级最高）" if local.exists() else "（未创建）"))
            print(f"\n加载顺序：")
            print(f"  1. {cfg.get('local_name')}/rules.md        ← 项目特化，最高优先级")
            print(f"  2. {cfg.get('link_name')}/rules/*.md      ← 大类硬约束，必读")
            print(f"  3. {cfg.get('link_name')}/INDEX.md        ← 本类技能索引，只读这个")
            print(f"  4. 命中 → 加载 skills/ 下对应文件；未命中 → 查 _common")
            print(f"\n→ 新技能默认归属：{name}（除非明显是跨领域通用）")
            return
    print(f"未找到 {link_name} 链接（已向上查找至 {p.root}）")
    print("→ 用 python3 scripts/domain.py --link <大类key> <项目路径> 接入")


def _key_by_name(cfg: dict, name: str) -> str:
    for k, m in cfg.get("domains", {}).items():
        if m.get("name", k) == name or k == name:
            return k
    return ""


def detect_key(cfg: dict, start: Path = None) -> str:
    """静默探测当前项目接入的大类 key，未接入返回空串。"""
    link_name = cfg.get("link_name", ".ai")
    p = Path(start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        link = d / link_name
        if link.is_symlink() or (IS_WIN and link.exists()):
            try:
                return _key_by_name(cfg, link.resolve().name)
            except Exception:
                return ""
    return ""


def cmd_route(cfg: dict, text: str, suggest_only: bool = False) -> None:
    """按关键词推荐归属大类。推荐，不自动写入。

    判定优先级：当前项目大类（强信号）> 独占候选 > 分差明显 > 人工判断。
    短描述命中词少是常态，因此「唯一候选」比「命中数达标」更有说服力。
    """
    common = cfg.get("common", "_common")
    scored = []
    for key, meta in cfg.get("domains", {}).items():
        hit = [k for k in meta.get("keywords", []) if k in text]
        if hit:
            scored.append((len(hit), key, meta, hit))

    print(f"技能描述：{text}\n")

    cur = detect_key(cfg)
    cur_name = cfg.get("domains", {}).get(cur, {}).get("name", cur) if cur else ""
    if cur and cur != common:
        print(f"当前项目已接入：{cur_name}（作为优先信号）\n")

    if not scored:
        print(f"未匹配任何大类关键词 → 归 {common}，或手动 --domain <key>")
        return

    # 当前大类加权：项目方向是最直接的归属线索
    if cur:
        scored = [(n + 1 if k == cur else n, k, m, h) for n, k, m, h in scored]
    scored.sort(key=lambda x: (-x[0], x[1] != cur if cur else 0))

    print("归属候选：")
    for n, key, meta, hit in scored[:5]:
        name = meta.get("name", key)
        tag = "  ← 当前项目" if key == cur else ""
        print(f"  {n} 分  {name:<8} {meta.get('desc', '')}{tag}")
        print(f"        命中词：{', '.join(hit)}")

    best_n, best_key, best_meta, _ = scored[0]
    best_name = best_meta.get("name", best_key)
    print()

    if len(scored) == 1:
        conf = "高" if best_n >= 2 else "中（唯一候选，但仅命中 1 词，建议确认）"
        print(f"→ 建议归属：{best_name}（置信度{conf}）")
    elif best_n > scored[1][0]:
        gap = best_n - scored[1][0]
        conf = "高" if gap >= 2 else "中"
        print(f"→ 建议归属：{best_name}（置信度{conf}，领先 {gap} 分）")
    else:
        rival = scored[1][2].get("name", scored[1][1])
        print(f"→ 候选持平，需人工判断：{best_name} vs {rival}")
        print("   判据：这个技能换个大类还成立吗？成立 → 归 _common")

    if not suggest_only:
        print(f"\n确认写入：python3 scripts/index.py --add <文件> --domain {best_key}")


LOCAL_TEMPLATE = """# 项目本地规则（优先级最高）

> 这是**真实目录**，不走 junction，内容归本项目独有。
> 与大类规则冲突时，以本文件为准。

## 本项目特化的输出约束

-

## 本项目常用术语

| 术语 | 本项目中的含义 |
|---|---|
"""


def cmd_link(cfg: dict, key: str, project: str) -> None:
    if key not in cfg.get("domains", {}):
        sys.exit(f"未注册的大类：{key}\n已注册：{', '.join(cfg.get('domains', {}))}")
    target = domain_dir(cfg, key)
    target.mkdir(parents=True, exist_ok=True)
    proj = Path(project).expanduser().resolve()
    proj.mkdir(parents=True, exist_ok=True)
    link = proj / cfg.get("link_name", ".ai")
    if make_link(link, target):
        print(f"✓ 已接入：{link} → {target}")
        print(f"  项目内可用：{cfg.get('link_name')}/skills")

    # 项目级覆盖层：真实目录，不走链接，项目删掉不影响大类
    local = proj / cfg.get("local_name", ".ai-local")
    local.mkdir(parents=True, exist_ok=True)
    (local / "skills").mkdir(exist_ok=True)
    rules_f = local / "rules.md"
    if not rules_f.exists():
        rules_f.write_text(LOCAL_TEMPLATE, encoding="utf-8")
    print(f"✓ 本地覆盖层：{local}/（真实目录，优先级高于大类）")


def cmd_where(cfg: dict, key: str, sub: str = "skills") -> None:
    if key not in cfg.get("domains", {}):
        sys.exit(f"未注册的大类：{key}")
    print(domain_dir(cfg, key) / sub)


def cmd_list(cfg: dict) -> None:
    root = domain_root(cfg)
    print(f"大类根目录：{root}\n")
    if not root.exists():
        print("（尚未初始化，运行 --init）")
        return
    for key, meta in cfg.get("domains", {}).items():
        d = domain_dir(cfg, key)
        n = len(list((d / "skills").rglob("*.md"))) if (d / "skills").exists() else 0
        mark = "（通用）" if key == cfg.get("common") else ""
        print(f"  {key:<12} {d.name:<8} skills {n:>3} 个{mark}  {meta.get('desc', '')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="初始化大类根目录")
    ap.add_argument("--list", action="store_true", help="列出全部大类")
    ap.add_argument("--detect", action="store_true", help="探测当前项目接入的大类")
    ap.add_argument("--route", metavar="描述", help="推荐技能归属大类")
    ap.add_argument("--link", nargs=2, metavar=("大类KEY", "项目路径"), help="接入项目")
    ap.add_argument("--add-common", action="store_true", help="各大类内建通用链接")
    ap.add_argument("--where", metavar="大类KEY", help="输出该大类 skills 真实路径")
    ap.add_argument("--config", default=str(CONFIG), help="指定配置文件")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))

    if args.init:
        cmd_init(cfg)
    elif args.list:
        cmd_list(cfg)
    elif args.detect:
        cmd_detect(cfg)
    elif args.route:
        cmd_route(cfg, args.route)
    elif args.link:
        cmd_link(cfg, args.link[0], args.link[1])
    elif args.add_common:
        cmd_add_common(cfg)
    elif args.where:
        cmd_where(cfg, args.where)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
