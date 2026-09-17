import os

def read_target(p):
    return os.readlink(p).encode()

def label(p):
    raw = open(p, 'rb').read()
    return raw.decode("utf-8", "replace")
