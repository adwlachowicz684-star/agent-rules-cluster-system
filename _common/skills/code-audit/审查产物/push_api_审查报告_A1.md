# push_api.py 审查报告 · A1

> **编号说明**：本报告采用独立序列（A1、A2…），不沿用「第 N 轮」，
> 以避开并行窗口的编号体系。内部问题编号沿用既有 A/B/C/D/E/F 族。

**审查对象**：`push_api.py`（3989 行，md5 `1a8b7d48`，自 2026-09-16 起未变）
**审查日期**：2026-09-20
**审查依据**：本仓库 `code-audit` 的 `common-severity.md`（四级 + 8 条升级规则 + 三个反问）、`common-reporting.md`
**审查方式**：AST 静态分析 + 源码实证 + 控制流推导
**本轮结论**：**新增 P1 ×1、P2 ×3**

**证据标注**：【实测】= 本地跑出；【代码事实】= 读码可确证

---

## 一、审查边界

| 项 | 说明 |
|---|---|
| **本轮切口** | `pull()` 完整流程、`_main` 第一层校验三分类、`preview` 参数传递、`api()` raw 与非 raw 两支的重试语义 |
| **前序** | 已出报告：第 10 轮（`--prune` 误删）、第 11 轮（`abandon_task` 缺主干保护）。本轮在其基础上继续 |
| **脚本状态** | 未更新，累计未修 16 条 → 本轮后 **20 条** |

---

## 二、【P1-NEW】`--force-overwrite` 丢失「会把主干回退」的警告

### 两类文件，危险程度天差地别

| 类别 | 判据 | 后果 |
|---|---|---|
| **revert** | 本地 == 基线（**本地没改过**，只是版本旧） | 推送后 `main` 被**回退**到你的旧内容。GitHub 三方合并时 theirs==base、ours 变了 → 直接采纳 ours，**静默回退他人改动** |
| **overlap** | 本地改过 + 远端也改过 | 真并发，合并时可能冲突，**不会静默覆盖** |

脚本自己把这两类分得很清楚（`_main` L3637-3665 的三分类），注释也写明：

> 三分类，不能只分两类……基线缺失必须**单独成类**：那不是「已知本地改过」，
> 是「无法证明本地改过」。二者后果相反，不能混。

### 但 `--force-overwrite` 恰好把它们混了【代码事实】

```python
ok = force or rel in allowed          # L3614
...
if (rmode, rsha) != (base_mode, base_rec_sha):
    if ok:
        todo.append(rel)
        risky.append(rel)
        print(f"  ! {rel} 远端已被改动（已放行，将整文件覆盖）")   # L3633
    else:
        blocked.append(...)                                        # L3635
```

`force=True` 时 `ok` 恒为 True → 文件**直接进 todo**，根本不进 `blocked`
→ 三分类（revert / unrecorded / overlap）**完全不执行**。

**实测对比：**

```
force=False：revert 单独成类 →
    「推送后 main 会被**回退**到你的旧内容」
    「这不是冲突，是覆盖：GitHub 会判定『你故意回退』并直接采纳」
    + raise _Cancel()

force=True ：revert 与 overlap 混在一起 →
    「远端已被改动（已放行，将整文件覆盖）」     ← 唯一提示
```

### 危害

`--force-overwrite` 恰恰是**最紧急、最可能无暇细看**时才用的开关，
而此时最危险的一类（会把主干回退）被降级成了泛泛的"整文件覆盖"。

**缓解因素（如实说明）**：`risky` 确认框仍在（`if risky and not yes`），
用户还有一次确认机会，且文件会被逐一列出。故不升 P0。

### 修法

```python
if ok:
    todo.append(rel); risky.append(rel)
    if _local_matches_baseline(state, lmap, rel):
        print(f"  !! {rel} 你没改过、只是落后 → 推送会把 {BRANCH} **回退**到你的旧内容")
    else:
        print(f"  ! {rel} 远端已被改动（已放行，将整文件覆盖）")
```

---

## 三、【P2-NEW】`pull()` 第二处 `if local is None:` 是死代码，且注释声称它可达

### AST 实证

```
════ pull() 内 `local is None` 的所有判断 ════
  L1940   body 内含 continue: True
  L2050   body 内含 continue: True

两处之间 local 未被重新赋值
第一处 body 有 continue → 第二处 ★ 永远不可达（死代码）
```

L1940 已 `continue`，`local` 在两处之间没有重新赋值，
所以 **L2050 的分支永远不会进入**。

### 注释与事实不符

L2050 上方注释写道：

> 「这段曾被两份审查报告判为死代码（旧版确有前置 continue 提前跳出），
> 修『远端新增文件拉不下来』时调整了控制流，**它才重新可达**。
> 不加这行注释，下一个人还会再判它一次死代码并删掉。」

**前置 continue（L1940）依然存在，它并未重新可达。**

### 为什么值得记

这条注释的**目的**是防止别人误删死代码——但它的**内容**是错的。
结果比没有注释更糟：下一个人读到它会以为"作者验证过，可达"，
从而不再核查。这与 A1（docstring 宣称已实现、代码未接上）是同一类
**「文档覆盖了事实」**的问题，而在本脚本里已是第三次出现。

### 建议

删除 L2050 那段死代码，或把注释改成实际情况。

---

## 四、【P2-NEW】`bypass=True` 与 `blocked` 非空互斥 → 两处提示不可达

### 推导【代码事实】

```
blocked 非空  ⟹ 存在某 rel 走了 blocked.append
              ⟹ 该 rel 的 ok == False
              ⟹ (force == False) 且 (rel not in allowed)      [ok = force or rel in allowed, L3614]
              ⟹ force == False
              ⟹ bypass == False                                [bypass = force, L3324]

∴ blocked 非空 ⟹ not bypass
∴ `if not bypass: raise _Cancel()` 在该上下文恒为真
```

**故以下两行恒不可达：**

```
L3676  print("   --force-overwrite 已放行，上述文件将被回退。")
L3689  print("   已放行，将按本地内容覆盖（无法排除是回退）。")
```

### 含义

代码**承诺** `--force-overwrite` 可以放行 revert / unrecorded 两类文件，
实际做不到——因为 force=True 时它们压根不进 `blocked`（直接进 todo）。

行为上是 **fail-closed（更安全）**，所以不升级；
但这两行 print 会让人误以为该能力存在并可用。

> 注意：L3358 / L3384 另两处 `--force-overwrite 已放行` 属于 P0-1 的
> `stale_local` / `rewound` 分支，**是可达的**，不在本条范围内。

---

## 五、【P2-NEW】`_remote_blob_lines` 的 `size_hint` 参数形同虚设

### 实证

```
定义签名: def _remote_blob_lines(sha, size_hint=None)          # L2827
唯一调用: old, new = _remote_blob_lines(rsha), _local_lines(...)  # L2901
                                        ↑ 只传 sha

★ 所有调用点都只传 sha → size_hint 恒为 None → 该参数形同虚设
```

### 后果

`size_hint` 的本意是「超过上限就不发请求」，直接省掉一次 API 调用。
但调用点从不传它，于是**大文件照样发一次 `GET /git/blobs`**，
直到拿回响应才发现没有 content、再降级返回 None。

这**直接违背** `preview` 里 `PREVIEW_CAP` 注释的意图：

> 每个文件都要一次 GET /git/blobs 拉远端内容……**--dry-run 也照发不误**
> —— 预演既不免费也不无害。叠加建 blob 本身，API 消耗直接翻倍，
> 撞上限流后报 403。

而 `preview` 里**已经算好了** `size = os.path.getsize(...)`（L2889），
本来就是现成的 `size_hint`。

### 修法（1 行）

```python
old, new = _remote_blob_lines(rsha, size), _local_lines(rel, lmode)
```

---

## 六、累计未修清单（20 条）

| # | 问题 | 位置 | 级别 | 来源 |
|---|---|---|---|---|
| A1 | curl 退出码非零未过 `_retryable`（docstring 宣称已实现） | L677-685 | P1 | 4 轮 |
| A2 | 绕过 `git()` 超时（5 处） | L415/864/927/1719/1799 | P2 | 4 轮 + 11 轮修正 |
| B1 | `--pull` 丢弃本地 symlink 改动 | L2057 | P1 | 5 轮 |
| B2 | symlink `.strip()` 致 sha 分叉 | L1766 | P1 | 5 轮 |
| B3 | CI 状态不参与合并决策（`blocked` 归为 need_update） | 全文 + L2371 | P1 | 4 轮 |
| B4 | `--prune` 只认 `task/` 前缀（漏报） | L2735/L2655/L3235 | P1 | 4 轮 |
| B5 | `abandon_task` 无确认、无内容校验 | L2594 | P1 | 4 轮 |
| B6 | `mark_synced` 不查 conflicts（实证：情形 2/3 会漏） | L1635 | P2 | 5 轮 |
| C1 | `ls-files -s` 未用 `-z` | L1472 | P2 | 5 轮 |
| C2 | 远端删除永不落地 | L1922 | P2 | 5 轮 |
| D1 | `_conflict_path` 命名碰撞 | L425 | P2 | 7 轮 |
| D2 | symlink 目标非 UTF-8 两处崩溃 | L1692/L3802 | P1 | 8 轮 |
| D3 | `_local_lines` 不 strip，与写入侧口径相反 | L2853 | P2 | 8 轮 |
| E1 | `--prune` 误删非 `task/` 前缀的活跃 tasks 记录 | L2735+L2696 | P1 | 9-10 轮 |
| E2 | `--dry-run` 门禁白名单漏 `prune` | L3125 | P2 | 9 轮 |
| F1 | `abandon_task` 缺主干保护（`--merge <N>` 可达） | L2594 | P1 | 11 轮 |
| **G1** | **`--force-overwrite` 丢失「会回退主干」警告** | L3633 | **P1** | **A1** |
| **G2** | **`pull()` 第二处 `local is None` 死代码 + 注释声称可达** | L2050 | **P2** | **A1** |
| **G3** | **`bypass`/`blocked` 互斥 → 两处 print 不可达** | L3676/L3689 | **P2** | **A1** |
| **G4** | **`_remote_blob_lines` 的 `size_hint` 从未传入** | L2901 | **P2** | **A1** |

---

## 七、本轮验证过没问题的部分（**不要重复改**）

1. **`pull()` 把「拉取失败」与「冲突」分开**（`failed` 不进 `conflicts`） —— 注释列出了混在一起的三个后果，其中"解除方式只有 `--resolve`，而 resolve 只是清标记——等于逼用户对一次网络抖动做一次毫无意义的冲突解决"
2. **`pull()` 对 `local == remote` 但 mode 不同的处理** —— 会重新 `_write_local` 同步权限位，注释记录了旧版只改基线不 chmod 导致的永久打架
3. **`pull()` 的 `base_ok` 三段判定** —— `baseline` 可信 / `git` 需 `local != base` / 无 base 退回 `dirty0`，注释详细论证了"用户已 commit 时 HEAD 含其改动，拿它当基点会让改动静默消失"
4. **`pull()` 结束故意不 `git commit`** —— 提交了工作区就干净，合并结果反而推不出去
5. **`pull()` 空集合时仍刷新 `synced_commit`** —— 注释列了三种"待合并为空但主干确实前进过"的死锁场景
6. **`_merge3` 只在 `base_ok` 时才写 `.base`** —— 并先清掉上一轮残留，注释说明"陈旧文件会让人以为有共同祖先可比对，比没有更误导"
7. **推送成功后本地补 commit 只提交 `todo` 路径** —— 避免卷走别人 `git add` 的文件
8. **`ensure_pr` 失败时的明确指引** —— "不要 `--delete-branch`（那会删掉本次改动）"，且 `except BaseException` 后 `raise`
9. **大文件预检用 `lstat` 兜 symlink** —— 注释指出 `os.path.getsize` 对悬空软链抛 `FileNotFoundError`，"此时 blob 已建、分支已建、状态未落盘"
10. **`api()` raw 分支对退出码 28（curl 超时）不重试** —— 与超时语义一致，避免重复创建
11. **`api()` 大 payload（>8MB）走临时文件** —— 避免 base64 串 / JSON 串 / 编码字节三份并存
12. **`api()` raw 分支 `_raise_api_error(..., None)`** —— 注释记录了"用不存在的变量会 NameError，上上轮的 P0 就是这么来的"

---

## 八、修复优先级（更新）

```
第一批（各 1-2 行）
  D2   L1692/L3802  .encode("utf-8","surrogateescape")   ← 堵 2 处崩溃
  F1   L2594        abandon_task 补主干保护（建议抽 _guard_not_protected 三处共用）
  G1   L3633        force 时对 revert 类单独警告「会把主干回退」
  G4   L2901        _remote_blob_lines(rsha, size)
  E2   L3125        MUTATING 补 "prune"
  A1   L677-685     补 and _retryable(method, path)
  B6   L1635        mark_synced 加 conflicts 检查
  A2   5 处         补 timeout=DEFAULT_GIT_TIMEOUT

第二批
  E1   L2735/L2696  remote_names 改全量分支（消 B4 的误删面）
  B4   L2735        prune 改排除法（消漏报面）
  D1   L425         _conflict_path 用 hash 或保留目录结构
  G2   L2050        删死代码或改注释
  G3   L3676/3689   删不可达 print 或修正 bypass 逻辑

第三批（需设计判断）
  B1 / B2 / B3 / B5 / C1 / C2 / D3
```

---

## 九、一句话总结

> 本轮四条新发现里，三条是同一种病：**注释/参数/代码承诺了一件事，实际不是那回事**。
>
> - G2：注释写"它才重新可达"，实际永远不可达——**这条注释的目的是防止别人误删，内容却是错的，比没注释更糟**
> - G3：代码承诺 `--force-overwrite` 能放行 revert，实际做不到（行为上更安全，但承诺落空）
> - G4：定义了 `size_hint` 来省 API 调用，唯一调用点不传它，参数形同虚设
> - G1：最实质的一条——`--force-overwrite` 把最危险的 revert 类（会回退主干）
>   降级成了泛泛的"整文件覆盖"，而 force 恰恰是紧急时才用的开关
>
> 加上 A1（docstring 宣称已实现、代码未接上），**「文档覆盖了事实」在本脚本里已第四次出现**。
> 这个脚本的注释密度极高——几乎每个坑都记了成因与实测——
> 但注释一旦写错，它不会报错，只会让下一个人停止核查。
