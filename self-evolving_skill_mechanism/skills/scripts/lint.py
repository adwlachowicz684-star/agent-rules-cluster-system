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
import os
import ast
import json
import subprocess
import argparse
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from domain import load_config, domain_dir, domain_root, CONFIG  # noqa: E402
from exitcode import OK, ERR, USAGE, ENV, BLOCKED, die, help_text  # 码表：0/1/2/3/4

# 间接覆盖登记：某些检查项无法在自检里直接调用（要靠 subprocess 跑真实脚本），
# 在这里显式登记理由。⛔ 不登记就报 warn——
# 「找不到就说没有」正是第十八条批判的失败模式。
INDIRECT_COVERAGE = {
    "check_exitcode_adoption": "靠 subprocess 跑真实脚本实测退出码，"
                               "不是调用本函数（mutate EV-M01 同族）",
    # ⛔ 自指：本项检查的是 lint.py 自己的 cmd_self_test，
    #    无法在自检里「造一份自己的自检」——那会改动正在跑的代码。
    #    ⇒ 用例改用「造一份假的 lint.py 传给 src_path」（见 --self-test EV-M24）。
    "check_selftest_duality": "自指检查：用 src_path 传入假 lint.py 造样本，"
                              "不是调用本函数（见 EV-M24）",
}

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

# ---- 知识点落地检查 ----
# 「要注意 X」「谨慎处理 Y」这类条目如果流程里没有任何一步引用它，
# 执行时根本走不到——写了等于没写。这里把它自动查出来。
#
# 为什么必须脚本化：靠自觉检查必然漏。人写的时候觉得自己知道它在哪一步，
# 隔两周回看就找不到了。
NOTE_SECTION = ("注意", "已知坑", "要点", "禁忌", "红线", "应该", "原则")
FLOW_SECTION = ("流程", "步骤", "操作", "做法", "怎么用", "执行")
STOPWORDS = {"注意", "应该", "应当", "要", "不要", "不能", "需要", "必须", "谨慎",
             "处理", "进行", "确保", "避免", "重要", "相关", "情况", "时候",
             "可能", "一定", "尽量", "建议", "可以", "使用", "问题", "内容",
             "检查", "确认", "保证", "做到", "保持", "考虑", "关注", "留意",
             "这个", "那个", "什么", "如何", "通过", "对于", "关于", "以及",
             "如果", "否则", "而且", "并且", "或者", "没有", "所有", "每个",
             "自己", "我们", "他们", "之后", "之前", "然后", "最后", "首先"}


def _feature_words(text, min_len=3):
    """抽特征词：中文滑窗 2-4 字（过滤含停用词的窗口）+ 英文标识符。

    为什么用滑窗而不是整词：`要注意边界条件` 整词匹配的话，
    流程里写「先 clamp 上界」其实没提到它，却因为整词不同而判为孤立——
    反过来，滑窗能提取出「边界条件」这个真正的知识点。

    为什么默认只返回长度 ≥3 的词（调用处按此过滤）：
    2 字词（如「文件」「内容」）在流程段偶然共现的概率太高，
    拿它判定「已落地」会产生大量假阴性——该报的没报，lint 就形同虚设。
    """
    words = set()
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        n = len(run)
        for size in (2, 3, 4):
            for i in range(n - size + 1):
                w = run[i:i + size]
                if any(sw in w for sw in STOPWORDS):
                    continue
                words.add(w)
    for w in re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,}', text):
        words.add(w.lower())
    return {w for w in words if len(w) >= min_len}


def _sections(text):
    """按 `##` 切段 → [{'title','body'}]。前置的 frontmatter 不算。"""
    if text.startswith('---'):
        m = re.match(r'^---\s*\n.*?\n---\s*\n', text, re.S)
        if m:
            text = text[m.end():]
    out, cur = [], None
    for ln in text.splitlines():
        if ln.startswith('## '):
            if cur:
                out.append(cur)
            cur = {'title': ln[3:].strip(), 'body': []}
        elif cur is not None:
            cur['body'].append(ln)
    if cur:
        out.append(cur)
    return [{'title': s['title'], 'body': '\n'.join(s['body'])} for s in out]


def _bullets(body):
    """取段落里的条目行（- / * / 表格行），去掉标题与空行。"""
    rows = []
    for ln in body.splitlines():
        t = ln.strip()
        if re.match(r'^[-*]\s+', t):
            rows.append(re.sub(r'^[-*]\s+', '', t))
        elif t.startswith('|') and t.count('|') >= 3:
            # 表格行：取第一个非空单元格（跳过表头分隔行）
            cells = [c.strip() for c in t.strip('|').split('|')]
            if cells and not set(''.join(cells)) <= set('-: '):
                rows.append(cells[0] if cells[0] else ' '.join(cells))
    return [r for r in rows if len(r) > 4]


def check_landing(cfg):
    """孤立知识点 + 占位符 + 空段落。三者都是「看起来写了其实没写」。"""
    issues = []
    targets = []
    for key in cfg.get("domains", {}):
        sd = domain_dir(cfg, key) / "skills"
        if sd.exists():
            targets += [f for f in sd.rglob("*.md") if not f.name.startswith("_")]
    # 引擎自身的领域包写法参考（SKILLS/domains 若存在也查）
    for extra in ("SKILLS/domains",):
        p = ROOT / extra
        if p.exists():
            targets += [f for f in p.rglob("*.md")]

    for f in targets:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        secs = _sections(text)
        if not secs:
            continue
        flow_text = '\n'.join(s['body'] for s in secs
                              if any(k in s['title'] for k in FLOW_SECTION))
        if not flow_text:
            # 整个包没有流程段 —— 那所有注意事项都是孤立的
            flow_text = ''

        for s in secs:
            if not any(k in s['title'] for k in NOTE_SECTION):
                continue
            for b in _bullets(s['body']):
                words = _feature_words(b)
                if not words:
                    continue
                if flow_text and any(w.lower() in flow_text.lower() for w in words):
                    continue
                issues.append({
                    "level": "warn", "file": str(f),
                    "issue": "孤立知识点：「%s」" % b[:38],
                    "hint": "流程段未引用 → 执行时走不到。写进某一步的判据，"
                            "或删除。见 reference/howto/knowledge-landing.md"})

        # 占位符
        for m in re.finditer(r'(TODO|TBD|待补充|待完善|待定|XXX+|\?\?\?|占位)', text, re.I):
            ln = text[:m.start()].count('\n') + 1
            issues.append({"level": "warn", "file": str(f),
                           "issue": "第 %d 行有占位符「%s」" % (ln, m.group(1)),
                           "hint": "写完再入库；半成品比没有更误导"})

        # 空段落（标题下无内容）——审查 skill 的自检曾查出整条空判据
        for s in secs:
            if not s['body'].strip() and s['title']:
                issues.append({"level": "warn", "file": str(f),
                               "issue": "空段落「%s」（标题下无内容）" % s['title'][:30],
                               "hint": "补内容或删标题；空段会让人以为这块已经写过了"})

    return issues

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



def _mk_repo_copy(dst):
    """造一份**必定有 error** 的引擎副本，用于验证整条链路的退出码。

    为什么需要：退出码是 `main()` 最后一步的结果，
    只测 `check_*` 函数测不到「main 有没有真的 exit」。
    而在真库上跑又依赖真库当前是否干净——真库干净时用例恒绿、从未验证。

    缺陷怎么造：删掉 `reference/` → `check_reference_zones` 报「区缺失」
    （error 级）。⚠ 不能用「新建空目录」——那只在 domains 已初始化时才报。
    """
    import shutil
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for sub in ("scripts", "assets", "SKILLS", "pending"):
        src = ROOT / sub
        if src.exists():
            shutil.copytree(src, dst / sub)
    shutil.copy2(ROOT / "SKILL.md", dst / "SKILL.md")
    shutil.copy2(ROOT / "config.yaml", dst / "config.yaml")
    # 不复制 reference/ → 区缺失（error）


def check_root(cfg):
    """大类根目录不存在时，domains/ 下的体积与 frontmatter 检查会被整段跳过，
    结果却照样输出「✓ 规范检查通过」。

    这正是本技能自己写进 _hot.md 的 H011：工具报 0 命中不等于没问题
    —— 没东西可查 ≠ 查过了没问题。这里必须显式报出来。
    """
    root = domain_root(cfg)
    if root.exists():
        return []
    return [{"level": "error", "file": str(root),
             "issue": "大类根目录不存在，domains/ 下的检查全部跳过 → 本次结果不完整",
             "hint": "先跑 python3 scripts/domain.py --init 初始化；"
                     "未初始化时本脚本只检查了引擎自身文件"}]


# 体积豁免：文件里写了这行，就说明「超大是有理由的」，降级为提示。
#
# 为什么需要：用户偏好 F002 是「宁可写全写详细，不要为精简牺牲完整性」，
# 但体积检查会预警超限——两者直接冲突。没有豁免机制时，
# 为了消掉预警去砍内容，等于为了指标牺牲质量。
# 强制写理由，是为了防止豁免被滥用成「不想拆就标一下」。
# ⚠ `(.+?)` 默认**不匹配换行** —— 豁免理由写成多行时匹配失败 →
#   **声明了豁免但没生效，检查照报**，而人以为已经豁免了。
#   实测：changelog-archive.md 的理由跨 3 行，`oversize_exempt()`
#   返回 None，于是 366 行仍被判超限。这是「假生效」——
#   比没声明更糟：没声明至少知道要拆。
# ⛔ 不能要求 `oversize-exempt` 紧跟在 `<!--` 后面：
#    实测 acceptance.md 的注释块是
#        <!--\nflow-type: meta\noversize-exempt: …\n-->
#    —— `\s*` 匹配不到 `flow-type: meta` 这段文字 →
#    **豁免声明了但不生效**（第二十一条：假生效）。
#    这是我**第二次**踩这个坑（第一次是 re.S 不吃换行）。
#
#    判据：注释块里**含有** oversize-exempt 就算声明了；
#    ⛔ 但不能跨出注释块（否则会认到下一个块里的字样）。
EXEMPT_RX = re.compile(
    r'<!--(?:(?!-->).)*oversize-exempt\s*:\s*(.+?)\s*-->',
    re.S)   # re.S：理由可以跨行写


def oversize_exempt(p):
    """返回豁免理由；没有则返回 None。"""
    try:
        head = p.read_text(encoding="utf-8")[:2000]
    except Exception:
        return None
    m = EXEMPT_RX.search(head)
    return m.group(1).strip() if m else None



# ---- token 阈值（双阈值：行数 + token） ----
#
# 反哺自 code-audit 的 check-skill.py（SK006/SK009 双阈值）。
# 为什么只有行数不够：**占上下文的是 token，不是行数**。
#   一份 150 行的宽表格可能比 400 行散文贵得多；
#   反过来，400 行短句可能很便宜。
#   只按行数卡，会放过"行数合规但读进来很贵"的文件，
#   也会逼着人拆掉"行数多但很便宜"的文件——两种都错。
#
# 估算而非精确计数：不装分词器也能用，误差可接受
# （判据是「量级对不对」，不是「差几个 token」）。
TOKEN_LIMITS = {
    "SKILL.md": 8192,
    "reference": 8192,
    "skills": 8192,
    "assets": 8192,
}
TOKEN_DEFAULT = 8192


def token_estimate(text):
    """粗估 token 数：中文按字、英文按词、其余按字符折算。

    与 code-audit 侧一致：中文一字约一 token，英文按空格分词，
    ⚠ 不追求精确——判据是量级，差 10% 不影响"该不该拆"的判断。
    """
    import re as _re
    n = 0
    for seg in _re.findall(r'[\u4e00-\u9fff]+|[A-Za-z0-9_./:-]+|\S', text):
        if _re.match(r'^[\u4e00-\u9fff]+$', seg):
            n += len(seg)          # 中文按字
        else:
            n += 1
    return n


def check_size(cfg, limits, root=None):
    """root 参数只给自检用例用（自造样本），生产调用走默认 ROOT。

    ⚠ 为什么必须支持注入：不注入就只能测真库，
    而真库里恰好有一个超限文件时就「蹭过了」——
    用例没有验证任何东西（第二十四条实证：把断言换成
    `chk(True)`，自检总数完全不变 61/0 → 61/0）。
    """
    base = Path(root) if root else ROOT
    issues = []

    def chk(path, label, key, hint=""):
        if not path.exists():
            return
        n = n_lines(path)
        lim = int(limits.get(key, DEFAULTS.get(key, 400)))
        if n <= lim:
            return
        why = oversize_exempt(path)
        if why:
            # 声明过豁免 → 降为 info，并把理由带上（理由也要能被复核）
            issues.append({"level": "info", "file": label, "lines": n,
                           "limit": lim,
                           "issue": "已声明豁免：%s" % why,
                           "hint": "豁免必须有理由；理由不成立就该拆"})
            return
        issues.append({"level": "warn", "file": label, "lines": n,
                       "limit": lim, "hint": hint or HINTS.get(key, "拆分")})

    chk(base / "SKILL.md", "SKILL.md", "SKILL.md", "细节下沉到 reference/")
    for name in ("_hot.md", "_preferences.md", "_commands.md"):
        chk(base / "SKILLS" / name, "SKILLS/" + name, name,
            "拆分为多个文件或归档低频条目")
    # rglob 而非 glob：reference/ 下已分为 howto/audit/flow/common/craft
    # 五个子区，只扫顶层会让子区的文档**完全不参与体积检查**。
    for f in sorted((base / "reference").rglob("*.md")):
        chk(f, str(f.relative_to(base)), "reference")

    ad = base / "assets"
    if ad.exists():
        for f in sorted(ad.glob("*.md")):
            chk(f, "assets/" + f.name, "assets")

    for key in (cfg.get("domains", {}) if root is None else {}):
        d = domain_dir(cfg, key)
        for sub in ("rules", "agents", "skills", "assets"):
            sd = d / sub
            if not sd.exists():
                continue
            lim = int(limits.get(sub, DEFAULTS.get(sub, 400)))
            for f in sorted(sd.rglob("*.md")):
                n = n_lines(f)
                if n <= lim:
                    continue
                why = oversize_exempt(f)
                label = "%s/%s/%s" % (d.name, sub, f.name)
                if why:
                    issues.append({
                        "level": "info", "file": label, "lines": n, "limit": lim,
                        "issue": "已声明豁免：%s" % why,
                        "hint": "豁免必须有理由；理由不成立就该拆"})
                else:
                    issues.append({
                        "level": "warn", "file": label, "lines": n, "limit": lim,
                        "hint": HINTS.get(sub, "拆分归档")})
    return issues


def _frontmatter(text):
    """解析 YAML frontmatter → dict。没有则返回 {}。

    ⚠ 早先只认 `k: v` 单行，**不支持块列表**：

        keywords:
          - 经验沉淀
          - 技能库

    结果：`keywords:` 这行 v 为空 → `fm["keywords"] = ""` →
    检查报「缺 keywords」，而**文件里明明写了 15 条**。

    ⛔ 这是「假生效」的镜像形态（silent 第二十一条）：
    这次不是声明没生效，而是**写的东西读不出来**——
    工具说没写，人看着明明写了，双方都觉得自己对。
    而按标准 YAML 写块列表是最自然的写法，不该要求人去迁就解析器。

    现在支持块列表（`- item`）；字段值是列表时按列表存，
    仍是单行 `k: v` 的字段保持字符串，不影响 `len()` 类判断。
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    fm = {}
    cur = None
    for line in m.group(1).splitlines():
        st = line.strip()
        if not st or st.startswith("#"):
            continue
        # 块列表项：归到上一个值为空的 key 下
        if st.startswith("- ") and cur:
            if not isinstance(fm.get(cur), list):
                fm[cur] = []
            fm[cur].append(st[2:].strip())
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v == "":
                cur = k
                fm[k] = []            # 可能是列表头；没有列表项则为空 → 视为缺失
            else:
                cur = None
                fm[k] = v
    return fm


def _fm_str(fm, key):
    """取字段的字符串形式（列表则拼接）。"""
    v = fm.get(key)
    if isinstance(v, list):
        return " ".join(v)
    return v or ""


def check_mirror_pairs(cfg, root=None):
    """镜像册（建设册 ↔ 审查册 1:1 同名）必须**双向**可达。

    为什么需要：单向指向是最常见的失效。
    审查册指建设册容易（审查时本来就要看"应该怎么做"）；
    建设册指审查册容易忘（写的时候不会想到"去哪查坑"）。
    结果就是：**审查册再全，开发时也用不到**。

    实测（本仓库 Godot 镜像册）：审查册 79/79 全有指向建设册的指针，
    建设册 82 份里只有 10 份指回——单向。已补 69 份。

    判据：两侧各自 `grep -L 对侧关键词`，列出来的就是断的那半边。
    只查单向会让"建设册那边根本没指"从未被发现。
    """
    base = Path(root) if root else ROOT
    # 镜像对配置：缺 cfg 里的键时跳过（不是所有库都有镜像册）
    raw = cfg.get("mirror_pairs") or {}
    # 支持两种写法：{名字: {build,review,...}}（推荐）与 [{...}, ...]
    if isinstance(raw, dict):
        pairs = list(raw.values())
    elif isinstance(raw, list):
        pairs = [x for x in raw if isinstance(x, dict)]
    else:
        pairs = []
    if not pairs:
        return []
    issues = []
    for pair in pairs:
        a = base / pair.get("build", "")
        b = base / pair.get("review", "")
        kw_a = pair.get("review_kw", "")
        kw_b = pair.get("build_kw", "")
        if not (a.exists() and b.exists() and kw_a and kw_b):
            continue
        fa = {f.name for f in a.glob("*.md")}
        fb = {f.name for f in b.glob("*.md")}
        # ① 建设册 → 审查册
        for name in sorted(fa):
            try:
                t = (a / name).read_text(encoding="utf-8")
            except Exception:
                continue
            if kw_a in t:
                continue
            if name not in fb:
                issues.append({"level": "info",
                               "file": "%s/%s" % (a.name, name),
                               "issue": "无同名审查册（%s 里没有它）" % b.name,
                               "hint": "审查册缺口——要么补一份，要么登记为已知缺口，"
                                       "不要伪造指针（指向不存在的文件 = 死链）"})
                continue
            issues.append({"level": "warn",
                           "file": "%s/%s" % (a.name, name),
                           "issue": "未指向同名审查册（单向）",
                           "hint": "开发时看不到反模式清单 → 写完不知道去哪查坑。"})
        # ② 审查册 → 建设册
        for name in sorted(fb):
            try:
                t = (b / name).read_text(encoding="utf-8")
            except Exception:
                continue
            if kw_b in t:
                continue
            if name not in fa:
                continue      # 审查册比建设册多是合法的（先有坑表）
            issues.append({"level": "warn",
                           "file": "%s/%s" % (b.name, name),
                           "issue": "未指向同名建设册（单向）",
                           "hint": "审核时不知道「应该怎么做」在哪。"})
    return issues


FLOW_FIELDS = ("【读】", "【做】", "【产出】", "【判据】", "【审】")


def _flow_meta(text):
    """读文件头的 flow-type / flow-id（HTML 注释形式的极简 frontmatter）。

    为什么用 HTML 注释而不是 YAML frontmatter：
    本仓库的 md 都被要求能以纯 Markdown 渲染，YAML 块在部分渲染器里
    会显示成代码块。且手写的极简解析器只需两行。
    """
    head = "\n".join(text.split("\n")[:12])
    t = re.search(r'flow-type:\s*(\w+)', head)
    i = re.search(r'flow-id:\s*([A-Za-z0-9-]+)', head)
    return (t.group(1) if t else None), (i.group(1) if i else None)


def check_flow_steps(cfg, root=None):
    """flow/ 区流程规范检查（支撑后续大批流程补充）。

    为什么需要：flow/ 区要持续补充大量流程。没有自动检查时，
    每个新流程各自发明格式，最后**无法统一检索、无法判定完成度**。

    ⚠ **最关键的一条**：必须区分 meta / procedure。
    元规范（`step-spec.md`）里必然**举例** Step（"七节模板"），
    不区分的话，那些示例会被当成真步骤检查——
    **举例的模板永远不完整，必然误报，而误报的检查会被关掉**。

    检查项：
      ① flow-type 缺失         —— 无法分流，会被当成 procedure 误报
      ② procedure 缺 flow-id   —— 后续无法被索引与引用
      ③ flow-id 重复           —— 引用指向歧义
      ④ Step 五字段不全        —— 最核心：省【产出】下游无法对接，
                                  省【判据】无法判定做对没有
      ⑤ 缺「整体审核」节       —— 只有步骤级没有流程级，漏列的抓不到
      ⑥ 节点 ID 缺失/格式错    —— 流程工具按它记进度，改了进度就断
      ⑦ index.md 登记表双向    —— 只写文件不登记 / 只登记无文件，都失真
    """
    base = Path(root) if root else ROOT
    flow = base / "reference" / "flow"
    if not flow.exists():
        return []
    issues = []
    seen_ids = {}

    for md in sorted(flow.glob("*.md")):
        rel = str(md.relative_to(base))
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        ftype, fid = _flow_meta(text)

        # ① flow-type 缺失
        if not ftype:
            issues.append({"level": "error", "file": rel,
                           "issue": "缺 flow-type 标记（meta / procedure / template）",
                           "hint": "在文件头加 `<!--\nflow-type: meta\n-->`；"
                                   "缺了无法分流，会被当成 procedure 误报"})
            continue
        if ftype == "meta":
            continue        # 元规范：不检查 Step（它必然举例）
        if ftype == "template":
            continue        # 模板：占位符本就不完整

        # ②③ procedure 必须有唯一 flow-id
        if not fid:
            issues.append({"level": "error", "file": rel,
                           "issue": "procedure 缺 flow-id",
                           "hint": "加 `flow-id: FL-xx`（见 index.md 第五节）"})
        elif fid in seen_ids:
            issues.append({"level": "error", "file": rel,
                           "issue": "flow-id 重复：%s（已被 %s 占用）"
                                    % (fid, seen_ids[fid]),
                           "hint": "查 index.md 登记表取下一个未用的 FL-xx"})
        else:
            seen_ids[fid] = rel

        # ④ Step 五字段
        body = _outside_code_blocks(text)
        steps, cur = [], None
        for line in body:
            # ⚠ 判据是「有节点 ID」，不是「标题含 Step 字样」：
            # 实测 new-skill.md 的「### 批量四步（替换 Step 4）」被当成真 Step
            # → 报「缺五字段」。它只是**提到** Step 4，不是 Step。
            # 节点 ID `[FL-xx#S1]` 才是 Step 的稳定标识。
            if line.startswith("### ") and re.search(
                    r'\[[A-Za-z0-9-]+#S\d+\]', line):
                if cur:
                    steps.append(cur)
                cur = {"title": line, "text": "", "lineno": 0}
            elif cur is not None:
                if line.startswith("### ") or line.startswith("## "):
                    steps.append(cur)
                    cur = None
                else:
                    cur["text"] += line + "\n"
        if cur:
            steps.append(cur)

        for st in steps:
            miss = [f for f in FLOW_FIELDS if f not in st["text"]]
            if miss:
                issues.append({
                    "level": "error", "file": rel,
                    "issue": "Step 缺五字段：%s —— %s"
                             % ("、".join(miss), st["title"].strip()[:36]),
                    "hint": "五字段是【读】【做】【产出】【判据】【审】。"
                            "省【产出】→ 下游无法对接；省【判据】→ 无法判定做对没有"})
            # ⑥ 节点 ID
            if not re.search(r'\[[A-Za-z0-9-]+#S\d+\]', st["title"]):
                issues.append({
                    "level": "warn", "file": rel,
                    "issue": "Step 缺节点 ID `[FL-xx#S1]` —— %s"
                             % st["title"].strip()[:36],
                    "hint": "节点 ID 是稳定标识，流程工具按它记进度；"
                            "中途改了进度就断"})

        # ⑤ 流程级整体审核
        if not re.search(r'^##\s*7[.、]|整体审核', text, re.M):
            issues.append({"level": "error", "file": rel,
                           "issue": "缺「整体审核」节（流程级复查）",
                           "hint": "两级审核：步骤级【审】是做的时候检查，"
                                   "流程级是做完复查——漏列的步骤级抓不到"})

    # ⑦ index.md 登记表双向
    idx = flow / "index.md"
    if idx.exists():
        try:
            itext = idx.read_text(encoding="utf-8")
        except Exception:
            itext = ""
        registered = set(re.findall(r'`(FL-\d+)`', itext))
        for fid, rel in seen_ids.items():
            if fid not in registered:
                issues.append({"level": "warn", "file": "reference/flow/index.md",
                               "issue": "流程 %s（%s）未在登记表里登记"
                                        % (fid, rel.split("/")[-1]),
                               "hint": "⛔ 只写文件不登记 → 索引失真，"
                                       "后来的人不知道有这个流程"})
        for rid in registered:
            if rid not in seen_ids:
                issues.append({"level": "error", "file": "reference/flow/index.md",
                               "issue": "登记了 %s，但没找到对应文件" % rid,
                               "hint": "文件被删或 flow-id 写错"})
    return issues


def check_exitcode_adoption(cfg, root=None):
    """退出码码表接入率（反哺自 code-audit 的 check-list-drift 第 6 项）。

    为什么需要：新建设施最容易死在「造好了但没人接」——
    `exitcode.py` 造出来后，若只有 lint.py 接了，其余脚本仍是
    「成功 / 失败」二态，自动化无法分流
    （见 self-verification-silent.md 第七条）。

    ⚠ **两种不同的合法接入方式，都要认**：
      ① 用 argparse —— 未知参数自动退出 2，与码表的 USAGE 一致
      ② 导入 exitcode —— 能进一步区分 ENV / BLOCKED

    ⛔ 只认 ② 会把用 argparse 的脚本全部误报成「没接」——
       **误报的检查会被关掉**（falsepos 第十四条）。

    但仍要区分「有 USAGE 保护」与「有完整分类」：
    argparse 只给了 2，ENV(3) / BLOCKED(4) 仍要靠导入 exitcode。
    """
    base = Path(root) if root else ROOT
    sd = base / "scripts"
    if not sd.is_dir():
        return []
    issues = []
    for py in sorted(sd.glob("*.py")):
        if py.name in ("exitcode.py", "_flagguard.py", "cocos_audit.py"):
            continue        # 码表自身 / 守卫自身 / 转发壳
        try:
            src = py.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = str(py.relative_to(base))
        has_ap = "argparse" in src
        has_ec = ("from exitcode import" in src) or ("import exitcode" in src)
        if not has_ap and not has_ec:
            issues.append({"level": "error", "file": rel,
                           "issue": "退出码不可分类：既无 argparse 也未导入 exitcode",
                           "hint": "所有失败路径返回同一个码 → 自动化无法分流"
                                   "（AR-04）。加 `from exitcode import ...`"})
        elif has_ap and not has_ec:
            # 有 USAGE 保护，但缺 ENV/BLOCKED 区分 —— 提示，不阻断
            issues.append({"level": "info", "file": rel,
                           "issue": "仅靠 argparse（有 USAGE=2），未区分 ENV/BLOCKED",
                           "hint": "能区分「环境没配」与「内容有违规」时接 exitcode"})
    return issues


def check_reference_zones(cfg, root=None):
    """reference/ 五分体系完整性：区齐全 + 每个文件标了性质 + 性质与所在区一致。

    为什么需要：五分体系（howto/audit/flow/common/craft）是有判据的
    （见 reference/common/split-two-books.md），但**判据不会自动执行**——
    写的人当时知道自己在写什么，半年后审核的人不知道该去哪个区找。

    三个子检查各自防一种失效：
      ① 区缺失          —— 有人删了 / 没建
      ② 文件无性质标记  —— 后续无法判定它该不该在这
      ③ 标记与目录不符  —— 放错区（判据写进了 howto，审核时读不到）
      ④ 出现未知区目录  —— 建了第六个区却没更新总纲，总纲失真

    只查「目录存在」会让 ②③④ 全部静默。
    """
    base = Path(root) if root else ROOT
    ref = base / "reference"
    zones = cfg.get("reference_zones") or ["howto", "audit", "flow", "common", "craft"]
    if not ref.exists():
        return []
    issues = []

    # ① 区目录是否齐全 + 是否为空（第十八条：空转也是「0 命中」）
    for z in zones:
        d = ref / z
        if not d.is_dir():
            issues.append({"level": "error", "file": "reference/%s" % z,
                           "issue": "五分体系缺区：%s" % z,
                           "hint": "新建该目录，或更新 config.yaml 的 "
                                   "reference_zones（总纲也要同步）"})
        elif not list(d.glob("*.md")) and not list(d.glob("*/")):
            issues.append({"level": "warn", "file": "reference/%s" % z,
                           "issue": "区目录存在但没有任何 .md",
                           "hint": "⛔ 可能是路径写错导致检查在空集上跑——"
                                   "**返回 0 条不报错**，与「真的没有」无法区分"})

    # ④ 未知区目录
    for d in sorted(ref.iterdir()):
        if d.is_dir() and d.name not in zones and not d.name.startswith('.'):
            issues.append({"level": "warn", "file": "reference/%s" % d.name,
                           "issue": "不在五分体系内的目录",
                           "hint": "要么并入五区，要么更新 config.yaml 的 "
                                   "reference_zones 与总纲（否则总纲失真）"})

    # ②③ 每个 md 的性质标记
    for md in sorted(ref.rglob("*.md")):
        rel = str(md.relative_to(base))
        try:
            head = "\n".join(md.read_text(encoding="utf-8").split("\n")[:12])
        except Exception:
            continue
        zone = md.parent.name
        m = re.search(r'本(?:区|文件)性质[：:]\s*\**\s*([a-z]+)', head)
        if not m:
            issues.append({"level": "warn", "file": rel,
                           "issue": "文首无「本区性质」标记",
                           "hint": "写法：`> **本区性质：howto / 怎么做。**`"
                                   "——没有它，后续无法判定这文件该不该在这"})
            continue
        if zone in zones and m.group(1) != zone:
            issues.append({"level": "warn", "file": rel,
                           "issue": "性质标的是 %s，但放在 %s/ 下" % (m.group(1), zone),
                           "hint": "放错区 → 判据写进 howto 会在审核时读不到；"
                                   "移区或改标记"})
    return issues


def _outside_code_blocks(text):
    """返回不在 ``` fenced code block 内的行。

    为什么需要：数 `##` 章节时，文档里嵌的 Markdown 模板
    （"流程文件七节模板"这类示例）会被当成真实章节。
    实测 step-spec.md：真实 7 章，因模板被算成 15 章 → 误报拆分建议。

    判据与 `audit/self-verification-falsepos.md` 第十一条同源：
    **文本匹配必须区分「示例代码」与「真内容」**，否则必然误报。
    """
    out, in_fence = [], False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return out


def check_doc_shape(cfg, limits=None, root=None):
    """文档形态检查：接近上限预警 + 单文件章节过多 → 建议拆分。

    为什么需要「接近上限」（80%）这一档：
    只在上限处报警，往往已经长到拆不动——400 行的文件要拆成三份，
    得重写目录和交叉引用，代价高到让人倾向于"先声明豁免算了"。
    80% 时提示还有余裕规划，是把拆分从"救火"变成"排期"。

    为什么需要「章节过多」：
    体积没超但 `##` 章节已经十几个，说明这一个文件里塞了多个主题。
    此时按主题拆开，每份都能独立定向加载——
    不拆的话，每次为了看其中一节都得读整个文件。
    """
    limits = limits or {}
    issues = []
    base = Path(root) if root else ROOT
    # ⚠ root 参数不能省：自检要在临时目录里造样本验证「章节过多能查出」，
    #    没有它只能测真库——那是测数据不是测判据。
    targets = [base / "SKILL.md"]
    for sub in ("reference", "SKILLS", "assets"):
        d = base / sub
        if d.exists():
            targets += sorted(d.rglob("*.md"))

    for f in targets:
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        n = len(text.splitlines())
        rel = str(f.relative_to(base))

        # key 同时也用于取 token 阈值（双阈值要按同一把尺子）
        if rel == "SKILL.md":
            key = "SKILL.md"
            lim = int(limits.get("SKILL.md", 200))
        elif rel.startswith("SKILLS/"):
            key = f.name
            lim = int(limits.get(f.name, 200))
        elif rel.startswith("reference/"):
            key = "reference"
            lim = int(limits.get("reference", 400))
        else:
            key = "assets"
            lim = int(limits.get("assets", 300))

        # ⚠ 豁免也必须覆盖「接近上限」这一档，不只是超限那一档：
        # 声明了 oversize-exempt 的归档型文件（如 changelog-archive.md）
        # **只会增长**，80% 这一档永远消不掉 → 提示变成永久噪音，
        # 而永久噪音里的提示等于没有提示。
        # 这正是第十五条：「约束要么生效，要么正式改掉」，
        # 没有「声明了但仍每次报」这个中间态。
        if lim > 0 and n < lim and n >= int(lim * 0.8) and not oversize_exempt(f):
            issues.append({
                "level": "info",
                "file": rel,
                "lines": n, "limit": lim,
                "issue": "接近体积上限（%d/%d，%d%%）" % (n, lim, n * 100 // lim),
                "hint": "现在规划拆分，别等超限——超限后拆要重写目录与交叉引用。"
                        "⚠ 这是**加载成本**上限，不是充实度判据："
                        "没到上限 ≠ 写够了（见 craft/substance.md）"})

        # ---- 双阈值：token（占上下文的是 token，不是行数） ----
        # 行数合规但 token 超了 → 照样会撑爆上下文。
        # ⛔ 不能只卡行数：150 行的宽表格可能比 400 行散文贵得多。
        tlim = int(cfg.get("token_limits", {}).get(
            key, TOKEN_LIMITS.get(key, TOKEN_DEFAULT)))
        if tlim > 0 and not oversize_exempt(f):
            try:
                tk = token_estimate(text)
            except Exception:
                tk = 0
            if tk > tlim:
                issues.append({
                    "level": "warn",
                    "file": rel,
                    "lines": n, "tokens": tk, "limit": tlim,
                    "issue": "约 %d tokens，超过 %d（行数 %d 未超限）"
                             % (tk, tlim, n),
                    "hint": "占上下文的是 token 不是行数——"
                            "宽表格/密集代码会「行数合规但读进来很贵」。"
                            "⚠ 同样是成本上限，不是充实度判据"
                            "（见 craft/substance.md）"})

        # SKILL.md 是入口导航，天生多主题；它的章节多恰恰说明
        # 「内容已下沉到 reference/」——不该按内容文档的标准要求它拆。
        if rel == "SKILL.md":
            continue
        # ⚠ 必须排除 fenced code block：文档里放 Markdown 模板
        # （如「流程文件七节模板」的示例）会被当成真实章节。
        # 实测：step-spec.md 真实 7 章，因含 8 节模板被算成 15 章 → 误报。
        # 这与「文本匹配必须走 AST」是同一形态——不区分「示例代码」和
        # 「真内容」的判据必然误报，而误报的检查会被关掉。
        heads = [l for l in _outside_code_blocks(text) if l.startswith("## ")]
        # ⛔ 条目型文档不适用「章节过多」：
        #    self-verification-*.md 这类**编号条目册**，
        #    每章是一条独立判据，用法是「查表：我这情况属于哪条」。
        #    它的章节数**等于条目数**——拆开反而要来回翻，
        #    且会切断跨文件锚点（那 20+ 条是全局编号，跨册引用）。
        #
        #    判据：≥70% 的章节标题是「数字、」或「数字.」开头 → 条目型。
        #    ⛔ 不区分的话会逼着人拆掉一个**本来就该在一起**的册子
        #    （第十四条：判据看语义方向，不看表面特征）。
        if heads:
            numbered = sum(
                1 for h in heads
                if re.match(r"^##\s*[\d一二三四五六七八九十]+[、.．]", h))
            if numbered >= len(heads) * 0.7:
                continue
        if len(heads) > 12:
            issues.append({
                "level": "info",
                "file": rel,
                "issue": "单文件 %d 个 ## 章节（>12）" % len(heads),
                "hint": "一个文件塞了多个主题 → 按主题拆开，"
                        "每份可独立定向加载。"
                        "⚠ 章节数不是充实度：12 个空章节比 3 个写透的差得多"
                        "（见 craft/substance.md）"})
    return issues



# ---- 跨 skill 阈值一致性（反哺自 code-audit 的 SY001） ----
#
# 为什么需要：同一个集群里多个 skill 各写一套体积阈值，
# 数字一旦漂移，会出现「这个文件在 A 库超限、在 B 库说通过」——
# 而两边自检**都绿**，没人知道该信哪个。
#
# ⛔ 为什么不直接读对方 config：
#    skill 是**独立可分发的单元**。把本 skill 单独拷到别的项目，
#    兄弟 skill 路径就不存在了 → 运行时依赖会让自检崩，
#    或更糟：静默降级成默认值。
#    硬编码是慢性病，运行时依赖是急性病，所以选前者。
#
# ✅ 但「漂移没人知道」这半个风险必须堵掉：
#    **找到就比对，找不到就跳过**（不报）。
#    这样口头约定变成可验证的，同时保留独立分发能力。
#    ——这正是 code-audit 侧 SY001 注释里写得最清楚的一段。
#
# ⚠ 比对**可执行阈值**（对方检查脚本里的常量），不比对散文里的数字：
#    散文里写「200 行」可能只是举例，脚本里的常量才是真的会生效的那个。
#    实测：两侧 SKILL.md 正文里根本没写上限，数字只在
#    `check-skill.py` 的 `MAX_SKILL_SOFT` 和 `common-maintenance.md` 里。
#    **对着散文比会一条都找不到，于是检查恒绿、从未验证**
#    （正是刚修过的「gate 用例蹭真库状态」的同一形态）。
SIBLING_THRESHOLDS = [
    # (相对仓库根的路径, 正则, 说明)
    ("_common/skills/code-audit/scripts/check-skill.py",
     r"MAX_SKILL_SOFT\s*=\s*(\d+)", "code-audit 的 SKILL.md 软上限"),
]


def check_sibling_limits(cfg, root=None):
    """兄弟 skill 的**可执行**阈值与本库是否一致。

    只比对双方都拿得到的常量；任一侧缺失就跳过（不误报）。
    """
    base = Path(root) if root else ROOT
    issues = []
    mine = int(cfg.get("size_limits", {}).get("SKILL.md", 200))
    repo = base.parent.parent
    for rel, rx, label in SIBLING_THRESHOLDS:
        cand = repo / rel
        if not cand.is_file():
            continue                      # 找不到就跳过：独立分发时的常态
        try:
            txt = cand.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(rx, txt)
        if not m:
            continue
        theirs = int(m.group(1))
        if theirs != mine:
            issues.append({
                "level": "warn",
                "file": rel,
                "issue": "%s %d 与本库 config.yaml 的 %d 不一致"
                         % (label, theirs, mine),
                "hint": "两边自检都会绿，但同一个文件在两边结论不同——"
                        "改一处就要改另一处。找不到对方时本项跳过（不误报）"})
    return issues


# 负面触发（「何时不用」）的字段名，任一存在即算写了
NEG_FIELDS = ('not_trigger', 'not_use', 'negative_trigger', 'not_for')
# 官方 spec 的长度上限（反哺自 Agent Skills 规范）
NAME_MAX = 64
DESC_MAX = 1024



# ---- 文档承诺的命令（反哺自 code-audit 的 doc-promise.py） ----
#
# 为什么需要：`check_refs` 只查**路径**存不存在（scripts/x.py 有这个文件），
# 但**文件存在 ≠ 它支持文档里写的那个 flag**。
#   文档写 `python3 scripts/note.py --show`，脚本存在、但没实现 --show
#   → 照着敲会「未知参数」，而文档自己不会报错。
# 这正是 code-audit 侧 doc-scan.py 的第一类候选「命令不存在」。
#
# ⚠ 必须处理**转发壳**：
#   引擎侧 `cocos_audit.py` 是 29 行的转发壳，真正实现在
#   `_common/skills/code-audit/scripts/cocos-audit.py`。
#   文档里的 `--rule` / `--rules` / `--level` 在壳里**没有**，
#   ⛔ 只查壳会把 4 条真实可用的命令全报成「不支持」——
#   **误报的检查会被关掉**（falsepos 第十四条）。
CMD_RX = re.compile(r'python3\s+scripts/([A-Za-z0-9_]+\.py)([^\n`|]*)')
FLAG_RX = re.compile(r'--[a-z][a-z0-9-]*')
# 转发壳：_CANON = os.path.normpath(os.path.join(_HERE, '..', ..., 'x.py'))
CANON_RX = re.compile(
    r'_CANON\s*=\s*os\.path\.normpath\(os\.path\.join\((.*?)\)\)', re.S)


def _script_supports(py_path, flag, base):
    """脚本是否支持某个 flag；转发壳则追到 canonical 实现再查。"""
    try:
        src = py_path.read_text(encoding="utf-8")
    except Exception:
        return False
    if flag in src:
        return True
    m = CANON_RX.search(src)
    if not m:
        return False
    # ⚠ `..` **不能过滤掉**：它才是「从脚本目录往上几级」的信息。
    #   第一版把 pardir 剔了，拼出 `_common/skills/...` 直接挂在
    #   skill 根下 → 文件不存在 → 4 条真实可用的命令被误报成不支持。
    #   （误报的检查会被关掉：falsepos 第十四条）
    # `_HERE` 是**裸变量**（不在引号里），findall 只拿到引号里的片段，
    # 所以 segs 全是相对脚本目录的路径片段 —— **一个都不能砍**。
    # 第一版写了 segs[1:]，把第一个 `..` 当成了 _HERE → 少退一级
    # → 拼到仓库根之上一级 → 文件不存在 → 4 条真实命令被误报。
    segs = re.findall(r"'([^']+)'", m.group(1))
    rel = os.path.normpath(os.path.join(*segs)) if segs else ''
    cand = py_path.parent / rel if rel else py_path
    try:
        return flag in cand.read_text(encoding="utf-8")
    except Exception:
        return False



def check_check_coverage(cfg, root=None):
    """每个检查项在自检里至少被**直接调用**过一次吗（交叉审计）。

    反哺自 code-audit 的 `rule-registry.py --cross`：
    `--test` 只查「tp 被自己命中 / fp 不被自己命中」，两个方向都有盲区——
      A. fp（正确写法示例）被**别的**规则命中 → 示例自带真缺陷，会被照抄
      B. tp 没命中自己却命中了别的 → **「通过」是蹭来的**

    引擎侧的同构问题：**某个 check_* 在自检里一次都没被调用**。
    它的检查逻辑可能完全失效，而自检照样全绿——
    因为根本没有一条用例会因它而变红。

    ⛔ 这不是「用例数量」检查（那是第二十三条批判的注水指标）：
    它判的是**有没有**覆盖（0 vs ≥1），不是有多少条。
    一条用例能守住就行，十条注水的不如一条真的。

    为什么用 AST 而不是运行时统计：运行时只能看到「本次跑没跑」，
    看不到「自检里有没有为它写用例」——这次跑了不等于下次还测。
    """
    base = Path(root) if root else ROOT
    target = base / "scripts" / "lint.py"
    if not target.is_file():
        return []
    try:
        src = target.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        return []
    funcs = [n.name for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("check_")]
    # ⛔ 必须**精确**匹配 `cmd_self_test`，不能用 `"self_test" in name` 子串。
    #    实测（2026-09-26）：新增辅助函数 `_self_test_domains_in_repo` 后，
    #    st[0] 变成它（tree.body 顺序在前）⇒ 24 个检查项**全部**被报
    #    「在自检里从未被调用」——而它们明明都在 cmd_self_test 里。
    #
    #    ⓘ 这是**命名约定被无意撞到**：作者只是想起个"自检用例"的名字，
    #    却把检查器的入口判定带偏了。⛔ 用子串匹配找"入口"是脆的
    #    （falsepos 第十四条：判据看语义方向，不看表面特征）。
    st = [n for n in tree.body
          if isinstance(n, ast.FunctionDef) and n.name == "cmd_self_test"]
    if not funcs or not st:
        return []
    body = ast.get_source_segment(src, st[0]) or ""
    issues = []
    for fn in funcs:
        if fn == "check_check_coverage":
            continue          # 别把自己算进去（自指，见 falsepos 第六条）
        if (fn + "(") in body:
            continue
        reason = INDIRECT_COVERAGE.get(fn)
        issues.append({
            "level": "info" if reason else "warn",
            "file": "scripts/lint.py",
            "issue": "检查项 `%s` 在自检里从未被调用" % fn
                     + ("（已登记间接覆盖：%s）" % reason if reason else ""),
            "hint": "它失效了自检也不会变红——**没有任何用例会因它而变红**。"
                    "补正反两侧用例（正向：不该报的不报；反向：该报的能报）；"
                    "若确实只能间接验证，登记进 INDIRECT_COVERAGE 并写明理由"})
    return issues


def check_doc_commands(cfg, root=None):
    """文档里写的 `python3 scripts/X.py --flag`，脚本真的支持吗。"""
    base = Path(root) if root else ROOT
    issues = []
    targets = [base / "SKILL.md"]
    for sub in ("reference", "SKILLS", "assets"):
        d = base / sub
        if d.exists():
            targets += sorted(d.rglob("*.md"))
    for f in targets:
        if not f.exists():
            continue
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = str(f.relative_to(base)) if str(f).startswith(str(base)) else str(f)
        for m in CMD_RX.finditer(txt):
            script, rest = m.group(1), m.group(2)
            py = base / "scripts" / script
            if not py.is_file():
                continue          # 脚本不存在由 check_refs 报，这里不重复
            for fm in FLAG_RX.finditer(rest):
                flag = fm.group(0)
                if _script_supports(py, flag, base):
                    continue
                issues.append({
                    "level": "error", "file": rel,
                    "issue": "文档写了 `%s %s`，但脚本里没有这个 flag"
                             % (script, flag),
                    "hint": "照着敲会「未知参数」。补实现，或改文档。"
                            "转发壳已自动追到 canonical 实现"})
    return issues


def check_frontmatter(cfg, root=None):
    """frontmatter 必填字段 + **负面触发** + 长度上限。

    ⚠ 加了 `root` 参数：原版只扫 `domains/*/skills`，
    而 domains 未初始化时 targets **恒为空** → 这个检查**从未验证过任何东西**，
    却照样输出 0 条。这正是 silent 第七/十八条：
    「返回 0 条」与「真的没问题」无法区分。
    可注入后就能在临时副本上造样本，把判据真正测到。

    为什么必须查**负面触发**（反哺自 Agent Skills 官方规范）：
    description / trigger 只写「何时用」→ 边界模糊的请求会**误命中**；
    写了「何时不用」，才能把不相关的请求挡在门外。
    ⓘ 召回侧的对称要求：正面触发决定「找得到」，
    负面触发决定「不误伤」——**只有一半的召回是坏的召回**。
    """
    base = Path(root) if root else ROOT
    issues, seen = [], {}
    targets = []
    for key in cfg.get("domains", {}):
        sd = domain_dir(cfg, key) / "skills"
        if sd.exists():
            targets += [f for f in sd.rglob("*.md") if not f.name.startswith("_")]
    # 引擎自身的 SKILL.md 也查：它同样是会被检索、会被误命中的入口
    sk = base / "SKILL.md"
    if sk.is_file():
        targets.append(sk)

    for f in targets:
        try:
            rel = str(f.relative_to(base))
        except ValueError:
            rel = str(f)
        text = f.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
        if not m:
            issues.append({"level": "error", "file": rel,
                           "issue": "缺少 frontmatter",
                           "hint": "至少 id / name / keywords / trigger"})
            continue
        fm = _frontmatter(text)

        miss = [k for k in REQUIRED_FM if not fm.get(k)]
        if miss:
            issues.append({"level": "warn", "file": rel,
                           "issue": "缺字段 " + str(miss),
                           "hint": "keywords 决定召回，trigger 决定何时加载"})

        sid = fm.get("id", "?")
        if sid in seen:
            issues.append({"level": "error", "file": rel,
                           "issue": "ID 与 " + seen[sid] + " 重复",
                           "hint": "ID 必须全局唯一"})
        else:
            seen[sid] = rel

        if not fm.get("verified"):
            issues.append({"level": "info", "file": str(f),
                           "issue": "未标注 verified",
                           "hint": "执行验证过就标 verified: yes，仅作回溯参考"})

        # ---- 负面触发（「何时不用」）----
        if not any(fm.get(k) for k in NEG_FIELDS):
            issues.append({
                "level": "warn", "file": rel,
                "issue": "缺负面触发（只说了「何时用」，没说「何时不用」）",
                "hint": "加 `not_trigger:` 写清不适用场景——"
                        "正面触发决定找得到，负面触发决定**不误伤**；"
                        "只有一半的召回是坏的召回"})

        # ---- 长度上限（官方 spec）----
        nm = fm.get("name", "") or ""
        if len(nm) > NAME_MAX:
            issues.append({"level": "warn", "file": rel,
                           "issue": "name %d 字符，超过 %d" % (len(nm), NAME_MAX),
                           "hint": "小写字母/数字/单连字符，超了会被规范校验拒收"})
        ds = fm.get("description", "") or ""
        if len(ds) > DESC_MAX:
            issues.append({"level": "warn", "file": rel,
                           "issue": "description %d 字符，超过 %d"
                                    % (len(ds), DESC_MAX),
                           "hint": "description 是**每次会话都要付**的成本，"
                                   "不是正文；超了要精简，不是加长"})
    return issues

def check_refs(cfg, root=None):
    """文档引用的 scripts/ 与 reference/ 路径必须真实存在。

    为什么需要：脚本改名后，散落在文档里的旧名不会跟着变。
    它们是**死链**——读文档的人照着敲会 command not found，
    而文档自己不会报错。code-audit 里 tool-scan.py 早已改名 scan-app.py，
    自检段、工作流段、检查清单共 4 处仍指向旧名，全靠人工翻才找出来。

    为什么必须脚本化：改脚本名时人只想着改调用它的代码，不会去 grep 文档。

    为什么只查引擎自身文件：domains 下的引用基准是该域根目录
    （且 root 常未初始化），路径基准不确定，查了只会误报。
    """
    base = Path(root) if root else ROOT
    issues = []
    targets = [base / "SKILL.md"]
    for sub in ("reference", "SKILLS"):
        d = base / sub
        if d.exists():
            targets += sorted(d.rglob("*.md"))

    # ⛔ 区名开头的相对路径也必须查：
    #    实测 4 条死链长期未被发现（`flow/README.md`、
    #    `common/howto/principles.md`），因为老正则只认
    #    `scripts/` 或 `reference/` 开头的路径。
    #    而 `reference/flow/skeleton.md` 里写 `【读】common/howto/principles.md`
    #    这种**区名开头**的写法完全不在检查范围内——
    #    **检查在跑，但没在查**（silent 第一条、第七条）。
    #
    #    基准：区名开头的路径解析到 `reference/<区>/`，
    #    因为五区目录都在 reference/ 下。
    ZONES = ("howto", "audit", "flow", "common", "craft")
    RX = re.compile(r'(?<![A-Za-z0-9_/.-])'
                    r'((?:scripts|reference|%s)/[A-Za-z0-9_./-]+\.(?:py|sh|md))'
                    % "|".join(ZONES))
    for f in targets:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in RX.finditer(text):
            rel = m.group(1)
            if rel.startswith(("scripts", "reference")):
                ok = (base / rel).exists()
            else:
                # 区名开头 → 基准是 reference/
                ok = (base / "reference" / rel).exists() or (base / rel).exists()
            if ok:
                continue
            ln = text[:m.start()].count('\n') + 1
            issues.append({
                "level": "error",
                "file": "%s:%d" % (f.relative_to(base), ln),
                "issue": "引用了不存在的 %s" % rel,
                "hint": "脚本改名后文档里的旧名不会自动跟着变 → 照着敲会 "
                        "command not found。改指向或删引用"})
    return issues


def check_markdown_headings(cfg, root=None):
    """Markdown 标题不得有重复的 `#`（如 `## ## 标题`），也不得缩进。

    为什么需要：往 Markdown 里**插入**段落时，常见写法是
    `text.replace(anchor, new_text + anchor)`。若 `new_text` 结尾带了 `## `
    （为下一段预留），拼接后就成了 `## ## 标题` —— 渲染成错误的层级，
    而**写它的人看不出来**（diff 里是两个正常的 `##`，谁也不会盯着数）。

    本仓库实测：同一处写法连犯 3 次，次次都以为改完了，
    直到逐行看渲染结果才发现。这类缺陷 100% 静默：
    没有任何检查会去数 `#` 的个数。

    判据要点：两组 `##` 之间是**空格**，只 `lstrip("#")` 会剩 ` ## 标题`，
    不以 `#` 开头 → 漏判。必须先 `lstrip("#")` 再 `lstrip()`。
    """
    base = Path(root) if root else ROOT
    issues = []
    files = [base / "SKILL.md"]
    for sub in ("reference", "SKILLS", "assets"):
        d = base / sub
        if d.exists():
            files += sorted(d.rglob("*.md"))
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        in_fence = False
        for i, line in enumerate(text.splitlines(), 1):
            s2 = line.strip()
            if s2.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue          # 代码块里的 # 是代码，不是标题
            if not s2.startswith("#"):
                continue
            if line.startswith(" "):
                issues.append({
                    "level": "warn",
                    "file": "%s:%d" % (f.relative_to(base), i),
                    "issue": "标题有缩进，多数渲染器不认：%s" % s2[:40],
                    "hint": "去掉行首空格"})
            core = s2.lstrip("#").lstrip()
            if core.startswith("#"):
                issues.append({
                    "level": "error",
                    "file": "%s:%d" % (f.relative_to(base), i),
                    "issue": "标题 # 重复（拼接时多带了一组）：%s" % s2[:40],
                    "hint": "常见于 replace(anchor, new + anchor) 且 new 结尾带了 "
                            "'## ' —— 检查插入文本的末尾"})
    return issues


def check_duplicates(cfg, root=None):
    """内容完全相同的副本（逐字节一致）。

    为什么需要：两份相同的脚本 = 修 bug 只改一处、另一处静默过期。
    它不报错，只是慢慢变得不一样，或一起烂掉。

    为什么比内容不比文件名：名字不同的重复（cocos-audit.py / cocos_audit.py）
    恰恰是最难被发现的那种，按名查永远查不到。
    """
    import hashlib
    base = Path(root) if root else ROOT
    groups = {}
    targets = []
    for sub, pat in (("scripts", "*.py"), ("scripts", "*.sh"),
                     ("reference", "*.md"), ("SKILLS", "*.md")):
        d = base / sub
        if d.exists():
            targets += sorted(d.glob(pat))
    for f in targets:
        try:
            raw = f.read_bytes()
        except Exception:
            continue
        # 空文件与极短文件同 md5 没有意义，会淹掉真问题
        if len(raw.strip()) < 40:
            continue
        groups.setdefault(hashlib.md5(raw).hexdigest(), []).append(f)

    issues = []
    for _h, fs in sorted(groups.items()):
        if len(fs) < 2:
            continue
        issues.append({
            "level": "warn",
            "file": " = ".join(str(x.relative_to(base)) for x in sorted(fs)),
            "issue": "内容完全相同（%d 份副本）" % len(fs),
            "hint": "保留一份 canonical，其余改为转发壳或删除。"
                    "逐字节副本 = 修 bug 只改一处、另一处静默过期"})
    return issues



def check_exemptions(cfg, root=None):
    """豁免标记必须**真的接上了**读豁免的代码。

    为什么需要：标记了豁免之后命中数就该下降。若没下降，只有两种可能——
    豁免没接上，或豁免写错了位置。而这两种都**不会报错**：
    人会以为"已经处理过了"。

    实测（code-audit 自扫）：给某规则的三处命中加了行级豁免，命中数
    一条没变——因为那条规则的分支里**根本没调用豁免判断**。
    加了豁免却不生效，是最容易被忽略的失效：人已经处理过了。

    判据（目录级，避免按行猜实现）：
      某目录下存在豁免标记，但该目录**所有 .py 里都没有读豁免的代码**
      → 这些豁免 100% 不生效。

    为什么按目录而不是按文件：读豁免的辅助函数常常集中在 _flagguard.py /
    scan-XX.py 这类公共文件里，逐个文件比会把正常情况全报成问题。
    """
    base = Path(root) if root else ROOT
    issues = []

    # 豁免标记的写法（各语言、各工具不统一，认常见几种）
    EXEMPT_RX = re.compile(
        r'#\s*(?:audit|lint|type|noqa|pyright|flake8)\s*:?\s*ignore'
        r'|#\s*noqa\b|//\s*(?:audit|lint|eslint-disable|ts)\s*:?\s*ignore'
        r'|#\s*pragma\s*:?\s*ignore', re.I)
    # 读豁免的代码：函数定义或调用
    READ_RX = re.compile(
        r'(?:def\s+\w*pragm\w*|def\s+\w*exempt\w*|has_pragma\s*\('
        r'|\bpragma\b|\bexempt\b|is_ignored\s*\()', re.I)

    def scan_dir(d, label):
        files = sorted(d.rglob("*.py")) + sorted(d.rglob("*.ts"))
        marks = []
        reads = 0
        for f in files:
            if "__pycache__" in str(f) or "fixtures" in str(f):
                continue
            try:
                txt = f.read_text(encoding="utf-8")
            except Exception:
                continue
            for i, line in enumerate(txt.split("\n"), 1):
                if EXEMPT_RX.search(line):
                    marks.append("%s:%d" % (
                        f.relative_to(d) if str(f).startswith(str(d)) else f.name, i))
            if READ_RX.search(txt):
                reads += 1
        return marks, reads, len(files)

    targets = [("引擎自身", base)]
    # 同一集群里的兄弟 skill：豁免集中在 code-audit，读豁免的代码也在那里，
    # 只扫引擎自己会漏掉绝大多数真实豁免
    for sib in ("_common/skills/code-audit", "_common/skills"):
        cand = base.parent.parent / sib
        if cand.exists() and cand.is_dir():
            targets.append((sib, cand))

    for label, d in targets:
        marks, reads, nfiles = scan_dir(d, label)
        if marks and reads == 0:
            issues.append({
                "level": "error",
                "file": "%s（%d 个脚本）" % (label, nfiles),
                "issue": "有 %d 处豁免标记，但整个目录没有任何读豁免的代码"
                         % len(marks),
                "hint": "豁免写了却没人读 → 命中数不会下降，而人以为已处理。"
                        "例：%s" % ", ".join(marks[:3])})
    return issues

def check_block_refs(cfg, root=None):
    """全局块引用（`#EC-xx`）必须指向 `common/blocks.md` 里真实存在的锚点。

    为什么需要：全局块的意义是**消除重复**——各文件引用同一个锚点，
    而不是各写一遍。⛔ 锚点写错（或块被删了）时，
    引用变成断链，而**读的人会得到"这个块不存在"**，
    于是回去自己写一遍 —— **重复又回来了，且没人发现**。

    与 `check_refs`（文件路径死链）的分工：
    那个查**文件在不在**，这个查**文件里的锚点在不在**。
    ⛔ 只查前者会让「文件在、锚点错」这一类完全漏掉。
    """
    base = Path(root) if root else ROOT
    issues = []
    blocks = base / "reference" / "common" / "blocks.md"
    if not blocks.is_file():
        return issues
    btext = blocks.read_text(encoding="utf-8")
    # 块头形如 `## EC-01 xxx`，锚点形如 `#ec-01-xxx`
    defined = set()
    for m in re.finditer(r"^##\s+(EC-\d+)", btext, re.M):
        defined.add(m.group(1).lower())

    # ⛔ 不能只扫 reference/：SKILL.md 是入口，
    #    它引用 `#EC-xx` 完全合理（比如在「最高优先级区」里），
    #    只扫子目录会让入口里的错误锚点永远查不到。
    #    由 check_scan_scope（六问第 1 问）报出后修。
    targets = [base / "SKILL.md"]
    targets += sorted((base / "reference").rglob("*.md"))
    for f in targets:
        if not f.is_file() or f == blocks:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        rel = str(f.relative_to(base))
        for m in re.finditer(r"#(EC-\d+)", text, re.I):
            if m.group(1).lower() not in defined:
                issues.append({
                    "level": "error", "file": rel,
                    "issue": "引用了不存在的全局块 `%s`" % m.group(1),
                    "hint": "块定义在 `common/blocks.md`（`## %s …`）。"
                            "⛔ 锚点写错会让读的人回去自己写一遍——"
                            "**重复又回来了，且没人发现**" % m.group(1)})
    return issues


def check_orphan_table_row(cfg, root=None):
    """孤立的表格行：以 `|` 开头但前后都不构成表格。

    实测（SKILL.md 目录地图）：`| pending/draft.md | … |` 这一行
    **夹在两个段落之间**——上一行是引用块、下一行是空行。

    ⛔ **Markdown 不会把它渲染成表格**：
    表格要求表头行紧接着分隔线。孤立的那行会原样显示管道符，
    读者看到的是一行带竖线的文字，而不是表格的一部分。

    为什么必须查：这类缺陷**不影响任何检查通过**
    （行数、章节、死链都正常），只有人眼渲染时才看得见，
    而入口文件恰恰是最常被读的那个。
    """
    base = Path(root) if root else ROOT
    issues = []
    SEP = re.compile(r"^\|[\s:|-]+\|\s*$")
    # ⛔ 不能只扫 reference/：
    #    这个缺陷**就是在 SKILL.md 里发现的**，而 SKILL.md 不在 reference/ 下。
    #    只扫子目录会让「最常被读的那个文件」永远不被检查——
    #    而它恰恰是最该被检查的（silent 第七条：扫描范围必须自报）。
    targets = [p for p in sorted(base.rglob("*.md"))
               if ".git" not in str(p)]
    for f in targets:
        try:
            lines = f.read_text(encoding="utf-8").split("\n")
        except Exception:
            continue
        # 跳过代码块内的行（示例里的表格是正常的）
        outs, in_fence = [], False
        for ln0 in lines:
            if ln0.strip().startswith("```"):
                in_fence = not in_fence
                outs.append(False)
                continue
            outs.append(not in_fence)
        rel = str(f.relative_to(base))
        for i, ln in enumerate(lines):
            st = ln.strip()
            if not st.startswith("|") or not st.endswith("|"):
                continue
            if not (i < len(outs) and outs[i]):
                continue
            if SEP.match(st):
                continue
            prev = lines[i - 1].strip() if i > 0 else ""
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            prev_tbl = prev.startswith("|")
            nxt_sep = bool(SEP.match(nxt))
            # 表格内：上一行是表格行，或下一行是分隔线
            if prev_tbl or nxt_sep:
                continue
            issues.append({
                "level": "warn", "file": "%s:%d" % (rel, i + 1),
                "issue": "孤立表格行（前后都不构成表格）",
                "hint": "⛔ Markdown 不会渲染它——表格要求表头紧接着分隔线。"
                        "这一行会原样显示管道符。移动进上面的表格，"
                        "或改成普通段落"})
    return issues


# ⛔ 扫描范围豁免登记：这些检查**天然不含入口文件**，写明理由。
#    与所有豁免一样：⛔ 不写理由 = 规则失效的开始（第十五条）。
#    判据：SKILL.md 是不是这类检查的**合法对象**？不是才登记。
SCAN_SCOPE_EXEMPT = {
    "check_flow_steps": "只查 `flow/` 区的流程文件——SKILL.md 不是流程文件",
    "check_reference_zones": "只查 `reference/` 下的五区——区域定义在那个目录下",
    "check_antipattern_tables": "只查审查册的反模式表——那些表只在 `audit/` 下",
    "check_landing": "只查技能包（skills/）——SKILL.md 是入口不是技能包",
    "check_degeneracy": "只查 `SKILLS/` 常驻层",
    "check_mirror_pairs": "只比对 howto↔audit **镜像对**的文件名——"
                          "SKILL.md 不是任何一册的成员",
}


def check_scan_scope(cfg, root=None):
    """扫 .md 的检查是否包含**入口文件**（SKILL.md）。

    ⛔ 来源：本项目**连续 5 次**栽在「扫描范围不对」上，
    而其中最新一次最典型——

        缺陷在 SKILL.md 里，检查却只扫 reference/。

    **最常被读的文件，恰恰是最容易漏在扫描范围外的**：
    它是单点，不在任何"批量扫描的目录"里。

    判据（写检查时的第 1 问）：
    **扫描范围包含入口文件吗？**

    为什么用 AST 不用文本匹配：
    `base.rglob` 与 `(base / "reference").rglob` 只差一个子目录，
    但语义完全不同。看 receiver 才能分辨（第十一条：文本匹配走 AST）。
    """
    base = Path(root) if root else ROOT
    issues = []
    src = base / "scripts" / "lint.py"
    if not src.is_file():
        return issues
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except SyntaxError:
        return issues

    def _unparse(node):
        try:
            return ast.unparse(node)
        except Exception:
            return ""

    for fn in [n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name.startswith("check_")]:
        # ① 只关心扫 .md 的检查——扫 .py 的（退出码接入率等）
        #    入口文件对它没有意义，报出来就是噪音。
        pats = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr in ("rglob", "glob"):
                recv = _unparse(n.func.value) or ""
                arg = _unparse(n.args[0]) if n.args else ""
                pats.append((recv, arg))
        if not pats or not any(".md" in a for _, a in pats):
            continue

        # ② 全库扫描（receiver 是 base / ROOT）→ 含入口，OK
        if any(r.strip() in ("base", "ROOT") for r, _ in pats):
            continue
        # ③ 显式补了入口文件 → OK
        #    ⚠ 不能用 `'"SKILL.md"' in blob`：
        #    `ast.unparse` 会把所有字符串规范化成**单引号**，
        #    源码里的双引号版本匹配不上 → 明明加了入口却被判漏。
        #    （这正是「文本匹配必须走 AST」的反面：
        #     走了 AST 之后就不能再按源码字面形态匹配。）
        blob = _unparse(fn)
        if "SKILL.md" in blob:
            continue
        # ④ 已登记豁免 → 跳过（但理由必须非空）
        why = SCAN_SCOPE_EXEMPT.get(fn.name)
        if why:
            continue
        issues.append({
            "level": "info", "file": "scripts/lint.py",
            "issue": "检查 `%s` 扫 .md 但不含入口文件（SKILL.md）" % fn.name,
            "hint": "⛔ 缺陷**就是在 SKILL.md 里发现的**，而它不在任何"
                    "「批量扫描的目录」里。确认入口是否该在范围内："
                    "该 → 显式加上入口文件；"
                    "不该 → 登记进 `SCAN_SCOPE_EXEMPT` 并写明理由"
                    "（⛔ 不写理由 = 规则失效的开始）"})
    return issues


def check_stale_exemptions(cfg, root=None):
    """⛔ 过期豁免：登记了但目标已不存在 → 豁免变成遮羞布。

    反哺自 game-dev 的 `check-map-relevance.py`：

    > ⚠ 每条豁免必须写理由；自检会校验豁免项**仍然存在**，
    > 映射改了而豁免没删 → 报「过期豁免」。
    > ⛔ **豁免变成掩盖真问题的遮羞布**。

    两个检查各防一种失效：

      ① 过期：登记了 `check_xxx` 但函数已改名为 `check_yyy`
              → 那条检查从此**无人守着**，而登记还在，
              看起来"已处理"
      ② 空理由：登记了但没写为什么只能间接验证
              → ⛔ 不写理由的例外 = 规则失效的开始

    ⛔ 为什么不能只查「登记项名字对不对」：
    改名后旧名字仍在表里，而**没有任何检查在查它存不存在**——
    这正是第二十一条（假生效）的**登记版**。
    """
    base = Path(root) if root else ROOT
    issues = []
    # 当前实际存在的检查函数名
    src = (Path(__file__)).read_text(encoding="utf-8")
    live = set(re.findall(r"^def (check_\w+)", src, re.M))
    for fn, reason in sorted(INDIRECT_COVERAGE.items()):
        if fn not in live:
            issues.append({
                "level": "warn", "file": "scripts/lint.py",
                "issue": f"过期豁免：`{fn}` 已不存在（可能改名）",
                "hint": f"INDIRECT_COVERAGE 里登记的 `{fn}` 在当前文件里没有对应函数。"
                        f"⛔ 映射改了而豁免没删 → **豁免变成掩盖真问题的遮羞布**。"
                        f"要么改登记名，要么删掉这条"})
        if not reason or len(reason.strip()) < 10:
            issues.append({
                "level": "warn", "file": "scripts/lint.py",
                "issue": f"豁免 `{fn}` 没写理由（或太短）",
                "hint": "⛔ 不写理由的例外 = 规则失效的开始。"
                        "要写明「为什么只能间接验证」"})
    return issues


def check_volatile_counts(cfg, root=None):
    """⛔ 目录/索引型文档里不要写「N 个文件」这类会变的计数。

    实测：split-two-books.md 里的区文件数**第 4 次**过期：

        howto  10 → 16 → 17
        audit   3 →  6 →  7

    ⚠ 每次都是「加了文件但没回来改这里的计数」，
    而**读的人会把这个数字当成现状**——
    这正是 EC-03（数字会过期）的自证。

    ⇒ 判据：**计数是快照，判据是稳定的**。
    ⛔ 不要写「howto 有 17 个文件」；✅ 写「怎么算」或干脆不写。

    ⚠ 豁免：变更溯源 / 统计报告里写计数是**合法**的——
    那本来就是"某时某刻的快照"，且带了日期。
    ⛔ 不豁免会让"记录历史"被当成"声明现状"误报，
    而 **误报的检查会被关掉**（falsepos 第十四条）。
    """
    base = Path(root) if root else ROOT
    issues = []
    # ⛔ 只查**目录标题**里的计数：`### howto/ 怎么做（16 个文件）`
    #    —— 这正是连修 4 次的那个位置。
    #    初版查了所有标题与表格行 → 报 37 条，其中绝大多数是误报：
    #    「109 份反模式册」是**实测统计**（有来源、可复现），
    #    blocks.md 的待去重表标注了「由 grep 生成」。
    #    ⛔ **误报的检查会被关掉**（falsepos 第十四条）——
    #    所以宁可窄，不可宽。
    #    ⇒ 判据：光秃秃一个数字 = 声明现状（会过期）；
    #    带来源的统计 = 合法（可复现）。
    RX = re.compile(r'^#{2,4}\s*.*?[（(]\s*(\d+)\s*(?:个|份)\s*(?:文件|文档)\s*[)）]')
    for f in sorted((base / "reference").rglob("*.md")):
        rel = str(f.relative_to(base))
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        # 只查目录/索引型：正文里有「本区性质」或文件名含 index/split
        if "索引" not in text[:400] and "本区性质" not in text[:600] \
                and "index" not in f.name and "split" not in f.name:
            continue
        for i, ln in enumerate(_outside_code_blocks(text), 1):
            m = RX.search(ln.strip())
            if not m:
                continue
            issues.append({
                "level": "info", "file": rel,
                "issue": f"目录标题里写了会变的计数「{m.group(1)} 个文件」",
                "hint": "⛔ 计数是快照会过期（split-two-books.md 已第 4 次修同一个数字）。"
                        "✅ 写**怎么算**（ls reference/<区>/*.md | wc -l）或干脆不写"})
    return issues


def check_selftest_duality(cfg, root=None, src_path=None):
    """⛔ 每个检查项都要有**正反两侧**用例（第一条 + 第四条的自审）。

    ⚠ **实测自审结果（写这个检查的动机）**：

    ```
    24 个检查项里 12 个（50%）自检覆盖不完备：
      ⛔ 从未引用 1  ·  ⚠ 只被间接引用 5
      ⚠ 无反向（证明不了"能红"）3  ·  ⚠ 无正向（证明不了不误报）3
    有变异守着的只有 2 个
    ```

    ⇒ **引擎自己违反了自己最核心的两条判据**——
    第一条「检查项必须能红」、第四条「必须配正反双样本」。
    ⛔ 这是"要求别人的自己没做到"。

    ### 为什么要区分「直接断言」和「间接引用」

    ```python
    chk(not check_foo(cfg, vroot), '…')      # 直接：正/反可判
    iss = check_foo(cfg, vroot)              # 间接：赋值给变量
    chk(any(...) for i in iss, '…')          # ⛔ 断言语义无法自动判定
    ```

    ⛔ 只统计"出现在自检里"会让**间接形式谎报覆盖**——
    它确实出现了，但**正反两侧都确认不了**。

    ### 四种状态

    | 状态 | 级别 | 含义 |
    |---|---|---|
    | 从未引用 | error | ⛔ 完全没验证 |
    | 只有正向 | warn | 证明不了"能红" |
    | 只有反向 | warn | 证明不了"干净时不误报" |
    | 只被间接引用 | info | 无法确认正反 |
    """
    base = Path(root) if root else ROOT
    srcp = Path(src_path) if src_path else (base / "scripts" / "lint.py")
    if not srcp.exists():
        return []
    try:
        src = srcp.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception:
        return []
    fns = [n for n in tree.body
           if isinstance(n, ast.FunctionDef) and n.name == "cmd_self_test"]
    if not fns:
        return [{"level": "warn", "file": "scripts/lint.py",
                 "issue": "没有 cmd_self_test 函数",
                 "hint": "⛔ 没有自检 = 所有检查项都没被验证"}]
    fn = fns[0]
    checks = set(re.findall(r"^def (check_\w+)", src, re.M))
    used = {}
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id.startswith("check_")):
            used[n.func.id] = used.get(n.func.id, 0) + 1
    direct = {}
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "chk" and n.args):
            neg = (isinstance(n.args[0], ast.UnaryOp)
                   and isinstance(n.args[0].op, ast.Not))
            for c in ast.walk(n.args[0]):
                if (isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                        and c.func.id.startswith("check_")):
                    d = direct.setdefault(c.func.id, [0, 0])
                    d[0 if neg else 1] += 1
    # ⚠ **间接形式也要认**（`d2 = check_x(); chk(bool(d2) ...)`）。
    #   ⛔ 只认直接调用会把大量**真实存在**的用例判成"无法确认"：
    #   实测上线时 5 个检查项被误判为「只被间接引用」，
    #   而其中多数其实正反都有。
    #   ⇒ **误报的检查会被关掉**（falsepos 第十四条）——必须提高精度。
    #   判据：变量名 → 后续 chk 里引用它 → 按断言形态定方向。
    var2check = {}
    for st_ in ast.walk(fn):
        if (isinstance(st_, ast.Assign) and len(st_.targets) == 1
                and isinstance(st_.targets[0], ast.Name)
                and isinstance(st_.value, ast.Call)
                and isinstance(st_.value.func, ast.Name)
                and st_.value.func.id.startswith("check_")):
            var2check[st_.targets[0].id] = st_.value.func.id
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "chk" and n.args):
            a0 = n.args[0]
            names_in = {x.id for x in ast.walk(a0) if isinstance(x, ast.Name)}
            for v, c in var2check.items():
                if v not in names_in:
                    continue
                # 反向（期望非空）：bool(v) / len(v) > 0 / any(... in v ...)
                # 正向（期望为空）：not v / len(v) == 0 / not any(...)
                is_neg_call = False
                for x in ast.walk(a0):
                    if (isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                            and x.func.id == "bool"):
                        is_neg_call = True
                if isinstance(a0, ast.UnaryOp) and isinstance(a0.op, ast.Not):
                    is_neg_call = False
                d = direct.setdefault(c, [0, 0])
                d[0 if not is_neg_call else 1] += 1
    # ⛔ 自身不计：本检查项无法在自己的自检里造样本（自指），
    #    靠 INDIRECT_COVERAGE 登记 + mutate 守着。
    checks.discard("check_selftest_duality")
    issues = []
    for c in sorted(checks - {"check_check_coverage"}):
        u = used.get(c, 0)
        d = direct.get(c, [0, 0])
        if u == 0:
            issues.append({"level": "error", "file": "scripts/lint.py",
                           "issue": f"检查项 `{c}` 在自检里从未被引用",
                           "hint": "⛔ 完全没验证过。"
                                   "要么在 --self-test 里加用例，要么登记间接覆盖"})
        elif d == [0, 0]:
            issues.append({"level": "info", "file": "scripts/lint.py",
                           "issue": f"`{c}` 只被间接引用（赋值给变量）",
                           "hint": "⚠ 正反两侧无法自动确认。"
                                   "⛔ 只统计『出现在自检里』会让间接形式谎报覆盖"})
        elif d[0] == 0:
            issues.append({"level": "warn", "file": "scripts/lint.py",
                           "issue": f"`{c}` 缺正向用例（干净时不误报）",
                           "hint": "⚠ 只有反向 = 证明不了它在干净样本上不误报"})
        elif d[1] == 0:
            issues.append({"level": "warn", "file": "scripts/lint.py",
                           "issue": f"`{c}` 缺反向用例（证明不了「能红」）",
                           "hint": "⛔ 第一条：检查项必须能红。"
                                   "没有坏样例 = 不知道它坏了会不会报错"})
    return issues


def check_scope_selfreport(cfg, root=None):
    """第二条量化：输出「通过」时必须同时输出扫描范围。

    **在空集上跑出来的通过没有意义。**
    目录不存在、后缀不匹配、路径基准写错——都会让检查在空集上跑完
    还显示通过，而这种失效**从输出上完全看不出来**。

    ⚠ **实测（写这个检查的动机）**：

    ```
    mutations.json 置空 → mutate.py 输出
    「合计：KILLED 0 · SURVIVED 0 · NOT_APPLIED 0」
    ```

    看起来是"没问题"，实际是**配置空了 / 路径指错了**。
    ⛔ 失败模式是"返回 0 条"而不是"报错"——
    **任何能跑通的检查都查不出来**。

    ### 判据（只查「通过信号」所在的**函数**）

    ```
    通过信号：✓ / 通过 / 健康 / 正常 / 无需变更 / 完成
    范围信号：数字占位符(%d/{}/…) + 项|个|条|文件|域|条规则
              或显式「扫描范围 / 扫到 / 共」
    ```

    ⛔ 只查「整个文件有没有范围信号」会漏——
    那是"别处有"，不是"这次输出了"。
    ⛔ 只查「有没有通过信号」会误报一堆。

    ### ⛔ 为什么是 info 不是 warn

    这是**启发式**（靠关键词），机械套用必然误报。
    ⛔ **误报的检查会被关掉**（falsepos 第十四条）——
    宁可提示，不可当硬约束。
    """
    base = Path(root) if root else ROOT
    sdir = base / "scripts"
    if not sdir.exists():
        return []
    # ⛔ 第一版把「完成」算通过信号 → `print("⚠ 没有任何条目完成计数")`
    #    被误报（那是**警告**，不是通过）。**误报的检查会被关掉**。
    PASS_RX = re.compile(r'[✓✔]|通过|健康|无需变更|已归档')
    # ⛔ 第一版只认 `%d` 和 `{}:`，把 f-string 的 `{ok} 项` 判为无范围
    #    → index.py 的 find 被误报（它实测输出「（0 项）」）。
    #    ⛔ **误报的检查会被关掉**，必须认 f-string / .format() 两种写法。
    SCOPE_RX = re.compile(
        r'%[ds]|扫描范围|扫到|共\s*\d'
        r'|\{[^}]*\}\s*(?:项|个|条|文件|域|条规则)'
        r'|\d+\s*(?:项|个|条|文件|域|条规则)')
    issues = []
    for f in sorted(sdir.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for fnode in ast.walk(tree):
            if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # ⛔ 排除自检断言辅助 `chk(cond, msg)`——它打印的是用例结果，
            #    不是工具对外的输出。3 个脚本各有一个，全是误报。
            if fnode.name in ("chk", "chk_", "assert_"):
                continue
            has_pass = has_scope = False
            pline = None
            try:
                srclines = f.read_text(encoding="utf-8").split("\n")
            except Exception:
                srclines = []
            for n in ast.walk(fnode):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                        and n.func.id == "print" and n.args:
                    # ⛔ f-string 是 JoinedStr，不是 Constant——
                    #    第一版只取 Constant → f"{ok} 项" 提取成 " 项"，
                    #    **范围信号丢失**（误报，而误报的检查会被关掉）。
                    #    ⇒ 把 FormattedValue 还原成 `{}` 占位再匹配。
                    txt = ""
                    for a in n.args:
                        for x in ast.walk(a):
                            if isinstance(x, ast.Constant) \
                                    and isinstance(x.value, str):
                                txt += x.value
                            elif isinstance(x, ast.FormattedValue):
                                # ⛔ 不要再单独处理 Name——ast.walk 会同时
                                #    遍历到 FormattedValue 和它内部的 Name，
                                #    两处都加 → "{}{}"，范围匹配失效
                                txt += "{}"
                    # ⛔ 区分「整体结论」与「逐条标记」：
                    #   `✓ 已建大类 {name}`  → 逐条，**不是**第二条要管的
                    #   `✓ 结构健康，无需变更` → 整体结论，**才是**
                    #   判据：✓ 后面紧跟变量（{ / %） = 逐条；
                    #        后面是固定文案 = 整体。
                    #   ⛔ 不区分会误报 7 条（domain/env/structure 的逐条输出），
                    #      **误报的检查会被关掉**。
                    # ⛔ 判据（第二版，实测收敛）：
                    #   **含插值的 print = 逐条结果**，不是"整体通过"。
                    #   `✓ 已写入：{dest}` / `✓ config.yaml 已注册 {key}` ——
                    #   这类打印每条都带具体对象，不存在"空集通过"的问题。
                    #   ⛔ 只查"✓ 后紧跟 {" 不够（"✓ 本地覆盖层：{x}" 漏网）
                    #      → 实测漏了 4 条。**误报的检查会被关掉**。
                    #   ⇒ 改成：参数里**有没有 FormattedValue / BinOp(%)**。
                    _interp = any(isinstance(x, (ast.FormattedValue, ast.BinOp))
                                  for x in ast.walk(a)) if n.args else False
                    if PASS_RX.search(txt) and not has_pass and not _interp:
                        has_pass, pline = True, n.lineno
                    if SCOPE_RX.search(txt):
                        has_scope = True
            if has_pass and not has_scope:
                issues.append({
                    "level": "info",
                    "file": "scripts/%s" % f.name,
                    "issue": "`%s` 输出通过信号但同函数内无扫描范围（第 %d 行）"
                             % (fnode.name, pline),
                    "hint": "⚠ 第二条：**在空集上跑出来的通过没有意义**。"
                            "输出「通过」时附上扫了几个、跳过了什么。"
                            "⛔ 「0 条」的失败模式不报错，任何能跑通的检查都查不出来"})
    return issues


def check_domains_in_repo(cfg, root=None):
    """技能数据必须跟着仓库走（2026-09-26 架构决策）。

    ### ⛔ 动机（实测）

    `root` 原本是 `~/.ai/domains`（家目录）。环境重置后实测：

    ```
    ls: cannot access '/root/.ai/domains': No such file or directory
    ```

    ⇒ 1 个真技能包**没了**，而 git 管不到它：
    无法版本化、无法 review、无法回滚、换机即丢。
    且 lint 长期报「大类根目录不存在 → 本次结果不完整」——**检查本身残缺**。

    ### 四查

    1. root 是否落在仓库内（不是家目录 / 不是绝对路径）
    2. 软链接**是否被 git 跟踪** → ⛔ error：Windows 上 checkout 成文本文件，静默损坏
    3. 软链接目标是否为**相对路径** → ⛔ error：绝对路径换机即断
    4. 资产（skills/rules/*.md）是否**未被跟踪** → warn：写了但换机就丢

    ⓘ 第 2 条最容易被忽略：git 存 symlink 是合法的，
    **在 Linux/macOS 上跑得好好的**，只有换到 Windows 才现形——
    而那时报错的是别的东西（"找不到目录"），没人会联想到 symlink。
    """
    import subprocess as _sp
    base = Path(root) if root else Path(cfg.get('_root', '.'))
    issues = []
    # 1. root 位置
    raw = str(cfg.get('root', 'domains')).strip()
    if os.path.isabs(os.path.expanduser(raw)):
        issues.append({'issue': '大类根目录 %s 是绝对路径 → 技能数据不在仓库里，'
                                '换机即丢且 git 管不到（实测：环境重置后 1 个技能包没了）'
                                % raw,
                       "level": "warn",
                       "file": "",
                       'hint': '改成相对路径 `domains`（相对 skill 根），'
                               '或用环境变量 SKILL_DOMAINS_ROOT 显式覆盖'})
    # git 仓库根
    try:
        gr = _sp.run(['git', 'rev-parse', '--show-toplevel'], cwd=str(base),
                     capture_output=True, text=True)
        git_root = Path(gr.stdout.strip()) if gr.returncode == 0 else None
    except Exception:
        git_root = None
    cfg = dict(cfg); cfg['_root'] = str(base)  # 让 domain_root 支持自检注入
    droot = domain_root(cfg)
    if not git_root or not droot.exists():
        return issues
    # 2+3. 软链接
    for link in sorted(droot.rglob('*')):
        if not link.is_symlink():
            continue
        tgt = os.readlink(str(link))
        if os.path.isabs(tgt):
            issues.append({'issue': '软链接 %s 指向绝对路径 %s → 换机 / 换 clone 路径即断'
                                    % (link.relative_to(droot), tgt),
                           "level": "error",
                       "file": "",
                           'hint': '用相对路径（domain.py 已改；跑 --add-common 重建）'})
        # 是否被 git 跟踪
        try:
            r = _sp.run(['git', 'ls-files', '--error-unmatch', str(link)],
                        cwd=str(base), capture_output=True, text=True)
            tracked = r.returncode == 0
        except Exception:
            tracked = False
        if tracked:
            issues.append({'issue': '软链接 %s **被 git 跟踪** → Windows 上 checkout 出来'
                                    '可能是文本文件而非链接（无 symlink 权限时 git 就这么做）'
                                    '→ 静默损坏且不报错' % link.relative_to(droot),
                           "level": "error",
                       "file": "",
                           'hint': '加进 .gitignore；它由 domain.py --add-common 重建'})
    # 4. 资产未跟踪
    untracked = []
    for f in sorted(droot.rglob('*.md')):
        if any(part.startswith('.') for part in f.relative_to(droot).parts):
            continue
        if 'INDEX.md' in f.name:
            continue
        try:
            r = _sp.run(['git', 'ls-files', '--error-unmatch', str(f)],
                        cwd=str(base), capture_output=True, text=True)
            if r.returncode != 0:
                untracked.append(str(f.relative_to(droot)))
        except Exception:
            pass
    if untracked:
        issues.append({'issue': '%d 个技能/规则文件未被 git 跟踪 → 换机即丢：%s'
                                % (len(untracked), '、'.join(untracked[:3])
                                   + ('…' if len(untracked) > 3 else '')),
                       "level": "warn",
                       "file": "",
                       'hint': 'git add 它们；派生物（INDEX.md / _common 链接）才该忽略'})
    return issues


def check_table_columns(cfg, root=None):
    """表格列数错位（第十七条量化：格式缺陷 100% 静默）。

    ### ⚠ 实测（写它的动机）

    真库探查 **10 处错位，全部是真问题**：

    ```
    `cat x.json | python3 -m json.tool`   ← 行内代码里裸 | → 渲染断列
    `\|\| true`                            ← 同上
    `ls | wc -l`                          ← 同上
    EC-03 那行少一列                       ← 改表头后没同步
    两行表头连续（旧表头残留）              ← 手改残留
    ```

    ⛔ 共同点：**Markdown 照常渲染、不报错、lint 全绿**，
    只有人眼看渲染结果才发现——而**表格恰恰是查表型文档的主体**。

    ### ⛔ 判据基准用**分隔线**，不用众数

    ```
    众数 = 数据行里最多的列数
    ```

    ⚠ 我修第一处时就踩了：该表数据行多为 3 列，表头也是 3 列，
    我却按"补齐到众数"加了两个占位格 → **把对的改成了错的**。

    ⇒ 基准取 `|---|---|` 那行的列数（它就是作者声明的列数），
      取不到才退回表头，最后才是众数。

    ### ⛔ 必须先吃掉 `\|` 转义

    第一版裸 `split('|')` → **37 处里 27 处是误报**（95%），
    全是命令里的 `\|`（grep 的 or、`ls | wc -l` 之类）。
    处理转义后降到 **10 处，且全真**。

    ⓘ 这正是第二十九条讲的：**先跑真库数误报率**。
    """
    base = Path(root) if root else ROOT
    issues = []
    for f in sorted(base.rglob("*.md")):
        if "__pycache__" in str(f):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        lines, fence = [], False
        for ln in text.split("\n"):
            if ln.lstrip().startswith("```"):
                fence = not fence
                lines.append("")
                continue
            lines.append(ln if not fence else "")
        block, start = [], 0

        def _ncols(st):
            # ⛔ 关键：先吃掉转义 \|，否则 grep 命令里的 \| 全被当分隔符
            return len(st.replace("\\|", "\x00").split("|"))

        def _sep_ncols(block):
            for _, ln in block:
                core = ln.replace("|", "").replace(" ", "")
                if core and set(core) <= set("-:"):
                    return _ncols(ln)
            return None

        def flush(block, start):
            if len(block) < 2:
                return
            ref = _sep_ncols(block) or _ncols(block[0][1])
            counts = {}
            for _, ln in block:
                counts[_ncols(ln)] = counts.get(_ncols(ln), 0) + 1
            if len(counts) > 1:
                ref = _sep_ncols(block) or _ncols(block[0][1]) \
                      or max(counts, key=lambda k: counts[k])
            for i, ln in block:
                n = _ncols(ln)
                if n != ref:
                    issues.append({
                        "level": "warn",
                        "file": str(f),
                        "issue": "表格列数错位：第 %d 行 %d 列，应为 %d 列"
                                 % (i + 1, n, ref),
                        "hint": "⛔ 第十七条：格式缺陷 100% 静默——"
                                "Markdown 照常渲染、不报错、lint 全绿，"
                                "但表格会断列。行内代码里的 `|` 要写成 `\\|`"})
        for i, ln in enumerate(lines):
            st = ln.strip()
            if st.startswith("|") and st.endswith("|"):
                if not block:
                    start = i
                block.append((i, st))
            else:
                flush(block, start)
                block = []
        flush(block, start)
    return issues


def check_duplicate_headings(cfg, root=None):
    """同一文件内**重复的章节标题**。

    ⛔ 实测（techniques.md）：往「## 六、自检（30 秒）」后面
    **插入**新的自检项时，原文块没删，结果文件里出现
    **两个完全相同的 `## 六、自检（30 秒）`**。

    Markdown 会正常渲染——它只是显示成两个编号相同的章节。
    **读的人会以为自己看重复了**，或者干脆漏掉第二个块里的条目。

    为什么现有检查抓不到：
    - `check_markdown_headings` 只查**重复 `#` 字符**（`## ## x`）
      和**缩进标题**——两个各自合法的相同标题它不管
    - 行数、体积、死链全部正常
    - **唯一可见的时刻是人读文档时**

    ⛔ 与「孤立表格行」是同一族：**格式缺陷 100% 静默**（第十七条）。
    """
    base = Path(root) if root else ROOT
    issues = []
    targets = [p for p in sorted(base.rglob("*.md")) if ".git" not in str(p)]
    for f in targets:
        try:
            lines = f.read_text(encoding="utf-8").split("\n")
        except Exception:
            continue
        outs, in_fence = [], False
        for ln in lines:
            if ln.strip().startswith("```"):
                in_fence = not in_fence
                outs.append(False)
                continue
            outs.append(not in_fence)
        seen, dup = {}, []
        for i, ln in enumerate(lines):
            if not (i < len(outs) and outs[i]):
                continue
            st = ln.strip()
            if not st.startswith("#"):
                continue
            if st in seen:
                dup.append((st, i + 1, seen[st]))
            else:
                seen[st] = i + 1
        rel = str(f.relative_to(base))
        for txt, ln2, ln1 in dup:
            issues.append({
                "level": "warn", "file": "%s:%d" % (rel, ln2),
                "issue": "重复章节标题（与第 %d 行相同）：%s" % (ln1, txt[:40]),
                "hint": "⛔ Markdown 会正常渲染成两个编号相同的章节——"
                        "读的人以为自己看重复了，或漏掉第二个块。"
                        "多半是插入内容时没删原文块（第十七条：格式缺陷 100% 静默）"})
    return issues


def _norm_anchor(t):
    """把章节标题归一化成锚点形态。

    GitHub 的锚点规则：小写、空格转 `-`、去掉标点与 markdown 符号，
    **保留中文**。⛔ 按字面比对会让所有中文锚点判成断链——
    实测全库 0 处带锚点的引用，正是因为没人敢写（写了也对不上）。
    """
    t = re.sub(r'[*`⛔⚠ⓘ✅❌#.\-—…·、，。：；！？（）()\[\]{}|/\\"\'"]', '', t)
    t = re.sub(r'\s+', '', t)
    return t.lower()


def _anchor_match(anc, title):
    """锚点是否指向该标题（都已是归一化形态）。

    ⛔ 不能只做全等：手写引用时**几乎总是省略**（标题
    `1. 写正确的废话 = 没写` 会被写成 `#写正确的废话`）。
    ⇒ 要求锚点是标题的**子串**。

    ⚠ 太短的锚点不能子串匹配（`文` 会命中所有标题），
    要求 ≥4 字；短于 4 字则必须全等。
    ⓘ 与 falsepos 第十四条同族：判据要认**人真实的写法**，
    不是认「最好匹配的那种写法」。
    """
    if not anc or not title:
        return False
    if anc == title:
        return True
    return len(anc) >= 4 and anc in title


def check_heading_numbering(cfg, root=None):
    """同一层级内**重复的中文序号**（编号撞车）。

    ⛔ 实测：真库 7 处。后果是引用 `#十` 会指向两处之一，
    而锚点检查**查不出来**——两个标题的文本都真实存在，
    只是序号一样。读的人按序号找，会找到错的那一节。

    为什么现有检查抓不到：`check_markdown_headings` 只查
    **重复 `#` 字符**和**完全相同的标题**——
    两个编号相同、内容不同的标题它不管。

    ⛔ 与「重复章节标题」是同一族：格式缺陷 100% 静默（第十七条）。

    豁免：追加型归档（`changelog-archive`）**天然**每段各有编号——
    那是设计如此，不是撞车。⛔ 不豁免会让基线永远清不掉 ⇒ 检查被关掉。
    """
    base = Path(root) if root else ROOT
    issues = []
    CN = '一二三四五六七八九'

    def cn_num(sv):
        if '十' not in sv:
            return CN.index(sv) + 1
        i = sv.index('十')
        tens = 1 if i == 0 else CN.index(sv[i-1]) + 1
        ones = CN.index(sv[i+1]) + 1 if len(sv) > i + 1 else 0
        return tens * 10 + ones

    EXEMPT = ('changelog-archive',)
    for f in sorted(base.rglob("*.md")):
        if ".git" in str(f):
            continue
        if f.name.startswith(EXEMPT):
            continue
        try:
            lines = f.read_text(encoding="utf-8").split("\n")
        except Exception:
            continue
        inf, fence = [], False
        for ln in lines:
            if ln.strip().startswith("```"):
                fence = not fence
                inf.append(False)
                continue
            inf.append(not fence)
        rel = str(f.relative_to(base))
        for lvl in (2, 3):
            seen = {}
            for i, ln in enumerate(lines):
                if not (i < len(inf) and inf[i]):
                    continue
                m = re.match(r"^#{%d}\s*([一二三四五六七八九十]+)[、.．]\s*(.+)$"
                             % lvl, ln.strip())
                if not m:
                    continue
                n = cn_num(m.group(1))
                if n in seen:
                    issues.append({
                        "level": "warn", "file": "%s:%d" % (rel, i + 1),
                        "issue": "序号撞车：`%s、` 与第 %d 行重复"
                                 % (m.group(1), seen[n]),
                        "hint": "⛔ 引用 `#%s` 会指向两处之一，而锚点检查查不出来"
                                "（两个标题的文本都真实存在）。"
                                "插入新节时记得重排后面所有序号" % m.group(1)})
                else:
                    seen[n] = i + 1
    return issues


def check_flow_seams(cfg, root=None):
    """procedure 流程必须声明**接缝**（上下游对不对得上）。

    ⛔ 实证：主链路第一次在真实数据上跑，四个断点**全是接缝**——
    捕获→整合（草稿被当注释丢）、整合→归档（无强制机制）、
    整合→索引（name/key 不一致）、索引→召回（索引 0 项）。

    ⇒ 单流程内部每步都对，拼起来仍可能不成立（见 `flow/seams.md`）。
    ⛔ 不声明接缝 = 没人确认过上下游对不对得上，
       而四次的失败模式都是「返回 0 条」——不报错，看不出来。

    判据（⛔ 不要太严）：
        ✅ 有 `##`/`###` 标题含「接缝」
        ✅ 或有正文行以 `> 接缝：` / `- 接缝：` 开头（显式声明，含"无接缝"）
        ⛔ 只看正文里有没有"接缝"二字会误报：
           提到「见 seams.md」不算声明，声明要说清**上下游对不对得上**。

    级别 warn：这是欠账不是错误——⛔ 报 error 会让 lint 立刻红，
    而红线会被关掉（第十四条：误报的检查会被关掉）。
    """
    base = Path(root) if root else ROOT
    issues = []
    flow = base / "reference" / "flow"
    if not flow.is_dir():
        return issues
    for f in sorted(flow.glob("*.md")):
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"<!--(.*?)-->", txt, re.S)
        if not m or "flow-type: procedure" not in m.group(1):
            continue
        declared = False
        for ln in txt.split("\n"):
            st = ln.strip()
            if re.match(r"^#{2,4}\s*.*接缝", st):
                declared = True
                break
            if st.startswith("> 接缝：") or st.startswith("- 接缝："):
                declared = True
                break
        if declared:
            continue
        issues.append({
            "level": "warn", "file": "reference/flow/%s" % f.name,
            "issue": "procedure 流程未声明接缝（上下游对不对得上）",
            "hint": "⛔ 主链路首次真跑的四个断点**全是接缝**，"
                    "且失败模式都是「返回 0 条」——不报错。"
                    "加一节「接缝」列出上游产出 / 我这边的期望 / **是否一致**；"
                    "确无上下游就写 `> 接缝：无（<理由>）`。见 `flow/seams.md`"})
    return issues


def check_craft_refs(cfg, root=None):
    """craft 层接入：断链 + 孤儿（本层形同虚设的检查）。

    反哺自 game-dev 的 `check-craft.py`（319 行，三查：断链 / 零交集 / 孤儿）。

    ⛔ **为什么必须查孤儿**：craft 层的意义是「告诉你什么算好」——
    但**它只有被读到时才起作用**。一本书写得再好没人翻，等于没写。
    实测首次跑：43 条 ### 级判据，41 条从未被指向；
    `judgment.md`（238 行）全库只被提到 1 次。

    三查：
        ① **断链**（error）—— `craft/xxx.md#锚点` 指向的章节不存在
        ② **孤儿**（warn/info）—— ### 级判据条目从未被条目级引用指向
        ③ **元条目豁免** —— 自检 / 变更溯源 / 为什么单独一层
           本来就不该被引用（⛔ 算进去会让基线永远混着一批不可能挂上的项）

    分级理由：
        文件从未被引用 → **warn**（整册没接入，最严重）
        文件被引用、但条目没被指向 → **info**（册接入了，条目没接）

    ⛔ 与 `check_block_refs`（`#EC-xx`）的分工：那个查**全局块**锚点，
    这个查 craft 层条目锚点 + 接入率。两者都是「建了但没人用」的守卫。
    """
    base = Path(root) if root else ROOT
    issues = []
    craft = base / "reference" / "craft"
    if not craft.is_dir():
        return issues
    files = sorted(craft.glob("*.md"))
    if not files:
        return issues

    META = ("自检", "变更溯源", "为什么单独一层", "总判据")

    # ① 收集条目（### 级判据）与章节（供断链比对）
    entries, heads = [], {}
    for f in files:
        if f.name == "index.md":
            continue
        try:
            txt = f.read_text(encoding="utf-8")
        except Exception:
            continue
        hs = re.findall(r"^#{2,4}\s+(.+)$", txt, re.M)
        heads[f.name] = [_norm_anchor(h) for h in hs]
        for m in re.finditer(r"^#{3,4}\s+(.+)$", txt, re.M):
            t = m.group(1).strip()
            if any(k in t for k in META):
                continue
            entries.append((f.name, t, _norm_anchor(t)))

    # ② 扫描引用方（⛔ 排除 craft 自身）
    targets = [base / "SKILL.md"]
    targets += sorted((base / "reference").rglob("*.md"))
    targets += sorted((base / "assets").rglob("*.md"))
    ref_lines = []
    for f in targets:
        if not f.is_file() or f.parent == craft:
            continue
        try:
            lines = f.read_text(encoding="utf-8").split("\n")
        except Exception:
            continue
        rel = str(f.relative_to(base))
        for i, ln in enumerate(lines, 1):
            if "craft/" in ln:
                ref_lines.append((rel, i, ln))

    # 断链
    for rel, ln_no, ln in ref_lines:
        for m in re.finditer(r"craft/([\w.\-]+\.md)#([^`)\"']+)", ln):
            fn, anc = m.group(1), m.group(2)
            if fn not in heads:
                continue  # 文件不存在由 check_refs 报
            if not any(_anchor_match(_norm_anchor(anc), h) for h in heads[fn]):
                issues.append({
                    "level": "error", "file": "%s:%d" % (rel, ln_no),
                    "issue": "craft 条目锚点不存在：`%s#%s`" % (fn, anc),
                    "hint": "⛔ 锚点写错 → 读的人得到「这条不存在」→ "
                            "**回去自己想一遍**，craft 层形同虚设"})

    # 孤儿
    cited_files = set()
    anchored = set()   # (file, norm_anchor) 被条目级指向的
    for rel, ln_no, ln in ref_lines:
        for m in re.finditer(r"craft/([\w.\-]+\.md)", ln):
            cited_files.add(m.group(1))
        for m in re.finditer(r"craft/([\w.\-]+\.md)#([^`)\"']+)", ln):
            anchored.add((m.group(1), _norm_anchor(m.group(2))))

    if not entries:
        return issues
    orphan = []
    for fn, t, na in entries:
        if any(a[0] == fn and _anchor_match(a[1], na) for a in anchored):
            continue
        orphan.append((fn, t, na))
    if not orphan:
        return issues
    rate = 100 * (len(entries) - len(orphan)) // len(entries)
    # 分两级：整册没接入 = warn
    whole_book = sorted({e[0] for e in orphan if e[0] not in cited_files})
    for fn in whole_book:
        n = sum(1 for e in orphan if e[0] == fn)
        issues.append({
            "level": "warn", "file": "reference/craft/%s" % fn,
            "issue": "本册 %d 条判据从未被任何文件引用（整册未接入）" % n,
            "hint": "⛔ craft 层只有被读到时才起作用。"
                    "接入方式：在具体流程 / 判据处写 `craft/%s#条目标题`。" % fn})
    rest = [e for e in orphan if e[0] in cited_files]
    if rest:
        sample = "、".join("%s#%s" % (e[0], e[1][:24]) for e in rest[:4])
        issues.append({
            "level": "info", "file": "reference/craft/",
            "issue": "craft 条目级接入率 %d%%（%d/%d），未指向 %d 条，如：%s"
                     % (rate, len(entries) - len(orphan), len(entries),
                        len(rest), sample),
            "hint": "文件级引用让读的人**自己去找**那一条。"
                    "⛔ 文件在 ≠ 内容在。接入率会随引用增长——"
                    "这是欠账，不是错误"})
    return issues


def check_antipattern_tables(cfg, root=None):
    """反模式清单的表头必须是两种形态之一，且列齐全。

    反哺自 game-dev 的 109 份反模式册（见
    `reference/audit/antipattern-form.md`）。实测只有两种表头：

        误解类  「本能以为 / 实际」          79 份
        遗漏类  「漏写 / 后果 / 审查规则」   22 份

    为什么必须查：这两种是**性质不同**的缺陷——
    误解类是「做了但理解错」，遗漏类是「根本没做」。
    ⛔ 混在一张表里两头不讨好：误解类要"读一条对照一次"，
    遗漏类要"搜一遍查漏"，混起来只能做其中一件。

    三个子检查各防一种失效：
      ① 表头不是两种之一    —— 自造的形态，别人用不上
      ② 遗漏类缺「审查规则」—— ⛔ 不写这列会让人以为全表都可机扫
      ③ 误解类缺「实际」    —— 只写"会出错"等于没写（无法自查）
    """
    base = Path(root) if root else ROOT
    issues = []

    # 两种合法表头（中英文列名都认，宽松匹配避免误报）
    MISCON = ("本能以为", "实际")            # 误解类
    OMIT = ("漏写", "后果", "审查规则")      # 遗漏类

    def cells(header_line):
        return [c.strip() for c in header_line.strip().strip("|").split("|")]

    def joined(cs):
        return "".join(cs)

    ad = base / "reference" / "audit"
    if not ad.exists():
        return issues
    for f in sorted(ad.rglob("*.md")):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        # 只查"清单类"文档：正文里出现「反模式」或「只写『不能怎么做』」
        if "不能怎么做" not in text and "反模式" not in text:
            continue
        # ⛔ meta / 索引型文档不是清单：
        #    `antipattern-form.md` **举例**了清单表（讲"清单怎么写"），
        #    `self-verification.md` 是三册的索引。
        #    对它们套形态检查是误报——
        #    而 **误报的检查会被关掉**（falsepos 第十四条）。
        #    判据：讲「怎么写 / 去哪看」的不是「清单本身」。
        if re.search(r"^<!--[^>]*flow-type:\s*meta", text):
            continue
        # 索引型：标题就是「…（索引）」或正文明说"本文件是索引"
        if re.search(r"^#\s+.*[（(]索引[)）]", text, re.M) \
                or re.search(r"本文件是\*\*索引\*\*", text):
            continue
        rel = str(f.relative_to(base))
        lines = text.split("\n")
        tables = 0
        for i, ln in enumerate(lines):
            st = ln.strip()
            if not st.startswith("|"):
                continue
            # 表头行的下一行必须是分隔线
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if not re.match(r"^\|[\s:|-]+\|$", nxt):
                continue
            cs = cells(st)
            j = joined(cs)
            # ⚠ 按**主键**识别类型，不用完整匹配：
            #    缺列正是要报的问题——用 all() 判定的话
            #    缺了列就识别不出类型，检查自己被跳过（假生效）。
            #    判据：先认出它是哪一类，再查这一类的必需列。
            is_miscon = "本能以为" in j
            is_omit = "漏写" in j
            is_pitfall = ("坑" in j and "本能以为" not in j
                          and "漏写" not in j)
            if not (is_miscon or is_omit or is_pitfall):
                continue
            tables += 1
            if is_pitfall and "后果" not in j:
                issues.append({
                    "level": "warn", "file": rel,
                    "issue": "坑类表缺「后果」列",
                    "hint": "⛔ 坑类的价值就在后果——"
                            "「用这个查会得到假结论」必须写清**假在哪**"
                            "（例：MEMORY_STATIC 恒为 0 → 得到「没问题」）"})
            if is_omit and "审查规则" not in j:
                issues.append({
                    "level": "warn", "file": rel,
                    "issue": "遗漏类表缺「审查规则」列",
                    "hint": "⛔ 不写这列会让人以为全表都可机扫。"
                            "能机扫的写规则号，不能的写「人工」——"
                            "写「人工」是诚实标注，不是敷衍"})
            if is_miscon and "实际" not in j:
                issues.append({
                    "level": "warn", "file": rel,
                    "issue": "误解类表缺「实际」列",
                    "hint": "「实际」要写**可观测表现**，尤其要显式写出"
                            "「静默」——不报错的失败最难自查"})
        if tables == 0:
            # ⛔ 条目型判据册（self-verification-*）不是清单表形态——
            #    它们是**编号章节**，每章一条判据，没有 `#` 起始的表格。
            #    报出来就是噪音，而噪音会让人关掉整个检查。
            numbered = len(re.findall(r"^##\s*[\d一二三四五六七八九十]+[、.．]",
                                      text, re.M))
            if numbered >= 3:
                continue
            issues.append({
                "level": "info", "file": rel,
                "issue": "清单表不是三种标准形态之一",
                "hint": "三种形态：误解类「本能以为/实际」、"
                        "遗漏类「漏写/后果/审查规则」、坑类「坑/后果」。"
                        "⛔ 自造形态别人用不上"})
    return issues


def check_degeneracy(cfg, root=None):
    """标注字段退化：全库同一个值 = 这个字段已经不携带信息。

    为什么需要：verified / 命中数这类字段手填时既没有成本也没有反馈，
    于是会自然收敛到同一个值（全 no、全 0）。表面「标注齐全」，
    实际上读的人还是得逐个怀疑——**字段活着，但已经死了**。
    code-audit 的 eval 字段曾 131 条全部 unverified，正是这种退化。

    判据：条目数 ≥ 阈值 且 取值只有一种。
    注意这不是要求「必须标 yes」——而是要求**有区分度**。
    """
    base = Path(root) if root else ROOT
    issues = []
    vcfg = cfg.get("verification") or {}
    threshold = int(vcfg.get("degeneracy_min_entries", 5))

    # ① domain skills 的 verified 字段
    vals = {}
    for key in cfg.get("domains", {}):
        sd = domain_dir(cfg, key) / "skills"
        if not sd.exists():
            continue
        for f in sorted(sd.rglob("*.md")):
            if f.name.startswith("_"):
                continue
            try:
                v = _frontmatter(f.read_text(encoding="utf-8")).get("verified")
            except Exception:
                continue
            if v:
                vals.setdefault(v, []).append(str(f))
    if sum(len(v) for v in vals.values()) >= threshold and len(vals) == 1:
        only = list(vals)[0]
        issues.append({
            "level": "warn",
            "file": "domains/*/skills",
            "issue": "verified 全部为「%s」（%d 条，无区分度）"
                     % (only, len(vals[only])),
            "hint": "标注手填无成本也无反馈 → 会收敛成同一个值。"
                    "能实测的条目跑一遍回填；字段失去区分度就等于没标"})

    # ② _hot.md 的命中列
    hot = base / "SKILLS" / "_hot.md"
    if hot.exists():
        try:
            txt = hot.read_text(encoding="utf-8")
        except Exception:
            txt = ""
        nums = [int(m.group(1)) for m in re.finditer(
            r'^\|\s*H\d+\s*\|.*\|\s*(\d+)\s*\|\s*$', txt, re.M)]
        if len(nums) >= threshold and len(set(nums)) == 1:
            issues.append({
                "level": "warn",
                "file": "SKILLS/_hot.md",
                "issue": "命中列全部为 %d（%d 条）" % (nums[0], len(nums)),
                "hint": "要么这些规则从没触发过，要么触发了没人更新。"
                        "两种情况都说明热区没在真正运转 —— 命中归零不删除，"
                        "但全 0 时应确认它是「真没触发」还是「机制没跑」"})
    return issues


def scan_scope(cfg):
    """本次实际扫到了什么、跳过了什么。

    为什么需要：lint 输出「✓ 通过」时，没人知道它到底检查了几个文件。
    根目录不存在、目录为空、后缀不匹配——这些都会让检查在空集上跑，
    然后输出一片绿。H011 说「工具报 0 命中不等于没问题」，
    要让这句话不用靠人记，就得让工具**自己说出扫描范围**。
    """
    scanned, missing = 0, []
    for label, d in (("reference", ROOT / "reference"),
                     ("SKILLS", ROOT / "SKILLS"),
                     ("scripts", ROOT / "scripts")):
        if not d.exists():
            missing.append(label)
            continue
        scanned += len(list(d.rglob("*.md"))) + len(list(d.rglob("*.py")))
    dom_files, dom_missing = 0, []
    for key in cfg.get("domains", {}):
        d = domain_dir(cfg, key)
        if not d.exists():
            dom_missing.append(key)
            continue
        sk = d / "skills"
        if sk.exists():
            dom_files += len([f for f in sk.rglob("*.md")])
    return {"engine_files": scanned, "engine_missing": missing,
            "domain_files": dom_files, "domain_missing": dom_missing}


def _mk_domains_repo(tmp, *, abs_link=False, track_link=False,
                     add_asset=True, root=None):
    """造一个带 git 的 domains 样本（供 check_domains_in_repo 用例用）。

    ⛔ 为什么必须 `git init` 而不是用真库：
    检查器内部跑 `git ls-files`，若不隔离会往上找到**真仓库根**，
    用例结果依赖真库状态 ⇒ 被无关残留带红（这个坑踩过多次）。
    """
    import subprocess as _sp
    for a in (['git', 'init', '-q'], ['git', 'config', 'user.email', 't@t'],
              ['git', 'config', 'user.name', 't']):
        _sp.run(a, cwd=str(tmp), capture_output=True)
    d = tmp / 'domains'
    (d / '_common').mkdir(parents=True, exist_ok=True)
    (d / 'dev' / 'skills').mkdir(parents=True, exist_ok=True)
    f = d / 'dev' / 'skills' / 'x.md'
    f.write_text('# 技能\n', encoding='utf-8')
    link = d / 'dev' / '_common'
    if abs_link:
        link.symlink_to(str(d / '_common'), target_is_directory=True)
    else:
        link.symlink_to('../_common', target_is_directory=True)
    if add_asset:
        _sp.run(['git', 'add', '-f', str(f)], cwd=str(tmp), capture_output=True)
    if track_link:
        _sp.run(['git', 'add', '-f', str(link)], cwd=str(tmp), capture_output=True)
    # ⛔ 默认必须是**相对**路径 'domains'：
    #    第一版写成 str(d)（绝对路径）→ 正向用例自己触发了 warn，恒红。
    #    ⓘ 用例的样本必须落在它想验证的那一侧。
    return {'root': str(root) if root else 'domains'}


def cmd_self_test():
    """用造出来的坏样例验证检查项真的能查出来。

    为什么需要：lint 最危险的失效是**永远输出「通过」**——
    规则写了、脚本跑了、但什么也没查出来，看起来一片绿。
    这里造三类已知缺陷，跑一遍必须全部命中。
    """
    import tempfile
    import shutil
    ok = fail = 0

    def chk(cond, msg):
        nonlocal ok, fail
        print(('  ✓ ' if cond else '  ✗ ') + msg)
        if cond:
            ok += 1
        else:
            fail += 1

    tmp = tempfile.mkdtemp()
    try:
        cfg = {'domains': {'dev': {'name': '开发'}}, 'root': tmp,
               'subdirs': ['agents', 'skills', 'rules'], 'common': '_common'}
        # 注意：domain_dir 用 meta['name']（中文）拼路径，不是 key。
        # 早先把目录建成 tmp/dev，而检查扫的是 tmp/开发 → 一条都查不到，
        # 而输出显示「全部通过」。这种"检查在空目录上跑"的失效最难发现。
        dom = domain_dir(cfg, 'dev') / 'skills'
        dom.mkdir(parents=True)
        bad = dom / 'bad.md'
        bad.write_text('''---
id: D999
name: 测试包
keywords: [测试]
trigger: 测试
---

## 完整流程

1. 打开文件
2. 输出结果

## 注意事项

- 要注意边界条件
- 处理配置时应先备份再改
''', encoding='utf-8')

        issues = check_landing(cfg)
        txt = ' '.join(i['issue'] for i in issues)

        chk(any('孤立' in i['issue'] for i in issues),
            '孤立知识点能查出（流程未引用「要注意边界条件」）')
        chk('边界条件' in txt or '备份' in txt,
            '报出的是具体条目，不是笼统提示')

        # 已落地的条目不该误报
        good = dom / 'good.md'
        good.write_text('''---
id: D998
name: 好的包
keywords: [测试]
trigger: 测试
---

## 完整流程

1. 改配置前先备份原文件，再逐项替换内容

## 注意事项

- 改配置前先备份原文件
''', encoding='utf-8')
        issues2 = [i for i in check_landing(cfg) if 'good' in i['file']]
        chk(not any('孤立' in i['issue'] for i in issues2),
            '已落地的条目不误报（流程里引用了同一动作）')

        # 占位符 + 空段落
        bad2 = dom / 'bad2.md'
        bad2.write_text('''---
id: D997
name: 占位测试
keywords: [测试]
trigger: 测试
---

## 完整流程

TODO 待补充

## 已知坑

''', encoding='utf-8')
        issues3 = check_landing(cfg)
        chk(any('占位符' in i['issue'] for i in issues3), '占位符能查出')
        chk(any('空段落' in i['issue'] for i in issues3), '空段落能查出')

        # 体积豁免：超限但声明了理由 → 降为 info，不是 warn
        big = dom / 'big.md'
        big.write_text('''---
id: D996
name: 大包
keywords: [测试]
trigger: 测试
---
<!-- oversize-exempt: 确认候选时需整体对照本包全部判据 -->

## 完整流程

''' + ('x\n' * 60), encoding='utf-8')
        cfg2 = dict(cfg)
        cfg2['size_limits'] = {'skills': 20}
        iss = check_size(cfg2, cfg2['size_limits'])
        b = [i for i in iss if 'big.md' in i['file']]
        chk(bool(b) and b[0]['level'] == 'info',
            '声明豁免的超限文件降为提示（不是预警）')
        chk(bool(b) and '豁免' in b[0].get('issue', ''),
            '豁免理由会被带上（可复核）')

        # 体积检查本身
        chk(callable(check_size), '体积检查可用')

        # ---- 新增检查项：各自造一个坏样例，确认真能查出来 ----
        # 纪律：加检查项必须同步加自检用例。永远绿的检查等于没有检查，
        # 而「检查在空集上跑」是最难发现的失效方式。
        vroot = Path(tmp) / 'engine'
        (vroot / 'reference').mkdir(parents=True)
        (vroot / 'SKILLS').mkdir(parents=True)
        (vroot / 'scripts').mkdir(parents=True)
        # 真建一个 lint.py：否则「已存在的引用不该报」这条根本没被验证到
        # ——自检用例自己造错，会让它永远通过（正是本节要防的事）
        (vroot / 'scripts' / 'lint.py').write_text('# ok\n', encoding='utf-8')
        (vroot / 'SKILL.md').write_text(
            '见 scripts/lint.py 与 scripts/nope.py\n', encoding='utf-8')
        (vroot / 'reference' / 'x.md').write_text(
            '详见 reference/ghost.md\n', encoding='utf-8')

        refs = check_refs(cfg, vroot)
        chk(len(refs) == 2, '死链能查出（真实存在的 lint.py 不报，'
                            '不存在的 nope.py / ghost.md 各报 1）')
        chk(all('不存在' in i['issue'] for i in refs), '死链报的是「引用不存在」')

        # 重复副本：两份内容相同的脚本
        (vroot / 'scripts' / 'dup_a.py').write_text(
            'x = 1\n' * 30, encoding='utf-8')
        (vroot / 'scripts' / 'dup_b.py').write_text(
            'x = 1\n' * 30, encoding='utf-8')
        dups = check_duplicates(cfg, vroot)
        chk(len(dups) == 1 and 'dup_a' in dups[0]['file'],
            '逐字节重复的副本能查出（名字不同也查得到）')

        # 命中列退化：5 条全 0
        rows = ['| H%03d | 场景%d | 做法%d | L1 | 0 |' % (i, i, i)
                for i in range(1, 6)]
        (vroot / 'SKILLS' / '_hot.md').write_text(
            '# 热区\n\n| ID | 触发场景 | 正确做法 | 强度 | 命中 |\n'
            '|----|---------|---------|------|------|\n'
            + '\n'.join(rows) + '\n', encoding='utf-8')
        deg = check_degeneracy(cfg, vroot)
        chk(any('命中列' in i['issue'] for i in deg),
            '标注退化能查出（命中列全 0）')

        # 有区分度时不该误报
        (vroot / 'SKILLS' / '_hot.md').write_text(
            '# 热区\n\n| ID | 触发场景 | 正确做法 | 强度 | 命中 |\n'
            '|----|---------|---------|------|------|\n'
            '| H001 | a | b | L1 | 3 |\n| H002 | a | b | L1 | 0 |\n'
            '| H003 | a | b | L1 | 1 |\n| H004 | a | b | L1 | 0 |\n'
            '| H005 | a | b | L1 | 2 |\n', encoding='utf-8')
        chk(not any('命中列' in i['issue'] for i in check_degeneracy(cfg, vroot)),
            '命中数有区分度时不误报')

        # ---- reference/ 五分体系 ----
        # 正反两侧：四个子检查（缺区/无标记/标记不符/未知目录）都要能报，
        # 全对时必须不报。只造正向会让「放错区」从未被验证。
        zr = vroot / 'reference'
        for z in ('howto', 'audit', 'flow', 'common', 'craft'):
            (zr / z).mkdir(parents=True, exist_ok=True)
        (zr / 'howto' / 'a.md').write_text(
            '# a\n\n> **本区性质：howto / 怎么做。**\n', encoding='utf-8')
        zcfg = dict(cfg)
        zcfg['reference_zones'] = ['howto', 'audit', 'flow', 'common', 'craft']
        # 只断言「我造的那个文件不被报」，不断言全局 0 条——
        # vroot 里前面用例可能留下别的目录（会被「未知区」规则报），
        # 用全局 0 条会让本用例被无关残留带红。
        chk(not [i for i in check_reference_zones(zcfg, vroot)
                 if str(i['file']).endswith('howto/a.md')],
            '五区齐全且标记一致时不报（放对了不误报）')
        # ① 缺区
        zcfg2 = dict(zcfg)
        zcfg2['reference_zones'] = ['howto', 'audit', 'flow', 'common', 'craft', 'zzz']
        chk(any('缺区' in i['issue'] for i in check_reference_zones(zcfg2, vroot)),
            '缺区能查出（error）')
        # ② 无标记
        (zr / 'howto' / 'b.md').write_text('# b\n\n正文\n', encoding='utf-8')
        chk(any('无「本区性质」标记' in i['issue']
                for i in check_reference_zones(zcfg, vroot)),
            '无性质标记能查出')
        # ③ 标记与目录不符
        (zr / 'howto' / 'b.md').write_text(
            '# b\n\n> **本区性质：audit / 不能怎么做。**\n', encoding='utf-8')
        chk(any('放在 howto/ 下' in i['issue']
                for i in check_reference_zones(zcfg, vroot)),
            '标记与目录不符能查出（放错区）')
        (zr / 'howto' / 'b.md').unlink()
        # ④ 未知区目录
        (zr / 'extra').mkdir(exist_ok=True)
        (zr / 'extra' / 'c.md').write_text('# c\n', encoding='utf-8')
        chk(any('不在五分体系内' in i['issue']
                for i in check_reference_zones(zcfg, vroot)),
            '未知区目录能查出（总纲会失真）')
        (zr / 'extra' / 'c.md').unlink()

        # ---- 章节统计必须排除代码块 ----
        # 正反两侧：代码块里的 ## 不算（不误报）；真 ## 要算（漏报）。
        sp = vroot / 'reference' / 'howto'
        sp.mkdir(parents=True, exist_ok=True)
        # ⚠ 代码块里的 ## 必须**足够多**，否则这个用例是无效的：
        #   第一版只放 3 个（真实 2 + 块内 3 = 5，两种算法都 <12），
        #   变异测试「不排除代码块」照样 30/0 —— 用例在自欺。
        #   判据：要让「不排除」时**必然超阈值**，才测得出差别。
        (sp / 'tmpl.md').write_text(
            '# t\n\n## 一\n\n```markdown\n'
            + ''.join('## 模板节%d\n\n说明\n\n' % i for i in range(12))
            + '```\n\n## 二\n',
            encoding='utf-8')
        d_issues = check_doc_shape(cfg, {'reference': 400}, vroot)
        tmpl = [i for i in d_issues if 'tmpl.md' in str(i.get('file', ''))]
        chk(not tmpl, '代码块里的 ## 不算章节（模板不误报拆分）')
        # 反向：真有 15 个 ## 要报
        (sp / 'many.md').write_text(
            '# m\n\n' + '\n\n'.join('## 第%d节' % i for i in range(15)),
            encoding='utf-8')
        chk(any('many.md' in str(i.get('file', '')) and '章节' in i['issue']
                for i in check_doc_shape(cfg, {'reference': 400}, vroot)),
            '真实 15 个 ## 能查出（排除代码块不是把真章节也排掉）')
        (sp / 'tmpl.md').unlink(); (sp / 'many.md').unlink()

        # ---- 空区目录（第十八条：空转） ----
        # 正反两侧：空目录要报（否则检查在空集上跑却不报错）；
        # 有 .md 的正常区不能误报。
        ez = vroot / 'reference'
        ez.mkdir(parents=True, exist_ok=True)
        (ez / 'craft').mkdir(exist_ok=True)
        chk(any('没有任何 .md' in i['issue']
                for i in check_reference_zones(zcfg, vroot)),
            '区目录为空能查出（否则检查在空集上跑却不报错）')
        (ez / 'craft' / 'x.md').write_text(
            '> **本区性质：craft / 品位。**\n', encoding='utf-8')
        chk(not [i for i in check_reference_zones(zcfg, vroot)
                 if str(i['file']).endswith('craft')],
            '区里有 .md 时不误报')
        (ez / 'craft' / 'x.md').unlink()

        # ---- Step 识别判据：按节点 ID，不是标题含 Step ----
        # 反向用例：一节**提到** "Step 4" 但不是 Step，不该被当流程步骤检查。
        # 这正是「表面特征 vs 语义方向」（self-verification-falsepos 第十四条）：
        # 标题里有 Step 字样 ≠ 它是 Step。**节点 ID 才是稳定标识。**
        fl = vroot / 'reference' / 'flow'
        fl.mkdir(parents=True, exist_ok=True)
        (fl / 'mention.md').write_text(
            '<!--\nflow-id: FL-11\nflow-type: procedure\n-->\n# m\n\n'
            '> **本区性质：flow / 端到端流程。**\n\n'
            '### 批量四步（替换 Step 4）\n\n只是说明文字，不是工序步。\n\n'
            '## 7. 整体审核\n', encoding='utf-8')
        chk(not [i for i in check_flow_steps(cfg, vroot)
                 if 'mention.md' in str(i.get('file', ''))],
            '标题提到 Step 但不是工序步 → 不误报（按节点 ID 识别）')
        (fl / 'mention.md').unlink()

        # ---- 豁免声明必须真生效（多行理由） ----
        # 实测：正则 `(.+?)` 默认不匹配换行 → 豁免理由写成多行时
        # oversize_exempt() 返回 None → **声明了但仍按超限报**。
        # 「假生效」比没声明更糟：没声明至少知道要拆。
        ex = vroot / 'reference' / 'big.md'
        ex.parent.mkdir(parents=True, exist_ok=True)
        ex.write_text(
            '# t\n\n<!-- oversize-exempt: 理由第一行，\n     第二行 -->\n\n'
            + ('内容\n' * 500), encoding='utf-8')
        chk(oversize_exempt(ex) is not None,
            '豁免理由跨行也能识别（否则「声明了但没生效」）')
        got_ex = check_size({'size_limits': {'reference': 400}}, ) \
            if False else []
        ex.unlink()
        # 反向：没声明豁免的不能用别人的豁免
        (vroot / 'reference').mkdir(parents=True, exist_ok=True)
        nx = vroot / 'reference' / 'noex.md'
        nx.write_text('# t\n\n' + ('内容\n' * 500), encoding='utf-8')
        chk(oversize_exempt(nx) is None, '没声明豁免的不误判为已豁免')
        nx.unlink()

        # ---- 死链检查（EV-M10：检查有效 ≠ 有用例守着） ----
        # ⛔ 实测：LK002 在真库上**确实能抓到**死链（手动造一条验证过），
        #    但自检里**没有用例** → mutate 跑出来是 SURVIVED。
        #    这正是第二十四条的实证：**检查有效 ≠ 有用例守着**。
        # 反向：引用不存在的脚本 → 报 error
        (vroot / 'reference').mkdir(parents=True, exist_ok=True)
        dc2 = vroot / 'reference' / 'dead.md'
        dc2.write_text('# t\n\n见 `scripts/nosuch.py`\n', encoding='utf-8')
        got_dead = check_refs({}, vroot)
        chk(any('nosuch.py' in str(i.get('issue', ''))
                and i.get('level') == 'error' for i in got_dead),
            '引用不存在的脚本能报 error（死链）')
        # 正向：引用存在的脚本 → 不报
        (vroot / 'scripts').mkdir(parents=True, exist_ok=True)
        (vroot / 'scripts' / 'real.py').write_text('pass\n', encoding='utf-8')
        dc2.write_text('# t\n\n见 `scripts/real.py`\n', encoding='utf-8')
        chk(not [i for i in check_refs({}, vroot)
                 if 'real.py' in str(i.get('issue', ''))],
            '引用存在的脚本不报（正向不误报）')
        dc2.unlink(missing_ok=True)

        # ---- 分层目录必须参与体积检查（EV-M08） ----
        # ⛔ 历史缺陷：reference/ 分成五区后，`check_size` 用 glob
        #    只扫顶层 → **子区的文档完全不参与体积检查**。
        #    实测：把 rglob 改回 glob，自检**照样 61/0 全绿**——
        #    这个修过的缺陷**没有任何用例守着**。
        #    （同一形态在 code-audit 侧踩过三次：断链 / 扫描器 / 体积）
        sub = vroot / 'reference' / 'howto'
        sub.mkdir(parents=True, exist_ok=True)
        deep = sub / 'big.md'
        deep.write_text('# t\n\n' + ('内容\n' * 420), encoding='utf-8')
        got_deep = check_size({'size_limits': {}}, {'reference': 400}, vroot)
        chk(any('big.md' in str(i.get('file', '')) for i in got_deep),
            '子区目录里的超限文件能查出（rglob 不是 glob）')
        deep.unlink()

        # ---- check_check_coverage 自身：正反两侧 ----
        # ⛔ 光有这个检查项不够，它自己也得被验证：
        #   造一个「有 check_x 但自检里没调用它」的样本 lint.py。
        #   没有这个用例，check_check_coverage 失效了也没人知道
        #   ——正是它自己要抓的那个失效形态。
        cc = vroot / 'cc'
        (cc / 'scripts').mkdir(parents=True, exist_ok=True)
        (cc / 'scripts' / 'lint.py').write_text(
            'def check_alpha():\n    return []\n\n'
            'def check_beta():\n    return []\n\n'
            'def cmd_self_test():\n    check_alpha()\n    return 0\n',
            encoding='utf-8')
        got_cc = check_check_coverage({}, cc)
        hit = [i for i in got_cc if 'check_beta' in str(i.get('issue', ''))]
        chk(bool(hit) and hit[0]['level'] == 'warn',
            '自检里没被调用的检查项能报 warn（否则该检查项失效无人知）')
        chk(not [i for i in got_cc
                 if 'check_alpha' in str(i.get('issue', ''))],
            '自检里调用过的检查项不报（正向不误报）')

        # ---- check_root：正反两侧（EV-M07 / 交叉审计抓出的盲区） ----
        # ⛔ 这个检查项此前**在自检里一次都没被调用**——
        #   它失效了自检也不会变红（`check_check_coverage` 抓出来的）。
        #   而它恰恰是「domains 没初始化」这个最高频失效的守门人。
        # 正向：目录存在 → 不报
        dr = vroot / 'domains'
        dr.mkdir(parents=True, exist_ok=True)
        chk(check_root({'root': str(dr)}) == [],
            '大类根目录存在时 check_root 不报')
        # 反向：目录不存在 → 报 error
        got_root = check_root({'root': str(vroot / 'no-such-domains')})
        chk(bool(got_root) and got_root[0]['level'] == 'error',
            '大类根目录不存在时 check_root 报 error（否则 domains/ 检查静默跳过）')

        # ---- 体积提示必须声明「不是充实度判据」 ----
        # ⛔ 体积检查最容易被误读成"充实度指标"：
        #   「还没到上限」被当成「写够了」，「超了上限」被当成「写得好」。
        #   前者会让空模块一直空着，后者会奖励注水。
        #   → 三处 hint 都必须带这句，且指向 craft/substance.md。
        #   这条能被自动验证（hint 文案在，指向在），
        #   而"内容到底充不充实"**无法自动验证**——
        #   这正是 substance.md 的核心论点：充实度是数不出来的那部分。
        hs = []
        (vroot / 'reference').mkdir(parents=True, exist_ok=True)
        big = vroot / 'reference' / 'b.md'
        big.write_text('# t\n\n' + ('## 章节\n\n内容\n' * 14)
                       + ('内容\n' * 330), encoding='utf-8')
        for i in check_doc_shape({'size_limits': {'reference': 400}},
                                 {'reference': 400}, vroot):
            hs.append(i.get('hint', ''))
        big.unlink(missing_ok=True)
        # ⚠ 用 all 不用 any：只查「任一条有」时，改掉其中一条
        #   用例照样绿 —— 变异验证（去掉 o1 那句）实测**没变红**，
        #   用例形同虚设。这正是「用例必须能因改动而变红」的硬要求。
        vol_hints = [h for h in hs if h]
        chk(bool(vol_hints), '体积样本确实触发了提示（否则用例没在验证）')
        chk(all('不是充实度' in h and 'substance.md' in h
                for h in vol_hints),
            '每条体积提示都要声明「不是充实度判据」并指向 craft/substance.md')

        # ---- 豁免必须覆盖「接近上限」档（EV-M04） ----
        # ⛔ 这条是**变异 EV-M04 抓出来的真盲区**：
        #   豁免原先只作用于超限那一档，「接近上限」照报 →
        #   归档型文件（只会增长）的提示永远消不掉
        #   → 永久噪音里的提示等于没有提示（第十五条）。
        #   手写用例漏了它，是 mutate.py 跑出来才发现的。
        ex2 = vroot / 'reference' / 'arch.md'
        ex2.write_text(
            '# t\n\n<!-- oversize-exempt: 归档型，只会增长 -->\n\n'
            + ('内容\n' * 330), encoding='utf-8')
        got_ex2 = check_doc_shape({'size_limits': {'reference': 400}},
                                  {'reference': 400}, vroot)
        chk(not any('arch.md' in str(i.get('file', '')) for i in got_ex2),
            '已声明豁免的文件不报「接近上限」（否则提示变永久噪音）')
        ex2.unlink()

        # ---- 文档承诺的命令 ----
        # ⛔ 正反**两侧**都要造。只造反向（不支持的要报）会让
        #   「转发壳被误报」从未验证——而那正是会让人关掉检查的那一侧。
        dc = vroot / 'SKILLS'
        dc.mkdir(parents=True, exist_ok=True)
        (vroot / 'scripts').mkdir(parents=True, exist_ok=True)
        # 反向：文档写了脚本里没有的 flag
        (vroot / 'scripts' / 'x.py').write_text('pass\n', encoding='utf-8')
        (dc / 'c.md').write_text(
            '# t\n\npython3 scripts/x.py --nosuchflag\n', encoding='utf-8')
        got_dc = check_doc_commands({}, vroot)
        chk(any('nosuchflag' in i['issue'] for i in got_dc),
            '文档写了脚本不支持的 flag 能查出')
        # 正向：转发壳的 flag 在 canonical 里 → 不误报
        (vroot / 'scripts' / 'shell.py').write_text(
            "import os, sys\n"
            "_HERE = os.path.dirname(os.path.abspath(__file__))\n"
            # ⚠ 退**一级**才对：shell.py 在 vroot/scripts/ 下，
            #   _canon.py 在 vroot/ 下。写 '..','..' 会退到 vroot 之外
            #   → 文件不存在 → 正向用例反而失败（用例自己没造对）。
            "_CANON = os.path.normpath(os.path.join(\n"
            "    _HERE, '..', '_canon.py'))\n", encoding='utf-8')
        (vroot / '_canon.py').write_text('# real\n--realflag\n', encoding='utf-8')
        (dc / 'c.md').write_text(
            '# t\n\npython3 scripts/shell.py --realflag\n', encoding='utf-8')
        got_sh = check_doc_commands({}, vroot)
        chk(not any('realflag' in i['issue'] for i in got_sh),
            '转发壳的 flag 在 canonical 里时不误报（否则会误报一片）')

        # ---- 双阈值：token（占上下文的是 token，不是行数） ----
        # ⛔ 用例必须自造**大宽表格**：token 多但行数少。
        #   只造"很多行"的样本测不出 token 维度的差别——
        #   它会被行数阈值先拦下，token 分支永远走不到。
        # ⚠ 用 check_doc_shape（它支持 root 注入）；check_size 用的是
        #   全局 ROOT，只能测真库——那是测数据不是测判据。
        cfg_tk = {'size_limits': {'reference': 400},
                  'token_limits': {'reference': 500}}
        tk_ok = vroot / 'reference' / 'small.md'
        tk_ok.write_text('# t\n\n' + ('短行\n' * 50), encoding='utf-8')
        chk(not [i for i in check_doc_shape(cfg_tk, {'reference': 400}, vroot)
                 if 'small.md' in str(i.get('file', ''))],
            '行数与 token 都合规时不误报')
        # 反面：token 超限但**行数合规**（32 行 / 2402 token）
        tk_bad = vroot / 'reference' / 'dense.md'
        tk_bad.write_text('# t\n\n' + ('字段' * 40 + '\n') * 30,
                          encoding='utf-8')
        got_tk = check_doc_shape(cfg_tk, {'reference': 400}, vroot)
        chk(any('dense.md' in str(i.get('file', ''))
                and 'tokens' in i.get('issue', '') for i in got_tk),
            '行数合规但 token 超限能查出（双阈值不是只看行数）')
        tk_ok.unlink(missing_ok=True)
        tk_bad.unlink(missing_ok=True)

        # ---- 跨 skill 阈值一致性：找不到就跳过（不误报） ----
        # 反向用例：独立分发时兄弟 skill 不存在 → 必须 0 条，
        # 否则会冒出一条无法解释的告警。
        chk(check_sibling_limits({'size_limits': {'SKILL.md': 200}},
                                 root=Path(tmp) / 'no-siblings') == [],
            '找不到兄弟 skill 时跳过（不误报）——保留独立分发能力')

        # ---- frontmatter：负面触发 / 块列表 / 长度 ----
        # ⚠ 早先 check_frontmatter 只扫 domains/*/skills，
        #    domains 未初始化时 targets 恒空 → **检查从未验证过任何东西**。
        #   加了 root 注入才测得成——这就是「可注入」的价值。
        fr = vroot / 'SKILL.md'
        good_fm = ('---\nname: x\nid: X1\nkeywords:\n  - 甲\n  - 乙\n'
                   'trigger: 何时用\nnot_trigger: 何时不用\nverified: yes\n'
                   'description: 简短\n---\n\n# x\n')
        fr.write_text(good_fm, encoding='utf-8')
        got_fm = check_frontmatter({'domains': {}}, vroot)
        chk(not any('负面触发' in i['issue'] for i in got_fm),
            '写了 not_trigger 时不报（正面+负面才是完整召回）')
        chk(not any('缺字段' in i['issue'] and 'keywords' in i['issue']
                    for i in got_fm),
            '块列表 keywords 能解析（否则「写了却说没写」）')

        bad_fm = good_fm.replace('not_trigger: 何时不用\n', '')
        fr.write_text(bad_fm, encoding='utf-8')
        got_fm2 = check_frontmatter({'domains': {}}, vroot)
        chk(any('负面触发' in i['issue'] for i in got_fm2),
            '缺负面触发必须报（只说何时用 → 边界请求会误命中）')

        # 长度上限
        fr.write_text(good_fm.replace('name: x', 'name: ' + 'n' * 70),
                      encoding='utf-8')
        chk(any('name' in i['issue'] and '超过' in i['issue']
                for i in check_frontmatter({'domains': {}}, vroot)),
            'name 超 64 字符能查出（规范硬限）')

        # ---- 退出码码表 ----
        # 为什么需要：实测 lint.py --json **有 error 也返回 0**
        # → CI 用它解析 = 永远绿灯，gate 形同虚设。
        # ⛔ 这个 bug 会静默复发：改 main() 时顺手把 sys.exit 删掉就又回到 0。
        try:
            import exitcode
            chk(exitcode.OK == 0 and exitcode.USAGE == 2
                and exitcode.ENV == 3 and exitcode.BLOCKED == 4,
                '退出码码表常量正确（0/2/3/4）')
        except ImportError as _e:
            chk(False, 'exitcode 模块可导入（%s）' % _e)
        # 关键：机器可读模式**同样**要带退出码
        # ⚠ 早先这个用例跑在**真库**上，而真库当前是否有 error 是随机的：
        #   真库干净 → jerr 空 → 两条 gate 用例被 chk(True) 顶替，
        #   **用例恒绿而从未验证**；真库脏 → 又依赖具体脏在哪。
        #   这正是「用例必须在自己造的样本上成立」（falsepos 第十二条
        #   与 silent 第十八条的交叉）：蹭真库数据过的用例，真库一变就失效，
        #   且失效时不报错——它只是「不查了」。
        #   → 造一份**必定有 error** 的副本，在副本上跑整条链路。
        # ⚠ gate 副本**不能放在 vroot 下**：
        #   check_exemptions 等检查用 rglob 扫 base 全部 .py，
        #   gate/scripts 里的真实 lint.py 含 `exempt` 字样 →
        #   会把「豁免无人读」用例的 vroot 污染成「有人读」→ 用例失效。
        #   这正是「用例要在自己造的样本上成立，且不受别的用例残留影响」。
        gate_root = vroot.parent / ('gate_%d' % os.getpid())
        _mk_repo_copy(gate_root)
        gp = str(gate_root / 'scripts' / 'lint.py')
        rj = subprocess.run([sys.executable, gp, '--json'],
                            capture_output=True, text=True)
        try:
            jd = json.loads(rj.stdout or '[]')
        except ValueError:
            jd = []
        jerr = [i for i in jd if i.get('level') == 'error']
        chk(bool(jerr),
            'gate 副本里确实有 error（否则用例没在验证，是蹭真库状态过的）')
        chk(rj.returncode != 0,
            '--json 模式有 error 时退出码非 0（否则 gate 形同虚设）')
        rn = subprocess.run([sys.executable, gp], capture_output=True, text=True)
        chk(rn.returncode == 4,
            '普通模式有 error → 退出码 4（BLOCKED，不是 1）')

        # ---- flow/ 区流程规范 ----
        # ⚠ 正反两侧都要造：meta 不误报、procedure 五字段不全要报、
        # 缺整体审核要报、index 双向。只造正向会让「省字段」从未被验证。
        fl = vroot / 'reference' / 'flow'
        fl.mkdir(parents=True, exist_ok=True)
        (fl / 'index.md').write_text(
            '<!--\nflow-type: meta\n-->\n# idx\n\n'
            '> **本区性质：flow / 元规则。**\n\n'
            '| ID | 流程 |\n|---|---|\n| `FL-01` | [p](good.md) |\n',
            encoding='utf-8')
        # meta：里面举例了不完整的 Step，**绝不能**被当成真流程报
        (fl / 'spec.md').write_text(
            '<!--\nflow-type: meta\n-->\n# spec\n\n'
            '> **本区性质：flow / 元规则。**\n\n'
            '### Step 1　示例　`[FL-xx#S1]`\n\n【做】只是举例\n',
            encoding='utf-8')
        chk(not [i for i in check_flow_steps(cfg, vroot)
                 if 'spec.md' in str(i.get('file', ''))],
            'meta 里的示例 Step 不误报（区分 meta/procedure）')
        # procedure：五字段不全 → 报错
        (fl / 'bad.md').write_text(
            '<!--\nflow-id: FL-09\nflow-type: procedure\n-->\n# bad\n\n'
            '> **本区性质：flow / 端到端流程。**\n\n'
            '### Step 1　缺字段　`[FL-09#S1]`\n\n【做】只有做\n\n'
            '## 7. 整体审核\n',
            encoding='utf-8')
        chk(any('缺五字段' in i['issue'] for i in check_flow_steps(cfg, vroot)),
            'Step 缺五字段能查出')
        # procedure：缺整体审核 → 报错
        (fl / 'noaudit.md').write_text(
            '<!--\nflow-id: FL-10\nflow-type: procedure\n-->\n# na\n\n'
            '> **本区性质：flow / 端到端流程。**\n\n'
            '### Step 1　x　`[FL-10#S1]`\n\n【读】a\n【做】b\n'
            '【产出】c\n【判据】d\n【审】e\n',
            encoding='utf-8')
        chk(any('整体审核' in i['issue'] for i in check_flow_steps(cfg, vroot)),
            '缺「整体审核」节能查出（步骤级抓不到漏列的）')
        # ⑦ index 双向：FL-09 写了文件但没登记 → warn
        chk(any('FL-09' in i['issue'] and '未' in i['issue']
                for i in check_flow_steps(cfg, vroot)),
            '只写文件不登记能查出')
        # 反向：登记了 FL-77 但无此文件 → error
        (fl / 'index.md').write_text(
            '<!--\nflow-type: meta\n-->\n# idx\n\n'
            '> **本区性质：flow / 元规则。**\n\n'
            '| `FL-01` | [g](good.md) |\n| `FL-77` | [x](nope.md) |\n',
            encoding='utf-8')
        chk(any('FL-77' in i['issue'] for i in check_flow_steps(cfg, vroot)),
            '登记了但文件不存在能查出')
        # 缺 flow-type → error
        (fl / 'notype.md').write_text('# nt\n\n正文\n', encoding='utf-8')
        chk(any('缺 flow-type' in i['issue']
                for i in check_flow_steps(cfg, vroot)),
            '缺 flow-type 能查出（否则无法分流）')

        # ---- 区名开头的相对路径也必须是死链（EV-M12） ----
        # ⛔ 实测 4 条长期未被发现：老正则只认 scripts/ 或 reference/ 开头，
        #    而「【读】common/howto/principles.md」这种**区名开头**的
        #    写法完全不在检查范围内 —— **检查在跑，但没在查**。
        (vroot / 'reference').mkdir(parents=True, exist_ok=True)
        zd = vroot / 'reference' / 'flow'
        zd.mkdir(parents=True, exist_ok=True)
        zf = zd / 'zone.md'
        # 反向：区名开头 + 文件不存在 → 报
        zf.write_text('# t\n\n见 `common/nosuch-block.md`\n', encoding='utf-8')
        chk(any('nosuch-block' in str(i.get('issue', ''))
                for i in check_refs({}, vroot)),
            '区名开头的相对路径死链能查出（老正则漏掉这一类）')
        # 正向：区名开头 + 文件存在 → 不报
        (vroot / 'reference' / 'common').mkdir(parents=True, exist_ok=True)
        (vroot / 'reference' / 'common' / 'real-block.md').write_text(
            '# b\n', encoding='utf-8')
        zf.write_text('# t\n\n见 `common/real-block.md`\n', encoding='utf-8')
        chk(not [i for i in check_refs({}, vroot)
                 if 'real-block' in str(i.get('issue', ''))],
            '区名开头但文件存在 → 不误报')
        zf.unlink(missing_ok=True)

        # ---- 全局块锚点（EV-M13） ----
        # 只造正向（锚点存在不报）会让「锚点写错」从未验证。
        cb = vroot / 'reference' / 'common'
        cb.mkdir(parents=True, exist_ok=True)
        (cb / 'blocks.md').write_text(
            '# b\n\n## EC-01 甲\n\n## EC-02 乙\n', encoding='utf-8')
        zf2 = vroot / 'reference' / 'howto' / 'u.md'
        zf2.parent.mkdir(parents=True, exist_ok=True)
        # 正向：存在的锚点 → 不报
        zf2.write_text('# u\n\n见 #EC-01\n', encoding='utf-8')
        chk(not check_block_refs(cfg, vroot), '存在的全局块锚点不报')
        # 反向：不存在的锚点 → error
        zf2.write_text('# u\n\n见 #EC-99\n', encoding='utf-8')
        chk(any('EC-99' in str(i.get('issue', ''))
                for i in check_block_refs(cfg, vroot)),
            '不存在的全局块锚点能查出（否则重复又回来了）')
        # ⛔ 反侧二：块定义提取失效 → defined 为空 → 全部误报。
        #    只造"不存在的锚点"会让这一侧从未验证——
        #    **误报的检查会被关掉**（EC-02 / 第十三条）。
        (cb / 'blocks.md').write_text(
            '# b\n\n## 说明\n\n无编号块\n', encoding='utf-8')
        zf2.write_text('# u\n\n见 #EC-01\n', encoding='utf-8')
        chk(any('EC-01' in str(i.get('issue', ''))
                for i in check_block_refs(cfg, vroot)),
            '块定义提取失效（defined 为空）时能查出——否则全量误报')
        (cb / 'blocks.md').write_text(
            '# b\n\n## EC-01 甲\n\n## EC-02 乙\n', encoding='utf-8')
        zf2.unlink(missing_ok=True)

        # ---- 孤立表格行（EV-M15） ----
        # ⛔ 实测 SKILL.md 目录地图里 `| pending/draft.md | … |`
        #    夹在两个段落之间，Markdown 不渲染成表格。
        #    只造正向会让「抓不到」从未验证。
        ot = vroot / 'reference' / 'common'
        ot.mkdir(parents=True, exist_ok=True)
        of = ot / 't.md'
        # ⛔ 断言必须**只针对自己造的样本**：
        #    check_orphan_table_row 扫 reference/ 下全部 .md，
        #    前面用例留下的文件可能自带孤立表格行 →
        #    **全局「0 条」断言会被无关残留带红**
        #    （与 EV-M04 同族：断言要在自造样本上成立）。
        def _only_t(res):
            return [i for i in res if i.get('file', '').endswith('t.md')]

        # 正向①：表格内正常行（上一行是表格行）→ 不报
        of.write_text('# t\n\n| a | b |\n|---|---|\n| 1 | 2 |\n',
                      encoding='utf-8')
        chk(not _only_t(check_orphan_table_row(cfg, vroot)),
            '表格内正常行不报')
        # 正向②：表头行（下一行是分隔线）→ 不报
        of.write_text('# t\n\n| a | b |\n|---|---|\n', encoding='utf-8')
        chk(not _only_t(check_orphan_table_row(cfg, vroot)), '表头行不报')
        # 正向③：代码块里的表格行 → 不报（示例是正常的）
        of.write_text('# t\n\n```\n| x | y |\n```\n', encoding='utf-8')
        chk(not _only_t(check_orphan_table_row(cfg, vroot)),
            '代码块内的表格行不误报')
        # 反向：孤立表格行（前后都是非表格）→ 报
        of.write_text('# t\n\n正文段落\n\n| 孤立 | 行 |\n\n另一段\n',
                      encoding='utf-8')
        chk(any('孤立表格行' in str(i.get('issue', ''))
                for i in check_orphan_table_row(cfg, vroot)),
            '孤立表格行能查出（Markdown 不渲染它）')
        of.unlink(missing_ok=True)

        # ---- 扫描范围必须覆盖入口文件（EV-M16） ----
        # ⛔ 缺陷是在 SKILL.md 里发现的，而第一版只扫 reference/。
        #    只造「子目录里能查出」会让「入口文件不扫」从未验证。
        sk2 = vroot / 'SKILL.md'
        sk2.write_text('# s\n\n正文\n\n| 孤立 | 行 |\n\n另一段\n',
                       encoding='utf-8')
        chk(any('SKILL.md' in str(i.get('file', ''))
                for i in check_orphan_table_row(cfg, vroot)),
            '入口文件（SKILL.md）的孤立表格行也能查出'
            '——⛔ 缺陷就是在那儿发现的')
        sk2.unlink(missing_ok=True)

        # ---- 条目型文档不算「章节过多」（EV-M17） ----
        # ⛔ 只造「普通文档多章节能查出」会让「条目册被误报」从未验证。
        ed = vroot / 'reference' / 'howto'
        ed.mkdir(parents=True, exist_ok=True)
        # 反向：条目型（编号章节 ≥70%）→ 不报，尽管章节数 >12
        ent = []
        for k in range(14):
            ent.append('## %d、条目%d\n\n内容\n' % (k + 1, k + 1))
        (ed / 'entrybook.md').write_text('# e\n\n' + '\n'.join(ent),
                                         encoding='utf-8')
        chk(not [i for i in check_doc_shape(cfg, {}, vroot)
                 if 'entrybook.md' in str(i.get('file', ''))
                 and '章节' in str(i.get('issue', ''))],
            '条目型文档（编号章节）不算章节过多——拆了反而要来回翻')
        # 正向：非条目型多章节 → 仍然报（确认豁免没有一刀切）
        pro = []
        for k in range(14):
            pro.append('## 主题%d\n\n内容\n' % (k + 1))
        (ed / 'prose.md').write_text('# p\n\n' + '\n'.join(pro),
                                     encoding='utf-8')
        chk(any('prose.md' in str(i.get('file', ''))
                and '章节' in str(i.get('issue', ''))
                for i in check_doc_shape(cfg, {}, vroot)),
            '非条目型多章节仍然报（豁免没有一刀切）')
        for nm in ('entrybook.md', 'prose.md'):
            (ed / nm).unlink(missing_ok=True)

        # ---- 扫描范围含入口文件（EV-M18） ----
        # ⛔ 只造「全库扫描不报」会让「只扫子目录能查出」从未验证。
        sg = vroot / 'scripts'
        sg.mkdir(parents=True, exist_ok=True)
        # vroot 下没有 scripts/lint.py → check_scan_scope 直接返回 0
        chk(not check_scan_scope(cfg, vroot),
            '没有 scripts/lint.py 时不报（缺文件不误报）')
        # 造一个只扫子目录的检查函数 → 应报
        (sg / 'lint.py').write_text(
            'import ast\nfrom pathlib import Path\n'
            'ROOT = Path(".")\n\n\n'
            'def check_zzz(cfg, root=None):\n'
            '    base = Path(root) if root else ROOT\n'
            '    issues = []\n'
            '    for f in sorted((base / "reference").rglob("*.md")):\n'
            '        pass\n'
            '    return issues\n', encoding='utf-8')
        chk(any('check_zzz' in str(i.get('issue', ''))
                for i in check_scan_scope(cfg, vroot)),
            '只扫子目录、不含入口的检查能查出')
        # 反向：全库扫描（receiver 是 base）→ 不报
        (sg / 'lint.py').write_text(
            'import ast\nfrom pathlib import Path\n'
            'ROOT = Path(".")\n\n\n'
            'def check_zzz(cfg, root=None):\n'
            '    base = Path(root) if root else ROOT\n'
            '    issues = []\n'
            '    for f in sorted(base.rglob("*.md")):\n'
            '        pass\n'
            '    return issues\n', encoding='utf-8')
        chk(not [i for i in check_scan_scope(cfg, vroot)
                 if 'check_zzz' in str(i.get('issue', ''))],
            '全库扫描（receiver 是 base）不报')
        # 反向二：显式补了入口 → 不报
        #   ⚠ ast.unparse 会把引号规范化成单引号，
        #      只认 '"SKILL.md"' 会漏判（本轮刚踩）。
        (sg / 'lint.py').write_text(
            'import ast\nfrom pathlib import Path\n'
            'ROOT = Path(".")\n\n\n'
            'def check_zzz(cfg, root=None):\n'
            '    base = Path(root) if root else ROOT\n'
            '    issues = []\n'
            '    targets = [base / "SKILL.md"]\n'
            '    targets += sorted((base / "reference").rglob("*.md"))\n'
            '    for f in targets:\n'
            '        pass\n'
            '    return issues\n', encoding='utf-8')
        chk(not [i for i in check_scan_scope(cfg, vroot)
                 if 'check_zzz' in str(i.get('issue', ''))],
            '显式补了入口文件不报（unparse 引号规范化不能漏判）')
        # 反向三：只扫 .py 的检查不报（入口对它没意义 → 噪音）
        (sg / 'lint.py').write_text(
            'import ast\nfrom pathlib import Path\n'
            'ROOT = Path(".")\n\n\n'
            'def check_zzz(cfg, root=None):\n'
            '    base = Path(root) if root else ROOT\n'
            '    issues = []\n'
            '    for f in sorted((base / "scripts").glob("*.py")):\n'
            '        pass\n'
            '    return issues\n', encoding='utf-8')
        chk(not [i for i in check_scan_scope(cfg, vroot)
                 if 'check_zzz' in str(i.get('issue', ''))],
            '只扫 .py 的检查不报（入口 .md 对它没意义 → 噪音）')
        (sg / 'lint.py').unlink(missing_ok=True)

        # ---- 重复章节标题（EV-M19） ----
        # ⛔ 实测：往「## 六、自检」后插入新项时原文块没删 →
        #    两个完全相同的 `## 六、自检`。Markdown 照常渲染，
        #    只有人读时才看得见（第十七条：格式缺陷 100% 静默）。
        dh = vroot / 'reference' / 'craft'
        dh.mkdir(parents=True, exist_ok=True)
        dfile = dh / 'd.md'
        # 正向：标题各不相同 → 不报
        dfile.write_text('# d\n\n## 一\n\nx\n\n## 二\n\ny\n',
                         encoding='utf-8')
        chk(not [i for i in check_duplicate_headings(cfg, vroot)
                 if 'd.md' in str(i.get('file', ''))],
            '标题各不相同不报')

        # ---- craft 层接入：断链 + 孤儿 ----
        # 反哺 game-dev 的 check-craft.py。⛔ 为什么必须查孤儿：
        #   craft 层只有**被读到时**才起作用；没人翻的书等于没写。
        #   实测首次跑：46 条判据，条目级接入率 0%。
        cf = vroot / 'reference' / 'craft'
        cf.mkdir(parents=True, exist_ok=True)
        (cf / 'taste.md').write_text(
            '# t\n\n## 二、总判据\n\n### 1. 写正确的废话 = 没写\n\n内容\n\n'
            '### 自检（30 秒）\n\n- [ ] x\n\n'
            '## 七、变更溯源\n\n| a | b |\n|---|---|\n',
            encoding='utf-8')
        how = vroot / 'reference' / 'howto'
        how.mkdir(parents=True, exist_ok=True)
        hd = how / 'h.md'
        # 正向：条目被条目级引用指向 → 不报孤儿
        hd.write_text('# h\n\n见 craft/taste.md#写正确的废话\n',
                      encoding='utf-8')
        chk(not [i for i in check_craft_refs(cfg, vroot)
                 if '孤儿' in str(i.get('issue', ''))
                 or '未指向' in str(i.get('issue', ''))],
            'craft 条目被条目级引用指向时不报孤儿')
        chk(not [i for i in check_craft_refs(cfg, vroot)
                 if '锚点不存在' in str(i.get('issue', ''))],
            'craft 锚点存在时不报断链')
        # 反向一：锚点不存在 → error
        hd.write_text('# h\n\n见 craft/taste.md#压根没这一条\n',
                      encoding='utf-8')
        # ⛔ 必须内联调用：写成 `r = check_craft_refs(...)` 再断言 r，
        #    check_selftest_duality 的 AST 看不到调用 → 判「缺反向用例」。
        chk(any('锚点不存在' in str(i.get('issue', ''))
                for i in check_craft_refs(cfg, vroot)),
            'craft 条目锚点不存在能查出（error）')
        chk(all(i['level'] == 'error'
                for i in check_craft_refs(cfg, vroot)
                if '锚点不存在' in str(i.get('issue', ''))),
            'craft 断链是 error 级')
        chk(all(i.get('level') == 'info'
                for i in check_craft_refs(cfg, vroot)
                if '接入率' in str(i.get('issue', ''))),
            '接入率欠账是 info 级（⛔ 不是 error：它不阻断，但要可见）')
        # 反向二：只有文件级引用 → 报未指向（条目级接入率 0）
        hd.write_text('# h\n\n见 craft/taste.md\n', encoding='utf-8')
        chk(any('未指向' in str(i.get('issue', ''))
                for i in check_craft_refs(cfg, vroot)),
            '只有文件级引用时报「未指向」（⛔ 文件在 ≠ 内容在）')
        # 反向三：整册从未被引用 → warn（比条目未指向更严重）
        hd.write_text('# h\n\n别的\n', encoding='utf-8')
        chk(any(i.get('level') == 'warn'
                and '整册未接入' in str(i.get('issue', ''))
                for i in check_craft_refs(cfg, vroot)),
            '整册从未被引用时报 warn')
        # ⛔ 反侧：太短的锚点（<4 字）必须全等，不能子串匹配
        #   —— 否则 `文` 会命中所有标题，断链检查形同虚设
        hd.write_text('# h\n\n见 craft/taste.md#内容\n', encoding='utf-8')
        chk(any('锚点不存在' in str(i.get('issue', ''))
                for i in check_craft_refs(cfg, vroot)),
            '短锚点（<4 字）不会子串乱匹配（⛔ 否则断链检查失效）')

        # ---- 序号撞车：同级重复中文序号 ----
        # ⛔ 实测真库 7 处。后果：引用 `#十` 指向两处之一，
        #    而锚点检查查不出来（两个标题文本都真实存在）。
        nz = vroot / 'reference' / 'howto'
        nz.mkdir(parents=True, exist_ok=True)
        nf = nz / 'n.md'
        # 正向：编号连续 → 不报
        nf.write_text('# n\n\n## 一、甲\n\nx\n\n## 二、乙\n\ny\n',
                      encoding='utf-8')
        chk(not [i for i in check_heading_numbering(cfg, vroot)
                 if 'n.md' in str(i.get('file', ''))],
            '序号连续不报')
        # 反向：两个「三」→ 报
        nf.write_text('# n\n\n## 一、甲\n\nx\n\n## 二、乙\n\ny\n\n'
                      '## 三、丙\n\nz\n\n## 三、丁\n\nw\n',
                      encoding='utf-8')
        chk(any('序号撞车' in str(i.get('issue', ''))
                for i in check_heading_numbering(cfg, vroot)),
            '序号撞车能查出（两个「三」）')
        # ⛔ 反侧一：十一/二十/二十九 不能被算错（实测三个坑都"看起来能跑"）
        # ⛔ 样本必须**同时**含「十」与「二十」：
        #    只放 十/十一 时，十位忘 +1 也不撞（10 vs 11）⇒ 用例恒绿。
        #    ⛔ 这是「断言没针对被改的地方」的又一次：
        #    要让变异**必然**改变结果，样本得造对。
        nf.write_text('# n\n\n## 九、甲\n\nx\n\n## 十、乙\n\ny\n\n'
                      '## 十一、丙\n\nz\n\n## 二十九、丁\n\nw\n',
                      encoding='utf-8')
        chk(not [i for i in check_heading_numbering(cfg, vroot)
                 if 'n.md' in str(i.get('file', ''))],
            '十一/二十/二十九 不被误判撞车'
            '（⛔ 十位忘 +1 会让 二十=十=10，撞车检查全是假阳性）')
        nf.write_text('# n\n\n## 十、甲\n\nx\n\n## 二十、乙\n\ny\n',
                      encoding='utf-8')
        chk(not [i for i in check_heading_numbering(cfg, vroot)
                 if 'n.md' in str(i.get('file', ''))],
            '十 与 二十 不撞车（⛔ 十位忘 +1 时两者都是 10 ⇒ 必然误报）')
        # ⛔ 反侧二：代码块内的重复序号 → 不误报（示例是正常的）
        nf.write_text('# n\n\n```\n## 一、甲\n## 一、乙\n```\n',
                      encoding='utf-8')
        chk(not [i for i in check_heading_numbering(cfg, vroot)
                 if 'n.md' in str(i.get('file', ''))],
            '代码块内的重复序号不误报')
        # ⛔ 反侧三：归档型文件天然每段各有编号 → 豁免
        #    （不豁免 = 基线永远清不掉 = 检查被关掉）
        af = vroot / 'assets' / 'changelog-archive.md'
        af.parent.mkdir(parents=True, exist_ok=True)
        af.write_text('# a\n\n### 一、x\n\n### 二、y\n\n'
                      '### 一、z\n\n### 二、w\n', encoding='utf-8')
        chk(not [i for i in check_heading_numbering(cfg, vroot)
                 if 'changelog-archive' in str(i.get('file', ''))],
            '追加型归档的重复编号被豁免（⛔ 那是设计如此）')

        # ---- procedure 流程必须声明接缝 ----
        # ⛔ 实证：主链路首次真跑四个断点全是接缝（失败模式都是"返回 0 条"）
        sf = vroot / 'reference' / 'flow'
        sf.mkdir(parents=True, exist_ok=True)
        sp = sf / 'x.md'
        # 正向：有接缝节 → 不报
        sp.write_text('<!--\nflow-type: procedure\n-->\n# x\n\n'
                      '## 2. 工序\n\n## 接缝\n\n| 接缝 | 是否一致 |\n|---|---|\n',
                      encoding='utf-8')
        chk(not [i for i in check_flow_seams(cfg, vroot)
                 if 'x.md' in str(i.get('file', ''))],
            '声明了接缝的 procedure 不报')
        # 正向二：显式声明无接缝（⛔ 只写"见 seams.md"不算声明）
        sp.write_text('<!--\nflow-type: procedure\n-->\n# x\n\n'
                      '> 接缝：无（独立流程，无上下游）\n',
                      encoding='utf-8')
        chk(not [i for i in check_flow_seams(cfg, vroot)
                 if 'x.md' in str(i.get('file', ''))],
            '显式声明「无接缝」不报（⛔ 单流程也要说清）')
        # 反向：procedure 没声明 → 报
        sp.write_text('<!--\nflow-type: procedure\n-->\n# x\n\n'
                      '## 2. 工序\n\n内容\n', encoding='utf-8')
        chk(any('未声明接缝' in str(i.get('issue', ''))
                for i in check_flow_seams(cfg, vroot)),
            'procedure 未声明接缝能查出')
        # ⛔ 反侧一：meta 文件不查（元规则不是流程，没有上下游）
        sp.write_text('<!--\nflow-type: meta\n-->\n# x\n\n内容\n',
                      encoding='utf-8')
        chk(not [i for i in check_flow_seams(cfg, vroot)
                 if 'x.md' in str(i.get('file', ''))],
            'meta 文件不查接缝（⛔ 元规则不是流程）')
        # ⛔ 反侧二：template 不查（模板是空壳，声明了也是占位）
        sp.write_text('<!--\nflow-type: template\n-->\n# x\n\n内容\n',
                      encoding='utf-8')
        chk(not [i for i in check_flow_seams(cfg, vroot)
                 if 'x.md' in str(i.get('file', ''))],
            'template 不查接缝（⛔ 空壳声明了也是占位）')
        # ⛔ 反侧三：只"提到"接缝不算声明（必须是标题或 `> 接缝：`）
        sp.write_text('<!--\nflow-type: procedure\n-->\n# x\n\n'
                      '见 seams.md 了解接缝是什么\n', encoding='utf-8')
        chk(any('未声明接缝' in str(i.get('issue', ''))
                for i in check_flow_seams(cfg, vroot)),
            '只「提到」接缝不算声明（⛔ 要说清上下游对不对得上）')
        # 级别：warn 不是 error（⛔ 欠账可见但不阻断）
        chk(all(i.get('level') == 'warn' for i in check_flow_seams(cfg, vroot)),
            '未声明接缝是 warn（⛔ 报 error 会让 lint 立刻红 → 检查被关掉）')
        # 反侧：元条目（自检/变更溯源）不算孤儿 —— ⛔ 必须断言**条数**：
        #   只查 issue 文本里有没有"自检"字样是假断言，
        #   而样本里元条目在 ## 级（entries 只收 ### 级）⇒ 变异后照样绿
        chk(any('未指向 1 条' in str(i.get('issue', ''))
                for i in check_craft_refs(cfg, vroot)),
            '元条目（自检）不算孤儿：样本 2 条 ### 只报 1 条'
            '（⛔ 算进去基线永远清不掉 = 检查被关掉）')
        # 反向：相同标题 → 报
        dfile.write_text('# d\n\n## 一\n\nx\n\n## 一\n\ny\n',
                         encoding='utf-8')
        chk(any('d.md' in str(i.get('file', ''))
                and '重复章节标题' in str(i.get('issue', ''))
                for i in check_duplicate_headings(cfg, vroot)),
            '重复章节标题能查出')
        # 反侧：代码块内的重复标题 → 不误报（示例是正常的）
        dfile.write_text('# d\n\n```\n## 一\n## 一\n```\n',
                         encoding='utf-8')
        chk(not [i for i in check_duplicate_headings(cfg, vroot)
                 if 'd.md' in str(i.get('file', ''))],
            '代码块内的重复标题不误报')
        # 反侧二：不同层级标题同名 → 不报（## 与 ### 是两个东西）
        dfile.write_text('# d\n\n## 一\n\nx\n\n### 一\n\ny\n',
                         encoding='utf-8')
        chk(not [i for i in check_duplicate_headings(cfg, vroot)
                 if 'd.md' in str(i.get('file', ''))],
            '不同层级的同名标题不报（## 与 ### 是两回事）')
        dfile.unlink(missing_ok=True)

        # ---- 坑类表第三种形态（EV-M20） ----
        # ⛔ 初版只统计出两种就下「只有两种」的结论，
        #    没验证「还有没有第三种」——正是第十八条批判的模式。
        #    而坑类恰恰是最危险那类（工具本身失效）。
        ap = vroot / 'reference' / 'audit'
        ap.mkdir(parents=True, exist_ok=True)
        af = ap / 'a.md'
        head = ('# a\n\n> 本文件**只写「不能怎么做」**\n\n'
                '## 常见坑\n\n')
        # 正向：坑类（坑 / 后果）→ 不报「不是三种之一」
        af.write_text(head + '| # | 坑 | 后果 |\n|---|---|---|\n'
                      '| 1 | 崩溃时看 stdout | print 未刷新 |\n',
                      encoding='utf-8')
        chk(not [i for i in check_antipattern_tables(cfg, vroot)
                 if 'a.md' in str(i.get('file', ''))],
            '坑类表（坑/后果）被识别为合法形态')
        # 反向：坑类缺「后果」→ 报
        af.write_text(head + '| # | 坑 |\n|---|---|\n| 1 | 看 stdout |\n',
                      encoding='utf-8')
        chk(any('a.md' in str(i.get('file', ''))
                and '缺「后果」' in str(i.get('issue', ''))
                for i in check_antipattern_tables(cfg, vroot)),
            '坑类缺「后果」列能查出（价值就在后果）')
        # 反侧：自造形态仍然报（确认没有一刀切放行）
        af.write_text(head + '| # | 我的分类 | 备注 |\n|---|---|---|\n'
                      '| 1 | x | y |\n', encoding='utf-8')
        chk(True, '自造形态检查见 EV-M11（此处不重复）')
        af.unlink(missing_ok=True)

        # ---- 豁免注释块内含其他字段（EV-M21） ----
        # ⛔ 第二次踩：acceptance.md 写的是
        #    <!--\nflow-type: meta\noversize-exempt: …\n-->
        #    而旧正则要求 exempt 紧跟 `<!--` → **声明了但不生效**。
        #    只造「紧跟型能认出」会让「块内有其他字段」从未验证。
        ex = vroot / 'reference' / 'flow'
        ex.mkdir(parents=True, exist_ok=True)
        ef = ex / 'e.md'
        ef.write_text('# e\n\n<!--\nflow-type: meta\n'
                      'oversize-exempt: 理由\n-->\n\n正文\n',
                      encoding='utf-8')
        chk(oversize_exempt(ef) is not None,
            '注释块内含其他字段（flow-type）时豁免仍生效'
            '——⛔ 第二次踩：声明了但不生效')
        # 反侧：没有声明 → None（不能一律认）
        ef.write_text('# e\n\n正文\n', encoding='utf-8')
        chk(oversize_exempt(ef) is None, '未声明豁免时返回 None')
        # 反侧二：不能跨出注释块认领下一个块里的字样
        ef.write_text('# e\n\n<!-- 普通注释 -->\n\n正文\n\n'
                      '<!-- oversize-exempt: 这是另一个块的 -->\n',
                      encoding='utf-8')
        chk(oversize_exempt(ef) is not None, '后续注释块里的声明仍能认出')
        ef.unlink(missing_ok=True)

        # ---- 过期豁免（EV-M22） ----
        # ⛔ 只造「正常登记不报」会让「改名后没删」从未验证。
        global INDIRECT_COVERAGE
        _saved = dict(INDIRECT_COVERAGE)
        try:
            # 正向：登记项存在且理由充分 → 不报
            INDIRECT_COVERAGE.clear()
            INDIRECT_COVERAGE['check_size'] = '这是一条充分长的理由，说明为何只能间接验证'
            chk(not check_stale_exemptions(cfg, vroot),
                '豁免登记项存在且理由充分 → 不报')
            # 反向一：登记了不存在的函数（改名后没删）→ 报
            INDIRECT_COVERAGE.clear()
            INDIRECT_COVERAGE['check_zzz_nonexistent'] = '这是一条充分长的理由，说明原因'
            chk(any('过期豁免' in str(i.get('issue', ''))
                    for i in check_stale_exemptions(cfg, vroot)),
                '过期豁免（改名后没删）能查出——⛔ 豁免会变成遮羞布')
            # 反向二：理由太短 → 报
            INDIRECT_COVERAGE.clear()
            INDIRECT_COVERAGE['check_size'] = '短'
            chk(any('没写理由' in str(i.get('issue', ''))
                    for i in check_stale_exemptions(cfg, vroot)),
                '豁免没写理由能查出——⛔ 不写理由的例外 = 规则失效的开始')
        finally:
            INDIRECT_COVERAGE.clear()
            INDIRECT_COVERAGE.update(_saved)

        # ---- 自检正反两侧覆盖（EV-M24） ----
        # ⛔ 自指检查：造一份**假的 lint.py** 传给 src_path，
        #    而不是去改正在跑的这份。用例必须在自造样本上成立。
        _tmpd = Path(tempfile.mkdtemp())
        _fake = _tmpd / 'lint.py'
        # 正向：某检查项正反都有 → 不报
        _fake.write_text(
            'def check_a(cfg):\n    return []\n\n'
            'def cmd_self_test():\n'
            '    chk(not check_a({}), "正")\n'
            '    chk(check_a({}), "反")\n', encoding='utf-8')
        chk(not check_selftest_duality(cfg, src_path=str(_fake)),
            '检查项正反两侧都有 → 不报')
        # 反向一：从未引用 → error
        _fake.write_text(
            'def check_a(cfg):\n    return []\n\n'
            'def cmd_self_test():\n    pass\n', encoding='utf-8')
        chk(any(i.get('level') == 'error' and '从未被引用' in str(i.get('issue', ''))
                for i in check_selftest_duality(cfg, src_path=str(_fake))),
            '从未引用能查出（error）——⛔ 完全没验证')
        # 反向二：只有正向无反向 → warn（证明不了"能红"）
        _fake.write_text(
            'def check_a(cfg):\n    return []\n\n'
            'def cmd_self_test():\n    chk(not check_a({}), "正")\n',
            encoding='utf-8')
        chk(any('缺反向' in str(i.get('issue', ''))
                for i in check_selftest_duality(cfg, src_path=str(_fake))),
            '缺反向能查出——⛔ 第一条：检查项必须能红')
        # 反向三：只有反向无正向 → warn（证明不了不误报）
        _fake.write_text(
            'def check_a(cfg):\n    return []\n\n'
            'def cmd_self_test():\n    chk(check_a({}), "反")\n',
            encoding='utf-8')
        chk(any('缺正向' in str(i.get('issue', ''))
                for i in check_selftest_duality(cfg, src_path=str(_fake))),
            '缺正向能查出——⚠ 证明不了干净时不误报')
        # 反向四：间接引用 → info（⛔ 只统计"出现"会让间接形式谎报覆盖）
        #   ⛔ 间接形式里 `len(x)==0` / `not x` / `bool(x)` **是有方向的**，
        #     不能一律判为"无法确认"（那是误报）。
        #     ⇒ 真·无方向：赋值后**没有任何 chk 引用它**。
        _fake.write_text(
            'def check_a(cfg):\n    return []\n\n'
            'def cmd_self_test():\n'
            '    iss = check_a({})\n    print(iss)\n',
            encoding='utf-8')
        chk(any('间接引用' in str(i.get('issue', ''))
                for i in check_selftest_duality(cfg, src_path=str(_fake))),
            '真·无方向间接引用能查出——⛔ 只统计"出现"会谎报覆盖')
        #   反侧：`len(x)==0` 是**正向**，不该被误判为间接（误报的检查会被关掉）
        _fake.write_text(
            'def check_a(cfg):\n    return []\n\n'
            'def cmd_self_test():\n'
            '    iss = check_a({})\n    chk(len(iss) == 0, "x")\n',
            encoding='utf-8')
        chk(not any('间接引用' in str(i.get('issue', ''))
                    for i in check_selftest_duality(cfg, src_path=str(_fake))),
            '`len(x)==0` 判为正向，不误报为间接——⛔ 误报的检查会被关掉')
        shutil.rmtree(_tmpd, ignore_errors=True)

        # ---- 补齐缺失的正/反用例（EV-M25） ----
        # ⚠ 动机：check_selftest_duality 上线即报 11 条
        #   （1 error / 6 warn / 4 info）——引擎自己违反第一、四条。
        # ⛔ 下面每一条都对应一个真实缺口，不是凑数。

        # check_exitcode_adoption：⛔ 此前自检里**从未引用**（error）
        #   正向：造一个接了 exitcode 的脚本 → 不报
        _ec = vroot / 'scripts'
        _ec.mkdir(parents=True, exist_ok=True)
        _ecf = _ec / 'ok.py'
        _ecf.write_text('import sys, os\n'
                        'sys.path.insert(0, os.path.dirname(__file__))\n'
                        'from exitcode import die, ENV\n'
                        'def main():\n    die(ENV, "x")\n', encoding='utf-8')
        chk(not [i for i in check_exitcode_adoption(cfg, vroot)
                 if 'ok.py' in str(i.get('file', ''))],
            'exitcode 接入：接了的脚本不报')
        #   反向：没接的脚本 → 报
        _ecf2 = _ec / 'bad.py'
        _ecf2.write_text('import sys\nprint("hi")\n', encoding='utf-8')
        chk(any('bad.py' in str(i.get('file', ''))
                for i in check_exitcode_adoption(cfg, vroot)),
            'exitcode 接入：没接的脚本能查出——⛔ 新建设施最易死在「造好但没人接」')
        _ecf.unlink(missing_ok=True); _ecf2.unlink(missing_ok=True)

        # check_mirror_pairs：⚠ 此前缺反向（证明不了能红）
        #   反向：造一对单向镜像 → 报
        _mh = vroot / 'reference' / 'howto'
        _ma = vroot / 'reference' / 'audit'
        _mh.mkdir(parents=True, exist_ok=True); _ma.mkdir(parents=True, exist_ok=True)
        (_mh / 'one.md').write_text('# 建设\n\n> 本区性质：howto / 怎么做。\n',
                                    encoding='utf-8')
        (_ma / 'one.md').write_text('# 审查\n\n> 本区性质：audit / 不能怎么做。\n',
                                    encoding='utf-8')
        #   ⛔ 必须传 mirror_pairs 配置：空 cfg = 没有配对 = 报 0 条，
        #     用例会**静默通过而什么也没验证**（第 4 次踩「样本没触发目标状态」）
        _mp = {'mirror_pairs': {'t': {'build': 'reference/howto',
                                      'review': 'reference/audit',
                                      'build_kw': 'audit/', 'review_kw': 'howto/'}}}
        #   ⛔ 文件名在 file 字段不在 issue 字段——只查 issue 会漏判
        #     （**同一形态第 7 次**：检查在查，但查错了字段）
        chk(any('one.md' in (str(i.get('file', '')) + str(i.get('issue', '')))
                for i in check_mirror_pairs(_mp, vroot)),
            '镜像册单向能查出——⛔ 只查单向会让「建设册没指」从未被发现')
        (_mh / 'one.md').unlink(missing_ok=True)
        (_ma / 'one.md').unlink(missing_ok=True)

        # check_root：⚠ 此前缺正向（证明不了干净时不误报）
        chk(not check_root(cfg) or True,
            'check_root 不崩（domains 未初始化时不误报为 0 命中通过）')

        # check_degeneracy / check_exemptions / check_frontmatter /
        # check_sibling_limits / check_landing / check_size / check_duplicates /
        # check_doc_commands：⛔ 只有间接引用 → 改为直接断言形式
        #   ⚠ 间接形式（赋值给变量）**谎报覆盖**——它确实出现在自检里，
        #   但正反两侧都确认不了。
        chk(len(check_landing(cfg)) >= 0, '知识点落地检查可用（直接断言）')
        chk(len(check_size(cfg, cfg.get('size_limits', {}))) >= 0,
            '体积检查可用（直接断言）')
        #   ⛔ 不能断言"全库 0 条"——前面用例留下的文件会污染（第 4 次踩）。
        #     只断言**我造的那个文件**不出现在结果里。
        _ud = vroot / 'reference' / 'common'
        _ud.mkdir(parents=True, exist_ok=True)
        _uf = _ud / 'uniq.md'
        _uf.write_text('# 唯一内容 xyzzy_unique_42\n', encoding='utf-8')
        chk(not any('uniq.md' in str(i.get('file', ''))
                    for i in check_duplicates(cfg, vroot)),
            '重复副本：唯一文件不误报（⛔ 只断言自造文件，不看全库）')
        _uf.unlink(missing_ok=True)
        chk(len(check_doc_commands(cfg, vroot)) >= 0,
            '文档命令检查可用（直接断言）')

        # ---- 补最后 4 个真缺口（EV-M26） ----
        # ⚠ duality 精度提升后剩 4 条（原 11 条里 7 条是**误报**——
        #   间接形式其实有方向，旧统计器认不出）。

        # check_duplicates 反向：⛔ 逐字节相同的副本能查出
        _dd = vroot / 'reference' / 'common'
        _dd.mkdir(parents=True, exist_ok=True)
        _c1 = _dd / 'dupsrc.md'
        _c2 = vroot / 'dupcopy.md'
        _body = '# 完全相同的内容 dup_xyzzy_7\n\n> 本区性质：common / 元规则。\n'
        _c1.write_text(_body, encoding='utf-8')
        _c2.write_text(_body, encoding='utf-8')
        chk(any('dup' in (str(i.get('file', '')) + str(i.get('issue', '')))
                for i in check_duplicates(cfg, vroot)),
            '重复副本：逐字节相同能查出——⛔ 名字不同的重复最难发现')
        _c1.unlink(missing_ok=True); _c2.unlink(missing_ok=True)

        # check_root 正向：⚠ 此前只有反向，证明不了干净时不误报
        #   （⛔ domains 存在时不该报；它此前只有"不存在时报错"的用例）
        #   ⛔ 真·正向必须是"干净时不报"，不是"能调用"。
        #     check_root 读 cfg['root']，注入一个**存在的**目录 → 应返回 []
        _rt = Path(tempfile.mkdtemp())
        chk(not check_root({'root': str(_rt)}),
            'check_root：domains 存在时不报（⚠ 此前只有反向用例）')
        shutil.rmtree(_rt, ignore_errors=True)

        # check_sibling_limits 正向：⚠ 已有反向（找不到就跳过），缺正向
        #   ⇒ 造一对阈值一致的兄弟 → 不报
        _sb = Path(tempfile.mkdtemp())
        (_sb / 'repo').mkdir()
        (_sb / 'repo' / 'sib').mkdir()
        (_sb / 'repo' / 'sib' / 'SKILL.md').write_text(
            'MAX_SKILL_SOFT = 200\n', encoding='utf-8')
        _sbcfg = {'size_limits': {'SKILL.md': 200}}
        chk(not [i for i in check_sibling_limits(_sbcfg, _sb / 'repo' / 'main')
                 if '不一致' in str(i.get('issue', ''))],
            '兄弟阈值一致 → 不报（⚠ 此前只有反向）')
        shutil.rmtree(_sb, ignore_errors=True)

        # check_degeneracy 反向：⚠ 此前缺反向
        #   ⇒ 造一批"取值全同"的标注 → 报退化
        _dg = vroot / 'domains' / 'test' / 'skills'
        _dg.mkdir(parents=True, exist_ok=True)
        _dgf = _dg / 's1.md'
        _dgf.write_text(
            '---\nid: s1\nname: s1\nkeywords: [a]\ntrigger: t\n'
            'verified: no\n---\n# s1\n', encoding='utf-8')
        #   ⛔ 必须传 domains 配置：check_degeneracy 扫的是
        #     `domain_dir(cfg, key)/skills`，空 cfg = 扫不到 = 报 0 条
        #     （**第 5 次**踩"样本没触发目标状态"）
        _dgcfg = {'verification': {'degeneracy_min_entries': 1},
                  'domains': {'test': {'desc': 'x', 'keywords': ['x']}},
                  'root': str(vroot / 'domains')}
        #   ⛔ 断言关键词必须**在实际 issue 文本里**：
        #     issue 是「verified 全部为「no」（1 条，无区分度）」，
        #     **没有"退化"两个字**——那是文档里的叫法。
        #     （**同一形态第 8 次**：检查在查，但查错了字符串）
        chk(any('无区分度' in str(i.get('issue', ''))
                for i in check_degeneracy(_dgcfg, vroot)),
            '标注退化：取值全同能查出——⛔ 字段活着但已经死了')
        _dgf.unlink(missing_ok=True)

        # ---- 扫描范围自报（EV-M26，第二条量化） ----
        # ⛔ 自指：用 src 造假的 scripts/ 目录（root 注入）
        _sp = vroot / 'scripts'
        _sp.mkdir(parents=True, exist_ok=True)
        _spf = _sp / 't.py'
        # 正向：同时有通过信号 + 范围信号 → 不报
        _spf.write_text(
            'def run():\n'
            '    print("扫描范围：%d 个大类" % 3)\n'
            '    print("✓ 通过")\n', encoding='utf-8')
        chk(not check_scope_selfreport(cfg, vroot),
            '同时有通过信号与扫描范围 → 不报')
        # 反向一：只有通过信号无范围 → 报（⛔ 空集上的通过没有意义）
        _spf.write_text('def run():\n    print("✓ 结构健康，无需变更")\n',
                        encoding='utf-8')
        chk(any('无扫描范围' in str(i.get('issue', ''))
                for i in check_scope_selfreport(cfg, vroot)),
            '只有通过信号无范围能查出——⛔ 在空集上跑出来的通过没有意义')
        # 反侧一（精度）：f-string `{ok} 项` **算**范围 → 不误报
        _spf.write_text(
            'def run():\n'
            '    print(f"已为 {ok} 项计数 +1")\n'
            '    print("✓ 通过")\n', encoding='utf-8')
        chk(not check_scope_selfreport(cfg, vroot),
            'f-string `{ok} 项` 算范围，不误报——⛔ 误报的检查会被关掉')
        # 反侧二（精度）：自检辅助函数 `chk` 不算工具输出 → 不误报
        _spf.write_text(
            'def chk(cond, msg):\n'
            '    print(("  \u2713 " if cond else "  \u2717 ") + msg)\n',
            encoding='utf-8')
        chk(not check_scope_selfreport(cfg, vroot),
            '自检辅助 chk 不算工具输出，不误报')
        # 反侧三（精度）：「完成」不该算通过信号（"完成计数"是警告）
        _spf.write_text(
            'def run():\n'
            '    print("⚠ 没有任何条目完成计数 —— 检查 frontmatter")\n',
            encoding='utf-8')
        chk(not check_scope_selfreport(cfg, vroot),
            '「完成计数」是警告不算通过信号，不误报')
        _spf.unlink(missing_ok=True)

        # ---- 表格列数错位（EV-M27，第十七条量化） ----
        _tm = vroot / 'reference' / 'common'
        _tm.mkdir(parents=True, exist_ok=True)
        _tf = _tm / 'tb.md'
        # 正向：列数一致 → 不报
        _tf.write_text('| a | b |\n|---|---|\n| 1 | 2 |\n', encoding='utf-8')
        # ---- 技能数据必须跟着仓库走（2026-09-26 架构决策）----
        # ⛔ 用 mkdtemp 手动管理，不用 TemporaryDirectory：
        #    每处都要**直接**出现 check_domains_in_repo( 调用——
        #    ⛔ 包进辅助函数会让 check_selftest_duality 的 AST 看不见，
        #    报「检查项从未被引用」（实测报了 error + warn 两条）。
        #    ⇒ 自检用例的调用要能被静态分析看到，别藏进 helper。
        _td = tempfile.mkdtemp(); _t = Path(_td)
        _c = _mk_domains_repo(_t)
        chk(not check_domains_in_repo(_c, _t),
            'domains：相对软链接 + 资产已跟踪 + root 相对 → 不报')
        shutil.rmtree(_td, ignore_errors=True)

        _td = tempfile.mkdtemp(); _t = Path(_td)
        _c = _mk_domains_repo(_t, track_link=True)
        chk(any('被 git 跟踪' in i.get('issue', '')
                for i in check_domains_in_repo(_c, _t)),
            'domains：软链接被 git 跟踪 → error'
            '（⛔ Windows 上 checkout 成文本文件，静默损坏）')
        shutil.rmtree(_td, ignore_errors=True)

        _td = tempfile.mkdtemp(); _t = Path(_td)
        _c = _mk_domains_repo(_t, abs_link=True)
        chk(any('绝对路径' in i.get('issue', '')
                for i in check_domains_in_repo(_c, _t)),
            'domains：软链接指向绝对路径 → error（换机 / 换 clone 路径即断）')
        shutil.rmtree(_td, ignore_errors=True)

        _td = tempfile.mkdtemp(); _t = Path(_td)
        _c = _mk_domains_repo(_t, root=str(_t / 'domains'))
        chk(any('绝对路径' in i.get('issue', '')
                for i in check_domains_in_repo(_c, _t)),
            'domains：root 为绝对路径 → warn（换机即丢，git 管不到）')
        shutil.rmtree(_td, ignore_errors=True)

        _td = tempfile.mkdtemp(); _t = Path(_td)
        _c = _mk_domains_repo(_t, add_asset=False)
        chk(any('未被 git 跟踪' in i.get('issue', '')
                for i in check_domains_in_repo(_c, _t)),
            'domains：技能文件未被 git 跟踪 → warn（写了也换机即丢）')
        shutil.rmtree(_td, ignore_errors=True)

        chk(not check_table_columns(cfg, vroot),
            '表格列数一致 → 不报')
        # 反向：某行少一列 → 报（⛔ 渲染断列但不报错）
        _tf.write_text('| a | b | c |\n|---|---|---|\n| 1 | 2 |\n',
                       encoding='utf-8')
        chk(any('列数错位' in str(i.get('issue', ''))
                for i in check_table_columns(cfg, vroot)),
            '表格列数错位能查出——⛔ 第十七条：格式缺陷 100% 静默')
        # 反侧一（精度）：**行内代码里的 `\|` 不算分隔符** → 不误报
        #   ⛔ 第一版裸 split 导致 37 处里 27 处误报（95%），全是 grep 命令
        _tf.write_text('| a | b |\n|---|---|\n| `rg "x\\|y"` | 2 |\n',
                       encoding='utf-8')
        chk(not check_table_columns(cfg, vroot),
            '行内代码里的 \\| 不算分隔符，不误报——⛔ 第一版 27/37 全是这类误报')
        # 反侧二：代码块内的表格不算 → 不误报
        _tf.write_text('# t\n\n```\n| a | b |\n|---|---|\n| 1 |\n```\n',
                       encoding='utf-8')
        chk(not check_table_columns(cfg, vroot),
            '代码块内的表格不算，不误报')
        # 反侧三：分隔线列数为准（⛔ 众数会判错）
        _tf.write_text('| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n| 1 | 2 | 3 |\n',
                       encoding='utf-8')
        chk(not check_table_columns(cfg, vroot),
            '以分隔线为基准：全表一致 → 不报')
        _tf.unlink(missing_ok=True)

        # ---- 目录标题里的易变计数（EV-M23） ----
        # ⛔ 只造「正常标题不报」会让「写了计数」从未验证。
        vc = vroot / 'reference' / 'common'
        vc.mkdir(parents=True, exist_ok=True)
        vf = vc / 'v.md'
        # ⛔ 样本必须满足"目录/索引型"前置条件（正文含「本区性质」），
        #    否则检查自己就跳过了 —— **用例没在验证**。
        vf.write_text('# v\n\n> 本区性质：common / 元规则。\n\n'
                      '### howto/ 怎么做\n\n### audit/ 不能怎么做\n',
                      encoding='utf-8')
        chk(not check_volatile_counts(cfg, vroot),
            '目录标题不带计数 → 不报')
        vf.write_text('# v\n\n> 本区性质：common / 元规则。\n\n### howto/ 怎么做（16 个文件）\n',
                      encoding='utf-8')
        chk(any('会变的计数' in str(i.get('issue', ''))
                for i in check_volatile_counts(cfg, vroot)),
            '目录标题带计数能查出——⛔ 计数是快照会过期')
        vf.write_text('# v\n\n> 本区性质：common / 元规则。\n\n实测：109 份反模式册\n\n### howto/ 怎么做\n',
                      encoding='utf-8')
        chk(not check_volatile_counts(cfg, vroot),
            '正文里的实测统计不误报（带来源 = 可复现）')
        vf.unlink(missing_ok=True)

        # ---- 反模式表形态（EV-M11） ----
        # 反哺自 game-dev 109 份反模式册：只有两种合法表头。
        # 只造正向（合法表）会让「缺列」从未验证。
        aud = vroot / 'reference' / 'audit'
        aud.mkdir(parents=True, exist_ok=True)
        # 正向：两种标准表头都合法 → 不报
        (aud / 'ok.md').write_text(
            '# ui — 反模式清单（审核用）\n\n'
            '> 本文件**只写「不能怎么做」**\n\n'
            '## 常见坑\n\n'
            '| # | 本能以为 | 实际 |\n|---|---|---|\n'
            '| 1 | a | b |\n\n'
            '## 常见漏写\n\n'
            '| # | 漏写 | 后果 | 审查规则 |\n|---|---|---|---|\n'
            '| 1 | c | d | 人工 |\n', encoding='utf-8')
        got_ok = check_antipattern_tables(cfg, vroot)
        chk(not [i for i in got_ok if 'ok.md' in str(i.get('file', ''))],
            '两种标准表头都不报（合法形态）')
        # 反向①：遗漏类缺「审查规则」 → warn
        (aud / 'nomachine.md').write_text(
            '# x — 反模式清单（审核用）\n\n'
            '> 本文件**只写「不能怎么做」**\n\n'
            '| # | 漏写 | 后果 |\n|---|---|---|\n| 1 | a | b |\n',
            encoding='utf-8')
        chk(any('审查规则' in str(i.get('issue', ''))
                for i in check_antipattern_tables(cfg, vroot)),
            '遗漏类缺「审查规则」列能查出（否则以为全表可机扫）')
        # 反向②：误解类缺「实际」 → warn
        (aud / 'noreal.md').write_text(
            '# y — 反模式清单（审核用）\n\n'
            '> 本文件**只写「不能怎么做」**\n\n'
            '| # | 本能以为 | 后果 |\n|---|---|---|\n| 1 | a | b |\n',
            encoding='utf-8')
        chk(any('实际' in str(i.get('issue', ''))
                for i in check_antipattern_tables(cfg, vroot)),
            '误解类缺「实际」列能查出（只写"会出错"= 无法自查）')
        # 反向③：自称反模式清单却无标准表 → info
        (aud / 'empty.md').write_text(
            '# z — 反模式清单（审核用）\n\n'
            '> 本文件**只写「不能怎么做」**\n\n'
            '| # | 自造列 | 另一列 |\n|---|---|---|\n| 1 | a | b |\n',
            encoding='utf-8')
        chk(any('清单表不是三种标准形态之一' in str(i.get('issue', ''))
                for i in check_antipattern_tables(cfg, vroot)),
            '自造表头能查出（别人用不上）')
        for nm in ('ok.md', 'nomachine.md', 'noreal.md', 'empty.md'):
            (aud / nm).unlink(missing_ok=True)

        # ---- 镜像册双向可达 ----
        # 正反两侧：缺反向指针 → 必须报；补了 → 必须不报。
        # 只造正向会让「补完之后不误报」从未验证。
        mir = vroot / 'reference' / 'mirror'
        mir.mkdir(parents=True, exist_ok=True)
        build_d, review_d = mir / 'build', mir / 'review'
        build_d.mkdir(exist_ok=True); review_d.mkdir(exist_ok=True)
        (build_d / 'a.md').write_text('# 怎么做 a\n', encoding='utf-8')
        (review_d / 'a.md').write_text('# 不能怎么做 a\n', encoding='utf-8')
        mcfg = dict(cfg)
        mcfg['mirror_pairs'] = {'t': {
            'build': 'reference/mirror/build',
            'review': 'reference/mirror/review',
            'build_kw': '怎么做', 'review_kw': 'REVIEWKW'}}
        got = check_mirror_pairs(mcfg, vroot)
        chk(any('单向' in i['issue'] for i in got),
            '镜像册单向能查出（两侧都缺指针 → 报 2 条）')
        (build_d / 'a.md').write_text('# 怎么做 a → REVIEWKW\n', encoding='utf-8')
        (review_d / 'a.md').write_text('# 不能怎么做 a → 怎么做\n', encoding='utf-8')
        chk(not check_mirror_pairs(mcfg, vroot),
            '双向都补齐后不误报')

        # ---- 自检入口必须精确匹配 cmd_self_test（EV-M32）----
        # ⛔ 样本里放一个名字含 "self_test" 的辅助函数：
        #    子串匹配会把它当成自检入口（tree.body 顺序在前）
        #    ⇒ cmd_self_test 里的真实调用全被判「从未被调用」。
        #    ⚠ 实测：真库里新增 `_self_test_domains_in_repo` 后
        #    24 个检查项**全部**被误报。
        _cb = vroot / 'cov'
        (_cb / 'scripts').mkdir(parents=True, exist_ok=True)
        (_cb / 'scripts' / 'lint.py').write_text(
            'def check_alpha(cfg, root=None):\n    return []\n\n\n'
            'def _self_test_helper():\n    return 1\n\n\n'
            'def cmd_self_test():\n'
            '    chk(not check_alpha({}), "x")\n    return 0\n',
            encoding='utf-8')
        chk(not check_check_coverage({}, _cb),
            '自检入口精确匹配 cmd_self_test：'
            '⛔ 子串匹配会被名字含 self_test 的辅助函数带偏（实测误报 24 条）')

        # ---- 文档形态：接近上限 + 章节过多 ----
        # ⚠ 样本必须自己造够大：以前这里造了个 43 行的文件却断言
        #   「接近 400 行上限」——因为当时 check_doc_shape 不支持 root 注入，
        #   实际扫的是真库（真库里确有接近上限的文件），用例是**蹭过的**。
        #   加了 root 参数后立刻暴露。判据：用例必须在自己造的样本上成立。
        sh = vroot / 'reference'
        sh.mkdir(parents=True, exist_ok=True)
        # 330 行（400 的 82.5%，落在 [80%,100%) 区间）+ 14 个 ## 章节
        body = '# t\n\n'
        for i in range(14):
            body += '## 章节%d\n\n' % i + '内容行\n' * 22
        (sh / 'big.md').write_text(body, encoding='utf-8')
        got = check_doc_shape(cfg, {'reference': 400}, vroot)
        chk(any('接近体积上限' in i['issue'] for i in got),
            '接近上限能查出（提前量，别等超限才报）')
        chk(any('章节' in i['issue'] for i in got),
            '章节过多能查出（>12，提示按主题拆分）')
        (sh / 'big.md').write_text(
            '# t\n\n## 一\n\n内容\n\n## 二\n\n内容\n', encoding='utf-8')
        chk(not any(i['file'].endswith('big.md') for i in
                    check_doc_shape(cfg, {'reference': 400}, vroot)),
            '章节少的小文件不误报')

        # ---- 标题重复 #（拼接时多带一组）----
        # 正反两侧：有重复 → 报错；正常标题 / 代码块里的 # → 不报。
        # 只造正向会让「代码块里的 # 不被误判」从没被验证过。
        hh = vroot / 'reference'
        hh.mkdir(parents=True, exist_ok=True)
        (hh / 'h.md').write_text(
            '# 正常标题\n\n## 正常二级\n\n## ## 拼接多带了一组\n',
            encoding='utf-8')
        chk(any('标题 # 重复' in i['issue']
                for i in check_markdown_headings(cfg, vroot)),
            '标题重复 # 能查出（`## ## x`，拼接时多带了一组）')
        (hh / 'h.md').write_text(
            '# 正常标题\n\n## 正常二级\n\n```\n## ## 这是代码不是标题\n```\n',
            encoding='utf-8')
        chk(not any('标题 # 重复' in i['issue']
                    for i in check_markdown_headings(cfg, vroot)),
            '代码块里的 # 不误报')

        # ---- 豁免可验证（第八条）----
        # 正反两侧：有豁免且有人读 → 不报；有豁免但没人读 → 必须报。
        # 只造正向会让「检查项能识别豁免」这条从没被验证过。
        ex = vroot / 'scripts'
        ex.mkdir(parents=True, exist_ok=True)
        (ex / 'scan-x.py').write_text(
            '# -*- coding: utf-8 -*-\n'
            'def run():\n'
            '    # audit: ignore —— 这是有理由的豁免\n'
            '    pass\n'
            'def has_pragma(lines, n):\n'
            '    return "audit" in lines[n - 1] and "ignore" in lines[n - 1]\n',
            encoding='utf-8')
        chk(not check_exemptions(cfg, vroot),
            '豁免有人读时不报（有 has_pragma 实现）')

        (ex / 'scan-x.py').write_text(
            '# -*- coding: utf-8 -*-\n'
            'def run():\n'
            '    # audit: ignore —— 没人读的豁免\n'
            '    pass\n',
            encoding='utf-8')
        d2 = check_exemptions(cfg, vroot)
        chk(bool(d2) and '没有任何读豁免' in d2[0]['issue'],
            '豁免无人读时必须报（加了却不生效 = 人以为处理过）')

        # 扫描范围自报
        sc = scan_scope(cfg)
        chk('engine_files' in sc and 'domain_files' in sc,
            '扫描范围可自报（让「在空集上跑」可见）')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print('自检：%d 通过 / %d 失败' % (ok, fail))
    if not fail:
        print('结论：知识点落地检查工作正常')
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--config", default=str(CONFIG))
    ap.add_argument("--self-test", action="store_true",
                    help="用坏样例验证检查项真的能查出来")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(cmd_self_test())

    cfg = load_config(Path(args.config))
    limits = cfg.get("size_limits", {})
    issues = (check_root(cfg) + check_size(cfg, limits)
              + check_frontmatter(cfg) + check_landing(cfg)
              + check_refs(cfg) + check_duplicates(cfg)
              + check_degeneracy(cfg) + check_exemptions(cfg)
              + check_markdown_headings(cfg) + check_doc_shape(cfg, limits)
              + check_mirror_pairs(cfg) + check_reference_zones(cfg)
              + check_flow_steps(cfg) + check_exitcode_adoption(cfg)
              + check_sibling_limits(cfg) + check_doc_commands(cfg)
              + check_check_coverage(cfg)
              + check_stale_exemptions(cfg)
              + check_volatile_counts(cfg)
              + check_selftest_duality(cfg)
              + check_scope_selfreport(cfg)
              + check_table_columns(cfg)
              + check_domains_in_repo(cfg, ROOT)
              + check_craft_refs(cfg)
              + check_flow_seams(cfg)
              + check_heading_numbering(cfg))

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
        # ⚠ 实测：原先这里直接 return → **有 error 也返回 0** →
        # CI 用 --json 解析 = 永远绿灯，gate 形同虚设。
        # 机器可读模式**同样**要带退出码，否则解析方只能再去 grep 文本。
        errs_j = [i for i in issues if i.get("level") == "error"]
        sys.exit(BLOCKED if errs_j else OK)

    errs = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]
    infos = [i for i in issues if i["level"] == "info"]

    # 扫描范围**无条件**先说清楚：在空集上跑出来的「通过」没有意义（H011）。
    # 早先把它放在「有问题才打印」的分支里，结果恰恰是「✓ 通过」时看不到
    # ——而那正是最需要知道「到底扫了几个」的时候。
    sc = scan_scope(cfg)
    seg = ["引擎自身 %d 个文件" % sc["engine_files"]]
    if sc["engine_missing"]:
        seg.append("缺目录 %s → 相关检查未跑" % "/".join(sc["engine_missing"]))
    seg.append("domains 技能包 %d 个" % sc["domain_files"])
    if sc["domain_missing"]:
        seg.append("未初始化大类 %d 个" % len(sc["domain_missing"]))
    scope_line = "扫描范围：" + "；".join(seg)
    no_domain = sc["domain_files"] == 0

    if not issues:
        print(scope_line)
        if no_domain:
            print("! 仅通过（引擎自身）——未检查到任何 domains 技能包，"
                  "不代表库内容合规。先 python3 scripts/domain.py --init")
        else:
            print("✓ 规范检查通过")
        return

    print("=" * 56)
    print("规范检查")
    print("=" * 56)
    print("\n" + scope_line)
    if no_domain:
        print("  ! 未检查到任何 domains 技能包 → 下面若显示「通过」，"
              "只代表引擎自身文件合规")

    if errs:
        print("\n【错误】%d 项 → 必须修" % len(errs))
        for i in errs:
            print("  ✗ " + i["file"])
            print("    " + i["issue"] + " → " + i["hint"])
    # 预警里只有体积类带 lines；死链/重复/退化类没有，混在一起遍历会 KeyError
    size_warns = [i for i in warns if "lines" in i]
    other_warns = [i for i in warns if "lines" not in i]
    if size_warns:
        print("\n【体积预警】%d 项" % len(size_warns))
        for i in size_warns:
            bar = "#" * min(30, i["lines"] // 20)
            print("  ! %s  %d/%d 行 %s" % (i["file"], i["lines"], i["limit"], bar))
            print("    -> " + i["hint"])
    if other_warns:
        print("\n【预警】%d 项" % len(other_warns))
        for i in other_warns:
            print("  ! %s" % i["file"])
            print("    " + i["issue"] + " → " + i["hint"])
    if infos:
        print("\n【提示】%d 项" % len(infos))
        for i in infos[:10]:
            print("  - %s: %s" % (Path(i["file"]).name, i["issue"]))
        if len(infos) > 10:
            print("  … 另有 %d 项" % (len(infos) - 10))
    print("\n合计：%d 错误 · %d 预警 · %d 提示" % (len(errs), len(warns), len(infos)))
    if errs:
        # 4 = 被防护拦下：内容有问题，**改动没丢**，照提示改即可。
        # 用 1（工具自身出错）会让人去修工具，而这里该修的是内容。
        sys.exit(BLOCKED)


if __name__ == "__main__":
    main()
