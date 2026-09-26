---
name: AST 提取文本时同一节点会被遍历两次
id: D001
domain: dev
keywords: [ast, ast.walk, FormattedValue, 提取, 重复, 文本提取, 静态检查, f-string]
trigger: 写静态检查脚本从 AST 提取源码文本、或提取结果与预期不符时
not_trigger: 纯文本正则匹配（不涉及 AST）；只是想知道某节点类型是否存在
tier: cold
hits: 2
last_used: 2026-09-26
---
# 从 AST 提取文本时，父节点与子节点会同时命中 isinstance

**来源**：2026-09-26 开发 `check_scope_selfreport`（信号 B：自己踩的坑）
**证据**：把 `FormattedValue` 与它内部的 `Name` 都还原成 `{}` → `"{}{}"`，范围正则失效，用例恒绿
**后果**：提取结果 ≠ 源码 → 检查器误报；⛔ 误报的检查会被关掉

## 判据

同一个语法结构，父节点和子节点都可能命中你的 isinstance。
写之前先打印一次提取结果，看有没有重复出现的花括号对。

## 反例

```python
# ⛔ 错：ast.walk 同时给出 FormattedValue 和它内部的 Name
for x in ast.walk(a):
    if isinstance(x, ast.FormattedValue): txt += "{}"
    elif isinstance(x, ast.Name):         txt += "{}"   # → "{}{}"
```

## 正例

```python
# ✅ 对：只处理 FormattedValue
for x in ast.walk(a):
    if isinstance(x, ast.Constant) and isinstance(x.value, str): txt += x.value
    elif isinstance(x, ast.FormattedValue): txt += "{}"
```
