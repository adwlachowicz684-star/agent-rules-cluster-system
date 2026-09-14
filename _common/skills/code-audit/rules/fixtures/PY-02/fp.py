def load(p):
    try:
        return open(p).read()
    except FileNotFoundError:
        return ''
