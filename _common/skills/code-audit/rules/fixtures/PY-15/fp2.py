# FP2：写侧与读侧同一套编解码参数
def _link_bytes(rel):
    return os.readlink(os.path.join(ROOT, rel)).encode(
        "utf-8", "surrogateescape")


def blob_sha(rel):
    return hash_stdin(_link_bytes(rel))


def build_blob(rel):
    raw = _link_bytes(rel)                # 与读侧共用同一个函数
    return api("POST", "/git/blobs",
               {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
