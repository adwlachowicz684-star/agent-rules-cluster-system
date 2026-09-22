# 语言包：Java（p-java）

**触发**：仓库里有 `.java` 文件（`pom.xml` / `build.gradle` 是强信号）。
**风险**：资源未关闭、线程池不退出、中断被吞、并发集合误用、异常被吞。

`overlaps:` 本包只放 **Java 语义特有**的判据。
跨语言并发判据主条目在 `s-concurrency` R-01~R-10 —— 本包是它们的 Java 形态：
JAVA-02↔R-02、JAVA-03↔R-03（中断即取消）、JAVA-04↔R-01。
注入类归 `s-backend`（K-08 命令注入、K-32 反序列化），本包不重复。

```bash
python3 scripts/scan-java.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
python3 scripts/scan-java.py --self-test        # 改规则后必跑
```

---

## 核心判据：Java 的静默失败常藏在中立的 API 名字后面

| 形态 | 为什么静默 |
|---|---|
| `ExecutorService` 不 shutdown | JVM 不退出，但看不出是谁在撑着 |
| catch `InterruptedException` 后什么都不做 | 中断标志被清掉，上层永远等不到 |
| 异常被 catch 后只打日志 | 调用方拿到正常返回值，按成功继续走 |

---

## 模式清单

### JAVA-01 (P0) 资源未用 try-with-resources
- **判据**：`new FileInputStream` / `new FileOutputStream` / `Connection` /
  `Statement` / `ResultSet` / `BufferedReader` 等 `Closeable` 赋值给变量，
  但不在 `try (` 里，也没有 `finally { .close() }`
- **确认**：异常路径下是否释放。抛错即泄漏 → **P0**
- **典型**：`Connection c = ds.getConnection();` 中途抛异常 → 连接池耗尽
- **修法**：`try (Connection c = ds.getConnection()) { ... }`
- **降级**：成员变量（生命周期更长）→ P2

### JAVA-02 (P0) ExecutorService 未 shutdown
- **判据**：出现 `Executors.newFixedThreadPool` / `newCachedThreadPool` /
  `newSingleThreadExecutor` / `new ThreadPoolTaskExecutor`，但无 `shutdown()` / `shutdownNow()`
- **确认**：是每请求创建还是全局单例。**每请求创建** → 线程数随请求累积到 OOM
- **典型**：某个方法里 `Executors.newCachedThreadPool()` → 每次调用建一个线程池，永不回收
- **修法**：全局共享线程池 + 显式 shutdown；或用 Spring 托管的 `ThreadPoolTaskExecutor`

### JAVA-03 (P0) InterruptedException 被吞（中断标志未恢复）
- **判据**：`catch (InterruptedException` 后既不 `Thread.currentThread().interrupt()`
  也不重新抛出
- **确认**：上层依赖中断来取消任务时，这里吞掉 = **取消永远不生效**
- **典型**：`catch (InterruptedException e) { log.warn("interrupted"); }` ——
  中断标志已被 JVM 清除，上层 `Future.cancel(true)` 形同虚设
- **修法**：`catch (InterruptedException e) { Thread.currentThread().interrupt(); return; }`
- **定级**：**P0** —— 这是 Java 里最常见、也最难查的取消失效

### JAVA-04 (P0) 并发集合误用
- **判据**：`HashMap` / `ArrayList` / `HashSet` / `StringBuilder` 被
  **多线程共享写**（附近有 `Thread` / `Executor` / `@Async` / `Runnable`）
- **确认**：确认该集合是否真的跨线程。是 → `HashMap` 并发 `put` 可能**死循环**（JDK7 扩容环形链表）
- **修法**：`ConcurrentHashMap` / `CopyOnWriteArrayList` / `Collections.synchronizedXxx`

### JAVA-05 (P1) ThreadLocal 在线程池中串数据
- **判据**：`ThreadLocal` / `InheritableThreadLocal` 声明，且附近有线程池
- **确认**：线程复用 → 上一次请求的值会被下一次读到（**跨请求数据串扰**）
- **典型**：`ThreadLocal<User> currentUser` 在线程池里不 remove → 用户 A 看到用户 B 的数据
- **修法**：`finally { tl.remove(); }`

### JAVA-06 (P1) synchronized 使用不当
- **判据**：两种——① `synchronized` 锁在**字符串常量**或 `Integer` 等会被 intern/缓存的对象上
  ② 同步块内做 IO / 远程调用（粒度过粗）
- **确认**：① 会导致**不相关的代码意外互斥**（甚至死锁）② 会让所有线程串行等网络
- **修法**：用专用 `private final Object lock = new Object()`

### JAVA-07 (P2) equals 与 hashCode 不配对
- **判据**：类里有 `equals(` 但没有 `hashCode(`，或反之
- **确认**：该类是否放进 `HashMap` / `HashSet`。是 → 查不到、重复插入
- **修法**：两者同时重写（IDE 可生成）

### JAVA-08 (P1) static 可变共享状态
- **判据**：`static` 非 `final` 的集合/可变对象字段（`static Map` / `static List` / `static StringBuilder`）
- **确认**：是否有多处写入。是 → 竞态 + 内存泄漏（类加载器无法回收）
- **修法**：`static final` + 不可变；或改实例字段 + 依赖注入

### JAVA-09 (P0) 异常吞没
- **判据**：`catch (Exception` / `catch (Throwable` 后既不抛出也不记录
  （空块或只有注释），或 `printStackTrace()` 后继续执行
- **确认**：调用方能否区分成功失败。不能 → **静默失败**
- **典型**：`catch (Exception e) { /* ignore */ }`
- **降级**：`printStackTrace()` 至少有痕迹 → P1（但仍应改日志框架）

### JAVA-10 (P1) 非线程安全的共享格式化/日期对象
- **判据**：`SimpleDateFormat` / `DateTimeFormatter`（旧版）/ `DecimalFormat`
  声明为 `static` 字段并被多线程使用
- **确认**：`SimpleDateFormat` **不是线程安全的**，共享会产出错乱日期
- **修法**：每次 new；或 `DateTimeFormatter`（不可变，线程安全）；或 `ThreadLocal`

---

## 检查方法

```
□ Closeable 是 try-with-resources 还是裸 new？（异常路径泄漏）
□ 线程池是全局共享还是每次新建？谁 shutdown？（线程累积）
□ catch InterruptedException 后恢复中断标志了吗？（取消失效）
□ 跨线程写的集合是 HashMap 还是 ConcurrentHashMap？（死循环/丢数据）
□ ThreadLocal remove 了吗？（跨请求串扰）
□ 锁对象是不是字符串常量/Integer？（意外互斥）
```

## 与 SpotBugs / Error Prone 的分工

| 工具 | 管什么 |
|---|---|
| SpotBugs | 空指针、资源泄漏（部分）、并发 bug 模式 |
| Error Prone | 编译期错误模式、集合误用 |
| Checkstyle | 风格、命名 |
| **本包** | 业务语义：线程池生命周期、中断语义、跨请求串扰、取消传播 |

## 常见误报

- **成员变量形式的资源** —— 生命周期由容器管理，`@PreDestroy` 里会关 → 确认后忽略
- **全局单例线程池** —— 生命周期等同应用，不 shutdown 可接受 → P2
- **单线程上下文里的 HashMap** —— 无并发即无问题
- **确实可忽略的异常**（如关闭时的 IOException）→ 加注释说明后忽略
- **测试代码** —— 降 P3
