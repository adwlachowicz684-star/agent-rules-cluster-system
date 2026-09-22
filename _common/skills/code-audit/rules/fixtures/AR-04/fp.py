# 退出码已分类：2=被防护拦下 / 3=冲突未解决 / 1=真出错
#
# 注意 main() 包裹：这些 raise 是 CLI 入口的终止行为，
# 不是「非 CLI 层就地终止」—— 不包 main 会被 AR-01 判成耦合而误报。
def main():
    cmd = parse_args()
    if cmd == "push":
        raise SystemExit(2)     # 2 = 被防护拦下
    if cmd == "pull":
        raise SystemExit(3)     # 3 = 冲突未解决
    raise SystemExit(1)         # 1 = 真出错


def parse_args():
    return "push"
