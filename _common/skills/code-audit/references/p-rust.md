# 语言包：Rust（p-rust）

**触发**：仓库里有 `.rs` 文件（`Cargo.toml` / `src-tauri/` 是强信号）。
**风险**：panic 静默化、整数回绕、unsafe 契约缺失、跨 await 持锁、Tauri 入参未校验。

`overlaps:` 本包只放 **Rust 语义特有**的判据。
跨语言的并发判据主条目在 `s-concurrency`（R-01~R-10）——本包是它们在 Rust 里的
**可机扫形态**，同源不重复报：RS-04↔R-01、RS-06↔R-06。
进程/命令执行与读入无边界归 `s-backend` K-01 / K-02。

```bash
python3 scripts/scan-rust.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
python3 scripts/scan-rust.py --self-test        # 改规则后必跑
```

---

## 核心判据：Rust 的静默性来自「安全网本身变成了遮蔽」

Rust 用类型系统挡住了大片错误，代价是**剩下的错误都藏在安全网的褶皱里**：

| 形态 | 为什么静默 |
|---|---|
| Tauri command 里 `unwrap()` | panic 不会让进程退出，前端只拿到一条模糊错误或空响应 |
| 整数溢出 | debug 模式 panic，**release 模式静默回绕**——测试全绿，上线算错 |
| `unwrap_or_default()` | 错误被转成"零值"，程序继续跑，没人知道出过错 |
| `as` 转换 | 大转小静默截断，`u64 → u32` 高位直接丢了 |
| `unsafe` 无 SAFETY 注释 | 契约只在作者脑子里，下一个人无法复核 |

**最关键的一条**：`unwrap()` 在库里是"快速失败"，在 Tauri/服务端命令里是
**把 panic 翻译成用户看不懂的错误**。同一个写法，场景不同，严重度相反。

---

## 模式清单

### RS-01 (P0) unwrap / expect 在外部输入或命令路径上
- **判据**：`#[tauri::command]` / `pub fn` 处理函数内出现 `.unwrap()` / `.expect(`
- **确认**：这个 unwrap 的输入是否来自外部（前端 invoke、文件、网络、环境变量）
  ——是 → P0；纯内部常量/启动期解析 → P2
- **典型**：`let v: Value = serde_json::from_str(&s).unwrap();` 前端传个坏 JSON，
  命令 panic，前端收到 `command ... failed` 或空响应，**用户只看到"点了没反应"**
- **修法**：`?` 向上传播，返回 `Result<T, String>`（Tauri command 支持）；
  或用 `map_err(|e| e.to_string())?` 带上上下文
- **降级**：`main()` 启动期、测试代码、确定非 None 的常量 → 不报

### RS-02 (P0) 整数溢出（release 静默回绕）
- **判据**：`as u8/u16/u32` 窄化转换，或算术运算未用 `checked_*` / `saturating_*`
- **确认**：这个值是否可能被外部输入推到边界。**release 下 debug_assert 不生效**
- **典型**：`let n = items.len() as u32;` 或 `total + price` 在循环里累加
- **修法**：`checked_add().ok_or("overflow")?`；窄化用 `try_into()` 并显式处理失败
- **注**：debug 会 panic 掩盖问题，release 静默回绕——**必须按 release 行为评估**

### RS-03 (P0) unsafe 块无 SAFETY 注释
- **判据**：`unsafe {` / `unsafe fn` 存在，但上方 2 行内无 `// SAFETY:` 注释
- **确认**：unsafe 的安全契约是**前置条件**，不写下来 = 无法复核 = 下次改动必然踩
- **典型**：裸指针解引用、FFI 调用、`slice::from_raw_parts` 凭信任构造切片
- **修法**：紧邻上方写 `// SAFETY: <为什么这里满足安全契约>`
- **定级**：无注释一律 P1；若内部做指针算术或 `from_raw_parts` 且长度来自外部 → **P0**

### RS-04 (P0) 跨 await 持有同步锁
- **判据**：`std::sync::Mutex` / `RwLock` 的守卫在 `.await` 之前取得、之后仍存活
  （同一函数内先出现 `.lock()` 后出现 `.await`）
- **确认**：Rust 的 `std::sync::MutexGuard` **不是 `Send`**，
  async 块里跨 await 持有会编译报错，或用 `block_on` / 手写 `unsafe impl Send` 绕过
  ——绕过的那些就是死锁源
- **典型**：`let g = state.lock().unwrap(); do_async(&g).await;`
- **修法**：用 `tokio::sync::Mutex`；或把 `lock()` 收进最小作用域，await 前 drop
- **注**：这是 Rust 相较其他语言**更安全**的地方——编译器会拦。
  真正危险的是用 `block_on` 或 unsafe 绕过编译器保护的那批

### RS-05 (P0) Tauri/ECS 命令参数未校验
- **判据**：`#[tauri::command]` 函数参数是 `String` / `PathBuf`，函数体内
  直接用于 `fs::` / `Command::new` / 路径拼接，无 `canonicalize` / 白名单 / starts_with 校验
- **确认**：前端能否传入 `../` 或绝对路径。**前端校验不算数**——invoke 可被直接调用
- **典型**：`fs::read_to_string(format!("{}/{}", base, name))` 传 `../../etc/passwd` 读到库外
- **修法**：`path.canonicalize()` 后 `starts_with(base_canonical)`；
  命令执行用白名单枚举而非拼接字符串
- **定级**：读文件 → P1；写/删除或执行命令 → **P0**

### RS-06 (P0) 外部输入驱动的无界分配
- **判据**：`Vec::with_capacity(x)` / `read_to_end` / 循环 `push`，
  其中容量或长度来自参数、请求体、文件内容，无上限校验
- **确认**：攻击者能否通过超大输入触发 OOM。**Rust 不会替你限制容量**
- **修法**：先校验长度上限；流式处理而非一次性读入；`take(n)` 限制读取量

### RS-07 (P1) 错误被 unwrap_or_default / let _ 掩盖
- **判据**：`.unwrap_or_default()` / `.unwrap_or(0)` / `let _ =` 出现在 Result 上
- **确认**：这个错误是否该被看见。数据库写入失败返回默认值 = 静默丢失
- **典型**：`let n: u32 = s.parse().unwrap_or(0);` 解析失败当 0，后续按 0 计算
- **修法**：能传播就 `?`；确实要降级则显式 `unwrap_or_else(|e| { log::warn!(...); default })`
- **降级**：纯展示字段（如格式化失败显示空串）→ P3

### RS-08 (P1) Arc 循环引用 / Rc 跨线程
- **判据**：两个结构体互相持有 `Arc<Mutex<..>>`（或 `Rc` 出现在 `thread::spawn` 内）
- **确认**：`Arc` 双向引用 = 引用计数永不归零 = 内存泄漏；
  `Rc` 跨线程是 UB（`Rc` 非 Send，编译器通常能拦，但 `unsafe impl Send` 能绕过）
- **修法**：反向引用改 `Weak<T>`；跨线程用 `Arc`

### RS-09 (P1) 裸指针 / transmute 未隔离
- **判据**：`std::mem::transmute` / `as *const` / `as *mut` 出现在非 FFI 边界模块
- **确认**：是否有更安全的替代（`as` 转换、`bytemuck`、显式序列化）
- **修法**：封装进单一 `unsafe` 小函数并写 SAFETY；业务代码不得直接出现

### RS-10 (P1) 格式化/日志注入与敏感信息
- **判据**：`println!` / `log::` / `format!` 里直接拼接密码、token、密钥变量
- **确认**：日志是否会被采集/上报。**日志里的密钥等同于泄露**
- **修法**：打印前脱敏；用 `Debug` 派生时给敏感字段加 `#[derive]` 跳过或自定义

---

## 检查方法

```
□ 命令入口（tauri::command / handler）里有 unwrap 吗？输入来自外部吗？
□ 整数运算在 release 下会回绕吗？（不能只测 debug）
□ unsafe 上方写 SAFETY 了吗？契约能复核吗？
□ 有 .lock() 之后 .await 吗？（死锁 / Send 违反）
□ 前端传来的路径做过 canonicalize + starts_with 吗？
□ 容量/长度来自外部时设上限了吗？
□ unwrap_or_default 掩盖的是不是关键错误？
```

## 与 clippy / miri 的分工

| 工具 | 管什么 |
|---|---|
| `cargo clippy` | 惯用法、明显冗余、**部分** unwrap 建议 |
| `cargo miri` | 未定义行为的**实际检测**（`unsafe`、借用违规） |
| `cargo test` | 行为正确性 |
| `RUSTFLAGS=-C overflow-checks=on` | 让 release 也检查溢出（**验证 RS-02 必备**） |
| **本包** | 业务语义：命令边界入参、release 行为差异、unsafe 契约、锁跨 await |

**证明手段**：RS-02 必须加 `overflow-checks=on` 重新编译验证；
RS-03/RS-09 靠 `cargo miri`；RS-04 靠编译器（`Send` 检查）与压测。
本包只给线索，不替代这些。

## 常见误报

- **`main()` 与测试代码里的 `unwrap`** —— 启动失败就该崩，这是正确用法
- **`Lazy`/`OnceLock` 初始化里的 `unwrap`** —— 只跑一次且必然成功
- **内部常量解析的 `unwrap`**（如 `Regex::new(r"...").unwrap()` 对字面量）→ 确认后忽略
- **已用 `?` 传播的函数** —— 本包只报 unwrap，不报 `?`
- **`unwrap_or` 用于纯展示字段** —— 降级 P3

## Tauri 专项补充

用 Tauri 时额外过一遍（`s-backend` K-01/K-02 的 Rust 形态）：

- **命令白名单**：`tauri.conf.json` 的 `allowlist` 是否按需开启，别整段放开
- **shell 执行**：`Command::new(...)` 的参数是否拼接了外部输入（命令注入）
- **路径穿越**：见 RS-05，前端校验不算数
- **前端直连**：`emit_all` 是否泄露内部状态给所有窗口
