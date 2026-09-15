# 工具审查 · scripts

本目录存放**被审查工具脚本的修复后版本**，与 `审查产物/<工具>/` 配套。

| 脚本 | 配套审查报告 | 说明 |
|---|---|---|
| `push_api.py` | `审查产物/push-api/审查报告.md` | 通过 GitHub Git Data API 推送本地改动。修复后版本（8 条问题已修，含 P0-1 静默回退远端） |

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
