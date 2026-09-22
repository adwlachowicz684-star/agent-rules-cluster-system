export function clampNum(v: any, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}
