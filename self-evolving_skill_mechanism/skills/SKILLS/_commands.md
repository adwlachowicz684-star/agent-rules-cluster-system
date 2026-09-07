# 可复用命令库

> **只存技能，不存事实。** 命令必须是通用的，绑定某个项目的路径/文件名一律不收。

> **要求**：每条都能直接复制执行，改改变量就能用。不写解释性废话。
> 多行逻辑一律封成 `scripts/` 下的脚本，这里只留调用命令。
> 命令里的 `|` 必须写成 `\|`，否则表格列会错位。
> **适用环境**：留空或用 `-` 表示通用；不同环境写法不同时**两条都留**（版本分化，不是冲突）。
> 命中：每次实际复制使用 +1。

| ID | 场景 | 命令 | 适用环境 | 说明 | 命中 |
|----|------|---------|------|------|------|
| C001 | 整合报告（查重/冲突/膨胀预警） | `python3 scripts/consolidate.py` | - | 只出报告不改写文件 | 0 |
| C002 | 归档草稿并清空 | `bash scripts/archive.sh` | - | 归档到 pending/archive-YYYYMM.md | 0 |
| C003 | 统计条目数 | `grep -c '^\| [A-Z][0-9]' SKILLS/*.md` | - | 单库 >40 需合并 | 0 |
| C004 | 列出全部 L1 铁律 | `rg '\| L1 \|' SKILLS/_hot.md` | - | 任务前必读清单 | 0 |
| C005 | 在技能库全文检索 | `rg -n '关键词' SKILLS/ reference/` | - | 比 grep 快，默认忽略 .git | 0 |
| C006 | 跨文件批量替换 | `rg -l '旧串' DIR \| xargs sed -i 's/旧串/新串/g'` | os:linux | GNU sed，-i 无需参数 | 0 |
| C007 | 打包交付（≥5 个产物必用） | `zip -rq NAME.zip DIR && unzip -l NAME.zip \| tail -3` | - | 只返单个路径 | 0 |
| C008 | 打包时排除缓存 | `zip -rq NAME.zip DIR -x '*/__pycache__/*' -x '*/.DS_Store'` | - | 0 | 0 |
| C009 | 备份技能库到 git | `git add SKILLS && git commit -m "skill: $(date +%F) 整合"` | - | 收工前 | 0 |
| C010 | 看某文件最近改动 | `git log --oneline -5 -- SKILLS/` | - | 追溯规则演变 | 0 |
| C011 | 当前时间（东八区） | `TZ='CST-8' date '+%F %T %Z'` | - | 写时间戳用 | 0 |
| C012 | 找大文件 | `du -ah . \| sort -rh \| head -20` | - | 排查产物体积 | 0 |
| C013 | 按内容找文件 | `rg --files-with-matches '关键词' .` | - | 只出文件名 | 0 |
| C014 | 起本地服务预览 | `python3 -m http.server 8000` | - | 预览 HTML 产物 | 0 |
| C015 | 格式化 JSON | `python3 -m json.tool < in.json > out.json` | - | 或 `cat x.json | python3 -m json.tool` | 0 |
| C016 | 统计文件行数 | `wc -l SKILLS/*.md reference/*.md` | - | 监控 skill 膨胀 | 0 |
| C017 | 清空 pyc 缓存 | `find . -name __pycache__ -type d -exec rm -rf {} +` | - | 打包前清理 | 0 |
| C018 | 批量改文件名后缀 | `for f in *.md; do mv "$f" "${f%.md}.markdown"; done` | - | 模板，按需改 | 0 |
| C019 | 重建技能索引（入库后必做） | `python3 scripts/index.py` | - | 不重建则定向加载找不到 | 0 |
| C020 | 定向检索并计数回热 | `python3 scripts/index.py --find 打包 zip` | - | 一条命令完成检索+计数+回热 | 0 |
| C021 | 列出全部技能 | `python3 scripts/index.py --list` | - | 含冷藏项 | 0 |
| C022 | 统计与分层建议 | `python3 scripts/index.py --stats` | - | 只建议不自动改 | 0 |
| C023 | 整合报告（查重/事实扫描） | `python3 scripts/consolidate.py` | - | 只出报告不改写文件 | 0 |
| C024 | 归档草稿并重置 | `bash scripts/archive.sh` | - | 归档到 pending/ 后清空 | 0 |
| C025 | 冷藏长期未用的技能 | `mv SKILLS/domains/X.md SKILLS/archive/ && sed -i 's/^tier:.*/tier: archive/' SKILLS/archive/X.md` | - | 改名后需重建索引 | 0 |
| C026 | 探测当前项目接入的大类 | `python3 scripts/domain.py --detect` | - | 新技能默认归属依据 | 0 |
| C027 | 推荐技能归属大类 | `python3 scripts/domain.py --route "合同审查流程"` | - | 只推荐不自动写 | 0 |
| C028 | 列出全部大类 | `python3 scripts/domain.py --list` | - | 含各人类技能数 | 0 |
| C029 | 初始化大类目录结构 | `python3 scripts/domain.py --init` | - | 建目录+通用链接 | 0 |
| C030 | 项目接入某大类 | `python3 scripts/domain.py --link legal .` | - | 建 junction | 0 |
| C031 | 各大类内建通用链接 | `python3 scripts/domain.py --add-common` | - | 新增大类后执行 | 0 |
| C032 | 写入技能到指定大类 | `python3 scripts/index.py --add X.md --domain legal` | - | 同名则提示补充 | 0 |
| C033 | 限定大类检索 | `python3 scripts/index.py --find 调试 --domain dev` | - | 缩小范围 | 0 |
| C034 | 输出某大类 skills 路径 | `python3 scripts/domain.py --where legal` | - | 脚本里拼接路径 | 0 |
| C035 | 项目接入大类（含本地覆盖层） | `python3 scripts/domain.py --link legal .` | - | 同时建 .ai-local/ | 0 |
| C036 | 读本类索引（不读全局） | `cat .ai/INDEX.md` | - | 任务开始必读，~20 行 | 0 |
| C037 | 读领域硬约束 | `cat .ai/rules/*.md` | - | 每次必读 | 0 |
| C038 | 多归属（软链接技能到其他大类） | `ln -s ../../_common/skills/X.md 法律/skills/` | - | 索引自动去重 | 0 |
| C039 | 判定现有结构是否装得下 | `python3 scripts/structure.py --route-check "描述"` | - | 装不下则提提案 | 0 |
| C040 | 提议新建大类 | `python3 scripts/structure.py --propose-new 名 --key k --kw "词,词"` | - | 只生成提案 | 0 |
| C041 | 查看当前提案 | `python3 scripts/structure.py --show` | - | 确认前先看 | 0 |
| C042 | 执行提案（自动备份） | `python3 scripts/structure.py --apply` | - | 可加 --yes | 0 |
| C043 | 回滚上一次变更 | `python3 scripts/structure.py --undo` | - | 从备份恢复 | 0 |
| C044 | 结构健康检测 | `python3 scripts/structure.py --check` | - | 大类>40/单包>200 报警 | 0 |
| C045 | 探测当前环境 | `python3 scripts/env.py` | 通用 | 输出 Python 版本/系统/可用工具 | 0 |
| C046 | 检查约束是否满足 | `python3 scripts/env.py --check "python>=3.9"` | 通用 | 退出码 0=适用 | 0 |
| C047 | 跨文件批量替换 | `rg -l '旧串' DIR \| xargs sed -i '' 's/旧串/新串/g'` | os:darwin | BSD sed，-i 必带空参 | 0 |
| C048 | 建目录链接 | `mklink /J .ai <target>` | os:windows | junction | 0 |
| C049 | 建目录链接 | `ln -s <target> <link>` | os:linux,os:darwin | symlink | 0 |
| C050 | 合并字典 | `z = a \| b` | python>=3.9 | 3.9+ 字典并集运算符 | 0 |
| C051 | 合并字典 | `z = {**a, **b}` | python<3.9 | 旧版兼容写法 | 0 |
| C052 | 探测当前环境 | `python3 scripts/env.py` | - | 输出版本/系统/可用工具 | 0 |
| C053 | 检查约束是否满足 | `python3 scripts/env.py --check "python>=3.9"` | - | 退出码 0=适用 | 0 |
| C054 | 规范检查（体积/ID/字段） | `python3 scripts/lint.py` | - | 超限预警，不硬报错 | 0 |
| C055 | 规范检查输出 JSON | `python3 scripts/lint.py --json` | - | 供其他脚本消费 | 0 |
| C056 | 记录变更溯源 | `python3 scripts/note.py "C047" 补充 "漏了X情况"` | - | 一行写清为什么改 | 0 |
| C057 | 记录到大类 | `python3 scripts/note.py "X" 参考 "Y" --domain legal` | - | 加 --src 标来源 | 0 |
| C058 | 查看变更记录 | `python3 scripts/note.py --show` | - | 加 --domain 看某大类 | 0 |
| C059 | 查看溯源类型 | `python3 scripts/note.py --types` | - | 新增/补充/修正/更新等 8 类 | 0 |
| C060 | Cocos 脚本审核（全量） | `python3 scripts/cocos_audit.py <路径>` | - | 有 P0 则退出码 1 | 0 |
| C061 | 只看阻塞级（CI 卡口） | `python3 scripts/cocos_audit.py <路径> --level P0` | - | 退出码 1 = 阻断 | 0 |
| C062 | 审核结果 JSON | `python3 scripts/cocos_audit.py <路径> --json` | - | 供 CI/脚本消费 | 0 |
| C063 | 找所有 update 方法 | `rg -n "^\s+(public\s+|private\s+)?update\s*\(" DIR -A 15` | rg | 逐个看内部操作 | 0 |
| C064 | 找资源加载与释放 | `rg -n "resources\.load\|assetManager\.load\|releaseAsset\|decRef" DIR` | rg | 成对核对 | 0 |
| C065 | 找高频对象创建 | `rg -n "instantiate\(\|new [A-Z]" DIR` | rg | 该用对象池 | 0 |
| C066 | 按类扫描（内存/性能/迁移/物理） | `python3 scripts/cocos_audit.py <路径> --rule memory` | - | 见 --rules | 0 |
| C067 | 查看审核规则分组 | `python3 scripts/cocos_audit.py --rules` | - | 不需 path | 0 |
| C068 | 找 tween 循环未停 | `rg -n "repeatForever" DIR -A 3` | rg | 需配 stop/clear | 0 |
| C069 | 找 2.x 遗留 API | `rg -n "cc\.loader\|cc\.find\|cc\.tween\|getScheduler" DIR` | rg | 迁移到 3.x | 0 |
| C070 | 找合批风险组件 | `rg -n "Mask\|RichText" DIR` | rg | 每个都可能加 DrawCall | 0 |
| C071 | 找全局单例持有 | `rg -n "getInstance\|static.*instance\|window\." DIR` | rg | 闭包泄漏排查入口 | 0 |
