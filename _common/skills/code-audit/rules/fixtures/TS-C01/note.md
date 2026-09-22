# TS-C01

裸对象查表：k = 'toString' / '__proto__' 时命中原型链，返回函数而非 undefined。
fp 用 hasOwnProperty 收口。

- `tp.ts` —— **必须命中**
- `fp.ts` —— **必须不命中**
