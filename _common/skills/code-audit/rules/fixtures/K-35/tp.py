def write_auth(token):
    tok = re.sub(r"[^\x21-\x7E]", "", token)        # ← 放行 " \ 反引号 $()
    if tok != token:
        raise SystemExit("含不可见字符")
    with open(cfg, "w") as f:
        f.write(f'header = "Authorization: Bearer {tok}"\n')
