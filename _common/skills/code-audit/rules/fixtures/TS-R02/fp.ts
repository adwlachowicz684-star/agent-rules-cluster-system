export function removeAt(list: any[], idx: number[]) {
  // splice 接受负数（从末尾算），外部传入的下标必须先校验范围
  const desc = idx
    .filter((i) => Number.isInteger(i) && i >= 0 && i < list.length)
    .sort((a, b) => b - a);
  for (const i of desc) {
    list.splice(i, 1);
  }
}
