// clampNum 内部有 numOr 兜底，非有限值不穿透 → 不是问题
export function f(opts:any){ return clampNum(opts.x, 0, 1); }
