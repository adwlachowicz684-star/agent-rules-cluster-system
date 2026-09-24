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
import json
import subprocess
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from domain import load_config, domain_dir, domain_root, CONFIG  # noqa: E402
from exitcode import OK, ERR, USAGE, ENV, BLOCKED, die, help_text  # 码表：0/1/2/3/4

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
EXEMPT_RX = re.compile(r'<!--\s*oversize-exempt\s*:\s*(.+?)\s*-->',
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


def check_size(cfg, limits):
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

    chk(ROOT / "SKILL.md", "SKILL.md", "SKILL.md", "细节下沉到 reference/")
    for name in ("_hot.md", "_preferences.md", "_commands.md"):
        chk(ROOT / "SKILLS" / name, "SKILLS/" + name, name,
            "拆分为多个文件或归档低频条目")
    # rglob 而非 glob：reference/ 下已分为 howto/audit/flow/common/craft
    # 五个子区，只扫顶层会让子区的文档**完全不参与体积检查**。
    for f in sorted((ROOT / "reference").rglob("*.md")):
        chk(f, str(f.relative_to(ROOT)), "reference")

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

    RX = re.compile(r'(?<![A-Za-z0-9_/.-])'
                    r'((?:scripts|reference)/[A-Za-z0-9_./-]+\.(?:py|sh|md))')
    for f in targets:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in RX.finditer(text):
            rel = m.group(1)
            if (base / rel).exists():
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
              + check_sibling_limits(cfg) + check_doc_commands(cfg))

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
