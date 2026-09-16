# TP3（形态扩展）：不是 subprocess，而是成对 encode / decode 路径不对称
def blob_sha(rel):
    full = os.path.join(ROOT, rel)
    if os.path.islink(full):
        raw = os.readlink(full).encode("utf-8", "surrogateescape")   # 读侧容错
        return hash_stdin(raw)
    return git("hash-object", "--no-filters", rel)


def build_blob(rel):
    full = os.path.join(ROOT, rel)
    raw = os.readlink(full).encode()      # ← 写侧严格，非法字节在这里炸
    return api("POST", "/git/blobs",
               {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
