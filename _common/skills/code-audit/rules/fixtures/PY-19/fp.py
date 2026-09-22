import os

def read_target(p):
    return os.readlink(p).encode("utf-8", "surrogateescape")

def label(p):
    raw = open(p, 'rb').read()
    return raw.decode("utf-8", "surrogateescape")
