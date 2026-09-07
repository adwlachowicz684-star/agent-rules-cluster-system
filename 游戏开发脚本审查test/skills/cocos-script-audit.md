---
id: DEV-S01
name: Cocos Creator 脚本审核
description: 审核 Cocos Creator 项目的 TypeScript 脚本，覆盖内存泄漏、性能陷阱、生命周期误用、代码质量与 2.x/3.x 迁移问题。当用户要求审查/审核/检查 cocos 脚本、游戏代码、看有没有内存泄漏或性能问题时使用。
keywords: [cocos, cocos creator, 游戏, 脚本, 审核, 审查, 检查, 游戏脚本, 脚本审核, 代码审查, code review, 内存泄漏, 泄漏, 性能, 卡顿, 优化, update, 生命周期, onLoad, onDestroy, 对象池, drawcall, 包体, 分包, 适配, TS, TypeScript, 游戏开发, cocos2d]
trigger: 用户要求审核/审查/检查 cocos 或游戏脚本；提到"有没有内存泄漏""性能有问题""包体太大""帮我看看这段游戏代码"；提交前的代码检查
applies_to: ""
verified: partial
related: [DEV-S02, DEV-S03]
---

# Cocos Creator 脚本审核

## 适用场景

**适用**：Cocos Creator 2.x / 3.x 的 TypeScript 脚本审核。

**不适用**（别硬套）：
- Cocos2d-x C++ 项目 —— 本技能的规则基于 Creator 的组件生命周期与 JS 内存模型
- 编辑器插件脚本（`editor/` 下）—— 不参与运行时
- 构建产物（`build/` `library/`）—— 改了也没用
- 纯 Shader / 美术资源 —— 本技能只看脚本

## 前置依赖

```bash
python3 --version                        # 需 3.7+
python3 scripts/cocos_audit.py --rules    # 确认脚本可调用
```

**不满足时**：无 Python 3.7+ 或脚本缺失 → 只能人工对照"审核清单"逐项检查，
效率显著降低；无法访问项目路径 → 请用户指名具体文件，不要凭空猜测代码结构。

## 完整流程

### 第 1 步：静态扫描（必做，一条命令）

```bash
python3 scripts/cocos_audit.py <项目路径或.ts文件>     # 全量
python3 scripts/cocos_audit.py <路径> --level P0       # 只看阻塞级（CI 卡口）
python3 scripts/cocos_audit.py <路径> --rule memory    # 只看内存类
python3 scripts/cocos_audit.py <路径> --rules          # 查看规则分组
python3 scripts/cocos_audit.py <路径> --json           # 机器可读
```

**规则分组**：`memory`（内存）· `perf`（性能）· `migration`（2.x 遗留）· `physics`（物理）

**级别定义**：

| 级别 | 含义 | 典型项 |
|---|---|---|
| **P0** | 阻塞：内存泄漏，线上累积 | on 无 off、schedule 无 unschedule、资源未释放、tween repeatForever 未停 |
| **P1** | 严重：性能或生命周期误用 | update 内 find/new、匿名回调、空 onDestroy、2.x 废弃 API、Dynamic 静态物体 |
| **P2** | 建议：代码质量 | console.log、any 类型、Mask/RichText 提示、Label cacheMode |

**退出码**：有 P0 返回 1（可直接接 CI），否则 0。

### 第 2 步：按问题类型加载专项

静态扫描给出方向后，**加载对应专项包深入处理**，不要在主包里硬啃：

| 扫描结果 | 加载 |
|---|---|
| P0 为主 / 提到内存上涨、切场景不释放 | **DEV-S02** 内存泄漏专项 |
| P1 性能项 / 卡顿、包体、适配 | **DEV-S03** 性能与包体专项 |
| 2.x 遗留 API 多 | 见下方"迁移对照" |

### 第 3 步：生命周期对照（人工）

顺序：**onLoad → onEnable → start → update → lateUpdate → onDisable → onDestroy**

| 回调 | 该放什么 | 常见误用 |
|---|---|---|
| `onLoad` | 自身变量、查找**自身/子节点**、注册**节点自身**事件 | 访问其他节点组件（可能未初始化 → null） |
| `onEnable` | 注册**全局/输入**事件、启动定时器 | 与 `onDisable` 不配对 |
| `start` | 依赖其他组件已 onLoad 的逻辑 | 放本该在 onLoad 的自身初始化 |
| `update` | 移动、计时、输入检测 | 每帧查找/创建对象 |
| `lateUpdate` | 相机跟随、依赖其他 update 结果 | — |
| `onDisable` | 注销 onEnable 注册的、停定时器 | 漏掉 → 重复激活时事件多次触发 |
| `onDestroy` | 清理监听、定时器、tween、资源 | 空实现 |

**关键**：`onEnable` 首次在 `onLoad` 之后、`start` 之前；之后每次激活都触发。
"只注册一次"放 `onLoad`，"每次激活都要"放 `onEnable`（并配 `onDisable`）。

### 第 4 步：输出报告

按 P0 → P1 → P2 分级，每条含：**文件:行号 · 问题 · 为什么 · 怎么改**。
不确定的标"待确认"，不硬判。

```bash
# 复核时看上下文，别只看一行
rg -n -B3 -A8 "\.on\(|schedule\(|repeatForever" <文件>
```

## 迁移对照（2.x → 3.x）

| 操作 | 2.x | 3.x |
|---|---|---|
| 查找节点 | `cc.find()` | `import { find } from 'cc'` |
| 加载资源 | `cc.loader.loadRes()` | `resources.load()` / `assetManager` |
| 释放资源 | `cc.loader.release()` | `assetManager.releaseAsset()` |
| 释放依赖树 | 手动遍历 | `assetManager.releaseAllDependencies()`（自动） |
| 分包 | `loader.downloader.loadSubpackage` | `assetManager.loadBundle()` |
| 对象池 | `cc.NodePool` | `import { NodePool } from 'cc'` |
| 缓动 | `cc.tween()` | `import { tween } from 'cc'` |
| 定时器 | `cc.director.getScheduler()` | `this.schedule` / `unschedule` |

⚠ **加载子资源写法变了**：
`resources.load('bg', Texture2D)` → `resources.load('bg/texture', Texture2D)`
`resources.load('bg', SpriteFrame)` → `resources.load('bg/spriteFrame', SpriteFrame)`

## 失败处理

| 失败情况 | 判据 | 动作 |
|---|---|---|
| 扫描 0 项 | 不代表没问题 | 静态扫不到闭包/循环引用/全局单例持有 → 仍需人工第 3 步 |
| 路径不存在/无 .ts | 输出"未找到 .ts 文件" | 确认路径，或让用户指名具体文件 |
| 大量误报 | 同一规则报几十条 | `--json` 导出按 rule 聚合；多为同一模式，改一处即可 |
| 无法判断是否为泄漏 | 组件是全局单例 | 标"待确认：生命周期长于页面" |
| 需运行时数据才能定论 | 内存曲线、DrawCall 数 | 明说"静态审核无法确认，建议 Profiler 验证"，不要猜 |

## 关键判断依据

**为什么内存泄漏是 P0**：会**随游戏时长累积**，测试期看不出，上线几十分钟后 OOM，
定位成本远高于修复成本。性能问题是持续可感知劣化，不会突然崩溃。

**为什么匿名回调单列 P1**：`on(EVT, () => {...})` 之后**无法**精确 off
（`off` 需同一函数引用）。是"写了也 off 不掉"而非"忘了写"，成因与改法都不同。

**为什么拆成三个包**：内存、性能、包体三类的排查方法完全不同——
内存看引用链，性能看帧耗时，包体看构建产物。塞一起会导致每次都加载全部内容，
违背定向加载原则。

**为什么 DrawCall 归专项而非扫描项**：它取决于场景结构与图集配置，
静态扫脚本看不出来，需 Profiler 或真机 Stats 面板观察。

## 已知坑

- ⚠ 本能会扫完就报"没问题"，但**闭包、循环引用、全局单例**静态扫不出来
- ⚠ 本能以为"扫出 0 项=通过"，但静态扫描**只抓模式明显的问题**
- ⚠ 本能只查 `onDestroy`，但 **`onEnable` 注册的必须配 `onDisable`**
- ⚠ 本能直接改代码，但**改前要确认该组件是不是全局单例**（泄漏影响不同）
- ⚠ 本能凭经验判断瓶颈，但**先分清 CPU 还是 GPU 瓶颈**再动手，否则白优化

## 可复用片段

**正确的事件注册/注销**：

```typescript
onLoad() {
    this.node.on(Node.EventType.TOUCH_START, this.onTouch, this);  // 一次
}
onEnable() {
    this.target?.on('custom', this.onCustom, this);   // 每次激活
}
onDisable() {
    this.target?.off('custom', this.onCustom, this);  // 必须配对
}
onDestroy() {
    this.node.off(Node.EventType.TOUCH_START, this.onTouch, this);
    this.unscheduleAllCallbacks();
}
private onTouch() { }      // 必须是类方法，不能匿名
private onCustom() { }
```

## 审核清单（扫描器不可用时的兜底）

```
□ 每个 on() 都有 off()/targetOff()；onEnable↔onDisable 配对
□ 事件回调是类方法不是匿名函数
□ 每个 repeatForever 都有 stop/clear
□ 每个 schedule/setInterval 都有清理
□ onDestroy 非空（或确认无需清理）
□ 动态加载资源有 decRef/release
□ update 内无 find/getComponent/instantiate/new
□ 频繁创建对象用了对象池（且有上限）
□ 无 any 类型；console 已移除或包 CC_DEBUG
□ 跨节点组件访问放 start（不是 onLoad）
□ 无 2.x 遗留 API（cc.loader / cc.find / cc.tween）
□ 静态物体标了 Static 刚体；非活体开了 allowSleep
□ Label cacheMode 匹配更新频率
□ 静态文本合并用 \n；能不用 RichText 就不用
□ 包体：引擎裁剪、分包、纹理压缩已做
□ 适配：Widget 对齐 + 安全区已处理
```

---

**专项子包**：
- `cocos-audit-memory.md`（DEV-S02）—— 六大泄漏源、运行时验证、泄漏安全组件模板
- `cocos-audit-performance.md`（DEV-S03）—— DrawCall、Label、物理、适配、包体瘦身

**变更记录**：见本大类 `assets/changelog.md`
（`python3 scripts/note.py "DEV-S01" 补充 "<原因>" --domain dev`）
