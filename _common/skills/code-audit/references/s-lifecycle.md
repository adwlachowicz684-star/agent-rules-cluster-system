# 场景：生命周期与资源（s-lifecycle）

**触发**：订阅 / 定时器 / 句柄 / 资源获取 / 每帧回调 / 重挂载。
**风险**：成对契约缺一侧、随运行时长累积的泄漏、每帧开销被放大、重挂载叠加。

配套：`s-lifecycle-fix.md`（修法）、`s-sandbox-host.md`（外壳-扩展的挂载与卸载契约）。

`overlaps:` **只管「获取 ↔ 释放」是否成对、是否清理**。
通道本身的 origin/握手/超时归 `s-boundary`；容器内部条目的回收归 `s-structures`；
子进程与文件句柄的**后端实现**归 `s-backend`。

---

## 核心判据：成对契约缺一侧 = P0

**为什么**：随运行时长累积，测试期看不出，上线后 OOM，
**定位成本远高于修复成本**。

| 成对项 | 常见缺失 |
|---|---|
| `addEventListener` ↔ `removeEventListener` | 卸载时未摘 |
| 订阅 ↔ 退订 | 只按事件名匹配，摘错 |
| `setInterval` / `setTimeout` ↔ clear | 重挂载时叠加 |
| `createObjectURL` ↔ `revokeObjectURL` | 预览关闭时未释放 |
| 子进程 start ↔ kill | 注册表无清理 |
| 快捷键 register ↔ unregister | 插件卸载时残留 |
| 侧边栏/UI 注入 add ↔ remove | 卸载时残留 |
| 监听器 start ↔ stop（watch / webhook） | 无 stop 命令 |
| `schedule` ↔ `unschedule` | 切场景后驻留 |
| `repeatForever` / `loop: true` ↔ `stop()` | 常驻任务永不结束 |
| `lock` / `acquire` / `open` ↔ 对应反向 | 有前半无后半 |

**检查方法**：列出模块创建的**全部外部资源**，逐个对照卸载钩子里的清理项。

---

## 模式清单

### L-01 (P0) 事件订阅无注销
- **正确**：注册与注销必须在同一生命周期层级对称出现
  （`onLoad`↔`onDestroy`，`onEnable`↔`onDisable`）
- **特征**：有 `.on(` / `addEventListener(` / `subscribe(`，全文无
  `off` / `removeEventListener` / `unsubscribe`
- **确认**：注销是否可能在基类或其他文件（是 → 降级，但仍需确认）
- **降级**：生命周期与页面/应用等长（如主窗口 keydown）→ P2 或忽略

### L-02 (P0) 定时器无清理
- **正确**：三套机制**各自配对，不能互相替代**：
  `schedule`↔`unschedule`、`setInterval`↔`clearInterval`、`setTimeout`↔`clearTimeout`
- **确认**：是否为全局单例（是 → 标「待确认：生命周期长于页面」）

### L-03 (P0) 资源/句柄无释放
- **正确**：load/open/acquire 后必须 decRef/release/close/dispose
- **确认**：框架是否提供自动释放（**自动释放通常不覆盖动态加载的资源**，高频误区）

### L-04 (P0) 循环/常驻任务无停止
- **正确**：持有引用并在销毁时 `stop()` / `clear()`
- **特征**：`repeatForever` / `setLoop(true)` / `loop: true` 无停止调用
- **为什么**：这类任务**永远不会自己结束**，宿主销毁后仍驻留

### L-05 (P1) 成对方法只出现一侧
- **正确**：`lock`↔`unlock`、`acquire`↔`release`、`open`↔`close`
- **确认**：是否有兜底路径（如 try/finally 中的释放写成了别的名字）

### L-06 (P1) 匿名回调注册（无法精确注销）
- **正确**：回调必须是**具名方法 / 持有引用**
- **特征**：`on(ev, () => {...})` 或 `on(ev, function(){})`
- **为什么**：`off` 需同一函数引用，匿名函数导致「写了 off 也 off 不掉」。
  与「忘了写 off」**成因不同、改法不同**，所以单列

### L-07 (P1) 重挂载时监听器/定时器叠加
- **判据**：`addEventListener` / `setInterval` 在可能重复执行的初始化流程里
- **确认**：是否有 generation 标记或先 remove 再 add
- **典型**：插件重载一次，同一事件的 handler 多一个 → **按一次快捷键执行两次**
- **期望形态**（三选一）：
  - **generation 令牌**：每次挂载 `++gen`，异步回来时 `gen` 变了就丢弃结果
  - **先清理再施加**：施加滤镜/覆盖层之前先清一遍，保证幂等
  - **卸载钩子兜底**：即使前两者漏了，卸载时也能清干净
- **⚠「宿主引擎」类代码若三样都没有，几乎必然存在叠加缺陷**

### L-08 (P0) 监听器遍历 + 回调内退订
- **正确**：`[...this._listeners].forEach(...)` 或倒序索引
- **特征**：`_listeners` / `_handlers` / `_callbacks` + `.forEach`
- **标准测法**：三个订阅者 A/B/C，A 在回调里退订，**执行序列必须包含 B**

### L-09 (P1) 取消订阅定位不精确
- **正确**：注册返回唯一句柄，按句柄取消
- **特征**：Set 存监听器 + `filter` 按函数值重建
- **失效**：同一函数注册多次时一次取消全删

### L-10 (P1) 状态字段只有置 true 没有复位 false
- **正确**：置 `true` 处配对置 `false`
- **特征**：`this._flag = true` 存在但全文无 `= false`

### L-11 (P1) 清理不彻底（clear/reset 遗漏部分容器）
- **正确**：`clear` / `reset` / `destroy` 覆盖全部内部容器
- **特征**：清理了部分但同文件还有别的容器字段
- **识别三种清理写法**：`.clear()` / `.length = 0` / `= []`

### L-12 (P1) 每帧回调内昂贵操作
- **正确**：把结果缓存到初始化阶段，回调内只做增量计算
- **特征**：`update` / `tick` / `lateUpdate` 内出现 `find` / `getComponent` /
  `instantiate` / `destroy` / `new X` / `JSON.parse` / `sort` / `Object.keys`
- **确认**：该回调是否真的每帧执行（有些引擎的回调可能被降频或手动驱动）
- **判据**：**每帧回调内的开销要乘 60 看**（60fps 下每秒执行 60 次）

### L-13 (P1) 每帧回调内分配对象
- **正确**：复用对象或预分配
- **特征**：`update` 内 `new` / 数组字面量 / 闭包

### L-14 (P1) 对象销毁后仍被外部持有并继续使用
- **判据**：销毁后无状态标记，外部仍持有引用
- **定级**：**静默**产生错误结果 → P1；抛异常（能被发现） → P2
- **加固**：加状态标记

### L-15 (P1) 缓存 Map 无上限增长
- **判据**：`Map.set(k, v)` 无对应 `delete` 且 key 来自外部/递增序列
- **确认**：key 是否有界（固定枚举 vs 用户输入 vs 时间戳）
- **典型**：pending 请求表、进程注册表、监听器表

---

## 卸载钩子检查表

对每个模块，列出它创建的**全部外部资源**，逐个对照：

```
□ 事件监听（DOM / 事件总线 / IPC）
□ 定时器（interval / timeout / schedule）
□ 请求（fetch / invoke 的 pending）
□ 句柄（objectURL / 文件 / socket / 子进程）
□ UI 注入（侧边栏 / 菜单 / 快捷键 / 覆盖层）
□ 全局引用（window.__X / 注册表 / 单例）
□ 观察者（MutationObserver / ResizeObserver / IntersectionObserver）
□ 动画帧（requestAnimationFrame）
```

## 常见误报

- **L-01 生命周期与页面等长** —— 主窗口 keydown 不摘也没事 → P2 或忽略
- **L-02 卸载钩子里有 clear，但写法是间接引用** —— 静态分析看不到 → 忽略
- **L-11 该容器本就不需要清** —— 与模块同生命周期 → 忽略
- **L-12 回调被降频或手动驱动** —— 不是每帧 → 降级
- **注释解释了为什么不能那样写** —— 先读注释

### 已知误报：`setInterval` 可能是 React state setter 名

```jsx
const [interval, setInterval] = useState(config.watchIntervalSecs || 30);
...
onChange={(e) => setInterval(Number(e.target.value))}
```
扫到 `setInterval` 时**先看是不是 `useState` 的 setter**。判断方法：
同一作用域内是否有 `const [xxx, setXxx] = useState(`。

**实测影响**：nexus-panel 里 `grep setInterval` = 8 处，其中 **2 处**是 React state setter、
1 处在注释里（「用 rAF 而不是 setInterval」），真定时器只有 4 处且**全部配对**。
不剔除就会报出"3 处定时器未清理"的假结论。

同理，`setTimeout` 也要警惕同名变量。
