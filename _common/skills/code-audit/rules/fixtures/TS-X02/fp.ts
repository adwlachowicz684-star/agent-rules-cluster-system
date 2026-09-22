export function start() {
  const h = setInterval(() => tick(), 16);
  onStop(() => clearInterval(h));
}
