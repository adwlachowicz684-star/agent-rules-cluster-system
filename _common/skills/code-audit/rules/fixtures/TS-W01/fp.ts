export function buy(count: number) {
  if (!Number.isInteger(count) || count <= 0) {
    return;
  }
  for (let i = 0; i < count; i++) {
    grant(item);
  }
}
