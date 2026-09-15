export function speedOf(opts: any) {
  const speed = clampNum(opts.speed ?? 10, 0, 100);
  return speed;
}
