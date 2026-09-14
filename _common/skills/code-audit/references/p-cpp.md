# 语言包：C/C++（p-cpp）

**触发**：仓库里有 `.c` / `.cc` / `.cpp` / `.cxx` / `.h` / `.hpp` 文件
（`CMakeLists.txt` / `Makefile` / `Cargo.toml` + `build.rs` 是强信号）。
**风险**：资源所有权不清、异常路径泄漏、缓冲区越界、数据竞争、析构期访问。

`overlaps:` 本包只放 **C/C++ 语义特有**的判据。
跨语言并发判据主条目在 `s-concurrency` R-01~R-10 —— 本包是它们的 C++ 形态：
CPP-05↔R-05、CPP-06↔R-10、CPP-04↔R-01。
整数溢出/角度归一化归 `s-numerics`（N-01~N-19），CPP-08 只记 C/C++ 特有的
**符号转换与 size_t 回绕**。

```bash
python3 scripts/scan-cpp.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
python3 scripts/scan-cpp.py --self-test        # 改规则后必跑
```

---

## 核心判据：C/C++ 的问题大多不是"慢"，是"未定义行为"

| 形态 | 后果 |
|---|---|
| `new` 后异常路径无 `delete` | 泄漏，且只在出错时发生——正常测试永远测不到 |
| `memcpy` 长度来自外部 | 缓冲区溢出，可被利用执行任意代码 |
| 条件变量用 `if` 而非 `while` | 虚假唤醒 → 状态错乱，偶发且难复现 |
| 返回局部变量引用 | 悬垂引用，读到的值取决于栈上残留 |

---

## 模式清单

### CPP-01 (P0) 裸资源所有权不清
- **判据**：`new` / `malloc` / `fopen` / `socket` / `pthread_mutex_init` 出现，
  但文件内**没有**对应的 `delete` / `free` / `fclose` / `close` / `destroy`，
  且未使用智能指针（`unique_ptr` / `shared_ptr`）
- **确认**：数一数每条路径——**正常路径配对了，异常路径呢？**
- **典型**：`char* p = new char[n]; parse(p); delete[] p;` —— `parse` 抛异常就泄漏
- **修法**：RAII —— `std::unique_ptr` / `std::vector` / `std::fstream`
- **定级**：异常路径泄漏 → **P0**；仅所有权不清晰但无异常 → P1

### CPP-02 (P0) 不安全的内存/字符串函数
- **判据**：`strcpy` / `strcat` / `sprintf` / `gets` / `memcpy` / `memset` /
  `alloca` 出现，**长度参数不是常量也不来自 sizeof**
- **确认**：长度是否可被外部输入影响。是 → **缓冲区溢出 = 任意代码执行**
- **典型**：`char buf[64]; strcpy(buf, user_input);`
- **修法**：`snprintf` / `strncpy`（注意末尾补 `\0`）/ `std::string` / `std::vector`
- **降级**：长度是 `sizeof(目标)` 或字面量常量 → 安全，不报

### CPP-03 (P0) 数组/指针越界风险
- **判据**：指针算术（`p + n` / `p[i]`）的下标来自外部输入或循环变量，
  且无边界检查；或 `arr[n]` 的 `n` 来自 `size()` / `strlen()` 之外的计算
- **确认**：下标上界是否收口（同 `s-structures` D-11 尺寸未收口）
- **典型**：`for (int i = 0; i <= n; ++i) a[i] = 0;` —— `<=` 多一个

### CPP-04 (P0) 共享数据无同步
- **判据**：全局/`static` 变量被写，且文件内有 `std::thread` / `pthread_create` /
  `std::async`，但**无** `std::mutex` / `atomic` / `lock_guard`
- **确认**：该变量是否被多线程写。是 → 数据竞争 = 未定义行为
- **修法**：`std::atomic` / `mutex` + `lock_guard`（RAII 式，异常安全）

### CPP-05 (P0) 条件变量用 `if` 而非 `while`
- **判据**：`wait(` 前是 `if (` 而非 `while (`
- **确认**：条件变量的**虚假唤醒**是合法的（POSIX 允许），`if` 会导致条件未满足就继续
- **典型**：`if (queue.empty()) cv.wait(lock);` → 醒来时 queue 可能仍为空 → 崩溃
- **修法**：`cv.wait(lock, []{ return !queue.empty(); });` 或 `while (queue.empty()) cv.wait(lock);`

### CPP-06 (P1/P0) 析构中的危险操作
- **判据**：析构函数 `~X()` 里调用 `lock()` / `open()` / 网络 IO / 虚函数
- **确认**：析构期对象可能已部分销毁，调用虚函数会分发到基类版本
- **定级**：析构里**加锁** → **P0**（与持锁线程互等形成死锁）；其余 → P1
- **注**：与 `s-concurrency` R-10 同源

### CPP-07 (P0) 悬垂引用 / 生命周期错误
- **判据**：函数返回**局部变量或临时对象的引用/指针**；
  或 `string_view` / `span` / 迭代器所引用的容器在其后被修改/销毁
- **典型**：`const std::string& f() { std::string s = "x"; return s; }` —— 返回即悬垂
- **修法**：按值返回；或延长被引用对象的生命周期
- **易漏点**：`std::string_view sv = std::string("tmp");` —— 临时对象语句结束即销毁

### CPP-08 (P1) 整数转换与回绕
- **判据**：`size_t` / 无符号数与 `int` 混算；`n - 1` 形式的长度计算；
  有符号→无符号隐式转换后参与比较
- **典型**：`for (size_t i = v.size() - 1; i >= 0; --i)` —— `size()` 为 0 时下溢成巨大值；
  且 `i >= 0` 对无符号恒真 → 无限循环 + 越界
- **修法**：用反向迭代器；或先判空；避免混用有符号无符号

### CPP-09 (P1) 未初始化的成员/变量
- **判据**：类构造函数初始化列表里**漏掉**某些内置类型成员；
  或 `int n;` 声明后直接参与计算
- **确认**：未初始化的值是**不确定的**（不是 0），调试版和发布版可能不同
- **修法**：成员默认初始化 `int count_{0};`

### CPP-10 (P2) 违反项目运行时策略
- **判据**：项目明确禁用项出现——异常（`throw` / `catch`）、RTTI（`dynamic_cast` /
  `typeid`）、全局 `operator new` 重载、`thread_local`、动态分配
  （游戏/嵌入式项目常见约束）
- **确认**：先读项目规范（如 HotSpot Style 禁用异常与 RTTI）。无规范则不报
- **定级**：P2（是约定违反，非缺陷本身）

---

## 检查方法

```
□ 每个 new/malloc 在异常路径上也有释放吗？（泄漏）
□ 内存函数的长度参数来自哪？能被外部控制吗？（溢出）
□ 条件变量是 while 还是 if？（虚假唤醒）
□ 跨线程写的变量是 atomic 还是有锁？（数据竞争）
□ 有没有返回局部变量引用？（悬垂）
□ 无符号数参与减法/比较了吗？（回绕/恒真）
□ 项目禁用的特性有没有混进来？（策略）
```

## 与 clang-tidy / ASan 的分工

| 工具 | 管什么 |
|---|---|
| `clang-tidy` | 大量现代化与正确性检查（可替代本包多条） |
| ASan / UBSan | **运行时**捕获越界、UAF、未定义行为 |
| TSan | 运行时数据竞争 |
| Valgrind | 泄漏（慢但全） |
| **本包** | 业务语义：所有权设计、异常路径、策略符合性、跨函数生命周期 |

**ASan/TSan 才是证明**。本包报的越界与竞争候选，要用 sanitizer 复现后才算确认。
clang-tidy 已覆盖的规则本包不重复主张——本包价值在于**跨函数的所有权与生命周期推理**。

## 常见误报

- **智能指针管理的资源** —— 无裸 `delete` 是正确的，不报
- **长度是 `sizeof` 的 memcpy** —— 安全，不报
- **单线程代码的全局变量** —— 无竞争
- **单元测试里的裸指针** —— 短生命周期，降 P3
- **C 风格项目用 `malloc/free` 是常态** —— 确认后按 CPP-01 的"异常路径"维度判，
  不要因为"没用 RAII"就报
