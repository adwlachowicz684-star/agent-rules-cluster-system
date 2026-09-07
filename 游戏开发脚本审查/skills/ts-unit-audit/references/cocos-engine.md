<!-- oversize-exempt: 引擎专项查表文档，含生命周期/迁移/性能/包体四张对照表，需整体查阅 -->
# Cocos Creator 引擎专项

通用缺陷见 `pattern-detection.md`（A–W 族）与 X/Y 族（成对配对、热路径）。
本文件只写**引擎特有**的规则——换个引擎不成立的部分。

## 适用场景

**适用**：Cocos Creator 2.x / 3.x 的 TypeScript 脚本。

**不适用**（别硬套）：Cocos2d-x C++ 项目（本文件的规则基于 Creator 组件生命周期与 JS
内存模型）· 编辑器插件脚本（`editor/` 下，不参与运行时）· 构建产物
（`build/` `library/`）· 纯 Shader 与美术资源。

## 前置依赖

```bash
python3 --version                          # 需 3.7+
python3 scripts/cocos-audit.py --rules     # 确认脚本可调用
```

无 Python 3.7+ 或脚本缺失 → 只能按「审核清单」人工逐项检查，效率显著降低。
无法访问项目路径 → 请用户指名具体文件，不要凭空猜测代码结构。

## 第 1 步 · 引擎层静态扫描

```bash
python3 scripts/cocos-audit.py <项目路径或.ts文件>        # 全量
python3 scripts/cocos-audit.py <路径> --level P0          # 只看阻塞级（CI 卡口）
python3 scripts/cocos-audit.py <路径> --rule memory       # 只看内存类
python3 scripts/cocos-audit.py <路径> --rules             # 查看规则分组
python3 scripts/cocos-audit.py <路径> --json              # 机器可读
```

**规则分组**：`memory`（内存）· `perf`（性能）· `migration`（2.x 遗留）· `physics`（物理）

**退出码**：有 P0 返回 1（可直接接 CI），否则 0。

**级别定义**：

| 级别 | 含义 | 典型项 |
|---|---|---|
| **P0** | 阻塞：内存泄漏，线上累积 | on 无 off、schedule 无 unschedule、资源未释放、repeatForever 未停 |
| **P1** | 严重：性能或生命周期误用 | update 内 find/new、匿名回调、2.x 废弃 API、Dynamic 静态物体 |
| **P2** | 建议：代码质量 | console.log、any 类型、Mask/RichText 提示、Label cacheMode |

## 第 2 步 · 生命周期配对（人工，扫描器扫不全）

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

## 六大泄漏源（按出现频率排序）

### 1. 循环缓动未停止

`repeatForever` 等不能自行销毁的缓动，**切换场景后继续驻留**，必须手动停止。

```typescript
private _rot: Tween<Node> = null!;
onLoad() {
  this._rot = tween(this.node).repeatForever(tween().to(1, { angle: 360 })).start();
}
onDestroy() {
  this._rot?.stop();
  Tween.stopAllByTarget(this.node);
}
```

| 停止方式 | 作用范围 | 适用 |
|---|---|---|
| `t.stop()` | 单个缓动 | 精确控制，推荐 |
| `Tween.stopAllByTarget(node)` | 该节点上所有缓动 | 组件销毁时批量清理 |
| `Tween.stopAllByTag(n)` | 指定标签 | 按分组管理 |
| `Tween.stopAll()` | 全部 | 场景切换，影响面大，慎用 |

**`stop()` vs `clear()`**：`stop()` 只停止（可重新 start）；`clear()` 停止并**释放
Tween 对象**。不再需要的用 `clear()`。

### 2. 事件监听未注销

| 注册 | 清理 | 位置 |
|---|---|---|
| `node.on()` | `node.off()` / `targetOff()` | `onDestroy` |
| `input.on()` | `input.off()` | `onDisable` |
| `systemEvent.on()` | `systemEvent.off()` | `onDestroy` |

回调必须是**类方法**，不能是匿名函数——`off` 需要同一函数引用。

### 3. 定时器未清理

```typescript
onDestroy() {
  this.unscheduleAllCallbacks();   // 只清 this.schedule 注册的
}
```

⚠ `this.schedule(cb, ...)` 与 `setInterval` 是**两套机制**，
`unscheduleAllCallbacks()` 清不掉 `setInterval`，后者要各自 `clearInterval`。

### 4. 动态资源未释放

场景切换的"自动释放"**不包括** `resources.load` / `bundle.load` 动态加载的资源。

```typescript
resources.load('images/bg/spriteFrame', SpriteFrame, (err, sp) => {
  if (err || !sp) return;
  this.sp = sp;
  this.sp.addRef();
});
onDestroy() { this.sp?.decRef(); }
```

**共享资源**：释放前用 `getDependsRecursively` 查完整依赖树，确认无人使用再释放。
按关卡/模块隔离成独立 Bundle，卸载时整体 `bundle.releaseAll()`，比逐个 release 更稳。

### 5. 对象池假回收

| 正确做法 | 理由 |
|---|---|
| `get/put` 严格成对，封装 `spawn()/despawn()` | 只 get 不 put → 池永远空，持续 instantiate |
| 设 `MAX_POOL_SIZE`，超出直接 destroy | 池无上限 → 内存只增不减 |
| despawn 时清理位置/状态/监听/tween | put 前不重置 → 状态残留、事件重复绑定 |
| 场景销毁时 `pool.clear()` | 池持有引用 → 整池无法 GC |

```
despawn(node)
  ├─ node.active = false
  ├─ 注销该节点上的事件监听
  ├─ Tween.stopAllByTarget(node)      ← 常漏
  ├─ unscheduleAllCallbacks()
  └─ pool.size < MAX ? pool.put(node) : node.destroy()
```

### 6. 闭包与全局引用（静态扫不到，必须人工看）

```bash
rg -n "getInstance|static.*instance|window\.|globalThis" <目录>
```

- 回调里引用了大对象（配置表、纹理数组）
- 单例/全局变量持有节点或资源引用
- 循环引用（A 持有 B，B 持有 A，计数永不归零）

## 第 3 步 · 运行时验证（静态扫描 0 项也要做）

| 工具 | 用法 | 看什么 |
|---|---|---|
| Chrome DevTools Memory | 构建 Web 版，操作前后各拍一次堆快照 | 对比 `cc.Node` / `Texture2D` 实例数是否持续增长 |
| 微信开发者工具 | Memory 面板，JS Heap 波形 | 峰值曲线是否只升不降 |
| Cocos Profiler | 编辑器内 Profiler，Memory 页签 | JS Heap + Texture Memory 曲线 |
| PerfDog | 真机录制 | 内存曲线随时间走势 |

**判定标准**：操作 N 次后回到初始状态，内存**应基本回到基线**。
每次操作后遗留的增量就是泄漏量。

## 性能项

### DrawCall 与合批

移动端目标 **<100**。打断合批的原因：

| 原因 | 处理 |
|---|---|
| 纹理不同（相邻节点用不同图集/散图） | 打自动图集，让它们共用一张 |
| **Mask 组件** | 产生额外 DrawCall + Stencil 操作，滚动列表慎用 |
| **RichText** | 每个样式片段都可能打断合批，能用 Label 就别用 |
| 材质/Blend 不同 | 同类节点放一起渲染 |
| Label 穿插 | 调整节点层级，同类聚拢 |

### Label cacheMode 三选一

| 模式 | 内存 | 适用 | 更新频率 |
|---|---|---|---|
| `NONE` | 低 | 静态文本（标题、菜单） | 不可动态更新 |
| `BITMAP` | 中 | 低频更新（倒计时、金币数） | ≤5 次/秒 |
| `CHAR` | 高 | 高频更新（聊天、伤害数字） | ≤30 次/秒 |

⚠ `BITMAP` 模式下改内容后需 `label.markForUpdateRenderData()` 才生效。
RichText 是 **JS 层实现**，底层创建大量 Label 节点，主循环中频繁修改会明显掉帧；
**BMFont 效率最高**。静态文本合并到同一 Label 用 `\n` 换行。

### 物理

| 优化项 | 做法 |
|---|---|
| **静态物体用 Static** | Dynamic 刚体开销是 Collider 的数倍（实测可达 5x） |
| **善用休眠** | `allowSleep = true` |
| **碰撞分组掩码** | 最有效手段，直接避免大量不必要的检测对 |
| **简化碰撞形状** | 能矩形/圆形就别多边形 |
| **CCD 只在必要时开** | 只给子弹等高速物体 |
| **远离视口禁用** | `collider.enabled = false` |

引擎选型（影响包体与性能）：`builtin`（最小，只需碰撞检测）· `cannon.js`（~141KB）
· `bullet/ammo.js`（~1.5MB）· `PhysX`（高稳定性）。不需要物理就整个关掉。

### 多分辨率适配

| 策略 | 效果 | 适用 |
|---|---|---|
| `FIXED_HEIGHT` | 高度固定，宽度自适应 | **竖屏推荐** |
| `FIXED_WIDTH` | 宽度固定，高度自适应 | 横屏 |
| `SHOW_ALL` | 保持比例，两侧留黑边 | 不希望内容被裁 |
| `NO_BORDER` | 填满屏幕，可能裁切边缘 | 背景可溢出 |
| `EXACT_FIT` | 拉伸填满，**会变形** | 不推荐 |

**Widget**：顶部 UI 勾 `Top`；底部按钮勾 `Bottom`；全屏背景四边全勾。
⚠ 避免同时锁定 Left + Right + Width（会冲突警告）。

**安全区**：`view.getSafeAreaRect()` 返回**物理像素**，需换算到设计分辨率坐标
再更新 Widget 边距。Web 非原生环境可能返回全屏，真机才暴露问题。

### 其他性能项

- **对象池**：频繁创建销毁的对象必用 `NodePool`（细节见上文泄漏源 5）
- **update 降频**：非每帧必要的逻辑累加 `dt` 或用 `frameCount % N`
- **避免在 update 中**：`find`、`getComponent`、`instantiate`、`new`、`destroy`
- **3D 项目**：面片数移动端建议 <10 万；用 LOD；骨骼动画开 GPU 蒙皮

### 包体（微信小游戏 4MB 硬限制）

| 手段 | 收益 | 做法 |
|---|---|---|
| **引擎裁剪** | 省 1.5~3MB | 项目设置→功能裁剪，去掉 3D/物理/视频/Spine 等未用模块 |
| **分包/Bundle** | 主包直降 | 内容放独立 Bundle，主包只留启动场景 |
| **引擎插件** | ~1.8MB | 微信小游戏勾选"启用微信小游戏引擎插件" |
| **WASM 分离** | 数百 KB | 开启 WASM 分包 |
| **纹理压缩** | 视资源量 | Android 用 ETC2/ASTC，iOS 用 PVRTC/ASTC |

⚠ **`resources` 目录会打包全部资源**——大项目应避免滥用，
优先用自定义 Bundle + 场景引用（引擎自动按需打包）。

Bundle 优先级：`internal(21)` > `resources(8)` > `main(7)` > 自定义 bundle(1+)

## 定位思路

用 Profiler / Chrome Performance 录制卡顿时段，先看 **Scripting（CPU 逻辑）**
还是 **Rendering（GPU 渲染）** 耗时过长——两边优化手段完全不同，
搞反了会白优化。脚本侧能做的是降频与缓存；DrawCall 与图集属渲染侧。

## 输出格式

按 P0 → P1 → P2 分级，每条含**文件:行号 · 问题 · 为什么 · 怎么改**四项。
不确定的标"待确认"，不硬判。复核时看上下文而非单行：

```bash
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

| 情况 | 判据 | 动作 |
|---|---|---|
| 扫描 0 项 | 不代表没问题 | 闭包/循环引用/全局单例静态扫不出 → 仍需人工第 2、3 步 |
| 大量误报 | 同一规则报几十条 | `--json` 导出按 rule 聚合；多为同一模式，改一处即可 |
| 无法判断是否为泄漏 | 组件是全局单例 | 标"待确认：生命周期长于页面"，不计 P0 |
| 需运行时数据才能定论 | 内存曲线、DrawCall 数 | 明说"静态审核无法确认，建议 Profiler 验证"，不要猜 |
| 模拟器流畅真机卡 | 设备性能差异 | 用低端机测；检查纹理压缩、面片数、DrawCall |
| 卡顿但不知瓶颈 | Profiler 数据不清晰 | 分别禁用逻辑/渲染对比帧率，先分清 CPU 还是 GPU |

## 关键判断依据

**为什么内存泄漏定 P0**：随游戏时长**累积**，测试期看不出，上线几十分钟后 OOM，
定位成本远高于修复成本。性能问题是持续可感知劣化，不会突然崩溃。

**为什么匿名回调单列**：`on(EVT, () => {...})` 之后**无法**精确 off
（`off` 需同一函数引用）。是"写了也 off 不掉"而非"忘了写"，成因与改法都不同。

**为什么 DrawCall 不进扫描项**：取决于场景结构与图集配置，静态扫脚本看不出来。

**为什么拆三个包**：内存看引用链，性能看帧耗时，包体看构建产物——排查方法完全不同，
塞一起会导致每次都加载全部内容。

## 已知坑

- ⚠ 本能会扫完就报"没问题"，但**闭包、循环引用、全局单例**静态扫不出来
- ⚠ 本能以为"扫出 0 项=通过"，但静态扫描**只抓模式明显的问题**
- ⚠ 本能只查 `onDestroy`，但 **`onEnable` 注册的必须配 `onDisable`**
- ⚠ 本能以为"tween 播完就自动没了"，但 **`repeatForever` 永远不会自己结束**
- ⚠ 本能以为"GC 会处理"，但**只要还有引用 GC 就不回收**——泄漏几乎全是"引用没断"
- ⚠ 本能以为"场景切换会自动释放资源"，但**动态加载的不在自动释放范围内**
- ⚠ 本能以为"用对象池就不会泄漏"，但**只 get 不 put / 池无上限 / put 前不清 tween** 都会让它变成泄漏池
- ⚠ 本能先优化代码逻辑，但**很多时候瓶颈在 DrawCall 而非脚本**——先看 Profiler 再动手
- ⚠ 本能以为 RichText 好用，但它**每个样式片段都可能打断合批**，频繁改内容明显掉帧
- ⚠ 本能以为 Label 都一样，但 **CacheMode 选错**会严重掉帧
- ⚠ 本能以为物理物体设 Dynamic 无所谓，但**静态物体用 Dynamic 浪费数倍性能**
- ⚠ 本能以为 `resources` 目录方便，但它**会全量打包**，是首包超标常见元凶

## 可复用片段

**泄漏安全组件模板**：

```typescript
import { _decorator, Component, Node, Tween, tween, resources, SpriteFrame } from 'cc';
const { ccclass, property } = _decorator;

@ccclass('SafeComponent')
export class SafeComponent extends Component {
    @property(Node) target: Node = null!;
    private _tween: Tween<Node> = null!;
    private _sp: SpriteFrame = null!;

    onLoad() {
        // 节点自身事件 → onLoad 注册，onDestroy 注销
        this.node.on(Node.EventType.TOUCH_START, this.onTouch, this);
    }
    onEnable() {
        // 全局/输入事件 → onEnable 注册，onDisable 注销（必须配对）
        this.target?.on('custom', this.onCustom, this);
        this._tween = tween(this.node).repeatForever(tween().to(1, { angle: 360 })).start();
        resources.load('images/bg/spriteFrame', SpriteFrame, (err, sp) => {
            if (err || !sp) return;
            this._sp = sp;
            this._sp.addRef();
        });
    }
    onDisable() { this.target?.off('custom', this.onCustom, this); }
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

**降频更新模板**：

```typescript
private _acc = 0;
private _interval = 0.2;
update(dt: number) {
    this._acc += dt;
    if (this._acc < this._interval) return;
    this._acc = 0;
    this.heavyWork();
}
private heavyWork() { /* 不需要每帧做的逻辑 */ }
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
□ 运行时验证：操作 N 次后内存回到基线
```
