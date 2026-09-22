export function emit(listeners: Array<() => void>) {
  listeners.forEach((fn) => fn());
}
