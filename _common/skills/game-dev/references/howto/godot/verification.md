# 待核对项：运行时录入与验证

## 为什么有这套机制

技能文档里写着大量**"我没有在目标版本/真机上实测过"**的结论。

这些结论如果和已验证结论混在一起，读者无法区分
"可以直接信"和"要先测一下"——而后者被当成前者用，
正是最难排查的一类问题：**代码写对了、逻辑想通了，但前提是错的。**

## 标记格式

写在 Godot 开发文档里，**一行一条**：

```
⚠ 待核对：{结论} · 验证：{怎么验证}
```

例：

```
⚠ 待核对：ArcCast3D 节点是否存在 · 验证：4.7.2 编辑器节点搜索框输入 ArcCast3D
```

⚠ **`验证：` 后面那句是必须的** —— 它决定了这条能不能被验证。
只写"待核对"不写方法的，`verify.py` 会报出来要求补。

## 用法

```bash
python3 scripts/verify.py                # 只看还没验证的（默认）
python3 scripts/verify.py --all           # 含已验证的
python3 scripts/verify.py --stats         # 统计概览
python3 scripts/verify.py --doc=xr-deep.md
python3 scripts/verify.py --grep=手部
```

### 运行时录入

在真机 / 目标版本上验证之后，把结果记下来：

```bash
python3 scripts/verify.py --verify=V5001 --result=ok
python3 scripts/verify.py --verify=V5001 --result=failed \
        --note="4.7.2 编辑器确实没有该节点，需手动实现"
python3 scripts/verify.py --verify=V5004 --result=skipped \
        --note="无头显设备，无法验证"
```

| result | 含义 |
|---|---|
| `ok` | 验证通过，结论成立 |
| `failed` | 验证推翻，结论错了 |
| `skipped` | 无条件验证（缺设备/版本） |

`--result=failed` 的记录特别有价值：它保留"当时以为是这样、后来发现不是"的痕迹，
避免同一个坑被重新踩一遍。

## 设计取舍

**ID 用「文档序号 + 条序号」，不用内容哈希。**
哈希的话改一个字 ID 就变，之前录入的验证结果会全部失配。

**状态不写回文档，放独立文件 `.verify-state.json`。**
多窗口并行改文档会互相覆盖（已发生过两次），状态放外面不参与冲突。

**ID 会在文档列表变化时漂移**，所以录入前先跑一次 `--verify` 时脚本会校验 ID 存在，
ID 不存在会直接报错而不是静默写错。

## 自检

```bash
python3 scripts/verify.py --self-test
```

覆盖：能收集到条目、ID 无重复、每条都有验证方法、
能检出"只写待核对没写验证方法"的条目（造坏样例）、状态读写往返。
