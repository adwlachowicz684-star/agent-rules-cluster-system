def write_auth(token):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", token):  # ← 限定真实字符集
        raise SystemExit("凭据含非法字符，请重新复制")
    with open(cfg, "w") as f:
        f.write(f'header = "Authorization: Bearer {token}"\n')
