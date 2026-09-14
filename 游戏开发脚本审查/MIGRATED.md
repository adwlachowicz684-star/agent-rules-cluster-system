# 已迁入 code-audit

本目录下的 `skills/ts-unit-audit` 已重组迁入 **`_common/skills/code-audit`**。

## 为什么迁

原按「语言 / 项目类型」分 skill 造成三个硬冲突：

1. **模式 ID 命名空间冲突** —— ts 侧 `A01` 是数值守卫，工具侧 `A01` 是承诺失效。
   两个 skill 共存时同一个 ID 指两种东西
2. **同名脚本语义相反** —— 两边都有 `doc-scan.py`，一个查交付物三件套，
   一个查文档承诺一致性
3. **体积装不下** —— 两侧 SKILL.md 分别是 190 / 170 行，合并即 360 行，超 200 行上限

改为按**结构条件**分场景后：每个场景内部独立编号（`N-` / `D-` / `L-` / `C-` …），
ID 冲突自动消失；同一份判据 TS 库和 Tauri 应用都能用。

## 内容去向

| 原文件 | 现位置 |
|---|---|
| `skills/ts-unit-audit/references/pattern-detection.md`（62 条） | 拆入 `s-numerics.md` / `s-structures.md` / `s-lifecycle.md` / `s-contracts.md` / `s-atomicity.md` / `s-state.md` |
| `skills/ts-unit-audit/scripts/pattern-scan.py` | `code-audit/scripts/scan-ts.py` |
| `skills/ts-unit-audit/scripts/doc-scan.py` | `code-audit/scripts/doc-deliverable.py` |
| `skills/ts-unit-audit/references/cocos-engine.md` | `code-audit/references/p-cocos.md` |
| 其余 fix-code-*.md / adversarial / manual-review / global-consistency | 同名迁入 `code-audit/references/` |

## 保留

`审查产物/` 下的历史审查报告与探针是**项目资料**，不是 skill，原样保留。

## 用法变化

```bash
# 旧
python3 skills/ts-unit-audit/scripts/pattern-scan.py --src=<根>

# 新：先路由，再按场景加载判据
python3 _common/skills/code-audit/scripts/route.py --src=<根>
python3 _common/skills/code-audit/scripts/scan-ts.py --src=<根>
```
