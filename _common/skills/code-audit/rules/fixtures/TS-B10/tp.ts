// curl -s 吞掉 HTTP 错误：错误响应的 body 照样进管道
export function fetchHead(): string {
    return execSync('curl -s https://api.example.com/head | jq -r .sha')
        .toString()
        .trim();
}

// 按字段存在性判成功：4xx 响应里恰好没有 sha 才算失败
export function ok(resp: Record<string, unknown>): boolean {
    return 'sha' in resp;
}
