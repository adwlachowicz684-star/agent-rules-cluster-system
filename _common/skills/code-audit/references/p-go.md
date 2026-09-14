# 语言包：Go（p-go）

**触发**：仓库里有 `.go` 文件（`go.mod` 是强信号）。
**风险**：goroutine 泄漏、取消不传播、channel 死锁、map 并发写、错误被丢。

`overlaps:` 本包只放 **Go 语义特有**的判据。
跨语言的并发判据主条目在 `s-concurrency`（R-01~R-10）——本包是它们在 Go 里的
**可机扫形态**，同源不重复报：GO-01↔R-02、GO-02↔R-03、GO-04↔R-01、GO-05↔R-04。
锁中毒/资源无限读入归 `s-backend` K-21 / K-01。

```bash
python3 scripts/scan-go.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
python3 scripts/scan-go.py --self-test        # 改规则后必跑
```

---

## 核心判据：Go 的并发静默性来自「不报错地挂着」

Go 让并发变得容易，也让**泄漏变得无声**：goroutine 挂住不会报错、不占 CPU、
只在内存曲线上缓慢上涨。等发现时通常已经 OOM。

| 形态 | 为什么静默 |
|---|---|
| goroutine 等一个永远不会来的 channel | 不报错、不退出、不占 CPU，只占内存 |
| `ctx` 没往下传 | 上游超时了，下游继续跑，业务看不出来 |
| `err` 用 `_` 丢掉 | 编译通过、逻辑继续，失败被吞 |

---

## 模式清单

### GO-01 (P0) goroutine 泄漏
- **判据**：`go func` / `go f()` 出现，但文件内**没有** `context` / `WaitGroup` /
  `done` channel / `sync` 包任何一个
- **确认**：找启动路径——是否每次请求/每次循环都起一个。是 → 随运行时长累积
- **典型**：`go func() { for { select { case v := <-ch: ... } } }()`，
  `ch` 永不关闭 → goroutine 永久挂住
- **修法**：接 `ctx.Done()`；`defer wg.Done()`；channel 由发送方关闭
- **降级**：`main` 里的 `go` 且生命周期等同进程 → P2

### GO-02 (P0) context 未传播
- **判据**：函数签名里有 `ctx context.Context`，但函数体内调用
  `http.Get` / `http.NewRequest` / `db.Query` / `time.After` 时**没传 ctx**
- **确认**：上游取消后，这些调用是否立刻返回。否 → 上游超时下游照跑
- **典型**：`http.Get(url)` 而非 `http.NewRequestWithContext(ctx, ...)`
- **修法**：所有阻塞调用都带 ctx；`time.After` 改 `time.AfterFunc` 或 ctx 定时器

### GO-03 (P0) channel 使用不当
- **判据**：三种形态——① 无缓冲 channel 在 `go func` 里收但可能无发送方
  ② `close()` 出现多次或出现在接收方 ③ `for range ch` 但没人关闭
- **确认**：画发送方/接收方数量与关闭位置。**由接收方关闭** = 多发送方时 panic
- **典型**：`c := make(chan int); go func(){ c <- 1 }()` 但主协程已 return → 永久阻塞
- **修法**：由发送方关闭；或用 `sync.Once` 保关闭唯一；加 `default` 分支防阻塞

### GO-04 (P0) map 并发写无同步
- **判据**：存在 `map[...]...` 类型 + 文件里有 `go func` 或 `sync` 未引入
- **确认**：该 map 是否被多个 goroutine 同时写。是 → `fatal error: concurrent map writes`
- **修法**：`sync.Mutex` / `sync.Map` / 用 channel 串行化
- **注**：Go 的 map 并发写会 **panic 崩溃**（不是静默），但只读并发是安全的——
  先确认到底是读还是写

### GO-05 (P1) mutex 值拷贝
- **判据**：函数参数或结构体字段出现 `sync.Mutex` **非指针**，或 `sync.Mutex` / `RWMutex` 被赋值传递
- **确认**：锁被拷贝后，两个副本各自保护自己的状态 → **保护完全失效**
- **修法**：用 `*sync.Mutex`；或结构体嵌入时不拷贝（`go vet` 可查）

### GO-06 (P0) 错误被丢弃
- **判据**：`_` 接收错误返回值，或 `err` 赋值后从未被判断
- **确认**：被丢的错误是否影响正确性（写文件失败、网络失败）
- **典型**：`v, _ := strconv.Atoi(s)` —— 解析失败时 `v` 是 0，后续按 0 算
- **修法**：至少 `if err != nil { return err }`；确实可忽略要写 `_ =` 并注释
- **定级**：写操作/网络/解析的 err 被丢 → P0；纯打印类 → P2

### GO-07 (P1) WaitGroup 计数不匹配
- **判据**：文件内有 `wg.Add(` 但无 `wg.Done()`，或 `Add` 在 goroutine **内部**调用
- **确认**：`Add` 必须在 `go` 之前调用，否则 `Wait()` 可能先返回
- **典型**：`go func(){ wg.Add(1); ...; wg.Done() }()` → Wait 可能提前结束

### GO-08 (P1) 循环里 defer（资源累积）
- **判据**：`for` 循环体内出现 `defer`
- **确认**：defer 在**函数返回时**才执行，循环 N 次就累积 N 个
- **典型**：`for _, f := range files { fh, _ := os.Open(f); defer fh.Close() }` →
  文件句柄累积到函数结束，上万文件直接打满 fd
- **修法**：循环体抽成函数；或显式 close

### GO-09 (P1) select 无退出路径
- **判据**：`select` 语句里既无 `ctx.Done()` 也无 `default` 也无超时分支
- **确认**：所有 case 的 channel 都不活跃时，这个 select 会永久阻塞
- **修法**：加 `case <-ctx.Done(): return`

### GO-10 (P1) goroutine 内 panic 无人 recover
- **判据**：`go func` 内没有 `defer func(){ if r := recover(); ... }()`
- **确认**：子 goroutine panic 会导致**整个进程退出**，且无法被外层 recover 捕获
- **修法**：每个长期 goroutine 加 recover + 日志

---

## 检查方法

```
□ go func 有几个？谁负责让它退出？（泄漏）
□ ctx 有没有传到每一个阻塞调用？（取消传播）
□ channel 谁关？发送方还是接收方？（死锁/panic）
□ map 被几个 goroutine 写？（崩溃）
□ err 去哪了？用 _ 丢了几个？（静默失败）
□ 循环里有 defer 吗？（句柄累积）
```

## 与 go vet / staticcheck 的分工

| 工具 | 管什么 |
|---|---|
| `go vet` | 锁拷贝、printf 格式、struct tag |
| `staticcheck` | 未用代码、简化建议、部分并发 |
| `go test -race` | **实际竞态**（本包只能发现线索，证明要靠它） |
| **本包** | 业务语义：泄漏路径、取消传播、错误丢弃、循环 defer |

**`-race` 才是证明**。本包报的竞态候选，都要用 `go test -race` 复现后才算确认。

## 常见误报

- **`main` 里起的 goroutine** —— 生命周期等同进程，不是泄漏
- **只读的 map** —— 并发读安全，不报
- **`_` 接收的确实是无关返回值**（如 `_, _ = f.Read()` 的 n）→ 确认后忽略
- **测试文件的 `go func`** —— 短生命周期，降 P3
- **已有 `go vet` 覆盖的锁拷贝** —— 本包与它重叠，重复报可接受（保险）
