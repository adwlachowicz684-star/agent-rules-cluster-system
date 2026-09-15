export function emit(items: Array<() => void>) {
  items.forEach((fn) => fn());
}
