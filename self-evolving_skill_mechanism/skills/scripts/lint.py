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
from domain import load_config, domain_dir, domain_root, CONFIG  # noqa: E402

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
                            "或删除。见 reference/knowledge-landing.md"})

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
EXEMPT_RX = re.compile(r'<!--\s*oversize-exempt\s*:\s*(.+?)\s*-->')


def oversize_exempt(p):
    """返回豁免理由；没有则返回 None。"""
    try:
        head = p.read_text(encoding="utf-8")[:2000]
    except Exception:
        return None
    m = EXEMPT_RX.search(head)
    return m.group(1).strip() if m else None


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
    """解析 YAML frontmatter → dict。没有则返回 {}。"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.strip().startswith("#"):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


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
        fm = _frontmatter(text)

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
              + check_degeneracy(cfg))

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
        return

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
        sys.exit(1)


if __name__ == "__main__":
    main()
