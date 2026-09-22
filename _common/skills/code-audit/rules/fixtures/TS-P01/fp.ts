export function clampNum(v: any, lo: number, hi: number) {
  if (typeof v !== 'number') {
    return lo;
  }
  return Math.min(hi, Math.max(lo, v));
}
