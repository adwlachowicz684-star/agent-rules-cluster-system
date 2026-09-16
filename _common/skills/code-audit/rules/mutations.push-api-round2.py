#!/usr/bin/env python3
"""变异定义 · 第二批（push_api.py 三轮审查提炼，9 条判据）

用法（与 PR #1 回填的 27 条同格式）：
    python3 scripts/mutate.py --defs rules/mutations.push-api-round2.json

每条变异：把已修复的代码**改回缺陷形态**，扫描器必须报出（KILLED）。
若扫描器在变异体上不报 → SURVIVED，说明规则有漏。
若变异无法应用（找不到锚点）→ NOT_APPLIED，需更新锚点而非静默跳过。
"""

MUTATIONS = [
    # ---------------- A-19：清理必须覆盖 return 路径 ----------------
    {
        "id": "M-A19-01",
        "rule": "A-19",
        "desc": "把 finally 清理改回 try/except，使 return 路径不清理",
        "file": "target/sample_push.py",
        "anchor": "    finally:\n        if branch and not committed:\n            cleanup(branch)",
        "mutated": "    except BaseException:\n        cleanup(branch)\n        raise",
        "expect": "KILLED",
        "why": "验证规则能否识别『清理挂在 except 而块内有 return』",
    },
    {
        "id": "M-A19-02",
        "rule": "A-19",
        "desc": "在已用 finally 的块内新增一个 return，验证规则仍能判定安全",
        "file": "target/sample_push.py",
        "anchor": "        do_push()\n        committed = True",
        "mutated": "        if not todo:\n            return\n        do_push()\n        committed = True",
        "expect": "SURVIVED",
        "why": "负向对照：finally 覆盖 return，规则**不应**报错；报了说明误报",
    },

    # ---------------- A-24：辅助文件命名空间 ----------------
    {
        "id": "M-A24-01",
        "rule": "A-24",
        "desc": "把隔离目录改回用户数据目录 + 后缀拼接",
        "file": "target/sample_conflict.py",
        "anchor": '    with open(os.path.join(AUX_DIR, safe + ".remote"), "wb") as f:',
        "mutated": '    with open(os.path.join(ROOT, rel + ".remote"), "wb") as f:',
        "expect": "KILLED",
        "why": "验证规则能否识别『写用户目录 + 用户可能采用的命名模式』",
    },
    {
        "id": "M-A24-02",
        "rule": "A-24",
        "desc": "移除写入前的存在性检查",
        "file": "target/sample_conflict.py",
        "anchor": '    if os.path.exists(target):\n        raise SystemExit(f"{target} 已存在，拒绝覆盖（疑似你的业务文件）")\n',
        "mutated": "",
        "expect": "KILLED",
        "why": "存在性检查是次选修法，移除后必须报",
    },
    {
        "id": "M-A24-03",
        "rule": "A-24",
        "desc": "负向对照：写系统临时目录，不应报",
        "file": "target/sample_conflict.py",
        "anchor": "AUX_DIR = \"/var/lib/mytool/aux\"",
        "mutated": "AUX_DIR = tempfile.mkdtemp(prefix=\"mytool-aux-\")",
        "expect": "SURVIVED",
        "why": "临时目录同样安全，规则不应区分两者",
    },

    # ---------------- PY-14：生成器多次消费 ----------------
    {
        "id": "M-PY14-01",
        "rule": "PY-14",
        "desc": "移除 list() 包裹，使其退化为二次消费生成器",
        "file": "target/sample_preview.py",
        "anchor": "d = list(difflib.unified_diff(old, new, n=0))",
        "mutated": "d = difflib.unified_diff(old, new, n=0)",
        "expect": "KILLED",
        "why": "核心变异：第二次 sum() 恒为 0（实测 -2 → -0）",
    },
    {
        "id": "M-PY14-02",
        "rule": "PY-14",
        "desc": "只消费一次的生成器，不应报",
        "file": "target/sample_preview.py",
        "anchor": "add = sum(1 for l in d if l.startswith(\"+\") and not l.startswith(\"+++\"))\nsub = sum(1 for l in d if l.startswith(\"-\") and not l.startswith(\"---\"))",
        "mutated": "add = sum(1 for l in d if l.startswith(\"+\") and not l.startswith(\"+++\"))",
        "expect": "SURVIVED",
        "why": "负向对照：单次消费合法",
    },
    {
        "id": "M-PY14-03",
        "rule": "PY-14",
        "desc": "生成器用于流程判定（升 P0 场景）",
        "file": "target/sample_preview.py",
        "anchor": "matches = list(re.finditer(pat, text))",
        "mutated": "matches = re.finditer(pat, text)",
        "expect": "KILLED",
        "why": "用于判定时后果更重，规则必须报且应升级别",
    },

    # ---------------- PY-15：输入方向编码容错 ----------------
    {
        "id": "M-PY15-01",
        "rule": "PY-15",
        "desc": "移除输入方向的 errors=（保留输出方向的，模拟局部修复）",
        "file": "target/sample_hash.py",
        "anchor": 'subprocess.run(cmd, input=s, capture_output=True,\n               text=True, encoding="utf-8", errors="surrogateescape")',
        "mutated": 'subprocess.run(cmd, input=s, capture_output=True, text=True)',
        "expect": "KILLED",
        "why": "最易误判为已修的形态：同一文件里输出方向已有 errors",
    },
    {
        "id": "M-PY15-02",
        "rule": "PY-15",
        "desc": "无 input 参数的 subprocess，不应报",
        "file": "target/sample_hash.py",
        "anchor": 'subprocess.run(["git", "hash-object", rel], capture_output=True, text=True)',
        "mutated": 'subprocess.run(["git", "hash-object", rel], capture_output=True, text=True, errors="surrogateescape")',
        "expect": "SURVIVED",
        "why": "负向对照：无 input 则不涉及输入方向",
    },

    # ---------------- A-25：单向属性写入 ----------------
    {
        "id": "M-A25-01",
        "rule": "A-25",
        "desc": "移除 else 反向分支",
        "file": "target/sample_write.py",
        "anchor": "    else:\n        os.chmod(path, 0o644)",
        "mutated": "",
        "expect": "KILLED",
        "why": "移除后权限只能单向漂移（实测：远端 100644 拉不回本地 0755）",
    },
    {
        "id": "M-A25-02",
        "rule": "A-25",
        "desc": "负向对照：无条件的属性写入，不应报",
        "file": "target/sample_write.py",
        "anchor": '    with open(path, "w") as f:\n        f.write(data)',
        "mutated": '    with open(path, "w", encoding="utf-8") as f:\n        f.write(data)',
        "expect": "SURVIVED",
        "why": "与属性单向性无关",
    },

    # ---------------- K-36：错误分类宽泛子串 ----------------
    {
        "id": "M-K36-01",
        "rule": "K-36",
        "desc": "往命中词表加入语义模糊项",
        "file": "target/sample_merge.py",
        "anchor": '_NEED_UPDATE = ("Base branch was modified", "not up to date")',
        "mutated": '_NEED_UPDATE = ("Base branch was modified", "not up to date",\n               "not mergeable", "Required status check")',
        "expect": "KILLED",
        "why": "加入后实测会把已合并 PR 的 405 误判为 need_update",
    },
    {
        "id": "M-K36-02",
        "rule": "K-36",
        "desc": "丢弃上游原始错误信息",
        "file": "target/sample_merge.py",
        "anchor": '        print(f"上游原文：{e}")',
        "mutated": "",
        "expect": "KILLED",
        "why": "丢弃原文后用户无法自行判断，只能依赖（可能错误的）分类",
    },

    # ---------------- K-37：分页不翻页 ----------------
    {
        "id": "M-K37-01",
        "rule": "K-37",
        "desc": "移除翻页循环",
        "file": "target/sample_list.py",
        "anchor": "    out, page = [], 1\n    while True:\n        batch = api(\"GET\", f\"{path}&per_page=100&page={page}\") or []\n        out += batch\n        if len(batch) < 100:\n            break\n        page += 1\n    return out",
        "mutated": "    return api(\"GET\", f\"{path}&per_page=100\") or []",
        "expect": "KILLED",
        "why": "移除后超 100 条静默漏报",
    },
    {
        "id": "M-K37-02",
        "rule": "K-37",
        "desc": "负向对照：明确告警截断，不应报",
        "file": "target/sample_list.py",
        "anchor": "    return api(\"GET\", f\"{path}&per_page=100\") or []",
        "mutated": "    r = api(\"GET\", f\"{path}&per_page=100\") or []\n    if len(r) == 100:\n        print(\"⚠ 结果可能不完整\")\n    return r",
        "expect": "SURVIVED",
        "why": "有告警即可，不算静默漏报",
    },

    # ---------------- B-02 扩展：破坏性入口白名单 ----------------
    {
        "id": "M-B02-01",
        "rule": "B-02",
        "desc": "移除分支白名单校验",
        "file": "target/sample_delete.py",
        "anchor": "    if branch == PROTECTED_BRANCH:\n        raise SystemExit(f\"不能用 {PROTECTED_BRANCH} 作为删除目标\")\n",
        "mutated": "",
        "expect": "KILLED",
        "why": "移除后 --delete-branch main 实测直删主干",
    },
    {
        "id": "M-B02-02",
        "rule": "B-02",
        "desc": "移除状态修改入口的成员资格校验（resolve 后门）",
        "file": "target/sample_resolve.py",
        "anchor": "    if rel not in (state.get(\"conflicts\") or []):\n        raise SystemExit(f\"{rel} 不在冲突列表中\")\n",
        "mutated": "",
        "expect": "KILLED",
        "why": "移除后对任意文件调用即可改写基线，绕过第一层校验",
    },

    # ---------------- R-08 扩展：持锁阻塞输入 ----------------
    {
        "id": "M-R08-01",
        "rule": "R-08",
        "desc": "移除锁等待的超时与进度提示",
        "file": "target/sample_lock.py",
        "anchor": "    if time.time() - start > 300:\n        raise SystemExit(\"等待锁超时，另一个进程可能已挂起\")\n    print(f\"  等待其他进程… {int(time.time()-start)}s\")",
        "mutated": "",
        "expect": "KILLED",
        "why": "移除后第二个进程表现为无声卡死",
    },
]


if __name__ == "__main__":
    import json
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "rules/mutations.push-api-round2.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": "push_api.py 三轮审查（2026-09-16）",
                "note": "第二批；PR #1 已回填 27 条为第一批",
                "mutations": MUTATIONS,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"已写出 {len(MUTATIONS)} 条变异定义 → {out}")
    killed = sum(1 for m in MUTATIONS if m["expect"] == "KILLED")
    survived = sum(1 for m in MUTATIONS if m["expect"] == "SURVIVED")
    print(f"  KILLED（必须报出）: {killed}")
    print(f"  SURVIVED（负向对照，不应报）: {survived}")
