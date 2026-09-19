---
name: game-dev
description: 游戏开发技能矩阵。按「引擎 + 功能域」路由：先识别项目用什么引擎，再按要实现的功能加载对应方案模板，产出可直接抄写的完整代码。Use when the user asks to 实现、怎么做、写一个、加个、搭一个 游戏功能，如角色控制、跳跃手感、UI 界面、背包系统、存档、敌人 AI、技能系统、关卡切换、音频管理、输入绑定、2D/3D 渲染效果。覆盖 Godot 4.x，结构预留 Unreal / Unity / Cocos。不用于代码审查（那是 code-audit）、不用于美术资源制作、不用于引擎源码修改。
---

# 游戏开发矩阵（game-dev）

**与 `code-audit` 是同一知识的两面**，分工见 `references/split-dev-audit.md`。
一句话：**开发给"能抄的正确写法"，审查给"能判的错误特征"**。

> ⚠ **本 skill 只写「怎么做」** —— 实现方案、选型依据、完整代码、参数含义。
> **「不能怎么做」（反模式、常见坑、漏写清单）全部在审查侧**，
> 见 `code-audit: references/godot-antipatterns/<同名>.md`（按功能域 1:1 对应）。
> 本 skill 的每个功能域文档末尾只留**一行指向**，不重复写判据。

```
第 1 步  识别引擎：project.godot → Godot；.uproject → Unreal …
第 2 步  定位功能域：角色控制 / UI / 存档 / 动画 / 音频 / 3D / 网络
第 3 步  加载对应方案模板（完整代码，可直接抄）
第 4 步  按项目的具体约束调整（2D 还是 3D、单人还是联网）
```

## 核心原则

1. **给能跑的完整代码，不给片段。** 片段看着懂、抄回去跑不起来，等于没给。
2. **先给选型，再给代码。** 同一个需求往往有多种实现（角色用 CharacterBody
   还是 RigidBody、计时用 Timer 节点还是 `create_timer()`），选错了后面全歪。
3. **标注引擎版本。** Godot 4.x 与 3.x 大量不兼容，模板必须写明版本。
4. **不写「不能怎么做」。** 每个功能域文档末尾只留一行指向
   `code-audit: godot-antipatterns/<同名>.md`，坑表与漏写清单都在那边。
   开发文档里保留的 `⚠` 只用于**提示正确做法的前提**（如"这个 API 4.7 才有"），
   不写"如果出现 X 就错了"这类判据（见 `split-dev-audit.md`）。

## 路由

```bash
python3 scripts/dev-route.py --src=<项目根>            # 识别引擎 + 建议功能域入口
python3 scripts/dev-route.py --src=<根> --need="角色跳跃"  # 按需求描述定位
python3 scripts/verify.py                                # 列出未验证的待核对项
python3 scripts/verify.py --verify=V5001 --result=failed  # 运行时录入验证结果
```

路由是**二维**的：先引擎，再功能域。与 `code-audit` 的「按风险面路由」不同——
那边输入是代码库找风险，这边输入是需求找方案。

## 目录

| 路径 | 作用 |
|---|---|
| `references/common.md` | 跨引擎通用：开发流程、选型原则、项目结构 |
| `references/godot/` | Godot 4.x 开发包（按功能域分文件） |
| `scripts/dev-route.py` | 引擎识别 + 功能域路由 |
| `scripts/verify.py` | 待核对项：收集 · 过滤 · 运行时录入验证结果 |

## 引擎包状态

| 引擎 | 识别信号 | 状态 |
|---|---|---|
| **Godot 4.x** | `project.godot` · `.gd` · `using Godot` | ✅ 可用（角色/UI/存档/动画/音频/输入/3D/物理） |
| Unreal | `.uproject` | 占位 |
| Unity | `ProjectSettings/` · `.asmdef` | 占位 |
| Cocos | `cc.config.json` | 开发模板在 `code-audit/references/p-cocos.md`，未拆分 |

## 使用边界

- **本 skill 给方案，判定交给 `code-audit`。** 写完代码想检查有没有坑，走审查。
- 不确定用户用哪个引擎 → 先问，别猜。猜错引擎整套模板都作废。
- 模板是起点不是终点：**必须按项目实际约束调整**（2D/3D、单人/联网、目标平台）。

## 常见漏写（跨引擎通用）

- 只在 `_ready` 连信号，`_exit_tree` 不断开 → 审查 GD15
- 用完的对象不释放 → 审查 GD01 / GD52
- 把易变配置硬编码进代码 → 应该 `@export` 出去
- `print()` 留在正式代码里 → 审查 GD74
