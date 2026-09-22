export function f(x: number) {
  // 注意用 !(x > 0) 而不是 x <= 0：NaN 参与所有比较恒为 false，
  // `x <= 0` 挡不住 NaN，会连 NaN 一起放过。
  if (!(x > 0)) {
    throw new Error('bad');
  }
  return x;
}
