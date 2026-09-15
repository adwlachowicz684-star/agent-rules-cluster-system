export function grow() {
  let r = 1;
  while (r < 64) {
    r *= 2;
  }
  return r;
}
