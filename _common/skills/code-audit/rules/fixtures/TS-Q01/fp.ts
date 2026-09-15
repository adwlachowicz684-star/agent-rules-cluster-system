export function make(n: number) {
  const c = Math.min(n, 4096);
  return new Float32Array(c);
}
