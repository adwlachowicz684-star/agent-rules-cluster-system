export function bestOf(list: number[]) {
  let best = -Infinity;
  for (const v of list) {
    if (v > best) {
      best = v;
    }
  }
  return best;
}
