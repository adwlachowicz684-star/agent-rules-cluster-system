<!-- oversize-exempt: 查表型文档，确认候选时需整体对照本场景全部判据，拆分反而增加往返 -->
# 场景：数值与边界（s-numerics）

**触发**：浮点运算 + 守卫 / `clamp` / 累加 / 循环上界 / 角度周期。
**风险**：NaN 静默穿透、Infinity 死循环或 OOM、哨兵值与合法极值冲突、展示层掩盖故障。
**来源**：A B P T U W 族（TS/JS 代码库 240+ 条真实 P0/P1 缺陷聚类）。

`overlaps:` **只管数值语义本身**。循环/递归的**结构**问题（无访问集、栈溢出）归 `s-structures`；
循环内的**每帧开销**归 `s-lifecycle`；数值判定的**放行**语义归 `s-atomicity`。

---

## 前置：NaN 的三副面孔（必读）

同一个 `NaN` 有三种完全不同的失效路径，**不区分就会误判**：

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

**必测对抗性输入**：`NaN` / `Infinity` / `-Infinity` / `undefined` / `null` / `-0` /
`Number.MAX_SAFE_INTEGER` / 极大值 / 极小值。详见 `s-numerics-adversarial.md`。

---

## 模式清单

### N-01 (P0) 数值守卫挡不住 NaN
- **正确**：`if (!(x > 0))` 或 `if (!Number.isFinite(x))`
- **特征**：`if (x <= 0)` / `if (x < n)`
- **确认**：变量是否可能来自外部输入；只可能是常量/枚举则忽略
- **为什么**：所有比较对 NaN 恒 false → 校验分支永不触发

### N-02 (P0) 配置默认值未收口
- **正确**：`clampNum(opts.x, min, max, def)`
- **特征**：`opts.x ?? d` 且附近无收口
- **确认**：字段是否为数值型（非数值字段 → 忽略）
- **注意**：命中数常常最多（常数百条），**按族批量修**，不逐条写报告

### N-03 (P0) clamp 穿透
- **正确**：入参来自外部时先 `Number.isFinite`
- **特征**：`clamp*(opts.x, ...)` 附近无 `isFinite`
- **降级**：**`clampNum` / `numOr` 不算问题**——它们内部走 `numOr(v,NaN)` + `isNaN→fallback`，
  非有限值有兜底，不穿透。只有裸 `clamp` / `clamp01` 才是
- **确认**：调用方有没有兜住

### N-04 (P0) 累加 / EMA 不可逆污染
- **正确**：脏样本**丢弃**（`if (!Number.isFinite(s)) return;`），不是兜底 0
- **特征**：`this._x +=` / `lerp(this._x, ...)` 无 `isFinite`
- **确认**：是否参与后续所有帧（是 → 污染不可逆）
- **为什么**：用兜底值会把「数据坏了」伪装成正常值

### N-05 (P1) 位运算把 NaN 静默归零
- **正确**：`Number.isFinite(o.seed) ? o.seed >>> 0 : defaultSeed`
- **特征**：`>>> 0` / `| 0`
- **确认**：种子类参数是高危

### N-06 (P0) 循环上界来自入参且未收口
- **正确**：`clampNum(opts.n ?? 4, 1, 64)`
- **特征**：`for (let i = 0; i < <标识符>; i++)` 非字面量且附近无 clamp
- **确认**：是否来自配置/入参

### N-07 (P0) while 退出条件可被绕过
- **正确**：有限上界 + guard 计数器
- **特征**：`while` 体内 `*= 2` / `++` / `+=`，条件涉及 `Infinity` / `maxRadius` / `limit`

### N-08 (P0) while 做角度 / 周期归一化
- **正确**：**常数时间取模**并先拒非有限值
  ```typescript
  const norm = (a: number) => { const r = a % (Math.PI * 2); return r < 0 ? r + Math.PI * 2 : r; };
  ```
- **特征**：`while` 体内 `- 360` / `- 2*Math.PI`（单语句与带大括号两种形态都检）
- **失效**：`diff` 为 `Infinity` 时减 360 后仍为 `Infinity` → **永不退出**

### N-09 (P0) 循环变量可为 ±Infinity
- **正确**：上下界都收口为有限值
- **特征**：`for (let i = <非字面量>; i < <非字面量>; ...)` 附近无收口
- **失效**：`-Infinity + 1` 仍为 `-Infinity`
- **与 N-06 区别**：N-06 看上界，N-09 **同时看起始值**

### N-10 (P0) 收口函数缺 typeof 校验
- **正确**：`typeof v === 'number' ? ... : def`
- **特征**：`clampNum`/`numOr`/`needCount` 体内无 `typeof ... === 'number'`
- **为什么**：`Number(null)` → 0，缺失配置会**静默变成合法的 0 或下界**，
  改变超时/容量/速度语义且不报错
- **确认**：先判类型再判有限性；若在 `Number.isFinite` 之前已做了 `Number(v)` 转换则无效

### N-11 (P0) Infinity 当哨兵
- **正确**：空集用 `length === 0` 或 `null`
- **特征**：`= -Infinity` / `=== Infinity`
- **为什么**：±Infinity 是**合法数值**，当哨兵会把含合法极值的集合静默替换为 fallback

### N-12 (P0) Math.max/min 当守卫
- **正确**：`clampNum` 或先 `Number.isFinite`
- **特征**：`Math.max(数字, 变量)`
- **失效矩阵**：
  ```
  Math.max(1, NaN)       → NaN        （守卫失效）
  Math.max(1, Infinity)  → Infinity   （当数组尺寸会崩）
  Math.max(1, -5)        → 1          （只有这个符合预期）
  ```

### N-13 (P1) slice / splice 负数参数
- **正确**：数量参数先转有限非负整数
- **特征**：`.slice(` / `.splice(` 参数含变量
- **失效**：`slice(0, -1)` 不是「取 0 个」而是「去掉最后 1 个」，负数配置会反转语义
- **降级**：参数已在上游夹紧为非负 → 忽略

### N-14 (P0) 数值 op 未校验操作数类型
- **正确**：两个操作数都校验为有限 number
- **特征**：`case 'add'` / `case 'mul'` 内用 `+` / `*=` 无类型校验
- **失效**：`10 + '5'` → `'105'`（拼接）。`add` 是重灾区

### N-15 (P1) 展示层掩盖非有限值
- **正确**：不得用 `|| 0` / `?? 0` 掩盖 NaN，应显式标注或抛错
- **特征**：`display` / `format` / `render` 体内有 `|| 0` / `?? 0`
- **为什么有害**：一次坏输入永久污染该维度，而 UI 显示正常的 0，**故障被完全隐藏**

### N-16 (P0) 交易 / 批量数量未校验有限正整数
- **正确**：`Number.isInteger(n) && n > 0 && Number.isFinite(n)`
- **特征**：`buy` / `sell` / `craft` / `pullN` / `roll` / `simulate` / `prewarm` 的数量参数无双重校验
- **失效**：购买 `-2` 件 → `total = -20` → **钱包凭空增加 20、库存增加 2**，日志却记为成功
- **注意**：`<= 0` 挡不住 NaN，且必须**同时查整数性**

### N-17 (P1) 位宽计算溢出
- **正确**：`Math.pow(2, n) - 1`
- **特征**：`1 << n` 且 `n >= 31`

### N-18 (P1) 除法分母无零 / NaN 防护
- **正确**：`total > 0 ? v / total : 0`
- **特征**：`/ scale` 等且无零判定

### N-19 (P1) 硬编码时间源 / 随机源（确定性）
- **正确**：`interface Options { readonly now?: () => number; }`；随机源构造注入 `IRandomSource`
- **特征**：`Date.now()` / `performance.now()` / 裸 `Math.random()`
- **降级**：已有 `now?` 注入口 → 忽略
- **升级**：注释声称「只影响观感」但实际参与逻辑累积 → **P0**（错误注释会阻止修复）
- **注意**：只在确实是注入口（箭头函数/函数类型声明）时才跳过，
  `const now = Date.now();` 是硬编码取值，不算

---

## 验证方法

**写探针实测，不靠推理**。最小模板：

```bash
cp scripts/probe-template.ts audit/probe_<单元>.ts
npx tsc --outDir build --module commonjs --target ES2019 \
        --skipLibCheck --lib ES2019,DOM audit/probe_<单元>.ts
node build/audit/probe_<单元>.js
```

**每个数值入口至少喂这 9 个值**（速查卡：`assets/adversarial-inputs-card.md`）：

```
正常值 · 0 · 负数 · NaN · Infinity · -Infinity · undefined · null · 极大值
```

**NaN 与 Infinity 必须单独测** —— 只测 0 / 负数 / 正常值测不出这两类缺陷，
很多守卫对 0 和负数有效，唯独 NaN 绕过。

**探针得出反直觉结论时先修探针**：被测单元内部可能 clamp 了 dt；
注册顺序影响回调顺序。打印累计时间核对；显式控制注册顺序；每组用 `{}` 独立作用域。

## 修法

按族分文件，改哪个族读哪个：

| 族 | 文件 |
|---|---|
| 收口与守卫（N-01~05, 10~14, 16~18） | `s-numerics-fix.md` |
| 深层值域（N-06~09, 15, 19） | `s-numerics-fix-adv.md` |
| 对抗性输入详解 | `s-numerics-adversarial.md` |

## 常见误报

- **用了 `clampNum` / `numOr`** —— 内部有兜底，不穿透（N-03 明确降级）
- **该参数是常量 / 枚举** —— 不可能为 NaN，忽略（N-01）
- **字段非数值型** —— N-02 不适用
- **已有 `now?` 注入口** —— N-19 不适用
- **参数已在上游夹紧** —— N-13 / N-06 不适用
- **代码上有长注释解释为什么这么写** —— 先读注释（最高频误报来源）
