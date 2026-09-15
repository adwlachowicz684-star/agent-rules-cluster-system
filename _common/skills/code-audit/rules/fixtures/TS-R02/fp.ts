export function removeAt(list: any[], idx: number[]) {
  const desc = idx.slice().sort((a, b) => b - a);
  for (const i of desc) {
    list.splice(i, 1);
  }
}
