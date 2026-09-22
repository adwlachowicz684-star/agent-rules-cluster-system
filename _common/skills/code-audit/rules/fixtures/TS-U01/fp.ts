export function formatHp(v: number): string {
    if (!Number.isFinite(v)) return '-';
    return v.toFixed(1);
}
