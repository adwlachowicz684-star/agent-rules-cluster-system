#!/usr/bin/env python3
"""通过 GitHub Git Data API 推送本地改动到远端 main。

背景
----
沙盒到 github.com 的 git / https 协议被网关拦成 403（带 token 也一样），
只有 api.github.com 通，所以推送只能走 Git Data API。

但 API 的 tree 更新是**整文件替换**，不带三方合并与冲突检测：
只要 ref 能快进（parent 取的是远端最新提交），本地某个文件的全文就会
直接顶掉远端同名文件——如果远端该文件已被别人改动，改动会静默消失。
因此本脚本加了四层防护（见 main() 里的注释）。

用法
----
  python3 push_api.py                 # 自动检测本地改动 → 预览 → 确认 → 推送
  python3 push_api.py --dry-run       # 只预览，不推送
  python3 push_api.py --yes           # 跳过交互确认（自动化时用，风险自负）
  python3 push_api.py -m "提交信息"    # 指定提交信息（推荐，否则用自动兜底）
  python3 push_api.py a.js b.js       # 显式指定文件（默认自动检测 git 改动）
  python3 push_api.py --init-baseline # 只把远端当前各文件状态记为基线，不推送
  python3 push_api.py --reset-baseline  # 基线已存在时强制重设（会丢弃旧基线！）
  python3 push_api.py --mark-synced   # 同步本地到远端最新后跑一次（解除过期拦截）
  python3 push_api.py --force-overwrite  # 明知远端有他人改动仍要覆盖（慎用）

约定
----
  · 基线状态写在 /data/workspace/.push-sync.json（仓库外，不入库）
  · 首次使用必须先跑 --init-baseline，否则推送会被拒绝
"""
import base64
import difflib
import json
import os
import re
import subprocess
import sys
import time

# 从环境变量读取。后续接入工具后，由工具内的加密编码注入。
#
# 为什么不放明文：GitHub 的 secret scanning 会**直接拒绝**包含有效凭据的提交
# （HTTP 422 + bypass_placeholders），写了就推不上去。这是平台强制，不是风格建议。
TOKEN = os.environ.get("GITHUB_TOKEN", "")


def _token():
    """惰性校验：放这里而不是模块顶层，是为了让 import 不被环境变量缺失打断。"""
    if not TOKEN:
        raise SystemExit("未设置 GITHUB_TOKEN 环境变量（token 禁止写进文件）")
    return TOKEN
OWNER, REPO = "adwlachowicz684-star", "tauriTools"
BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
ROOT = "/data/workspace/tauriTools"
BRANCH = "main"
STATE_PATH = "/data/workspace/.push-sync.json"
MSG_FALLBACK = "chore: 通过 API 推送本地改动"

STATE_VERSION = 2                     # 1=只记 sha；2=记 (mode, sha)

MAX_BLOB_BYTES = 10 * 1024 * 1024     # 超过这个大小直接拒推（应改走 Git LFS）
MAX_PREVIEW_LINES = 20000             # 预览用 diff 的行数上限，超了只报行数差
MAX_PREVIEW_BYTES = 256 * 1024        # 超过这个大小不拉远端内容做预览
VALID_MODES = ("100644", "100755", "120000")
DEFAULT_TIMEOUT = 60                  # 默认 curl 超时（秒）


# ---------------------------------------------------------------- 基础

def _timeout_for(size_bytes):
    """超时按体积动态算：每 MB 加 10 秒，30 秒保底，10 分钟封顶。"""
    return min(600, max(30, 30 + size_bytes // (1024 * 1024) * 10))


def api(method, path, payload=None, retries=3, timeout=None):
    """调 GitHub API。path 以 http 开头时按绝对 URL 用。

    显式检查 HTTP 状态码：curl -s 会把 403/404/422 的错误体也原样返回，
    不检查的话调用方只能靠 "sha" in resp 这种启发式猜，排查成本很高。

    重试策略（**区分幂等性**）：
      · 超时（curl 退出码 28）**一律不重试** —— 服务端可能已生效，
        重试会重复建对象、重复消耗限流额度
      · 5xx：GET / POST 都退避重试（服务端未处理）
      · 429：只对 GET 重试（限流下重发非幂等写风险更大）
    """
    url = path if path.startswith("https") else BASE + path
    max_time = str(timeout or DEFAULT_TIMEOUT)
    for attempt in range(1, retries + 1):
        cmd = [
            "curl", "-s", "--max-time", max_time, "-X", method, url,
            "-H", f"Authorization: Bearer {_token()}",
            "-H", "Accept: application/vnd.github+json",
            "-H", "Content-Type: application/json",
            "-w", "\n%{http_code}",
        ]
        if payload is not None:
            cmd += ["--data-binary", "@-"]
            out = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True)
        else:
            out = subprocess.run(cmd, capture_output=True, text=True)

        if out.returncode != 0:
            if out.returncode == 28:
                raise SystemExit(
                    f"请求超时（{max_time}s）{method} {url}\n"
                    f"  不重试：服务端可能已生效，重试会重复创建。请确认远端状态后重跑。"
                )
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise SystemExit(f"curl 失败（退出码 {out.returncode}）: {out.stderr}")

        body, _, code = out.stdout.rpartition("\n")
        code = code.strip()
        try:
            data = json.loads(body or "{}")
        except json.JSONDecodeError:
            raise SystemExit(f"响应非 JSON (HTTP {code}): {body[:400]}")

        if code.startswith("2"):
            return data
        retryable = code in ("500", "502", "503", "504") or (code == "429" and method == "GET")
        if retryable and attempt < retries:
            time.sleep(2 ** attempt)
            continue
        raise SystemExit(f"API {method} {url} → HTTP {code}: {body[:400]}")


def git(*args, check=False, raw=False):
    """跑 git。check=True 时非 0 直接中止。

    默认不中断但**必须告警**：只看 stdout 会让失败完全静默——
    `git add` 部分路径被 .gitignore 拦下时退出码为 1，
    正常文件虽然进了暂存区，调用方却以为全部成功。

    raw=True 时**不做 strip**。

    为什么需要：porcelain 格式是定长的「XY + 1空格 + 路径」，
    未暂存修改的 X 位就是空格（" M path"）。strip() 会把这个空格吃掉，
    整个串左移一位，于是 item[3:] 切出来的路径**丢掉首字符**
    （`_common/...` → `common/...`）。
    后果是静默的：该文件的本地 sha 取不到，lmap 回落到 git 索引里的旧值，
    被判「已与远端一致」跳过——改动推不上去，还以为推成功了。
    """
    proc = subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        msg = f"git {' '.join(args)} 退出码 {proc.returncode}"
        if proc.stderr.strip():
            msg += f"：{proc.stderr.strip()[:300]}"
        if check:
            raise SystemExit(msg)
        print(f"  ! {msg}")
    return proc.stdout if raw else proc.stdout.strip()


def safe_rel(rel):
    """把用户/脚本给的路径规范成仓库内相对路径；越界的返回 None。

    越界校验必须用 realpath 而非 normpath：normpath 只做字符串规整，
    会放过「仓库内指向外部的符号链接」——`etcdir -> /etc` 时
    `etcdir/passwd` 能通过 normpath 检查，open() 却读到 /etc/passwd。

    但返回值仍按 normpath 算，避免把 `link`（合法内部链接）改写它的目标路径。
    """
    if not rel or os.path.isabs(rel) or rel.startswith("~"):
        return None
    full = os.path.normpath(os.path.join(ROOT, rel))
    out = os.path.relpath(full, ROOT)
    if out == ".." or out.startswith(".." + os.sep):
        return None
    root = os.path.realpath(ROOT)
    real = os.path.realpath(full)
    if real != root and not real.startswith(root + os.sep):
        return None
    return out


def local_blob_sha(rel):
    """本地文件的 git blob sha（与 GitHub 的 blob sha 同一算法）

    符号链接特殊处理：git 存的 symlink blob 内容是「目标路径字符串」，
    而 hash-object 默认会跟随链接读取目标文件内容，两者 sha 不一致。
    """
    full = os.path.join(ROOT, rel)
    if os.path.islink(full):
        out = subprocess.run(["git", "-C", ROOT, "hash-object", "--stdin"],
                             input=os.readlink(full), capture_output=True, text=True)
        return out.stdout.strip()
    return git("hash-object", rel)


def remote_state_map(ref_sha):
    """一次性取远端整棵树的 path → (mode, sha)

    mode 一起取：只比 sha 会漏掉「只改了可执行位」的变更（见 T-11）。
    """
    tree = api("GET", f"/git/trees/{ref_sha}?recursive=1")
    if tree.get("truncated"):
        raise SystemExit("远端 tree 被截断（仓库过大），无法做覆盖校验，已中止")
    if "tree" not in tree:
        # 别静默降级成空表：那会让每个文件都落到「基线未记录」分支，
        # 表现得像「疑似他人改动」，把网络/限流问题伪装成冲突。
        raise SystemExit(f"取远端 tree 失败: {json.dumps(tree, ensure_ascii=False)[:300]}")
    return {t["path"]: (t.get("mode", "100644"), t["sha"])
            for t in tree["tree"] if t["type"] == "blob"}


def load_state():
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"{STATE_PATH} 已损坏（{e}）。请手动检查，或用 "
                f"`--reset-baseline` 重建基线（重建后文件级防护会短暂失效）。"
            )


def save_state(state):
    """原子写：写 tmp 再 os.replace，避免写一半崩溃留下坏 JSON。"""
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def migrate_state(state, rstate):
    """v1（只记 sha）→ v2（记 mode+sha）。

    v1 基线里没有 mode，迁移时取**远端当前**的 mode 填上——
    v1 的 sha 本就是远端 sha，远端 mode 是当时最接近事实的值。
    """
    if state.get("version") == STATE_VERSION and all(
            isinstance(v, dict) for v in state.get("files", {}).values()):
        return state, False
    files = {}
    for p, v in state.get("files", {}).items():
        if isinstance(v, dict):
            files[p] = v
        else:
            files[p] = {"mode": rstate.get(p, ("100644", v))[0], "sha": v}
    state["files"] = files
    state["version"] = STATE_VERSION
    state.setdefault("synced_commit", state.get("base_commit"))
    return state, True


_CHANGES_CACHE = None


def detect_changes():
    """用 git 检测工作区相对本地基线的改动（含未跟踪文件）

    用 -z 避免 git 对含空格/中文/引号的路径做 quoting 转义（省掉反转义）。
    加 --no-renames：重命名会退化成 "D 旧路径" + "?? 新路径"，旧路径被跳过、
    新路径当新增推送，正好符合本脚本「不支持删除」的语义，也绕开了 -z 下
    重命名记录的字段顺序问题。
    """
    global _CHANGES_CACHE
    if _CHANGES_CACHE is not None:
        return _CHANGES_CACHE

    out = git("status", "--porcelain", "-z", "--untracked-files=all",
              "--no-renames", raw=True)
    fields = out.split("\0")
    paths, i = [], 0
    while i < len(fields):
        item = fields[i]
        i += 1
        if not item or len(item) < 3:
            continue
        xy, path = item[:2], item[3:]     # 标准格式 "XY<space>path"
        if not path:
            continue
        # 解析校验 + 存在性校验：见 git() 的 raw 参数说明。
        # porcelain 是定长的「XY + 1空格 + 路径」，前导空格被 strip 会让
        # 路径丢首字符，进而取不到该文件的工作副本 sha，被误判「已与远端
        # 一致」跳过——改动推不上去却报成功。
        if not re.fullmatch(r"[ MADRCU?!]{2}", xy):
            raise SystemExit(
                f"git status 解析异常：状态位 {xy!r} 不合法"
                f"（路径 {path[:60]!r}）。porcelain 是定长格式，"
                f"前导空格被 strip 会让路径丢首字符。")
        if not os.path.exists(os.path.join(ROOT, path)):
            raise SystemExit(
                f"git status 解析异常：路径 {path[:80]!r} 在仓库内不存在。\n"
                f"porcelain 是定长格式（XY+空格+路径），前导空格被 strip 后\n"
                f"整个串左移一位，路径首字符会被切掉。请检查 git() 的 raw 参数。")
        if "D" in xy:                     # 删除：本脚本不处理
            print(f"  ! 跳过已删除文件（脚本不支持删除）：{path}")
            continue
        if "R" in xy or "C" in xy:        # 防御：理论上 --no-renames 后不会走到
            if i < len(fields):
                path = fields[i]
                i += 1
        paths.append(path)

    _CHANGES_CACHE = paths
    return paths


# ---------------------------------------------------------------- 本地状态

_EXEC_RELIABLE = None


def _exec_bit_reliable():
    """该环境能否靠 os.access 判断可执行位（惰性探测，只探一次）。

    两个条件都要满足，缺一不可：
      1. git 跟踪执行位（core.fileMode != false）
      2. 文件系统真的区分权限（不是所有文件都 0777）

    容器 / 挂载目录常两条都不满足：core.fileMode=false，或权限一律 0777
    导致 os.access(X_OK) 恒为真——此时推断会把 .md / .json 全判成 100755。
    """
    global _EXEC_RELIABLE
    if _EXEC_RELIABLE is not None:
        return _EXEC_RELIABLE

    if git("config", "--bool", "core.fileMode").strip() == "false":
        _EXEC_RELIABLE = False
        print("  ! core.fileMode=false：git 不跟踪可执行位，新文件一律按 100644 处理")
        return _EXEC_RELIABLE

    # 挑一个明显不该可执行的已跟踪文件探一下文件系统
    for line in git("ls-files").splitlines():
        if not line.endswith((".md", ".txt", ".json", ".py", ".yml", ".yaml")):
            continue
        probe = os.path.join(ROOT, line)
        if os.path.isfile(probe) and os.access(probe, os.X_OK):
            _EXEC_RELIABLE = False
            print(f"  ! 文件系统不区分权限（{os.path.basename(probe)} 也是可执行的）："
                  f"os.access 恒为真，新文件一律按 100644 处理")
            return _EXEC_RELIABLE
        break

    _EXEC_RELIABLE = True
    return _EXEC_RELIABLE


def local_state_map():
    """本地 path → (mode, sha)：以 git 索引为唯一权威来源。

    新文件（索引里没有）不靠 os.access 推断——先过 _exec_bit_reliable()，
    环境不可靠时**回退 100644**：宁可丢执行位，也不要把文档推成可执行。
    """
    m = {}
    for line in git("ls-files", "-s").splitlines():
        if "\t" not in line:
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        mode = parts[0] if parts[0] in VALID_MODES else "100644"
        m[path] = (mode, parts[1] if len(parts) > 1 else "")

    for rel in detect_changes():
        full = os.path.join(ROOT, rel)
        if os.path.islink(full):
            m[rel] = ("120000", local_blob_sha(rel))
        elif os.path.isfile(full):
            idx = m.get(rel)
            if idx:                       # 已跟踪：索引 mode 是唯一权威
                mode = idx[0] if idx[0] in ("100644", "100755") else "100644"
            else:                          # 新文件：环境不可靠就用保守值
                mode = "100755" if (_exec_bit_reliable() and os.access(full, os.X_OK)) else "100644"
            m[rel] = (mode, local_blob_sha(rel))
    return m


def init_baseline(head_sha, rstate):
    """把远端当前状态记为基线。

    这一步本质是「无条件信任远端当前状态」，无法区分差异是别人改的还是你改的，
    所以必须把「本地 ≠ 远端」的文件列出来让人过目：这些文件后续会被当作你的改动
    整文件覆盖上去。
    """
    state = {
        "version": STATE_VERSION,
        "remote": f"{OWNER}/{REPO}",
        "branch": BRANCH,
        "base_commit": head_sha,
        # 本地副本基于哪个远端 commit —— P0-1 的过期校验靠它。
        # 建基线时本地尚未改动，等价于「已同步到 head_sha」。
        "synced_commit": head_sha,
        "files": {p: {"mode": m, "sha": s} for p, (m, s) in rstate.items()},
    }
    save_state(state)
    print(f"✅ 基线已写入 {STATE_PATH}（记录 {len(state['files'])} 个文件，未做任何推送）")

    lmap = local_state_map()
    diff = [p for p in rstate if p in lmap and lmap[p][1] != rstate[p][1]]
    if diff:
        print(f"\n⚠️  本地与远端不一致的文件 {len(diff)} 个（会被视为你的改动，推送时整文件覆盖）：")
        for p in diff[:20]:
            print(f"   - {p}")
        if len(diff) > 20:
            print(f"   … 其余 {len(diff) - 20} 个")
        print("   若其中含他人改动，请先把本地同步到远端最新再推。")


def mark_synced(state, head_sha, rstate):
    """标记「本地副本已同步到远端 head_sha」，解除 P0-1 的过期拦截。

    顺带刷新「本地已与远端一致」的条目基线，避免同步后仍报旧的差异。
    """
    lmap = local_state_map()
    refreshed = 0
    for p, (rmode, rsha) in rstate.items():
        lm = lmap.get(p)
        if not lm or lm[1] != rsha:
            continue
        cur = state["files"].get(p)
        if not isinstance(cur, dict) or cur.get("sha") != rsha or cur.get("mode") != rmode:
            state["files"][p] = {"mode": rmode, "sha": rsha}
            refreshed += 1
    state["synced_commit"] = head_sha
    state["base_commit"] = head_sha
    save_state(state)
    print(f"✅ 已标记本地副本基于远端 {head_sha[:8]}（刷新 {refreshed} 条已一致的基线）")


# ---------------------------------------------------------------- 预览

def _remote_blob_lines(sha, size_hint=None):
    """取远端 blob 的文本行；拿不到、二进制或超大返回 None。

    注：GitHub 对超过 1MB 的 blob 在 JSON 响应里不返回 content，此时降级。
    """
    if size_hint is not None and size_hint > MAX_PREVIEW_BYTES:
        return None
    data = api("GET", f"/git/blobs/{sha}")
    if data.get("encoding") != "base64" or not data.get("content"):
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", "replace").splitlines()
    except Exception:
        return None


def _local_lines(rel, mode):
    """本地文件文本行；symlink 直接展示它指向哪（这才是要推上去的内容）。"""
    full = os.path.join(ROOT, rel)
    if mode == "120000":
        return [f"-> {os.readlink(full)}"]
    try:
        if os.path.getsize(full) > MAX_PREVIEW_BYTES:
            return None
        with open(full, "rb") as f:
            if b"\0" in f.read(64 * 1024):      # 粗判二进制
                return None
        with open(full, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return None


def preview(todo, rstate, lmap):
    """预览：直接对比「本地文件 vs 远端最新内容」。

    不能用 `git diff HEAD`：本地 HEAD 只是拉取时的快照，而实际推送是以
    base_tree=head_sha（远端最新）为底的，远端比你新时 diff 基准就错了，
    会出现「确认的内容 ≠ 实际推上去的内容」。
    """
    print(f"\n待推送 {len(todo)} 个文件（对比基准 = 远端 {BRANCH} 最新内容，非本地 HEAD）：")
    for rel in todo:
        try:
            size = os.path.getsize(os.path.join(ROOT, rel))
        except OSError:
            size = 0
        lmode = lmap.get(rel, ("100644", ""))[0]
        r = rstate.get(rel)
        if r is None:
            print(f"   A {rel}   新增（{size} B，mode {lmode}）")
            continue
        rmode, rsha = r
        mode_changed = (lmode != rmode)
        if mode_changed:
            print(f"   M {rel}   mode {rmode} → {lmode}（权限/类型变更）")
        old, new = _remote_blob_lines(rsha), _local_lines(rel, lmode)
        if old is None or new is None:
            why = "超过预览上限" if size > MAX_PREVIEW_BYTES else "二进制或过大"
            if mode_changed:
                print(f"        （{why}，跳过内容预览，本地 {size} B）")
            else:
                print(f"   M {rel}   {why}，跳过内容预览（本地 {size} B）")
            continue
        if len(old) > MAX_PREVIEW_LINES or len(new) > MAX_PREVIEW_LINES:
            print(f"   M {rel}   远端 {len(old)} 行 → 本地 {len(new)} 行")
            continue
        d = difflib.unified_diff(old, new, n=0)
        add = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
        sub = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
        if mode_changed and add == 0 and sub == 0:
            continue                       # 上面已报 mode 变更，内容无变化
        print(f"   M {rel}   +{add} / -{sub}")


def default_msg(todo):
    if len(todo) == 1:
        return f"chore: 更新 {todo[0]}"
    if len(todo) <= 3:
        return "chore: 更新 " + "、".join(todo)
    return MSG_FALLBACK


# ---------------------------------------------------------------- 参数

def parse_args(argv):
    opts = {"dry": False, "yes": False, "init": False, "reset": False,
            "force": False, "mark_synced": False, "msg": None}
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--dry-run":
            opts["dry"] = True
        elif a in ("--yes", "-y"):
            opts["yes"] = True
        elif a == "--init-baseline":
            opts["init"] = True
        elif a == "--reset-baseline":
            opts["reset"] = True
        elif a == "--mark-synced":
            opts["mark_synced"] = True
        elif a == "--force-overwrite":
            opts["force"] = True
        elif a in ("-m", "--message"):
            if i + 1 >= len(argv):
                raise SystemExit("-m/--message 缺少参数")
            opts["msg"] = argv[i + 1]
            i += 1
        elif a.startswith("--message="):
            opts["msg"] = a.split("=", 1)[1]
        elif a.startswith("--"):
            raise SystemExit(f"未知参数: {a}")
        else:
            rest.append(a)
        i += 1
    return opts, rest


# ---------------------------------------------------------------- 主流程

def main():
    opts, explicit = parse_args(sys.argv[1:])
    dry, yes = opts["dry"], opts["yes"]
    init, reset, force = opts["init"], opts["reset"], opts["force"]

    ref = api("GET", f"/git/ref/heads/{BRANCH}")
    head_sha = ref.get("object", {}).get("sha")
    if not head_sha:
        raise SystemExit(f"取不到远端 {BRANCH}：{json.dumps(ref)[:300]}")
    print(f"远端 {BRANCH} = {head_sha}")

    rstate = remote_state_map(head_sha)
    print(f"远端文件 {len(rstate)} 个")

    state = load_state()

    # -------- 基线建立 / 重设 --------
    if init or reset or state is None:
        if state is None:
            if not (init or reset):
                print("\n⚠️  没有基线记录（首次使用），无法判断远端文件是否被他人改动过。")
                print("   请先跑一次 `python3 push_api.py --init-baseline` 建立基线，再推送。")
                return
            init_baseline(head_sha, rstate)
            return
        if not reset:
            # 旧基线是无条件覆盖的话，第一层文件级防护会随之失效，必须拦一道。
            print(f"\n⚠️  基线已存在（记录于 commit {str(state.get('base_commit'))[:8]}），未做任何改动。")
            print("   确要丢弃旧基线并重设，请加 `--reset-baseline`：")
            print("   重设后「远端文件是否被他人改过」将失去参照，请确认远端已是最新。")
            return
        ans = "y" if yes else input(
            f"\n重设基线会丢弃现有 {len(state.get('files', {}))} 条记录，"
            f"文件级防覆盖校验将暂时失效。继续？(y/N) "
        ).strip().lower()
        if ans != "y":
            print("已取消")
            return
        init_baseline(head_sha, rstate)
        return

    # -------- 基线归属校验 --------
    # 换仓库推时旧基线仍生效，会让所有文件报「可能被他人改动」——
    # 方向虽然是 fail-closed，但把人引向错误的排查方向。
    if state.get("remote") not in (None, f"{OWNER}/{REPO}"):
        raise SystemExit(
            f"基线属于另一个仓库：{state.get('remote')}，当前目标是 {OWNER}/{REPO}。\n"
            f"  不是他人改动，是仓库换了。请换用对应的 STATE_PATH，或用 --reset-baseline 重建。"
        )

    # -------- 基线版本迁移 --------
    state, migrated = migrate_state(state, rstate)
    if migrated:
        save_state(state)
        print(f"  · 基线已从 v1 迁移到 v{STATE_VERSION}（补记 mode，取自远端当前值）")

    # -------- 标记已同步（解除过期拦截）--------
    if opts["mark_synced"]:
        mark_synced(state, head_sha, rstate)
        return

    # -------- 第零层：本地副本是否过期（P0-1）--------
    # 前面几层只能证明「远端没被别人改」，证明不了「本地是从最新版改的」。
    # 本地副本一旦过期（CDN 缓存的 tarball、离线包、未 pull 的旧 clone），
    # 过期的全文 + 你的改动会被整文件覆盖上去，**把远端更新的内容回退掉且不报错**。
    synced = state.get("synced_commit")
    if synced and synced != head_sha and not force:
        print(f"\n❌ 本地副本落后于远端：基线上记录本地基于 {synced[:8]}，远端现在是 {head_sha[:8]}。")
        print("   此时推送会把远端这段时间的更新整文件回退掉，且不会报错。")
        print("\n   请先把本地同步到远端最新，然后：")
        print("     python3 push_api.py --mark-synced")
        print("   再重新推送。确认本地就是最新（例如刚由本脚本推送过）才加 --force-overwrite。")
        return
    if synced and synced != head_sha:
        print(f"\n  ! 本地副本落后（{synced[:8]} → {head_sha[:8]}），--force-overwrite 已放行，"
              f"存在回退远端更新的风险")

    # -------- 收集待推文件 --------
    candidates = explicit or detect_changes()
    files, rejected = [], []
    for f in candidates:
        rel = safe_rel(f)
        if rel is None:
            rejected.append(f)
        elif os.path.isfile(os.path.join(ROOT, rel)) or os.path.islink(os.path.join(ROOT, rel)):
            files.append(rel)
    if rejected:
        print(f"\n❌ 以下路径越出仓库范围或非法，已忽略：{rejected}")
    if not files:
        print("\n本地没有待推送的改动。")
        return

    lmap = local_state_map()

    # -------- 第一层：文件级基线校验（mode + sha 一起比）--------
    # 远端某文件必须等于「我们上次推送后记下的状态」，否则说明远端
    # 被别的通道改过（别人 git push / 网页编辑 / 另一台机器）。
    # 这是防静默覆盖的关键：ref 级 force=False 管不到这种情况。
    # 比 (mode, sha) 而非只比 sha：只比 sha 会让「只改了可执行位」的变更
    # 被判为「内容已一致」而跳过，改了等于没改（T-11）。
    todo, blocked = [], []
    for rel in files:
        lmode, lsha = lmap.get(rel, ("100644", ""))
        rmode, rsha = rstate.get(rel, (None, None))
        base = state["files"].get(rel)
        base_mode = base.get("mode") if isinstance(base, dict) else None
        base_sha = base.get("sha") if isinstance(base, dict) else base

        if (lmode, lsha) == (rmode, rsha):
            print(f"  · {rel} 已与远端一致，跳过")
            continue
        if base is None:
            if rsha is None and not force:
                # 基线没记录**且远端也没这个文件** → 纯新增，不存在覆盖风险。
                # 只有当「基线没记录、远端却有」时才真的无法确认原状态，那才要拦。
                todo.append(rel)
                print(f"  + {rel} 新增文件（远端不存在）")
                continue
            if force:
                todo.append(rel)
                print(f"  ! {rel} 基线未记录（--force-overwrite 已放行）")
            else:
                blocked.append((rel, "基线里没有这个文件、远端却已存在，无法确认远端原状态"))
            continue
        if (rmode, rsha) != (base_mode, base_sha):
            if force:
                todo.append(rel)
                print(f"  ! {rel} 远端已被改动（--force-overwrite 已放行，将整文件覆盖）")
            else:
                detail = f"远端 {str(rsha)[:8]}/{rmode} ≠ 基线 {str(base_sha)[:8]}/{base_mode}"
                blocked.append((rel, f"{detail}，可能被他人改动"))
            continue
        todo.append(rel)

    if blocked:
        print("\n❌ 以下文件可能覆盖他人改动，已中止：")
        for rel, why in blocked:
            print(f"   - {rel}: {why}")
        print("\n   确认要覆盖就加 --force-overwrite；否则先同步远端改动到本地再推。")
        return

    if not todo:
        print("\n没有需要推送的内容。")
        return

    # -------- 远端已前进的整体提示 --------
    prev = state.get("base_commit")
    if prev and prev != head_sha:
        print(f"\n⚠️  远端自上次推送后已前进（基线 {prev[:8]} → 现在 {head_sha[:8]}），可能含他人提交。")
        print("   本次只覆盖下面校验通过的文件，其余文件保持远端原样。")

    # -------- 预览 --------
    preview(todo, rstate, lmap)

    # -------- 提交信息 --------
    # 原来复用 `git log -1`，但推送成功后本脚本会在本地补一个同信息的 commit，
    # 导致从第二次起 log -1 永远拿到同一条 → 所有推送共用同一个提交信息。
    msg = opts["msg"]
    if msg is None and not yes:
        msg = input(f"提交信息（单行，留空则用「{default_msg(todo)}」）：\n> ").strip()
    if not msg:
        msg = default_msg(todo)
    if not opts["msg"]:
        print(f"提交信息：{msg}")

    if dry:
        print("\n[dry-run] 未做任何推送")
        return
    if not yes:
        ans = input(f"\n推送到 {OWNER}/{REPO}@{BRANCH}？(y/N) ").strip().lower()
        if ans != "y":
            print("已取消")
            return

    # -------- 大文件预检 --------
    for rel in todo:
        size = os.path.getsize(os.path.join(ROOT, rel))
        if size > MAX_BLOB_BYTES:
            raise SystemExit(
                f"{rel} 有 {size / 1024 / 1024:.1f} MB，超过 {MAX_BLOB_BYTES // 1024 // 1024} MB 上限。"
                f"base64 后还会再膨胀约 33%，容易超时/被拒。请改走 Git LFS。"
            )

    # -------- 第二层：ref 乐观锁 --------
    # 建对象期间若有人又推了提交，head_sha 就不是最新了，重取一次确认。
    now = api("GET", f"/git/refs/heads/{BRANCH}")["object"]["sha"]
    if now != head_sha:
        raise SystemExit(f"远端已前进到 {now}（预期 {head_sha}），出现并发提交，已中止")

    # -------- 建对象 --------
    entries = []
    for rel in todo:
        mode = lmap.get(rel, ("100644", ""))[0]
        full = os.path.join(ROOT, rel)
        if mode == "120000":                      # symlink：blob 内容是目标路径
            raw = os.readlink(full).encode()
        else:
            with open(full, "rb") as f:
                raw = f.read()
        blob = api("POST", "/git/blobs",
                   {"content": base64.b64encode(raw).decode(), "encoding": "base64"},
                   timeout=_timeout_for(len(raw)))
        if "sha" not in blob:
            raise SystemExit(f"创建 blob 失败 {rel}: {json.dumps(blob)[:300]}")
        # mode 必须跟着走，否则 .sh / 二进制推上去就丢了可执行位。
        entries.append({"path": rel, "mode": mode, "type": "blob", "sha": blob["sha"]})
        print(f"  blob {rel} ({mode})")

    tree = api("POST", "/git/trees", {"base_tree": head_sha, "tree": entries})
    if "sha" not in tree:
        raise SystemExit(f"创建 tree 失败: {json.dumps(tree)[:300]}")

    commit = api("POST", "/git/commits", {"message": msg, "tree": tree["sha"], "parents": [head_sha]})
    if "sha" not in commit:
        raise SystemExit(f"创建 commit 失败: {json.dumps(commit)[:300]}")

    # -------- 第三层：PATCH 用 force=False，非快进由 GitHub 拒绝 --------
    upd = api("PATCH", f"/git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": False})
    if upd.get("object", {}).get("sha") != commit["sha"]:
        raise SystemExit(f"更新 ref 失败（可能非快进）: {json.dumps(upd, ensure_ascii=False)[:300]}")

    # -------- 更新基线 --------
    for i, rel in enumerate(todo):
        state["files"][rel] = {"mode": entries[i]["mode"], "sha": entries[i]["sha"]}
    state["base_commit"] = commit["sha"]
    state["synced_commit"] = commit["sha"]     # 推送后本地即远端最新
    save_state(state)

    # 本地也落一个提交，让工作区重回干净（下次 detect_changes 才准）。
    # 注意：本地历史与远端历史并无父子关系，纯粹当快照基线用。
    # 只提交 todo 这些路径，避免把别人先前 git add 进暂存区的文件一起卷进来。
    git("add", "--", *todo)
    if git("diff", "--cached", "--name-only", "--", *todo):
        git("-c", "user.name=yuanbao", "-c", "user.email=yuanbao@users.noreply.github.com",
            "commit", "-q", "-m", msg, "--", *todo)

    print(f"\n✅ 已推送 https://github.com/{OWNER}/{REPO}/commit/{commit['sha']}")
    print(f"   基线已同步（{STATE_PATH}），本地已补提交 {git('log', '-1', '--format=%h')}")


if __name__ == "__main__":
    main()
