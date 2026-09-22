# GO-02

context 未传播：函数接收 ctx 但 http.Get 没用 WithContext

- `tp.go` —— **必须命中**
- `fp.go` —— **必须不命中**
