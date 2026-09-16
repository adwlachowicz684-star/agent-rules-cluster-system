# 工具审查 · scripts

本目录存放**被审查工具脚本的修复后版本**，与 `审查产物/<工具>/` 配套。

| 脚本 | 配套审查报告 | 说明 |
|---|---|---|
| `push_api.py` | `审查产物/push-api/审查报告.md` | 通过 GitHub Git Data API 推送本地改动。**已同步到 4403 行版本**（原快照 2864 行，缺第 3 轮之后的修复：`_CI_PENDING_HINTS` / `_refuse_direct_if_protected` / `local_head` 回退检测）。
  | | | 第 4 轮审查的 7 条变异定义见 `_common/skills/code-audit/rules/mutations.push-api-round4.json`，锚点按本版本校验（`--check` 全部唯一命中） |

## 为什么单独存一份

审查报告里的问题清单如果脱离代码，很快就对不上了——报告说「第 405 行有宽泛异常」，
代码早改了。存一份**与报告同版本的脚本**，才能：

- 复现报告里的问题（对照行号与判据）
- 回归验证修复是否真的生效
- 让后来的审查者看到「修之前是什么样、修成了什么样」

## 用法

```bash
python3 push_api.py --init-baseline                    # 首次：建立远端基线
python3 push_api.py --dry-run                          # 预览
python3 push_api.py -m "提交信息" a.js b.js             # 推送指定文件
python3 push_api.py --mark-synced                      # 同步远端后解除过期拦截
```

`TOKEN` / `ROOT` / `STATE_PATH` 在文件顶部，按实际仓库改。
