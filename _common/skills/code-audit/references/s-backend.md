<!-- oversize-exempt: 后端与外部交互模式表，共 35 条判据，确认候选时需整体对照本场景全部模式 -->
# 场景：原生后端（s-backend）

**触发**：有 Rust / C++ / Go / C# 后端、文件系统操作、子进程、本地网络服务、FFI。
**风险**：资源无上限（OOM）、命令注入面、路径黑名单可绕过、锁中毒崩溃、跨设备操作失败。

以 Rust / Tauri 为主，原则同样适用于 Electron 主进程、Go/C++ 后端。

`overlaps:` **只管后端自身的资源与健壮性**。
后端与前端的**消息契约**归 `s-boundary`；后端的**权限策略**归 `s-sandbox`；
后端命令是否**被文档正确描述**归 `s-contracts`。

---

## 文件系统操作（最高频缺陷源）

| 模式 | 判据 | 级别 |
|---|---|---|
| **K-01** 读入是否有界 | 是否用 `take(cap)` 流式读取，而非 `fs::read` 后截断 | P1 |
| **K-02** `max_bytes == 0` 的语义 | 退化成 `usize::MAX` 还是合理默认值 | **P0** |
| **K-03** 删除保护 | 黑名单是否 `canonicalize` 后比较 | **P0** |
| **K-04** 删除目录 | 是否要求显式 force + dry-run 预览 | P1 |
| **K-05** 递归遍历 | 是否用 `symlink_metadata` 跳过链接点 | P1 |
| **K-06** 跨设备移动 | `rename` 是否有 copy+delete 回退 | P2 |
| **K-07** 路径穿越 | 是否 `canonicalize` / `realpath` 后比较（**`normpath` 不算**）。本地工具可免责，但要在文档写明 | P2 |
| **K-30** 元数据推断 | mode / 类型是否取自版本库索引，而非 `os.access` / `os.stat` 现算 | **P1** |
| **K-31** 子进程返回码 | 包装函数是否丢弃 `returncode` 只看 stdout | **P1** |
| **K-32** 不安全反序列化 | `pickle.loads` / `yaml.load`（无 SafeLoader）/ `ObjectInputStream` / 无 allowlist 的 JSON 转对象。Python 形态见 `p-python` PY-05 | **P0** |
| **K-33** 环境能力探测样本不足 | 用**单个**样本推断整个环境的能力（是否区分权限位 / 是否支持某特性 / 编码是什么） | P2 |
| **K-34** 对可能不存在的路径 `stat` | `os.path.getsize` / `os.stat` / `File::metadata` 用在路径列表上且无 `try`。悬空 symlink、并发删除、权限变更都会抛 | P2 |
| **K-35** 写入 `key = "value"` 格式时 value 未限定字符集 | 把不可信内容写进配置文件（curl `--config`、`-H @file`、生成的 ini/yaml/env）时，只做「排除危险字符」而非「限定真实字符集」 | **P1** |

**典型缺陷**（K-01）：
```rust
let bytes = std::fs::read(p)?;                        // 10GB 直接进内存
let text = &bytes[..bytes.len().min(cap)];            // 之后才截断 → 上限形同虚设
```
先整文件读入再按 `max_bytes` 截断 —— **上限参数形同虚设**，10GB 文件直接 OOM。

**典型缺陷**（K-07，`normpath` 不等于 `canonicalize`）：
```python
full = os.path.normpath(os.path.join(ROOT, rel))      # 只做字符串规整
if full.startswith(ROOT): 通过                        # ← 符号链接被放过
```
仓库内若有指向外部目录的符号链接（`etcdir -> /etc`），
`etcdir/passwd` 通过校验，`open()` 却读到 `/etc/passwd`。
**判据**：路径校验必须解析链接后再比较（`os.path.realpath` / `canonicalize`），
只做 `..` / `.` 的字符串规整等于没校验。
**确认**：造一个 `ln -s /etc <repo>/etcdir`，读 `<repo>/etcdir/passwd` 看是否可读。

**修法注意（易踩）**：用 `realpath` **校验**、用 `normpath` **返回**。
若把 `realpath` 的结果直接当路径用，仓库内的合法符号链接（`link -> sub/t.txt`）
会被改写成 `sub/t.txt`，推送的就不是链接本身了。校验与取值要用两套结果。

**典型缺陷**（K-30，容器里 `os.access` 恒为 true）：
```python
mode = "100755" if os.access(p, os.X_OK) else "100644"
```
容器 / 挂载文件系统（overlayfs、Windows 盘、共享目录）上文件权限常是 `0777`
或 `core.fileMode=false`，此时 `os.access(X_OK)` **恒真**，
结果是把所有改动文件一律写成可执行，污染远端。

**典型缺陷**（K-35，**排除危险字符 ≠ 限定字符集**）：
```python
tok = re.sub(r"[^\x21-\x7E]", "", TOKEN)     # ✗ 只排除「不可见字符」
f.write(f'header = "Authorization: Bearer {tok}"\n')
```
写入的是 `key = "value"` 格式，**引号能被提前闭合、换行能开启新的一行**，
而配置文件是「每行一条指令」。上述白名单拦得住换行，
却**放行** `"`、`\`、反引号、`$()`。

**核心判据**：**白名单应是「限定真实字符集」，不是「排除危险字符」。**
前者是设计保证，后者依赖解析器的具体行为，属于**碰巧安全**。

**实测**（起本地 HTTP 服务收真实请求，curl 当前**无法利用**：
一行只解析一条指令，多余内容被丢弃）—

| token | curl 实际发出的 header | 能否注入新指令 |
|---|---|---|
| `ghp_"x` | `Bearer ghp_`（后续被截断） | 否 |
| `ghp_x\` | `Bearer ghp_x"` | 否 |

**但这依赖 curl 未文档化的解析行为。** 代码注释里自己写着
「白名单把它变成设计保证」，实际并没做到 —— **注释承诺的安全 ≠ 实现的安全**。

**修法**：
```python
if not re.fullmatch(r"[A-Za-z0-9_.-]+", TOKEN):   # ✓ 限定真实字符集
    raise SystemExit("凭据含非法字符，请重新复制")
```
**确认**：① 看写法是 `re.sub(排除)` 还是 `re.fullmatch(限定)`；
② 用**真实解析器实测**（起本地服务收请求），**不要靠推理**；
③ 确认收紧后不误伤合法值（枚举该字段的真实字符集 ——
实测 `ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_` / `github_pat_` 前缀
与旧版 40 位十六进制均不受影响）。

**与 K-08 的分界**：K-08 针对**命令行参数**的 shell 解析；
本条针对**配置文件内容**，两者转义规则完全不同。
**与 S-08 的分界**：S-08 是密钥存储布局可被推导，本条是写入格式。

**确认敏感信息是否进了进程列表**（K-31 的配套手法）：钩住
`subprocess.run` 抓取**真实的 argv**，检查里面有没有凭据 ——
代码里可能做了转义 / 配置文件 / 环境变量等多种处理，
**只有真实 argv 能证明最终形态**。
（实测 fp：token 走 `curl --config` 时，argv 里只剩一个不敏感的临时文件名 ✅）
**判据**：文件 mode 应取自版本库索引（`git ls-files -s`），
索引缺失（新文件）时**回退 `100644` 而非 `100755`** —— 宁可丢执行位，
也不要把 `.md` / `.json` 变成可执行。
**确认**：`git config core.fileMode` 与 `ls -l` 一起看；
`chmod +x` 后 `git ls-files -s` 的 mode 不变 → 该环境不跟踪执行位，禁用推断。

**典型缺陷**（K-31，返回码被吞）：
```python
def git(*a):
    return subprocess.run([...], capture_output=True, text=True).stdout.strip()
```
只看 stdout，`git add` 部分失败（退出码 1，被 `.gitignore` 拦下部分路径）
**照常返回空字符串**，调用方以为成功。
**确认**：造一条必然失败的子命令，看包装函数的返回值是否可区分成功与失败。

**典型缺陷**（K-32，反序列化 = 任意代码执行）：
```python
data = pickle.loads(request.body)          # 攻击者构造 payload 即可执行任意代码
config = yaml.load(f)                      # 无 SafeLoader，同样可达
```
**判据**：先看数据来源是否可被外部控制（网络、文件上传、消息队列）。
可控 + 无 allowlist/签名 → **P0**。
**修法**：改 JSON / `yaml.safe_load`；必须反序列化原生对象则加类型 allowlist + 验签。
**降级**：数据完全由本进程产生且不可被替换（如本地临时文件）→ P2。
**为什么易漏**：代码看起来只是"读个配置"，没有 `eval` / `exec` 那么显眼。

**典型缺陷**（K-33，一个样本代表整个文件系统）：
```python
for line in git("ls-files").splitlines():
    if not line.endswith((".md", ".txt", ".json")):
        continue
    probe = os.path.join(ROOT, line)
    if _file_is_executable(probe):
        _EXEC_RELIABLE = False        # 这一个文件带执行位 → 判整个环境不可靠
    break                             # ← 只探一次就下结论
```
被探到的文件若恰好被 `chmod +x`（合法但少见），整个环境被判为「不区分权限」，
于是**所有**新文件按 `100644` 落盘，可执行位静默丢失。
**判据**：环境能力探测必须**多样本**（≥5）或**可显式覆盖**（配置项 / 命令行开关）。
**确认**：把被探样本改成反例，看结论是否整个翻转。翻转 → 判据过脆。
**定级**：推断错了只是丢元数据 → P2；推断错了导致**放行或拒绝**判定反转 → **P0**。

**探测本身会静默退化（易漏）**：设了环境变量**不等于生效** ——
沙盒常没装 tzdata，此时 `TZ="Asia/Shanghai"` 被解析成无效的 `"Asia"`，
**静默回退 UTC**（实测 `time.tzname` 输出 `('Asia','Asia')`）。
必须改用 POSIX 格式 `CST-8` 才真正生效。
**验证方式**：设完打印 `time.tzname` 确认真的生效了，而不是假设它生效。

**UTC 环境是时间测试的盲区**：沙盒 TZ 常为 UTC，此时
`time.mktime` 与 `calendar.timegm` 结果**完全相同**、
naive 与 aware datetime 也看不出差别 →
**任何只依赖当前时区的测试都恒真、形同虚设**。
**确认**：写时间相关的用例时显式设 TZ，并**断言它与 UTC 有差值**。

**典型缺陷**（K-34，悬空 symlink 让预检崩栈）：
```python
for rel in todo:
    size = os.path.getsize(os.path.join(ROOT, rel))   # 无 try
```
git 允许提交指向不存在目标的符号链接。此时 `os.path.getsize` 抛
`FileNotFoundError`，崩在「大文件预检」这种附属步骤上——
而此时远端对象可能已建、分支已开，状态文件未落盘，留下脏远端状态。
**判据**：对外部路径列表做 `stat` / `getsize` / `open` 必须兜 `OSError`；
symlink 用 `os.lstat` 取长度更符合语义（不跟随链接）。
**确认**：`ln -s no-such-target dangling` 后跑一遍主流程。
**同类**：TOCTOU（stat 之后文件被删）—— 兜底后按「取不到记 0」降级处理即可。

---

## 进程与命令执行

| 模式 | 判据 | 级别 |
|---|---|---|
| **K-08** shell 解析 | 是否存在 `cmd /c` + 外部输入 | **P0** |
| **K-09** 可执行文件来源 | 白名单 vs 用户配置任意路径 | **P0** |
| **K-10** 参数传递 | 参数数组 vs 字符串拼接 | P1 |
| **K-11** 子进程生命周期 | 是否有注册表 + kill 能力 | P1 |
| **K-12** 注册表清理 | 进程结束后是否 remove（否则内存持续增长） | P2 |
| **K-13** 权限声明 | capabilities 里的 spawn 白名单是否克制 | P2 |
| **K-14** 探测命令 | `where` / `which` 起子进程在 debug 下会闪控制台窗口 | P3 |

---

## 本地网络服务

自建 HTTP / WebSocket 服务时逐项查：

| 模式 | 判据 | 级别 |
|---|---|---|
| **K-15** 请求体上限 | 是否按客户端声明的 `content-length` 直接分配 | **P0** |
| **K-16** 读写超时 | 是否设置 `set_read_timeout` / `set_write_timeout` | **P0** |
| **K-17** 绑定地址 | `127.0.0.1` vs `0.0.0.0`（后者对局域网开放） | **P0** |
| **K-18** 鉴权 | token 为空时是否直接放行 | **P0** |
| **K-19** 并发上限 | 每连接一线程是否有上限 | P1 |
| **K-20** 响应构造 | 状态码与 reason 是否匹配（401 却写 OK） | P2 |

**K-18 最容易忽略**：代码写成 `if expected.is_empty() { return true; }`，
本意是「没配口令就不校验」，实际效果是
「**本机任何进程都能触发工作流**」——进而启动子进程、执行文件操作。

**K-15 典型**：`vec![0u8; content_len]` —— 声明 10GB 就分配 10GB。

---

## 锁与错误处理

| 模式 | 判据 | 级别 |
|---|---|---|
| **K-21** `lock().unwrap()` | 是否改为 `unwrap_or_else(\|e\| e.into_inner())` | P1 |
| **K-22** 配合 `panic = "abort"` | 一次锁中毒 = 应用直接崩，无降级空间 | **P0** |
| **K-23** 错误向上抛 | `Result` 是否一路传到命令边界 | P2 |
| **K-24** 阻塞式固定 sleep 轮询 | 该等待是否有更精确的信号（`transitionend` / 事件 / 条件变量）。有 → 应替换，P2；串起来造成可感卡顿（>1s）→ P1 | P2 |

---

## 命令注册与状态管理

| 模式 | 判据 | 级别 |
|---|---|---|
| **K-25** 注册完整性 | 命令是否都在 `invoke_handler` 里注册（未注册 = 死代码） | P2 |
| **K-26** 孤儿文件 | `.rs` 文件是否都被 `mod` 声明（未声明 = 改了不生效） | P2 |
| **K-27** 重复实现 | 是否存在内容近似但已分叉的两份文件（**最危险**：改了不生效） | **P1** |
| **K-28** 状态管理 | 注册表（进程/监听/端口）是否在对象销毁时清理 | **P1** |
| **K-29** 启动参数 | 是否在 Builder 之前处理自有子命令，避免与框架参数冲突 | P2 |

**注意**：`build.rs` 是 Cargo 约定的构建脚本，本就不该被 `mod` 声明，不算孤儿。

---

## 依赖与构建

- 引入的每个 crate 都要能说清为什么不能用标准库替代
- 平台特定依赖（Windows 句柄类型）要写明规避理由
- release profile（`lto` / `panic` / `strip`）与错误处理能力要匹配

---

### K-36 (P1) 错误分类用宽泛子串匹配，且丢弃原始错误信息

- **判据**：把上游错误按**子串匹配**分到若干「处理策略」类目，且：
  ① 命中词在语义上**同时覆盖多种真实原因**
  （如 `not mergeable` 既是「分支旧」也是「真冲突」；
  `Required status check` 与「分支旧」根本无关）
  ② 分类后**丢弃原始 message**，只输出预设的模板文案

- **确认**：
  ```bash
  grep -nE "_HINTS|any\(h in msg|in msg\.lower\(\)" <file>
  # 看命中词表是否含语义模糊项；看 except 块是否 re-raise 原文
  ```

- **后果**：给出**不可执行的修复建议**（如提示「去点 Update branch」，
  而该按钮在特定状态下不存在）。按 common-severity 文档类判据属 P1；
  若导致用户销毁防护机制（重置基线 / 加 `--force`），升 P0

- **修法**：
  ```python
  # ① 命中词只留语义唯一的
  _NEED_UPDATE = ("Base branch was modified", "not up to date")

  # ② 分类后必须保留原文
  except SystemExit as e:
      print(f"上游原文：{e}")        # 兜底信息，不能丢
      if any(h in str(e) for h in _NEED_UPDATE):
          ...
  ```

- **实测**：某推送工具的 `_NEED_UPDATE_HINTS` 含 `not mergeable` 与
  `Required status check`；已合并 PR 重跑撞 405，被判 `need_update`
  → 提示「去网页点 Update branch」，而 PR 已合并，**该按钮不存在**


---

### K-37 (P1) 分页接口设了 `per_page` 但不翻页

- **判据**：请求带 `per_page=N` / `limit=N` / `page_size=N`，
  但**没有** `page` 递增循环，也没有「结果可能被截断」的提示

- **确认**：
  ```bash
  grep -nE "per_page|limit=|page_size" <file>
  grep -nE "page=|offset=|cursor" <file>       # 为空即成立
  ```

- **定级**：
  - 结果用于**展示 / 统计** → P2
  - 结果用于**完整性判定**（清理扫描、遗漏检查、全量比对）→ **P1**：
    漏报比误报更危险，因为「没报」被理解为「没有」

- **修法**：
  ```python
  def list_all(path):
      out, page = [], 1
      while True:
          batch = api("GET", f"{path}&per_page=100&page={page}") or []
          out += batch
          if len(batch) < 100:
              break
          page += 1
      return out
  ```

- **实测**：某推送工具三处均设 `per_page=100` 无翻页。
  `--prune` 用于分支清理扫描，超 100 个分支时**静默漏报**，
  而该命令的全部价值在于不漏

---

## 常见误报

- **「刻意不引第三方 crate」** —— 注释常会解释（如「少一个依赖就少一类编译失败」）
- **「路径穿越不做限制」** —— 本地工具可免责，但需确认文档写明
- **「用 std::fs 而非官方 fs 插件」** —— 语义上更接近「执行一条命令」，
  可省去逐条声明路径权限，不是缺陷
- **「硬编码 sleep 等待」** —— 若有更精确的信号可用才报（见 K-24）
