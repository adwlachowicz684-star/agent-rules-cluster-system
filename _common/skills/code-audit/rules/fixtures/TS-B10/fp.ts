// 配了 --fail：HTTP 错误会退出码非 0
export function fetchHead(): string {
    return execSync('curl -sSf https://api.example.com/head').toString().trim();
}

// 看状态码判成功
export function ok(resp: Response): boolean {
    return resp.ok && resp.status === 200;
}
