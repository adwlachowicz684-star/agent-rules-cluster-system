# -*- coding: utf-8 -*-
"""验证 _exec_bit_reliable 的 fail-closed 修复"""
import importlib.util, os, subprocess, shutil, sys

SRC = "/data/workspace/push_api_repo.py"


def load(root):
    spec = importlib.util.spec_from_file_location("pa", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.ROOT = root
    m._EXEC_RELIABLE = None
    return m


def case(name, setup, expect):
    d = "/dev/shm/_exec_t"
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    subprocess.run(["git", "init", "-q", d], check=True)
    setup(d)
    m = load(d)
    got = m._exec_bit_reliable()
    ok = (got == expect)
    print("  %-42s _EXEC_RELIABLE=%-5s 期望 %-5s %s"
          % (name, got, expect, "PASS" if ok else "FAIL"))
    return ok


print("=== _exec_bit_reliable fail-closed 验证 ===")
r = []

# 1. 全新 git init，没有 add → 索引为空 → 必须 False（旧代码返回 True）
r.append(case("① 空索引（全新 git init 未 add）", lambda d: None, False))


# 2. 索引里有 .md，且全部 0777 → 文件系统不区分权限 → False
def s2(d):
    for n in ("a.md", "b.md", "c.txt"):
        p = os.path.join(d, n)
        open(p, "w").write("x")
        os.chmod(p, 0o777)
    subprocess.run(["git", "-C", d, "add", "-A"], check=True)


r.append(case("② 样本全部带执行位（0777）", s2, False))


# 3. 索引里有 .md，全部 0644 → 环境可靠 → True
def s3(d):
    for n in ("a.md", "b.md", "c.txt"):
        p = os.path.join(d, n)
        open(p, "w").write("x")
        os.chmod(p, 0o644)
    subprocess.run(["git", "-C", d, "add", "-A"], check=True)
    subprocess.run(["git", "-C", d, "config", "core.fileMode", "true"], check=True)


r.append(case("③ 样本均不带执行位（0644）", s3, True))


# 4. core.fileMode=false → False
def s4(d):
    for n in ("a.md",):
        p = os.path.join(d, n)
        open(p, "w").write("x")
        os.chmod(p, 0o644)
    subprocess.run(["git", "-C", d, "add", "-A"], check=True)
    subprocess.run(["git", "-C", d, "config", "core.fileMode", "false"], check=True)


r.append(case("④ core.fileMode=false", s4, False))


# 5. 索引里只有 .rs / .go（不在样本扩展名白名单）→ 探不到样本 → 必须 False
def s5(d):
    for n in ("main.rs", "lib.go"):
        p = os.path.join(d, n)
        open(p, "w").write("x")
        os.chmod(p, 0o644)
    subprocess.run(["git", "-C", d, "add", "-A"], check=True)


r.append(case("⑤ 索引只有非白名单扩展名", s5, False))

print()
print("结果: %d/%d PASS" % (sum(r), len(r)))
sys.exit(0 if all(r) else 1)
