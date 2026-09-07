---
id: DEV-S02
name: Cocos 内存泄漏专项审核
description: 深度排查 Cocos Creator 项目的内存泄漏，覆盖 Tween 缓动、事件监听、定时器、动态资源、对象池、闭包六大泄漏源。当用户提到"内存一直涨""切场景不释放""跑久了卡"或需要上线前内存体检时使用。
keywords: [内存泄漏, 泄漏, 内存, 内存增长, 切场景不释放, OOM, 崩溃, tween, repeatForever, 事件监听, off, schedule, 定时器, 资源释放, release, decRef, 对象池, NodePool, 闭包, GC, 垃圾回收, 堆快照]
trigger: 用户报告内存持续增长/切场景后不回落/OOM 崩溃；上线前内存体检；配合 DEV-S01 做深度内存排查
applies_to: ""
verified: partial
related: [DEV-S01, DEV-S03]
---

# Cocos 内存泄漏专项审核

> 主包见 `cocos-script-audit.md`（DEV-S01）。本包只讲**内存**，
> 与 DEV-S03（性能）并列。命中内存类问题时加载本包。

## 适用范围

**为什么单独成包**：内存泄漏是 Cocos 项目**唯一会累积恶化**的问题类别——
测试期看不出来，上线跑几十分钟 OOM，且定位成本远高于修复成本。
它的排查方法和性能问题完全不同（看引用链而非看帧耗时）。

## 六大泄漏源（按实际出现频率排序）

### 1. Tween 缓动未停止 —— 最容易被忽略

**官方文档明确点名**：`repeatForever` 等未能自行销毁的缓动，
**切换场景后会一直驻留内存**，必须手动停止。v3.8.4 之前尤其要注意。

```typescript
// ❌ 切场景后这个 tween 还在跑
tween(this.node).repeatForever(tween().to(1, { angle: 360 })).start();

// ✅ 持有引用，销毁时停
private _rot: Tween<Node> = null!;

onLoad() {
    this._rot = tween(this.node)
        .repeatForever(tween().to(1, { angle: 360 }))
        .start();
}

onDestroy() {
    this._rot?.stop();
    // 或：Tween.stopAllByTarget(this.node);  停掉该节点上的所有缓动
}
```

**停止方式的选择**（官方 API）：

| 方式 | 作用范围 | 适用 |
|---|---|---|
| `t.stop()` | 单个缓动 | 精确控制，推荐 |
| `Tween.stopAllByTarget(node)` | 该节点上所有缓动 | 组件销毁时批量清理 |
| `Tween.stopAllByTag(n)` | 指定标签 | 按分组管理 |
| `Tween.stopAll()` | 全部 | 场景切换，影响面大，慎用 |

**`stop()` vs `clear()`**：`stop()` 只停止（可重新 start 继续）；
`clear()` 停止并**释放 Tween 对象**。不再需要的用 `clear()`。

### 2. 事件监听未注销

```bash
# 扫描
python3 scripts/cocos_audit.py <路径> --rule memory
```

三类必须配对：

| 注册 | 清理 | 位置 |
|---|---|---|
| `node.on()` | `node.off()` / `targetOff()` | `onDestroy` |
| `input.on()` | `input.off()` | `onDisable` |
| `systemEvent.on()` | `systemEvent.off()` | `onDestroy` |

**幂等陷阱**：`onEnable` 里注册 → 必须配 `onDisable` 注销。
只在 `onDestroy` 清，节点反复激活会导致**事件重复注册**（同一回调触发多次）。

### 3. 定时器未清理

```typescript
onDestroy() {
    this.unscheduleAllCallbacks();   // 清 this.schedule 注册的
    // setInterval/setTimeout 要各自 clear
}
```

⚠ `this.schedule(cb, ...)` 与 `setInterval` 是**两套机制**，
`unscheduleAllCallbacks()` 清不掉 `setInterval`。

### 4. 动态资源未释放

**关键认知**：场景切换的"自动释放"**不包括** `resources.load` / `bundle.load`
动态加载的资源。必须手动。

```typescript
// 方式 A：引用计数（官方推荐）
resources.load('images/bg/spriteFrame', SpriteFrame, (err, sp) => {
    this.sp = sp;
    this.sp.addRef();          // 我要用
});

onDestroy() {
    this.sp?.decRef();         // 我不用了，计数归零后引擎自动释放
}

// 方式 B：显式释放
assetManager.releaseAsset(this.sp);
```

**共享资源陷阱**（最容易踩）：
prefab A 引用资源 2、3，prefab B 引用 2、3、4。
直接释放 A 的全部依赖 → B 的资源失效报错。
用 `getDependsRecursively` 查完整依赖树，确认无人使用再释放。

**Bundle 粒度**：按关卡/模块隔离成独立 Bundle，卸载时整体 `bundle.releaseAll()`，
比逐个资源release 更不容易出错。

### 5. 对象池"假回收"

NodePool 用错反而变成泄漏池：

| 错误 | 后果 | 正确 |
|---|---|---|
| 只 `get()` 不 `put()` | 池永远空，持续 instantiate | `get/put` 严格成对，封装 `spawn()/despawn()` |
| 池无上限 | 内存只增不减 | 设 `MAX_POOL_SIZE`，超出直接 destroy |
| `put()` 前不重置 | 状态残留、事件重复绑定 | despawn 时清理位置/状态/**注销该节点上的监听与 tween** |
| 池持有引用不释放 | 整池无法 GC | 场景销毁时 `pool.clear()` |

**despawn 标准流程**：
```
despawn(node)
  ├─ node.active = false
  ├─ 注销该节点上的事件监听
  ├─ Tween.stopAllByTarget(node)      ← 常漏
  ├─ unscheduleAllCallbacks()
  └─ pool.size < MAX ? pool.put(node) : node.destroy()
```

### 6. 闭包与全局引用

静态扫描**抓不到**，必须人工看：

- 回调里引用了大对象（配置表、纹理数组）
- 单例/全局变量持有节点或资源引用
- 循环引用（A 持有 B，B 持有 A，计数永不归零）

```bash
# 人工排查入口
rg -n "getInstance|static.*instance|window\.|globalThis" <目录>
```

## 排查流程

```bash
# 1. 静态扫描（抓模式明显的）
python3 scripts/cocos_audit.py <路径> --rule memory

# 2. 人工复核每条 P0
rg -n -B3 -A8 "\.on\(|schedule\(|repeatForever|resources\.load" <目录>

# 3. 运行时验证（静态扫不出的必做这步）
```

### 运行时验证方法

| 工具 | 用法 | 看什么 |
|---|---|---|
| Chrome DevTools Memory | 构建 Web 版，操作前后各拍一次堆快照 | 对比 `cc.Node` / `Texture2D` 实例数是否持续增长 |
| 微信开发者工具 | Memory 面板，JS Heap 波形 | 峰值曲线是否只升不降 |
| Cocos Profiler | 编辑器内 Profiler，Memory 页签 | JS Heap + Texture Memory 曲线 |
| PerfDog | 真机录制 | 内存曲线随时间走势 |

**判定标准**：操作 N 次后回到初始状态，内存**应基本回到基线**。
每次操作后遗留的增量就是泄漏量。

## 失败处理

| 情况 | 判据 | 动作 |
|---|---|---|
| 扫描 0 项但内存仍涨 | 静态扫不到闭包/全局引用 | 走第 6 项 + 运行时验证，不要报"没问题" |
| 不确定某组件是否泄漏 | 是全局单例、生命周期同 App | 标注"待确认：生命周期长于页面"，不计 P0 |
| 关掉某模块后内存正常 | 基本可定位 | 二分法：逐个禁用模块缩小范围 |
| 真机才复现，模拟器正常 | 平台差异 | iOS 用 Xcode Memory Graph，Android 用 Android Profiler |

## 已知坑

- ⚠ 本能以为"tween 播完就自动没了"，但 **`repeatForever` 永远不会自己结束**，切场景后继续驻留
- ⚠ 本能以为"GC 会处理"，但**只要还有引用，GC 就不会回收**——Cocos 的泄漏几乎全是"引用没断"而非"GC 失效"
- ⚠ 本能以为"场景切换会自动释放资源"，但**动态加载的不在自动释放范围内**
- ⚠ 本能以为"用对象池就不会泄漏"，但**只 get 不 put / 池无上限 / put 前不清 tween** 都会让它变成泄漏池
- ⚠ 本能只查 `onDestroy`，但**`onEnable` 注册的事件必须在 `onDisable` 注销**（否则重复激活会重复注册）

## 可复用片段

**完整的泄漏安全组件模板**：

```typescript
import { _decorator, Component, Node, Tween, tween, resources, SpriteFrame } from 'cc';
const { ccclass, property } = _decorator;

@ccclass('SafeComponent')
export class SafeComponent extends Component {
    @property(Node)
    target: Node = null!;

    private _tween: Tween<Node> = null!;
    private _sp: SpriteFrame = null!;

    onLoad() {
        // 1. 节点自身事件 → onLoad 注册，onDestroy 注销
        this.node.on(Node.EventType.TOUCH_START, this.onTouch, this);
    }

    onEnable() {
        // 2. 全局/输入事件 → onEnable 注册，onDisable 注销（必须配对）
        this.target?.on('custom', this.onCustom, this);

        // 3. 缓动：持有引用
        this._tween = tween(this.node)
            .repeatForever(tween().to(1, { angle: 360 }))
            .start();

        // 4. 动态资源：addRef
        resources.load('images/bg/spriteFrame', SpriteFrame, (err, sp) => {
            if (err || !sp) return;
            this._sp = sp;
            this._sp.addRef();
        });
    }

    onDisable() {
        this.target?.off('custom', this.onCustom, this);
    }

    onDestroy() {
        // 与注册顺序严格对称
        this.node.off(Node.EventType.TOUCH_START, this.onTouch, this);
        this._tween?.stop();
        Tween.stopAllByTarget(this.node);
        this.unscheduleAllCallbacks();
        this._sp?.decRef();
    }

    private onTouch() { }
    private onCustom() { }
}
```

**泄漏自检清单**：

```
□ 每个 repeatForever 都有 stop/clear
□ 每个 on() 都有对应的 off()（且位置对称：onEnable↔onDisable）
□ 事件回调是类方法不是匿名函数
□ 每个 schedule 都有 unschedule；setInterval 都有 clearInterval
□ 每个 resources.load 都有 decRef/release
□ 对象池 get/put 成对，且有容量上限
□ put() 前清了 tween 与监听
□ 无全局单例持有节点/资源引用
□ 共享资源释放前查过依赖树
□ 运行时验证：操作 N 次后内存回到基线
```

---

**变更记录**：见本大类 `assets/changelog.md`
（`python3 scripts/note.py "DEV-S02" 补充 "<原因>" --domain dev`）
