import sys


def load(p, warns):
    try:
        return open(p).read()
    except Exception as e:
        # 有可见输出的降级：调用方看得到失败，不是「吞没」
        print('读取失败 %s: %s' % (p, e), file=sys.stderr)
        warns.append(str(e))
        return ''
