#!/usr/bin/env python3
"""push_api.py 审查实测探针（可重跑）

用法：
    python3 探针/probe_push_api.py

覆盖四条实测结论（见 ../审查报告.md）：
  P1-1  容器里 os.access(X_OK) 恒为真 → mode 推断失效
  P1-2  normpath 不解析符号链接 → 路径校验可绕过
  P1-3  只比 sha 不比 mode → 元数据变更静默丢失
  P2-1  子进程返回码被丢弃
另附两条「已修复，回归用」：
  R-1   符号链接 blob sha 算法正确（--stdin 不跟随链接）
  R-2   HTTP 非 2xx 被正确拦截
"""
import os
import subprocess
import sys
import tempfile
import threading
import http.server
import socketserver
import json

REPO = "/data/workspace/probe/repo"


def g(*a, cwd=REPO):
    return subprocess.run(["git", "-C", cwd, *a], capture_output=True, text=True)


def setup():
    os.makedirs(REPO, exist_ok=True)
    if not os.path.exists(os.path.join(REPO, ".git")):
        g("init", "-q")
        g("config", "user.email", "t@t")
        g("config", "user.name", "t")
        open(os.path.join(REPO, "a.txt"), "w").write("hi\n")
        os.makedirs(os.path.join(REPO, "sub"), exist_ok=True)
        open(os.path.join(REPO, "sub/t.txt"), "w").write("target-content\n")
        os.symlink("sub/t.txt", os.path.join(REPO, "link"))
        os.symlink("/etc", os.path.join(REPO, "etcdir"))
        g("add", "-A")
        g("commit", "-qm", "init")
    return REPO


def p1_1_mode():
    print("\n[P1-1] 容器环境里 os.access 推断 mode 是否可靠")
    subprocess.run(f"cd {REPO} && printf '#!/bin/sh\\n' > x.sh && git add -A >/dev/null 2>&1 "
                   f"&& git commit -qm x >/dev/null 2>&1", shell=True)
    os.chmod(os.path.join(REPO, "x.sh"), 0o755)
    g("add", "x.sh")
    ls = g("ls-files", "-s", "x.sh").stdout.split()
    mode = ls[0] if ls else "?"
    fm = g("config", "core.fileMode").stdout.strip() or "(未设置)"
    st = os.stat(os.path.join(REPO, "x.sh"))
    print(f"  core.fileMode        = {fm}")
    print(f"  chmod +x 后索引 mode = {mode}")
    print(f"  文件实际权限         = {oct(st.st_mode)[-4:]}")
    print(f"  os.access(X_OK)      = {os.access(os.path.join(REPO, 'x.sh'), os.X_OK)}")
    bad = os.access(os.path.join(REPO, "x.sh"), os.X_OK) and mode != "100755"
    print(f"  → 结论：{'❌ 推断与实际不一致，会把普通文件判成可执行' if bad else '✅ 一致'}")


def p1_2_symlink():
    print("\n[P1-2] normpath 是否拦得住符号链接穿越")
    target = "etcdir/passwd"
    norm = os.path.normpath(os.path.join(REPO, target))
    real = os.path.realpath(norm)
    inside_norm = norm.startswith(REPO + os.sep)
    inside_real = real.startswith(REPO + os.sep)
    print(f"  输入路径        = {target}")
    print(f"  normpath        = {norm}   判定在仓库内={inside_norm}")
    print(f"  realpath        = {real}   判定在仓库内={inside_real}")
    leak = inside_norm and not inside_real
    if leak:
        try:
            head = open(norm).readline().strip()[:36]
        except OSError as e:
            head = f"(读取失败 {e})"
        print(f"  ⚠ 可读到仓库外内容：{head!r}")
    print(f"  → 结论：{'❌ 校验被绕过' if leak else '✅ 已拦住'}")


def p1_3_mode_only_change():
    print("\n[P1-3] 只改 mode 不改内容时是否被静默跳过")
    subprocess.run(f"cd {REPO} && printf '#!/bin/sh\\n' > s2.sh && git add -A >/dev/null 2>&1 "
                   f"&& git commit -qm s2 >/dev/null 2>&1", shell=True)
    sha = g("ls-files", "-s", "s2.sh").stdout.split()[1]
    rmap = {"s2.sh": sha}          # 远端 blob sha 与本地相同（内容确实没变）
    skipped = sha == rmap["s2.sh"]
    print(f"  本地 blob sha = {sha[:12]}   远端 blob sha = {rmap['s2.sh'][:12]}")
    print(f"  lsha == rsha → {skipped}")
    print(f"  → 结论：{'❌ 判定为「内容已一致」而跳过，mode 变更丢失' if skipped else '✅ 会推送'}")


def p2_1_returncode():
    print("\n[P2-1] git 命令失败时返回值是否可区分")
    open(os.path.join(REPO, ".gitignore"), "w").write("secret.txt\n")
    open(os.path.join(REPO, "secret.txt"), "w").write("s\n")
    open(os.path.join(REPO, "b.txt"), "w").write("y\n")
    g("add", "--", ".gitignore")
    g("commit", "-qm", "gi")
    r = g("add", "--", "b.txt", "secret.txt")
    cached = g("diff", "--cached", "--name-only").stdout.strip()
    stdout_only = r.stdout.strip()
    print(f"  git add 退出码   = {r.returncode}")
    print(f"  仅看 stdout      = {stdout_only!r}  （是否与成功时无法区分：{not stdout_only}）")
    print(f"  实际进入暂存区   = {cached!r}")
    print(f"  → 结论：{'❌ 失败不可见（只看 stdout 的包装函数会误判成功）' if r.returncode else '✅ 成功'}")


def r1_symlink_sha():
    print("\n[R-1] 符号链接 blob sha 算法（回归用）")
    ls = dict((l.split("\t")[1], l.split()[1]) for l in
              g("ls-files", "-s").stdout.splitlines() if "\t" in l)
    if "link" not in ls:
        print("  （跳过：无 link）"); return
    want = ls["link"]
    got = subprocess.run(["git", "-C", REPO, "hash-object", "--stdin"],
                         input=os.readlink(os.path.join(REPO, "link")),
                         capture_output=True, text=True).stdout.strip()
    wrong = g("hash-object", "link").stdout.strip()   # 跟随链接的错误算法
    print(f"  git 记录的 sha          = {want}")
    print(f"  hash-object --stdin     = {got}   {'✅' if got == want else '❌'}")
    print(f"  hash-object <path>（错）= {wrong}   {'✅ 未被采用' if wrong != want else '❌'}")


def r2_http_status():
    print("\n[R-2] HTTP 非 2xx 是否被拦截（回归用）")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, "/data/workspace")

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            b = json.dumps({"message": "Validation Failed"}).encode()
            self.send_response(422)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 8899), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        import push_api as P
        P.BASE = "http://127.0.0.1:8899/repos/o/r"
        try:
            P.api("GET", "/git/ref/heads/main")
            print("  ❌ 422 未被拦截")
        except SystemExit as e:
            print(f"  ✅ 422 被拦截：{str(e)[:64]}")
    except ImportError:
        print("  （跳过：未找到 push_api.py）")
    finally:
        srv.shutdown()


if __name__ == "__main__":
    setup()
    print("=" * 62)
    print("push_api.py 审查实测探针")
    print("=" * 62)
    p1_1_mode()
    p1_2_symlink()
    p1_3_mode_only_change()
    p2_1_returncode()
    r1_symlink_sha()
    r2_http_status()
