<!-- oversize-exempt: 语言包，确认候选时需整体对照本包全部判据 -->
# 语言包：Python（p-python）

**触发**：仓库里有 `.py` 文件（含脚本、服务、工具、测试）。
**风险**：Python 的缺陷形态与 TS/JS 不同——**不能把 TS 规则翻译一遍了事**。

`overlaps:` 本包只放 **Python 语义特有**的判据。
通用的归各自场景：不安全反序列化归 `s-backend` K-32、敏感日志归 `s-sandbox` S-10、
命令注入归 `s-backend` K-08（本包的 PY-10 是它的 Python 形态，同源不重复报）。

> **为什么需要单独一个语言包**：`scan-ts.py` / `scan-app.py` 对 Python 输出
> `文件: 0　候选: 0`。这不是「没命中」，是**压根没看**（该陷阱见 `route.md` 末节）。
> 本包配 `scripts/scan-py.py`（AST 驱动），让 Python 真正进入审查范围。

```bash
python3 scripts/scan-py.py --src=<根> [--p0] [--json] [--sarif=out.sarif]
python3 scripts/scan-py.py --self-test        # 改规则后必跑，20/20
```

---

## 核心判据：Python 的静默失败有四种独有形态

| 形态 | 为什么静默 |
|---|---|
| 可变默认参数 | 默认值在**模块加载时求值一次**，跨调用累积，只有运行一段才看得出 |
| `except Exception: pass` | 异常被吞，调用方拿到的是正常返回值 |
| `assert` 做校验 | `python -O` 下 assert 被整体移除，校验凭空消失 |
| `__del__` 里做清理 | 解释器退出期不保证执行，资源静默泄漏 |

---

## 模式清单

### PY-01 (P0) 可变默认参数
- **判据**：`def f(x=[])` / `={}` / `=set()`，且函数体内对该参数做 `append` / `update` / `add` 等
- **确认**：连调两次不带该参数，看返回值是否累积
- **典型**：`def add_item(x, acc=[]): acc.append(x); return acc` —— 第二次调用返回第一次的结果
- **修法**：`acc=None` + `acc = acc or []`
- **定级**：函数体内检出修改 → P0；仅声明未检出修改 → P1（需人工确认）
- **为什么易漏**：第一次调用永远正确，只在第二次起暴露

### PY-02 (P0) 宽泛异常吞没
- **判据**：`except:` / `except Exception:` / `except BaseException:` 后**不重新抛出**
- **确认**：看 handler 里有没有 `raise`；没有则异常路径对调用方完全不可见
- **降级**：清理路径（如 `finally` 里关文件）且已注释说明 → P2
- **注**：与 `s-atomicity` A-02 同源，本条是 Python 语法形态

### PY-03 (P1) 资源未用 `with`
- **判据**：`open()` / `socket.socket()` / `Lock()` / `Popen()` 直接赋值给变量，无 `with`
- **确认**：异常路径下是否释放。抛错即泄漏 → 升 P0
- **修法**：`with open(p) as f:`；锁用 `with lock:`

### PY-04 (P0) 并发无同步证据（Python 形态，主判据见 `s-concurrency` R-01）
- **判据**：出现 `Thread` / `Process` / `ThreadPoolExecutor` / `asyncio.create_task`，
  但文件内**找不到** `Lock` / `Queue` / `Semaphore` 等任何同步原语
- **确认**：画出被这些任务共同读写的状态；有共享且无同步 → 真竞态
- **降级**：任务间无共享状态（纯计算、参数传入结果返回）→ P2

### PY-05 (P0) 不安全反序列化（Python 形态，主判据见 `s-backend` K-32）
- **判据**：`pickle.loads` / `pickle.load` / `marshal.loads` / `yaml.load`（无 `SafeLoader`）
- **确认**：数据来源是否可被外部控制（网络、文件上传、消息队列）。是 → 任意代码执行
- **修法**：改 JSON / `yaml.safe_load`；必须 pickle 则验签
- **降级**：数据完全由本进程产生且不可被替换 → P2

### PY-06 (P0) 敏感数据进日志（Python 形态，主判据见 `s-sandbox` S-10）
- **判据**：`log/print/logger.*` 的参数名或关键字名含
  `password` / `token` / `secret` / `api_key` / `身份证` / `phone` 等
- **确认**：该日志是否落盘/上报。落盘即长期泄露，比内存泄露更严重
- **修法**：脱敏（只留前 4 位）、或移出日志字段
- **注意**：关键字名本身也要查——`logger.info("login", password=pw)` 的敏感信息在 **arg** 上

### PY-07 (P1) `__del__` 中执行 IO / 加锁
- **判据**：`__del__` 里有 `open()` / `socket` / `requests` / `acquire()`
- **确认**：解释器退出期模块可能已被回收，这些调用会抛异常或静默失败
- **修法**：显式 `close()` + `atexit` / 上下文管理器
- **定级**：`__del__` 里做跨线程操作 → 归 `s-concurrency` R-10，升 P0

### PY-08 (P1) 模块级可变全局且被修改
- **判据**：模块级 `X = {}` / `= []`，且全文件有对 `X` 的修改（`X[k] = v` / `X.append(...)`）
- **确认**：是否有多线程/多请求同时读写。是 → 竞态
- **⚠ 不要按「全大写就跳过」降级**：名为常量、实际被改的（`CACHE[k] = v`）
  恰恰最危险——名字暗示不可变，读代码的人不会加锁
- **降级（实测 68 条里 67 条是误报）**：只读常量（`EXCLUDE_DIRS` / `LEVEL_DESC`）→ 忽略。
  **判据只看「有没有被改」**

### PY-09 (P1) `assert` 做运行时校验
- **判据**：`assert isinstance(...)` / `assert x is not None` / `assert len(x) > 0`
- **确认**：生产是否可能跑 `python -O`。是 → 校验凭空消失
- **修法**：改成显式 `if ...: raise ValueError(...)`
- **降级**：仅测试文件或内部开发脚本 → P3

### PY-10 (P0) `shell=True` / `os.system`（Python 形态，主判据见 `s-backend` K-08）
- **判据**：`subprocess.*(..., shell=True)` / `os.system()` / `os.popen()`
- **确认**：命令串是否拼接了外部输入。是 → 命令注入
- **修法**：传参数数组 `subprocess.run(['ls', '-l'])`，不用字符串拼接

### PY-11 (P0) 裸 `except:`
- **判据**：`except:` 不指定异常类型
- **后果**：连 `KeyboardInterrupt` / `SystemExit` 一起吞掉，Ctrl-C 都停不下来
- **修法**：`except Exception:` 起，最好指定具体类型

### PY-12 (P2) naive datetime（无时区）
- **判据**：`datetime.now()` / `utcnow()` / `fromtimestamp()` 不带 `tz`
- **确认**：是否跨时区部署或与其它时间源比较。是 → 升 P1
- **修法**：`datetime.now(timezone.utc)`
- **注意**：本条在 **TZ=UTC 的机器上测不出来**（沙盒 / 容器默认常为 UTC）——
  naive 与 aware 此时看不出差别。显式设 `TZ` 并**断言与 UTC 有差值**才有效。
  另见 `s-backend` K-33 的「探测静默退化」（没装 tzdata 时 `TZ` 名会被静默回退）

### PY-13 (P1) 清理 / 回滚用 `except Exception`（抓不到 `BaseException`）
- **判据**：清理、回滚、状态恢复、资源释放代码被 `except Exception` 包裹
- **后果**：`KeyboardInterrupt` 是 `BaseException` **子类**，不走 `except Exception`
  → 用户 Ctrl-C 时清理**不执行** → 留下 `s-atomicity` **A-18 / A-19** 的残留
- **与 PY-11 的分界**：PY-11 是**裸 `except:`**（连类型都不指定，直接吞）；
  本条是**写了 `except Exception`，看起来很规范**，但做清理时同样漏
- **修法**：`except BaseException:` 清理后 `raise`（**不要吞**），
  或把清理放 `finally`（中断时**也会**执行）
- **连带陷阱**：很多人以为 `except Exception` 能兜住清理，
  于是把清理写在 `except` 里而非 `finally` 里 —— 后者在中断时照样执行
- **确认**：搜 `except Exception` / `except:`，
  逐个判断 handler 体里是不是清理 / 回滚代码（含
  `close` / `unlink` / `remove` / `rollback` / `cleanup` / `delete` / `restore`）
- **实测**：某推送工具把「建 tree / commit / PATCH / 本地 commit」包进
  `try ... except BaseException: _cleanup_failed_branch(); raise` ——
  修复前 PATCH 之后 Ctrl-C 会留下孤儿分支；改后无残留

---

### PY-14 (P1/P0) 生成器被二次消费 → 第二次恒为空

- **判据**：`difflib.unified_diff` / `map` / `filter` / `zip` / 生成器表达式 /
  `re.finditer` 的返回值赋给变量后被**两次以上**消费
  （两次 `for`、两次 `sum()`、两次 `list()`，或 `if any(...)` 后再 `sum(...)`）。
  第二次拿到的是**已耗尽**的迭代器 → 恒为空 / 恒为 0

- **确认**：
  ```bash
  grep -nE "=\s*(difflib\.|map\(|filter\(|zip\(|re\.finditer\()" <file>
  # 追踪该变量被用了几次
  ```

- **定级**：
  - 结果用于**展示 / 统计** → **P1**（信息失真）
  - 结果用于**判定 / 校验**（`if not gen`、`sum(...) == 0` 决定流程分支）
    → **P0**（判定失效，常表现为「永远通过」）

- **修法**：
  ```python
  d = list(difflib.unified_diff(old, new, n=0))     # 物化
  add = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
  sub = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
  ```

- **实测**：`old=[a,b,c,d] / new=[a,X,c]`（真实 +1/-2），
  两次遍历同一生成器 → 输出 `+1 / -0`。
  该预览是人工确认推送内容的**唯一**内容差异展示环节
  → 按 common-severity「对外承诺完全失效」定 P0

- **同类**：`any(gen)` 后再 `list(gen)`；`if gen:` 后再遍历（生成器永真）


---

### PY-15 (P1) `subprocess` 的 `errors=` 只配了输出，没配输入

- **判据**：`subprocess.run(..., text=True)` 且存在 `input=` 参数时：
  - `errors=` 只影响 **stdout/stderr 的解码**（输出方向）
  - **stdin 的编码**由 `input` 参数走另一条路，`text=True` 下默认**严格 UTF-8**
  → 传入含 surrogate / 非法字节的字符串时抛 `UnicodeEncodeError`，
  **崩溃位置比修之前更隐蔽**

- **确认**：
  ```bash
  grep -nE "subprocess\.run\(.*text=True.*input=|input=.*text=True" <file>
  # 是否有 errors=
  ```

- **修法**（三选一）：
  ```python
  # ① 传 bytes，绕开文本层
  subprocess.run(cmd, input=data_bytes, capture_output=True)

  # ② 显式双端 errors
  subprocess.run(cmd, input=s, capture_output=True,
                 text=True, encoding="utf-8", errors="surrogateescape")

  # ③ 入口处拒绝，给出可诊断的报错
  if any(0xD800 <= ord(c) <= 0xDFFF for c in s):
      raise SystemExit("路径含非法 UTF-8 字节")
  ```

- **实测**：同一文件里 `git()` 正确写了 `errors="surrogateescape"`，
  甚至配注释警告「只修输出不修输入，崩溃只是换个地方（实测）」；
  而几十行外的 `local_blob_sha()` 用 `input=os.readlink(full)` 恰恰**漏在输入方向**
  → symlink 目标含 `\xff` 时实测抛 `UnicodeEncodeError`。
  **注释警告的坑就在几十行外真实存在** —— 典型的「局部修复未推广到同族调用点」

---

- **形态扩展：不止 `subprocess`，任意成对 encode / decode 路径都算**
  同一份数据有「读侧」与「写侧」两条编码路径时，只修一侧等于没修：
  读侧用 `surrogateescape` 容错、写侧用严格的 `.encode()` /
  `open(..., encoding="utf-8")`，非法字节会在**写侧**炸。
  确认：对每条数据列出所有 `encode` / `decode` / `open` / `subprocess` 调用点，
  逐个比对 `errors=` / `encoding=` 是否一致。
- **实测**：symlink 目标在算 sha 时用
  `os.readlink(full).encode("utf-8", "surrogateescape")`，
  建 blob 上传时却用 `os.readlink(full).encode()`（默认 strict）
  → 非 UTF-8 目标在建 blob 前抛 `UnicodeEncodeError`。


## 检查方法

```
□ 默认值里有没有可变对象？（跨调用累积）
□ except 之后是 raise 还是 pass？（静默失败）
□ 资源是 with 还是裸赋值？（异常路径泄漏）
□ 有没有 assert 在守大门？（-O 下失效）
□ 起线程的地方，共享状态靠什么保护？（竞态）
□ 反序列化的输入谁可控？（任意代码执行）
□ 日志里有没有凭据/PII？（落盘即泄露）
□ 清理/回滚用的是 except Exception 吗？Ctrl-C 时还执行吗？（PY-13 → P1）
□ 报错里有没有凭据原文？（S-10）
□ 写进磁盘的凭据/状态文件是 0600 吗？（S-10）
```

## 与其它工具的分工

| 工具 | 管什么 |
|---|---|
| Flake8 / Ruff | 风格、未用变量、基础质量 |
| Bandit | 已知安全 CVE 模式（硬编码密钥、`eval` 等） |
| **本包** | **业务风险**：跨调用累积、静默失败、资源生命周期、并发、测试证据 |

**不重复造轮子**：已有工具能查的不重复报。本包只管它们管不到的业务语义。

## 常见误报

- **只读常量被判为可变全局** —— 已加降级（无 mutate 即跳过）
- **`except Exception: pass` 在清理路径** —— 确认后降 P2，建议加注释说明为什么可以忽略
- **`shell=True` 但命令是字面量常量** —— 无外部输入拼接 → 降 P2
- **测试文件里的 assert** —— pytest 依赖 assert，不报
- **脚本类文件的模块级全局** —— 单进程短生命周期，无并发 → 降 P2

### PY-16 (P1) `subprocess.run(timeout=)` 未捕获 `TimeoutExpired`
- **判据**：`subprocess.run(..., timeout=N)` 没有 `try` 包，
  或只 `except OSError` —— **`TimeoutExpired` 不是 `OSError` 子类**
  （它继承 `SubprocessError`），因此抓不到，超时直接裸抛 traceback
- **同类**：`check=True` 时抛的 `CalledProcessError` **同样**是
  `SubprocessError` 而非 `OSError`，`except OSError` 也抓不到
- **确认**：
  ```bash
  grep -nE "subprocess\.run\([^)]*timeout=" <file>      # 有没有 try
  grep -nE "except (OSError|Exception)" <file>            # 抓的是哪一层
  ```
  每个带 `timeout=` 的调用点都要单独查 —— **辅助函数里捕获了，
  不代表所有调用点都安全**（见实测）
- **实测**：某推送脚本自己封装的 `git()` 辅助函数（行 866）捕获了
  `TimeoutExpired` 并给出可诊断报错；但另一处**直接调**
  `subprocess.run(["git","-C",ROOT,"merge-base",...], timeout=120).returncode`
  没包 `try` → 大仓库里这条命令挂满 120 秒就裸抛堆栈。
  **同一份代码里两处调 git，一处安全一处不安全** —— 正是 A-22 的形态
- **修法**：
  ```python
  try:
      rc = subprocess.run([...], timeout=TIMEOUT).returncode
  except subprocess.TimeoutExpired:
      # 超时既不是成功，也不是「确定失败」——按 fail-closed 处理
      return True, (f"...超时（{TIMEOUT}s）\n   无法确认，按最保守方式处理")
  ```
- **定级 P1**（裸 traceback，流程中断）；
  若发生在**写操作之后 / 无法回滚**的位置 → **升 P0**

### PY-17 (P2) 解析外部时间戳时漏掉负时区偏移
- **判据**：用 `split("+")[0]` 之类方式剥离时区偏移，只处理了 `+08:00`，
  **剥不掉 `-05:00`** → 后续 `strptime` 全部失败 → 返回 `None` / `0` / 默认值
- **与 PY-12 的分界**：PY-12 是**生成**时间时 naive（无 tz）；
  本条是**解析**外部时间字符串时格式覆盖不全。两者常同时存在
- **确认**：给解析函数喂**负偏移**样本，看是显式报错还是静默返回哨兵值
- **实测**：时间解析对 `2026-09-01T12:00:00-05:00` 返回 `None`
  → 「距今天数」算不出 → 该条目被静默归入「无需处理」，
  **体检报告少了一条应当清理的分支**。线上服务实际返回 `Z`，
  影响有限——但这是**碰巧安全**，换一个上游就是漏检
- **修法**：用正则同时剥 `+` / `-` 偏移
  （`re.sub(r"[+-]\d{2}:?\d{2}$", "", ts)`），
  或直接用 `datetime.fromisoformat`（3.11+ 已支持 `Z` 与偏移）
- **定级 P2** → 若解析结果参与**清理 / 告警判定**（判错即漏检）则升 P1

## 检查方法

```
□ 默认值里有没有可变对象？（跨调用累积）
□ except 之后是 raise 还是 pass？（静默失败）
□ 资源是 with 还是裸赋值？（异常路径泄漏）
□ 有没有 assert 在守大门？（-O 下失效）
□ 起线程的地方，共享状态靠什么保护？（竞态）
□ 反序列化的输入谁可控？（任意代码执行）
□ 日志里有没有凭据/PII？（落盘即泄露）
□ 清理/回滚用的是 except Exception 吗？Ctrl-C 时还执行吗？（PY-13 → P1）
□ 生成器/迭代器被用了两次吗？第二次是不是恒为空？（PY-14 → P1）
□ 解析外部时间戳时，负时区偏移（-05:00）也能解析吗？（PY-15 → P2）
□ 报错里有没有凭据原文？（S-10）
□ 写进磁盘的凭据/状态文件是 0600 吗？（S-10）
```

## 与其它工具的分工

| 工具 | 管什么 |
|---|---|
| Flake8 / Ruff | 风格、未用变量、基础质量 |
| Bandit | 已知安全 CVE 模式（硬编码密钥、`eval` 等） |
| **本包** | **业务风险**：跨调用累积、静默失败、资源生命周期、并发、测试证据 |

**不重复造轮子**：已有工具能查的不重复报。本包只管它们管不到的业务语义。

## 常见误报

- **只读常量被判为可变全局** —— 已加降级（无 mutate 即跳过）
- **`except Exception: pass` 在清理路径** —— 确认后降 P2，建议加注释说明为什么可以忽略
- **`shell=True` 但命令是字面量常量** —— 无外部输入拼接 → 降 P2
- **测试文件里的 assert** —— pytest 依赖 assert，不报
- **脚本类文件的模块级全局** —— 单进程短生命周期，无并发 → 降 P2

### PY-18 (P2) 文档字符串不在函数体首位 → 变成死表达式
- **判据**：`def` / `async def` 之后**第一条语句不是字符串字面量**，
  而函数体里另有一个独立的三引号字符串（通常紧跟在第一行语句后面）
- **为什么错**：Python 只把**函数体第一条语句位置**的字符串当作 `__doc__`。
  写在别处的字符串只是被求值后**丢弃的表达式** —— 语法合法、多数 linter 不报，
  读代码的人却以为「这里有文档」
- **确认**：`python3 -c "import mod; print(mod.f.__doc__)"` 为 `None` → 命中；
  机扫 `scan-py.py`（PY-18，AST 驱动）
- **后果**：`help()` / `pydoc` / Sphinx autodoc 全部拿不到该文档；
  「查文档」这条路径静默失效
- **修法**：把三引号字符串移到 `def` 之后的第一行；若其实是注释性质，写成 `#`
- **定级**：**P2**；该函数是**对外 API / CLI 子命令 / 有文档承诺**时 → **P1**
- **与 C-08 的分界**：C-08 是「文档与代码矛盾」；本条是「文档**根本没生效**」，
  代码本身可以完全正确
- **实测**：某推送工具 `prune(state, grace_days=...)` 的 `def` 之后第一行是
  `_report_conflict_artifacts()`，其后 10 行三引号文本全部是死表达式 →
  `help(prune)` 取不到「只报告不删除」这条最重要的约定
