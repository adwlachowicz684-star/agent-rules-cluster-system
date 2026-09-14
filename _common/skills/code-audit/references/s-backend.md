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

| 模式 | 判据 |
|---|---|
| **K-25** 注册完整性 | 命令是否都在 `invoke_handler` 里注册（未注册 = 死代码） |
| **K-26** 孤儿文件 | `.rs` 文件是否都被 `mod` 声明（未声明 = 改了不生效） |
| **K-27** 重复实现 | 是否存在内容近似但已分叉的两份文件（**最危险**：改了不生效） |
| **K-28** 状态管理 | 注册表（进程/监听/端口）是否在对象销毁时清理 |
| **K-29** 启动参数 | 是否在 Builder 之前处理自有子命令，避免与框架参数冲突 |

**注意**：`build.rs` 是 Cargo 约定的构建脚本，本就不该被 `mod` 声明，不算孤儿。

---

## 依赖与构建

- 引入的每个 crate 都要能说清为什么不能用标准库替代
- 平台特定依赖（Windows 句柄类型）要写明规避理由
- release profile（`lto` / `panic` / `strip`）与错误处理能力要匹配

## 常见误报

- **「刻意不引第三方 crate」** —— 注释常会解释（如「少一个依赖就少一类编译失败」）
- **「路径穿越不做限制」** —— 本地工具可免责，但需确认文档写明
- **「用 std::fs 而非官方 fs 插件」** —— 语义上更接近「执行一条命令」，
  可省去逐条声明路径权限，不是缺陷
- **「硬编码 sleep 等待」** —— 若有更精确的信号可用才报（见 K-24）
