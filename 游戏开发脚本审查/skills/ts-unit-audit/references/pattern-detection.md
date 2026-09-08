<!-- oversize-exempt: 查表型文档，确认候选时需整体对照 61 条判据，拆分反而增加往返 -->
# 缺陷模式检测（61 条）

每条给出：**正确做法 → 扫描特征 → 如何确认是否为真问题**。
扫描器输出的是候选，确认按本文判据。

## 前置：NaN 的三副面孔

同一个 `NaN` 有三种完全不同的失效路径：

| 方式 | 机制 | 典型形态 |
|---|---|---|
| **穿透** | `clamp(NaN)` 用比较实现，两条分支都 false → 原样返回 | `clamp(opts.x, 0, 1)` |
| **绕过守卫** | `x <= 0` / `x < 5` 恒 false → 校验不触发 | `if (interval <= 0) throw` |
| **静默归零** | `x >>> 0` / `| 0` 得 0 | `const seed = opts.seed >>> 0` |

**关键推论**：`historyLimit` 传 **0 和负数往往安全**（`length > 0` 为真会走裁剪），
**唯独 NaN 失效**。只测 0 / 负数 / 正常值**测不出这类缺陷**。

**两个反直觉陷阱**：

- `Math.max(1, NaN)` → `NaN`；`Math.max(1, Infinity)` → `Infinity`。
  **Math.max 不是有效守卫。**
- `Number.isFinite(null)` → `false`，能挡住 null；但 `Number(x)` 强制转换会把 null 变成 0。

更多对抗性输入见 `adversarial-inputs.md`。

---

## A 族 · 数值收口

**A01 (P0) 数值守卫** — 正确：`if (!(x > 0))` 或 `if (!Number.isFinite(x))`；
特征：`if (x <= 0)` / `if (x < n)`；确认：变量是否可能来自外部输入，只可能是常量则忽略。

**A02 (P0) 配置默认值** — 正确：`clampNum(opts.x, min, max, def)`；
特征：`opts.x ?? d` 且附近无收口；确认：字段是否为数值型。命中最多（常数百条），按族批量修。

**A03 (P0) clamp 前置校验** — 正确：入参来自外部时先 `Number.isFinite`； **注意：`clampNum` / `numOr` 不算问题**——它们内部走 `numOr(v,NaN)`+`isNaN→fallback`，非有限值有兜底，不穿透；只有裸 `clamp` / `clamp01` 才是。
特征：`clamp*(opts.x, ...)` 附近无 `isFinite`；确认：调用方有没有兜住。

**A04 (P0) 累加 / EMA** — 正确：脏样本**丢弃**（`if (!Number.isFinite(s)) return;`），
不是兜底 0；特征：`this._x +=` / `lerp(this._x, ...)` 无 `isFinite`；
确认：是否参与后续所有帧（是 → 污染不可逆）。用兜底值会把「数据坏了」伪装成正常值。

**A05 (P1) 位运算取整数** — 正确：`Number.isFinite(o.seed) ? o.seed >>> 0 : defaultSeed`；
特征：`>>> 0` / `| 0`；确认：种子类参数是高危。

## B 族 · 循环与递归收敛

**B01 (P0) 循环上界** — 正确：`clampNum(opts.n ?? 4, 1, 64)`；
特征：`for (let i = 0; i < <标识符>; i++)` 非字面量且附近无 clamp；确认：是否来自配置/入参。

**B02 (P0) while 退出条件** — 正确：有限上界 + guard 计数器；
特征：`while` 体内 `*= 2` / `++` / `+=`，条件涉及 `Infinity` / `maxRadius` / `limit`。

**B03 (P0) 递归** — 正确：传访问集或深度上限；
特征：**普通函数自递归**与**方法自递归**两种形态都会检；
确认：深度是否由数据决定（子表互引用、嵌套树）→ 是则必改。

## C 族 · 原型链安全

**C01 (P0) 外部键查表** — 正确：`new Map()` / `Object.create(null)` / `Object.hasOwn(T,k)`；
特征：`TABLE[k]` 或 `k in TABLE`；危险键：`toString` / `constructor` / `__proto__` / `valueOf` / `hasOwnProperty`。

**C02 (P1) 外部键累加** — 正确：`new Map<string, number>()`；特征：`const x = {}` 后 `x[key] +=`。

**C03 (P1) 合并外部对象** — 正确：过滤 `__proto__` / `constructor` / `prototype` 后再合并；
特征：`Object.assign(` / `...spread` 涉及 JSON / import / state。

## D 族 · 死契约

**D01 (P0) 接口字段未实现** — 正确：实现它，或连同 README/JSDoc 声明一起删；
特征：接口字段在模块内只出现 1 次（声明处）；确认：同目录其他文件是否使用。

**D02 (P0) 参数未使用** — 正确：用起来或删除；
特征：类方法 / 独立函数 / 箭头方法三种形态都检；
确认：是否为刻意保留的签名参数（接口一致性）→ 是则降级。

## E 族 · 遍历安全

**E01 (P0) 监听器遍历** — 正确：`[...this._listeners].forEach(...)` 或倒序索引；
特征：`_listeners`/`_handlers`/`_callbacks` + `.forEach`；
**标准测法**：三个订阅者 A/B/C，A 在回调里退订，**执行序列必须包含 B**。

**E02 (P1) 取消订阅定位** — 正确：注册返回唯一句柄，按句柄取消；
特征：Set 存监听器 + `filter` 按函数值重建；失效：同一函数注册多次时一次取消全删。

## F / G / H 族 · 入口与校验

**F01 (P0) 反序列化入口** — 正确：`import` 复用与 `register`/`set` **相同的归一化函数**；
特征：`import*`/`deserialize`/`load` 内直接 `this._x.set/push/add`；
规律：后加的便捷入口最容易漏校验。

**G01 (P1) 多订阅者** — 正确：数组或 Set 存订阅者，`on()` 返回取消函数；
特征：`this._onXxx = fn` 直接赋值。

**H01 (P1) 成对 API 校验对称** — 正确：抽 `private _normalize(raw)`，所有入口共用；
特征：`set`/`add`、`register`/`import`、`preview`/`upgrade` 一个有校验一个没有；
注意：需两个成员都出现才触发。

## I / J / K 族 · 资源与原子性

**I01 (P1) 容量上限** — 正确：`clampNum` 收口 + 超限裁剪；
特征：`_log`/`_history`/`_seen`/`_cache` 容器全文无 `shift`/`splice`/`clear`。

**I02 (P1) 嵌套全量扫描** — 正确：预建索引；
特征：`filter`/`map` 回调内调用 `this.get()` / `indexOf` / `includes`。

**J01 (P0) 多步写操作原子性** — 正确：先全量预检再统一动账，或 try/catch 整体回滚；
特征：扣减与增加在相邻行且无 `try`。

**J02 (P1) 空 catch** — 正确：至少记录日志；特征：`catch (e) { }`。

**K01 (P1) 状态复位** — 正确：置 `true` 处配对置 `false`；
特征：`this._flag = true` 存在但全文无 `= false`。

**K02 (P1) 清理完整** — 正确：`clear`/`reset`/`destroy` 覆盖全部内部容器；
特征：清理了部分但同文件还有别的容器字段；识别三种清理写法：`.clear()` / `.length = 0` / `= []`。

## L / M / N / O 族 · 完整性与确定性

**L01 (P0) 空 if 块** — 正确：补处理体或删除整个 `if`；特征：`if (...) { }`。
命中少但几乎条条是真问题，**优先处理**。

**L02 (P1) 三元同值** — 正确：改写分支或删条件；特征：`cond ? A : A`。

**M01 (P0) fail-open** — 正确：**fail-closed**；
特征：`can*`/`is*`/`should*`/`check*` 体内 `if (!x) return true`；
确认：放行分支是否涉及货币、解锁、封禁、权限 → 是则致命。

**M02 (P0) 判定依赖脏数值** — 正确：比较前先校验有限性；
特征：`can*`/`has*` 返回 boolean，体内有数值比较但无 `isFinite`/`numOr`。

**N01 (P1) 时间源注入** — 正确：`interface Options { readonly now?: () => number; }`；
特征：`Date.now()` / `performance.now()`；
注意：只在确实是注入口（箭头函数/函数类型声明）时才跳过，`const now = Date.now();` 是硬编码取值。

**N02 (P1) 随机源注入** — 正确：构造注入 `IRandomSource`；特征：裸 `Math.random()`；
确认：注释声称「只影响观感」但实际参与逻辑累积 → 按 P0（错误注释会阻止修复）。

**O01 (P1) 位宽计算** — 正确：`Math.pow(2, n) - 1`；特征：`1 << n` 且 `n >= 31`。

**O02 (P1) 除法分母** — 正确：`total > 0 ? v / total : 0`；特征：`/ scale` 等且无零判定。

**O03 (P1) 日志注入** — 正确：库走 logger 注入；特征：`console.log/warn/error/info`。

**O04 (P1) 返回引用** — 正确：返回副本 `[...arr]`，或文档明确标注；
特征：`return this._x;` 无 `.slice()`；确认：调用方是否长期持有，文档已标注则降级。

## P 族 · 值域与类型收口（深层）

**P01 (P0) 收口函数缺 typeof 校验** — 正确：`typeof v === 'number' ? ... : def`；
特征：`clampNum`/`numOr`/`needCount` 体内无 `typeof ... === 'number'`；
**为什么**：`Number(null)` → 0，缺失配置会**静默变成合法的 0 或下界**，改变超时/容量/速度语义且不报错。
判据：先判类型再判有限性；若在 `Number.isFinite` 之前已做了 `Number(v)` 转换则无效。

**P02 (P0) Infinity 当哨兵** — 正确：空集用 `length === 0` 或 `null`；
特征：`= -Infinity` / `=== Infinity` 等；
**为什么**：±Infinity 是**合法数值**，当哨兵会把含合法极值的集合静默替换为 fallback。

**P03 (P0) Math.max/min 当守卫** — 正确：`clampNum` 或先 `Number.isFinite`；
特征：`Math.max(数字, 变量)`；失效矩阵：
```
Math.max(1, NaN)       → NaN        （守卫失效）
Math.max(1, Infinity)  → Infinity   （当数组尺寸会崩）
Math.max(1, -5)        → 1          （只有这个符合预期）
```

**P04 (P1) slice/splice 负数参数** — 正确：数量参数先转有限非负整数；
特征：`.slice(`/`.splice(` 参数含变量；
失效：`slice(0, -1)` 不是「取 0 个」而是「去掉最后 1 个」，负数配置会反转语义。

**P05 (P0) 数值 op 未校验操作数类型** — 正确：两个操作数都校验为有限 number；
特征：`case 'add'`/`case 'mul'` 内用 `+`/`*=` 无类型校验；
失效：`10 + '5'` → `'105'`（拼接），`add` 是重灾区。

## Q 族 · 内存分配与数据结构

**Q01 (P0) TypedArray/大数组尺寸未收口** — 正确：有限正整数 + **总元素量上限**；
特征：`new Array(x)` / `new Float32Array(x)`，x 非字面量且附近无 clamp；
**为什么 P0**：错误不在 API 边界报出，而是传导到底层 `RangeError` 或瞬时 OOM，
**诊断信息完全指向不了配置字段**。特别检查宽高相乘（两个都合法但乘积极大）。

**Q02 (P1) 惰性删除 size 语义** — 正确：维护有效计数，`remove` 幂等；
特征：`LazyHeap`/tombstone + `get size`/`get isEmpty`；
失效：`size` 返回物理条目数但 `pop()` 返回 undefined → 以 isEmpty 驱动的循环与 pop 不一致。

**Q03 (P0) 分桶不回收空桶** — 正确：删除元素后若 `bucket.size === 0` 同步删 Map key；
特征：`new Map()` 分桶字段有 `.delete(` 但全文无 `.size === 0`；
**为什么 P0**：开放世界持续移动会**长期积累空桶**，难以察觉的内存泄漏。

**Q04 (P0) 对象池三类** — 正确：`put()` 拒绝非本池借出的对象（扣减 active 必须以归属为前提）；`active` 不得为负；`prewarm` 必须有限整数上限。 特征：`prewarm()` 无上界收口 / `active--` 无 `Math.max(0,...)` / `put()` 里 active 扣减**直接写在方法体**（花括号深度 1，不在任何 if 内）。 确认：实测 `get 3 个 → put 5 个外部对象 → active 被刷成 0`。 **注意**：不能用「有没有 `has()`」判归属——重复归还拦截也用 `has()`，但它查的是「是否已空闲」，方向与归属相反（实测会漏掉只有重复拦截的池）。

**Q05 (P1) spread 展开不定参数** — 正确：循环归约；特征：`Math.max(...arr)`；
**Q06 (P1) 容器摘除未清内容** — 正确：删除 `Map<K, Set<V>>` 条目时先 `set.clear()`； `map.clear()` 前先遍历 clear 各内部容器。 特征：`_map.delete(k)` / `map.clear()` 附近无 `clear()`； 确认：**是否存在闭包持有容器内条目**（`on()` 返回的取消函数、暴露迭代器、直接返回容器）——无持有途径则 delete 后可 GC，是误报。 降级：摘除时容器已空（同行有 `.size === 0` 判断）→ 忽略。 注意与 Q03 是反向同类：Q03 删元素不删空桶，Q06 删桶不清内容。
失效：参数量大时 `RangeError`。**AST 深度限制挡不住**——深度很浅但参数很多。

## R 族 · 路径、序列化与 key 编码

**R01 (P0) 路径写入未过滤危险段** — 正确：解析后拒绝 `__proto__`/`prototype`/`constructor` 段，只在自有容器写入；
特征（两种写法都覆盖）：① `str.split('.')` ② 正则 `/([^.[\]]+)|\[(\d+)\]/g` ③ `parsePath` 类函数；
**为什么**：不可信存档/网络差量可**改写进程级对象行为**。只扫 split 会漏掉正则实现。

**R02 (P0) 批量删除未降序** — 正确：同一父数组多个索引必须**按索引降序** splice；
特征：循环内 `splice` 且上下文无 `sort`/`reverse`；
失效：`['a','b','c']` 删 [1] 与 [2]，先删 1 后原 [2] 移到 [1]，结果 `['a','c']` 而非 `['a']`。
**按路径深度排序不足以处理同层多删。**

**R03 (P0) 路径协议不可逆** — 正确：JSON Pointer（RFC 6901）或带转义 token 数组；
特征：路径解析 + patch 应用同时存在；
失效：`{'a.b':1}` 往返一次变成 `{'a.b':1, a:{b:2}}`，合法 JSON 键被静默改造成另一棵树。

**R04 (P0) 复合 key 未编码** — 正确：长度前缀编码/转义，或结构化 tuple / 嵌套 Map；
特征：`join('|')` 拼 key 或模板字符串 `${a},${b}`；
失效：`{a:'1,b=2'}` 与 `{a:'1', b:'2'}` 生成同一 key → 两个维度写入同一项，数值静默合并。

## S 族 · 安全默认值

**S01 (P0) 调试/作弊/后门默认启用** — 正确：`enabled`/`debug`/`cheat`/`devMode` 默认 **false**，
宿主显式开启；生产构建应 hard fail 或剔除；
特征：`enabled = true` / `enabled: true` / `enabled ?? true`；
**为什么 P0**：生产构建漏配即可暴露作弊命令、经济/关卡修改能力。
把安全寄托于「调用方记得关」不可靠。

## T 族 · 角度与周期归一化

**T01 (P0) while 做角度归一化** — 正确：**常数时间取模**并先拒非有限值
```typescript
const norm = (a: number) => { const r = a % (Math.PI * 2); return r < 0 ? r + Math.PI * 2 : r; };
```
特征：`while` 体内 `- 360` / `- 2*Math.PI`（单语句与带大括号两种形态都检）；
失效：`diff` 为 `Infinity` 时减 360 后仍为 `Infinity` → **永不退出**。

**T02 (P0) 循环变量可为 ±Infinity** — 正确：上下界都收口为有限值；
特征：`for (let i = <非字面量>; i < <非字面量>; ...)` 附近无收口；
失效：`-Infinity + 1` 仍为 `-Infinity`。与 B01 区别：B01 看上界，T02 同时看**起始值**。

## U 族 · 展示层掩盖

**U01 (P1) 展示层掩盖非有限值** — 正确：不得用 `|| 0`/`?? 0` 掩盖 NaN，应显式标注或抛错；
特征：`display`/`format`/`render` 体内有 `|| 0`/`?? 0`；
**为什么有害**：一次坏输入永久污染该维度，而 UI 显示正常的 0，**故障被完全隐藏**。

## W 族 · 交易与批量数量

**W01 (P0) 交易/批量数量未校验有限正整数** — 正确：
`Number.isInteger(n) && n > 0 && Number.isFinite(n)`；
特征：`buy`/`sell`/`craft`/`pullN`/`roll`/`simulate`/`prewarm` 的数量参数无双重校验；
失效：购买 `-2` 件 → `total = -20` → **钱包凭空增加 20、库存增加 2**，日志却记为成功。
注意：`<= 0` 挡不住 NaN，且必须同时查整数性。

## X 族 · 成对 API 配对（获取 ↔ 释放）

**来源与抽象**：从引擎脚本审计的「on 无 off / schedule 无 unschedule / load 无 release」
抽象而来。判据是**换个语言或框架还成立**——任何「注册-注销」「获取-归还」的成对契约，
缺一侧即泄漏。**这类泄漏随运行时长累积，测试期看不出，上线后 OOM，定位成本远高于修复成本。**

**X01 (P0) 事件订阅无注销** — 正确：注册与注销必须在同一生命周期层级对称出现
（`onLoad`↔`onDestroy`，`onEnable`↔`onDisable`）；
特征：有 `.on(` / `addEventListener(` / `subscribe(`，全文无 `off`/`removeEventListener`/`unsubscribe`；
确认：注销是否可能在基类或其他文件（是 → 降级，但仍需确认）。

**X02 (P0) 定时器无清理** — 正确：`schedule`↔`unschedule`、`setInterval`↔`clearInterval`、
`setTimeout`↔`clearTimeout`，**三套机制各自配对，不能互相替代**；
特征：有注册无清理；确认：是否为全局单例（是 → 标"待确认：生命周期长于页面"）。

**X03 (P0) 资源/句柄无释放** — 正确：load/open/acquire 后必须 decRef/release/close/dispose；
特征：有获取无释放；
确认：框架是否提供自动释放（注意：**自动释放通常不覆盖动态加载的资源**，这是高频误区）。

**X04 (P0) 循环/常驻任务无停止** — 正确：持有引用并在销毁时 `stop()`/`clear()`；
特征：`repeatForever` / `setLoop(true)` / `loop: true` 无停止调用；
**为什么**：这类任务**永远不会自己结束**，宿主销毁后仍驻留。

**X05 (P1) 成对方法只出现一侧** — 正确：`lock`↔`unlock`、`acquire`↔`release`、`open`↔`close`；
特征：有前半无后半；确认：是否有兜底路径（如 try/finally 中的释放写成了别的名字）。

**X06 (P1) 匿名回调注册** — 正确：回调必须是**具名方法/持有引用**；
特征：`on(ev, () => {...})` 或 `on(ev, function(){})`；
**为什么**：`off` 需同一函数引用，匿名函数导致"写了 off 也 off 不掉"，
与"忘了写 off"成因不同、改法不同，所以单列。

## Y 族 · 热路径与高频回调

**抽象**：每帧/高频回调内的操作会随帧率**线性放大**——60fps 下每秒执行 60 次。

**Y01 (P1) 每帧回调内昂贵操作** — 正确：把结果缓存到初始化阶段，回调内只做增量计算；
特征：`update`/`tick`/`lateUpdate` 内出现 `find` / `getComponent` / `instantiate` /
`destroy` / `new X` / `JSON.parse` / `sort` / `Object.keys`；
确认：该回调是否真的每帧执行（有些引擎的回调可能被降频或手动驱动）。

**Y02 (P1) 每帧分配对象** — 正确：复用外部对象（`this._tmp.length = 0` 而非 `= []`）；
特征：`update` 内创建数组/对象字面量/闭包/数组变换；
确认：是否在热路径（每秒 >30 次）→ 否则降级为 P2。

---

## 确认候选的通用流程

1. 打开 `文件:行号`，**先读上方注释**
2. 问：这个变量/参数**可能**取到非法值吗？（来自配置、用户输入、前序运算 → 是）
3. 问：取到非法值后**会报错吗**？（不报错 = 静默失效，严重度更高）
4. 问：能恢复吗？（不可逆 → 严重度更高）
5. 按 `adversarial-inputs.md` 的九类输入写 probe 实测
6. 定级（见 `severity.md`）

## 扫描器的已知边界

| 边界 | 说明 |
|---|---|
| 算法语义 | 扫不出（A* 的 closed 集语义、八分体符号） |
| 文档一致性 | 扫不出（需人工比对 README/JSDoc 与源码） |
| 跨单元一致性 | 扫不出（见 `global-consistency.md`） |
| 误报 | D02 签名参数、A02 非数值默认值、O04 文档已标注 |

扫描器的价值是**把人工精审范围从「全部代码」缩小到「具体文件具体行」**，
不是替人下结论。

改过模式逻辑后跑 `pattern-scan.py --self-test` —— 它会注入已知缺陷验证每条模式能否检出。
**永远返回 0 命中的检查等于没有检查。**
