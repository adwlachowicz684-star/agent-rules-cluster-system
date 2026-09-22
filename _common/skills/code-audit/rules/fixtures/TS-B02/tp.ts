export function grow(limit: number) {
  let r = 1;
  while (r < limit) {
    r *= 2;
  }
  return r;
}
