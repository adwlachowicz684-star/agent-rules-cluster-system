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
from exitcode import OK, USAGE, ENV, ERR, die  # 码表：0/1/2/3/4

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
IS_WIN = os.name == "nt"


# ---------- 配置 ----------

def _logical_lines(text: str) -> list:
    """把跨行的流式列表合并成逻辑行，返回 [(行号, 缩进, 内容)]。

    为什么需要：解析器逐行处理，而

        keywords: [通用, 交付, 打包,
                   审查, 审计]

    这种 YAML 流式列表的开头行不以 `]` 结尾，`_scalar` 认不出它是列表，
    整包退化成**字符串**。下游 `for k in kws` 遍历字符串 → 逐字符匹配，
    路由命中显示成「命中 c, o, 空格」这类噪音，归属判定全面失真。
    判据就是括号是否闭合：未闭合就并上下一行。
    """
    out, buf = [], None
    start = indent = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        c = raw.split("#")[0].rstrip()
        if not c.strip():
            continue
        if buf is None:
            start, indent, buf = lineno, len(raw) - len(raw.lstrip()), c.strip()
        else:
            buf = buf + " " + c.strip()
        if buf.count("[") > buf.count("]"):
            continue                      # 未闭合，继续并下一行
        out.append((start, indent, buf))
        buf = None
    if buf is not None:                   # 文件结束时仍未闭合，交给 _scalar 兜底
        out.append((start, indent, buf))
    return out


def load_config(path: Path = CONFIG) -> dict:
    """极简 YAML 解析（只支持本文件用到的结构，避免引入依赖）。

    加了孤儿行检测：缩进 4 的字段若前面没有 key（通常是删 key 时漏删内容），
    会被静默归给上一个大类，导致「金融被改名成区块链」这类隐蔽错误。
    宁可报错，也不要静默产生错误结果。

    收尾另加 keywords 类型校验：退化成字符串会让路由静默失真，
    与其给出错误归属，不如直接报错。
    """
    if not path.exists():
        die(ENV, f"找不到配置文件：{path}")
    cfg, section, cur = {}, None, None
    cfg["__path__"] = str(path)   # 供写回时定位，避免硬编码引擎自带配置
    for lineno, indent, s in _logical_lines(path.read_text(encoding="utf-8")):
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
                die(USAGE,                    f"配置错误：{path}:{lineno} 「{s}」缩进为 4 但前面没有大类 key。\n"
                    f"  多半是删除某个大类时只删了 `  key:` 行、漏删了下面的内容。\n"
                    f"  请补齐 key 行，或删掉这段孤儿字段。"
                )
            k, v = s.split(":", 1)
            k = k.strip()
            # 同一大类内字段名重复 → 多半是孤儿块混进来了
            # （删 key 时漏删内容，属性被静默并入上一个人类的后果）
            if k in cfg[section][cur]:
                die(USAGE,                    f"配置错误：{path}:{lineno} 大类「{cur}」中字段 `{k}` 重复定义。\n"
                    f"  常见原因：删除某个人类时只删了 `  key:` 行，下面的内容成了孤儿块，\n"
                    f"  被静默并入上一个人类（表现为某个人类被改名为别的名字）。\n"
                    f"  请检查 `{section}` 段，补齐缺失的 key 行或删掉孤儿字段。"
                )
            cfg[section][cur][k] = _scalar(v.strip())
    _check_keyword_types(cfg, path)
    return cfg


def _check_keyword_types(cfg: dict, path: Path) -> None:
    """keywords / core 必须是列表。

    退化成字符串时下游 `for k in kws` 会逐字符遍历 → 路由静默失真。
    与孤儿行检测同一个原则：宁可报错，也不要给出看起来正常的错误归属。
    """
    for key, meta in (cfg.get("domains") or {}).items():
        if not isinstance(meta, dict):
            continue
        for field in ("keywords", "core"):
            v = meta.get(field)
            if v is not None and not isinstance(v, list):
                die(USAGE,                    f"配置错误：{path} 大类「{key}」的 {field} 被解析成 "
                    f"{type(v).__name__}，应为列表。\n"
                    f"  常见原因：跨行流式列表的括号没成对，未被合并成一行。\n"
                    f"  逐字符匹配会让路由结果失真，请检查该字段的括号或改写成单行。"
                )


def _scalar(v: str):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
    return v


def domain_root(cfg: dict) -> Path:
    """大类根目录。

    ### ⛔ 2026-09-26：默认改为**仓库内**（`domains/`，跟着 git 走）

    三种取值，优先级从高到低：

    | 来源 | 用途 |
    |---|---|
    | 环境变量 `SKILL_DOMAINS_ROOT` | 需要"每台机器独立积累"时覆盖 |
    | config 里的**绝对**路径 | 用户显式指定 |
    | config 里的**相对**路径 | **默认**：`domains`，相对 skill 根 |

    ⛔ **为什么不直接写 `~/.ai/domains`**：
    技能数据是**资产**，不是运行时产物。实测环境重置后 1 个真技能包没了，
    而 git 管不到它 ⇒ 无法版本化、无法 review、无法回滚，
    且 lint 长期报「大类根目录不存在 → 检查不完整」。

    ⚠ **相对路径必须相对 skill 根解析，不是 CWD**：
    从别处调用脚本时 CWD 不定，按 CWD 解析会指向错误目录
    ⇒ 扫到 0 个包而不报错（第十八条）。
    """
    raw = os.environ.get("SKILL_DOMAINS_ROOT", "").strip()
    if raw:
        return Path(os.path.expanduser(raw))
    raw = cfg.get("root", "domains")
    raw = os.path.expanduser(str(raw))
    if os.path.isabs(raw):
        return Path(raw)
    # 相对路径 → 相对 skill 根
    # ⛔ 支持 cfg['_root'] 覆盖：自检要能在临时目录上跑，
    #    否则检查器只能用真库，而用例会依赖真库状态（踩过多次）。
    _b = cfg.get('_root')
    return (Path(_b) if _b else Path(ROOT)) / raw


def domain_dir(cfg: dict, key: str) -> Path:
    """大类的真实目录名：优先用 name（中文），否则用 key。

    ⛔ **实测（主链路真跑第 4 个断点）**：
    目录实际建在 `key`（`dev`），而 `name` 是中文（`开发`）。
    只认 name ⇒ `scan()` 扫 `domains/开发/skills` 不存在 ⇒ **索引永远 0 项**，
    而 `--find` 输出「未命中：… 库里还没有这个技能」——
    ⛔ **失败模式是"返回 0 条"而不是报错**（第十八条）。

    ⇒ name 目录不存在而 key 目录存在时回退到 key，避免整套召回空转。
    """
    meta = cfg.get("domains", {}).get(key, {})
    root = domain_root(cfg)
    named = root / meta.get("name", key)
    if not named.exists():
        by_key = root / key
        if by_key.exists():
            return by_key
    return named


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
            # ⛔ 2026-09-26：改用**相对**软链接。
            #    绝对软链接（/data/workspace/.../domains/_common）在：
            #      · 换机器 / 换 clone 路径 → **指向不存在的目录**（断链）
            #      · 进 git → checkout 出来是写死别人路径的链接
            #    ⇒ domains 现在跟着仓库走（root 改为相对路径），
            #      链接也必须相对，否则仓库搬一次就全断。
            #    ⓘ os.path.relpath 需要基于 link 的父目录计算。
            link_path.symlink_to(os.path.relpath(str(target), str(link_path.parent)),
                                 target_is_directory=True)
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
        die(USAGE, f"未注册的大类：{key}\n已注册：{', '.join(cfg.get('domains', {}))}")
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
        die(USAGE, f"未注册的大类：{key}")
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


def cmd_self_test() -> int:
    """正反样本：证明断点 3（name/key 回退）真的被守住。"""
    import tempfile
    ok = True

    def chk(cond, label):
        nonlocal ok
        print(('  ✓ ' if cond else '  ✗ ') + label)
        if not cond:
            ok = False

    print('=' * 62)
    print('domain 自检（主链路断点守门）')
    print('=' * 62)
    cfg = {'domains': {'dev': {'name': '开发'}, '_k': {'name': '_k'}}}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg['root'] = str(Path(root).resolve())
        # 反向一：目录建在 key（dev）而非 name（开发）→ 必须回退
        (root / 'dev').mkdir()
        _R = Path(root).resolve()
        chk(domain_dir(cfg, 'dev').resolve() == _R / 'dev',
            'name 目录不存在而 key 目录存在 → 回退 key —— '
            '⛔ 不回退则索引永远 0 项（实测：--find 输出「未命中」而不报错）')
        # 正向：name 目录存在 → 优先 name
        (root / '开发').mkdir()
        chk(domain_dir(cfg, 'dev').resolve() == _R / '开发',
            'name 目录存在 → 优先 name（不误伤正常情况）')
    # ---- 相对路径必须相对 skill 根解析，不是 CWD ----
    # ⛔ CWD 不定（从别处调用脚本时）⇒ 按 CWD 解析会指向错误目录
    #    ⇒ 扫到 0 个包而不报错（第十八条）。
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        _r = base / 'skills'
        _r.mkdir()
        chk(domain_root({'root': 'domains', '_root': str(_r)}) == _r / 'domains',
            '相对 root 基于 skill 根解析（⛔ 不是 CWD）—— '
            '落错目录会扫到 0 个包且不报错')
        chk(domain_root({'root': 'domains'}) == ROOT / 'domains',
            '未注入 _root 时回退到真 skill 根（不误伤生产路径）')

    print()
    print('自检：%s' % ('全部通过' if ok else '有失败'))
    return OK if ok else ERR


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
    ap.add_argument("--self-test", action="store_true",
                    help="用正反样本验证 name/key 回退真的生效")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(cmd_self_test())

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
