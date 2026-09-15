export function withUrl(blob: Blob, use: (u: string) => void): void {
    const u = URL.createObjectURL(blob);
    use(u);
    URL.revokeObjectURL(u);
}
