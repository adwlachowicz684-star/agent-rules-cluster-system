export function fill(count: number) {
  const n = Math.min(count, 1024);
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push(i);
  }
  return out;
}
