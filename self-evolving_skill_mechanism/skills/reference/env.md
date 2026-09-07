# 环境分化：同一技能的多个版本

> 同一件事在不同环境下写法不同。这不是冲突，是**版本分化**——两条都要留。

## 为什么不能只留一条

你今天在 Python 3.12 + Linux + 有 `rg` 的环境下，
下次可能面对 3.8 + Windows + 只有 `grep`。
**删掉旧写法 = 下次重新踩坑**，正是自进化机制要避免的。

同理，不要因为"我现在用不上"就删——那和删低频技能是同一个错误。

## 用法

### 1. 标注适用范围

在技能 frontmatter 加 `applies_to`：

```yaml
---
id: C006
name: 跨文件批量替换
applies_to: sed, os:linux
keywords: [替换, sed, 批量]
---
```

### 2. 加载前检查

```bash
python3 scripts/env.py --check "python>=3.8, os:linux"
# → ✓ 适用 / ✗ 不适用
```

### 3. 探测当前环境

```bash
python3 scripts/env.py
# Python  : 3.10.12  (linux)
# OS      : posix    Shell: bash
# 可用工具: rg, git, zip, unzip, jq, curl, ...
```

## 约束表达式写法

| 写法 | 含义 | 示例 |
|---|---|---|
| `python>=3.10` | Python 版本 | `python<3.12` |
| `python==3.8` | 精确版本 | |
| `os:linux` / `os:windows` / `os:darwin` | 系统 | `os:posix`（含 linux/darwin） |
| `rg` / `git` / `docker` / `zip` | 工具是否可用 | |
| 逗号分隔 | **同时满足** | `python>=3.8, os:linux` |

## 组织方式：同一 ID 多版本 vs 分开 ID

**推荐：分开 ID，互相 `related`。**

```yaml
# C006a
id: C006a
name: 批量替换（GNU sed）
applies_to: os:linux
related: [C006b]

# C006b
id: C006b
name: 批量替换（macOS/BSD sed）
applies_to: os:darwin
related: [C006a]
```

**为什么不用一个 ID 多段**：索引里一行一条，多版本会看不清有几个变体；
分 ID 后各自独立计数，也能看出哪个变体真被用到了。

## 写入时机

捕获到"这个方法在我的环境下不行，换了个写法"时：

- **不是**删掉旧写法
- **而是**给新写法加 `applies_to`，并在旧写法上补 `related`

例：发现 macOS 上 `sed -i` 要写成 `sed -i ''`
→ 新增 C006b（标注 `os:darwin`），C006a 补 `related: [C006b]`

## 反模式

| ❌ 不要 | 后果 | ✅ 应该 |
|---|---|---|
| 删掉"过时"的写法 | 换环境就抓瞎 | 留着，标 `applies_to` |
| 一条里写"Windows 用 X，Linux 用 Y" | 加载时全读进来了 | 拆成两条，按需加载 |
| 不标注直接用 | 在不适用的环境加载，白占上下文 | 加载前 `--check` |
