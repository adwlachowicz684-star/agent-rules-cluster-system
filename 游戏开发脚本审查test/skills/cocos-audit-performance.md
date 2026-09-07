---
id: DEV-S03
name: Cocos 性能与包体专项审核
description: 审核 Cocos Creator 项目的运行性能与包体体积，覆盖 DrawCall 合批、Label 文本渲染、物理系统、多分辨率适配、构建瘦身与分包。当用户提到"卡顿""帧率低""包体太大""首包超4MB""适配错位"时使用。
keywords: [性能, 卡顿, 帧率, FPS, 掉帧, DrawCall, 合批, 图集, Label, cacheMode, RichText, 文本渲染, 物理, 碰撞, 刚体, RigidBody, 休眠, 适配, 分辨率, Widget, 安全区, 刘海屏, 包体, 首包, 4MB, 分包, 引擎裁剪, 构建, 瘦身, 微信小游戏]
trigger: 用户报告卡顿/掉帧/包体过大/首包超限/UI在不同机型错位；上线前性能与包体体检
applies_to: ""
verified: partial
related: [DEV-S01, DEV-S02]
---

# Cocos 性能与包体专项审核

> 主包见 `cocos-script-audit.md`（DEV-S01），内存问题见 `cocos-audit-memory.md`（DEV-S02）。
> 本包处理**运行性能**与**包体体积**——两者都不是"会不会崩溃"而是"体验好不好"。

## 一、DrawCall 与合批

**为什么重要**：DrawCall 是 CPU 调用图形 API 的次数，每次切换渲染状态都有开销。
移动端目标 **<100**，超过就该优化。

```bash
# 找可能打断合批的组件
python3 scripts/cocos_audit.py <路径> --rule perf
rg -n "Mask|RichText" <目录>
```

**打断合批的常见原因**：

| 原因 | 说明 | 处理 |
|---|---|---|
| 纹理不同 | 相邻节点用了不同图集/散图 | 打自动图集，让它们共用一张 |
| **Mask 组件** | 产生额外 DrawCall + Stencil 操作 | 滚动列表慎用；非必要不用 |
| **RichText** | 每个样式片段都可能打断合批 | 能用 Label 就别用 RichText |
| 材质/Blend 不同 | 自定义材质混排 | 同类节点放一起渲染 |
| Label 穿插 | 文本节点夹在 Sprite 之间 | 调整节点层级，同类聚拢 |

## 二、Label 文本渲染（官方文档明确的坑）

**CacheMode 三选一**（选错直接影响帧率）：

| 模式 | 内存 | 适用 | 更新频率 |
|---|---|---|---|
| `NONE` | 低 | 静态文本（标题、菜单） | 不可动态更新 |
| `BITMAP` | 中 | 低频更新（倒计时、金币数） | ≤5 次/秒 |
| `CHAR` | 高 | 高频更新（聊天、伤害数字） | ≤30 次/秒 |

⚠ `BITMAP` 模式下改内容后需 `label.markForUpdateRenderData()` 才生效。

```typescript
// 高频变化的数字
label.cacheMode = Label.CacheMode.CHAR;
label.string = `${this.score}`;
// 降频：不必每帧更新
this.schedule(() => { label.string = `${--this.remain}`; }, 0.1);
```

**其他文本要点**：
- **RichText 是 JS 层实现**，底层创建大量 Label 节点；官方明确警告
  "避免在主循环中频繁修改 RichText 内容"，能用普通 Label 就用 Label，
  **BMFont 效率最高**
- 静态文本尽量**合并到同一 Label 用 `\n` 换行**（多个 Label = 多次 DrawCall）
- 字体裁剪：TTF 裁掉未用字符可减 50%~90%
- 慎用 Outline/Shadow，移动端尤其

## 三、物理系统

```typescript
// 静态物体（地面、墙）——引擎会特殊优化，务必标 Static
const rb = node.addComponent(RigidBody2D);
rb.type = ERigidBody2DType.Static;
rb.allowSleep = true;              // 非活体休眠
```

| 优化项 | 做法 |
|---|---|
| **静态物体用 Static** | Dynamic 刚体性能开销是 Collider 的数倍（实测可达 5x） |
| **善用休眠** | `allowSleep = true`，不活跃的动态刚体停止计算 |
| **碰撞分组掩码** | 最有效手段——直接避免大量不必要的检测对 |
| **简化碰撞形状** | 能矩形/圆形就别多边形；复杂多边形开销可达矩形数十倍 |
| **CCD 只在必要时开** | 防高速穿透，但开销大，只给子弹等高速物体 |
| **远离视口禁用** | `collider.enabled = false` |
| **降低迭代次数** | 节奏不快的游戏可调大 `fixedTimeStep`，减 `solverIterations` |

**引擎选型**（影响包体与性能）：

| 引擎 | 大小 | 适用 |
|---|---|---|
| builtin | 最小 | 只需碰撞检测，无物理模拟 |
| cannon.js | ~141KB | 需要较完整物理功能 |
| bullet(ammo.js) | ~1.5MB | 功能完善、性能佳，但包体大 |
| PhysX | — | 高稳定性、高性能 |

⚠ **不需要物理就整个关掉**（项目设置→功能裁剪），能显著减小包体。

## 四、多分辨率适配

**适配策略选择**：

| 策略 | 效果 | 适用 |
|---|---|---|
| `FIXED_HEIGHT` | 高度固定，宽度自适应（左右可能裁切） | **竖屏游戏推荐** |
| `FIXED_WIDTH` | 宽度固定，高度自适应（上下可能裁切） | 横屏游戏 |
| `SHOW_ALL` | 保持比例，两侧留黑边 | 不希望内容被裁（有黑边） |
| `NO_BORDER` | 填满屏幕，可能裁切边缘 | 背景可溢出的场合 |
| `EXACT_FIT` | 拉伸填满，**会变形** | 不推荐 |

**Widget 用法**：
- 顶部 UI（血条/金币）勾 `Top`；底部按钮勾 `Bottom`；两侧勾 `Left/Right`
- 全屏背景四边全勾
- ⚠ **避免同时锁定 Left + Right + Width**（会冲突警告）

**刘海屏安全区**：

```typescript
const rect = view.getSafeAreaRect();     // 物理像素
// 需转换到设计分辨率坐标，再更新 Widget 边距
const widget = this.node.getComponent(Widget);
if (widget) {
    widget.top = /* 转换后的偏移 */;
    widget.updateAlignment();
}
```

⚠ 常见坑：`getSafeAreaRect()` 返回**物理像素**，与设计分辨率坐标系不同，需换算；
Web 非原生环境下可能返回全屏，导致真机才暴露问题。

## 五、包体与构建（微信小游戏 4MB 硬限制）

**优化优先级（按收益排序）**：

| 手段 | 收益 | 做法 |
|---|---|---|
| **引擎裁剪** | 省 1.5~3MB | 项目设置→功能裁剪，去掉 3D/物理/视频/DragonBone/Spine 等未用模块 |
| **分包/Bundle** | 主包直降 | 游戏内容放独立 Bundle，主包只留启动场景；小游戏平台选"小游戏分包" |
| **引擎插件** | ~1.8MB | 微信小游戏勾选"启用微信小游戏引擎插件"（复用微信内置引擎） |
| **WASM 分离** | 数百 KB | 开启 WASM 分包 |
| **纹理压缩** | 视资源量 | Android 用 ETC2/ASTC，iOS 用 PVRTC/ASTC |
| **大文件排查** | 常有意外 | 微信开发者工具→代码依赖分析，找超大文件（社区案例：默认天空盒 4096×3072 改成 1024×768，总包从 7.66MB 降到 4.77MB） |

**Bundle 优先级**（决定打包归属与加载顺序）：
`internal(21)` > `resources(8)` > `main(7)` > 自定义 bundle(1+)

⚠ **`resources` 目录会打包全部资源**——大项目应避免滥用，
优先用自定义 Bundle + 场景引用（引擎自动按需打包）。

## 六、其他性能项

- **对象池**：子弹/敌人/特效等频繁创建销毁的必用 `NodePool`（细节见 DEV-S02）
- **update 降频**：非每帧必要的逻辑累加 `dt` 或 `frameCount % N`
- **避免在 update 中**：`find`、`getComponent`、`instantiate`、`new`、`destroy`
- **3D 项目**：面片数移动端建议 <10 万；用 LOD；骨骼动画开 GPU 蒙皮

## 排查流程

```bash
# 1. 静态扫描性能类
python3 scripts/cocos_audit.py <路径> --rule perf

# 2. 找高频更新与 DrawCall 风险点
rg -n "^\s+update\s*\(" <目录> -A 12
rg -n "Mask|RichText|\.string\s*=" <目录>

# 3. 运行时：Profiler 看 Script vs Rendering 耗时占比
#    卡顿定位：先分清是 CPU 逻辑还是 GPU 渲染瓶颈，再针对性优化
```

**定位思路**：用 Profiler / Chrome Performance 录制卡顿时段，
先看 **Scripting（CPU 逻辑）** 还是 **Rendering（GPU）** 耗时过长，
两边优化手段完全不同，别搞反。

## 失败处理

| 情况 | 判据 | 动作 |
|---|---|---|
| 静态扫描 0 项但仍卡 | 性能问题多在配置与场景结构，脚本看不出 | 走 Profiler 实测，别停在静态扫描结论 |
| 包体超标但不知从哪减 | 无依赖分析数据 | 先用微信开发者工具做代码依赖分析，找 TOP 大文件 |
| 模拟器流畅真机卡 | 设备性能差异 | 用低端机测；检查纹理压缩、面片数、DrawCall |
| 无法判断瓶颈在 CPU 还是 GPU | Profiler 数据不清晰 | 分别禁用逻辑/渲染对比帧率 |

## 已知坑

- ⚠ 本能会先优化代码逻辑，但**很多时候瓶颈在 DrawCall 而非脚本**——先看 Profiler 再动手
- ⚠ 本能以为 RichText 很强很好用，但官方明确说它**每个样式片段都可能打断合批**，
  且是 JS 层实现，频繁改内容会明显掉帧
- ⚠ 本能以为 Label 都一样，但 **CacheMode 选错**（高频更新用了 NONE/BITMAP）会严重掉帧
- ⚠ 本能以为物理物体设 Dynamic 无所谓，但**静态物体用 Dynamic 会浪费数倍性能**
- ⚠ 本能以为 `resources` 目录方便，但它**会全量打包**，是首包超标的常见元凶

## 可复用片段

**降频更新模板**：

```typescript
private _acc = 0;
private _interval = 0.2;      // 每 0.2 秒执行一次

update(dt: number) {
    this._acc += dt;
    if (this._acc < this._interval) return;
    this._acc = 0;
    this.heavyWork();
}

private heavyWork() { /* 不需要每帧做的逻辑 */ }
```

---

**变更记录**：见本大类 `assets/changelog.md`
（`python3 scripts/note.py "DEV-S03" 补充 "<原因>" --domain dev`）
