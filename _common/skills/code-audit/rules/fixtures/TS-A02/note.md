# TS-A02

`??` 只挡 undefined：opts.speed = NaN 时原样穿透。
收口函数（clampNum/numOr）才同时挡 NaN 与 Infinity。

- `tp.ts` —— **必须命中**
- `fp.ts` —— **必须不命中**
