export function bestOf(list: number[]) {
  let best = 0;
  for (const v of list) {
    if (v > best) {
      best = v;
    }
  }
  return best;
}
