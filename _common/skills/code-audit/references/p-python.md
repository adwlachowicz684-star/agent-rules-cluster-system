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
