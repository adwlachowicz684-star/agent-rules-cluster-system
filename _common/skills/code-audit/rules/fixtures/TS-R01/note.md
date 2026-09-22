# TS-R01

按路径写入未过滤危险段：path = '__proto__.x' 造成原型污染。
fp 显式过滤 __proto__ / constructor / prototype。

- `tp.ts` —— **必须命中**
- `fp.ts` —— **必须不命中**
