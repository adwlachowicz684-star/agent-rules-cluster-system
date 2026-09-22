export function range(from: number, to: number) {
  const a = Math.max(from, 0);
  const b = Math.min(to, 1024);
  const out = [];
  for (let i = a; i < b; i++) {
    out.push(i);
  }
  return out;
}
