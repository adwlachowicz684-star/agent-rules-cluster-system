# TS-B01

上界来自入参且未收口：count = Infinity → 死循环；= NaN → 一次都不跑且不报错。
fp 先用 Math.min 收口。

- `tp.ts` —— **必须命中**
- `fp.ts` —— **必须不命中**
