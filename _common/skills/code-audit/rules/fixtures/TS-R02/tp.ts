export function removeAt(list: any[], idx: number[]) {
  for (const i of idx) {
    list.splice(i, 1);
  }
}
