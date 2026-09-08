# 精审报告 · rng

> 审计对象：`AI-cocos-` main 分支（2026-09-08 拉取）
> `rng/RNG.ts` 148 行 + `rng/Seed.ts` 106 行 = 254 行
> 基线：`tsc --noEmit` 0 错误；`npm test` 3697 项全过
> 审查日期：2026-09-08
> 审查方式：通读源码 254 行 + 比对 README + 探针实测（2 组，含 10 万次分布检验）
> 历史：round01 已覆盖（修 1 个 `sample` 缺陷，留 4 项"仅报告"）

---

## 结论

**算法层完全正确**——mulberry32 实现、Fisher-Yates 无偏性（实测 3000 次洗牌首元素分布
731/756/762/751）、10 万次 `next()` 十分位分布均匀、`gaussian` 均值 −0.0049、
10000 次 `fork()` 零碰撞、可复现性成立。核心承诺守住了。

**问题集中在参数校验与文档**：4 个数值入口对 NaN/Infinity/负数/大小倒置全部放行，
其中 `rangeInt(5, 1)` 的真实危害不是"越界"而是**端点丢失**（实测值域只剩 3/5 档，
1 和 5 永远取不到）——历史 round01 报的是"静默返回区间外的数"，方向有偏差，本轮修正。

| 等级 | 数量 |
|---|---|
| P0 | 0 |
| P1 | 2 |
| P2 | 4 |

---

## 问题

### [R-01] P1 — `rangeInt(min, max)` 在 min > max 时静默丢端点

- 位置：`RNG.ts:66-68`

- 证据（探针 `audit/probe_rng2.ts` 实证 A）：

```
rangeInt(5,1) 5000 次的值域 = [2, 3, 4]
期望值域 = [1, 2, 3, 4, 5]
→ 实际只得到 3/5 个值，缺失 1, 5
→ 分布本应均匀 5 档，实际被压缩到 3 档
```

  推导：`rangeInt(5,1)` = `floor(range(5, 2))` = `floor(5 + r*(2−5))`，
  r∈[0,1) → 结果落在 (2, 5] → floor 后 2..4（5 仅在 r=0 时出现，概率趋 0）。

- 后果：**不越界、不报错、不抛异常**——只是永久取不到 min 和 max 两个端点。
  典型触发：`rangeInt(lo, hi)` 里 lo/hi 来自配置或计算（如 `level-5, level+5` 算反了），
  或 `count - alreadyPicked` 类算式。
  表现为"这个宝箱从来不掉最高档""这把武器永远不出满攻"，
  且因为**输出仍在合理区间内**，几乎不可能被怀疑到 RNG。

  历史 round01 报的是"静默返回区间外的数"，实测**不越界**——危害描述需修正为"丢端点"。

- 建议：

```typescript
  /** [min, max] 区间整数（含两端） */
  rangeInt(min: number, max: number): number {
    // 参数顺序写反是常见笔误，且 min/max 常常是算出来的。
    // 不校验的话不会越界也不会报错，只是**永久取不到两个端点**——
    // 实测 rangeInt(5,1) 的值域只剩 [2,3,4]，1 和 5 永远出不来。
    // 这种"仍在合理区间内"的静默错误最难查，必须在这里挡住。
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      throw new RangeError(`[RNG] rangeInt 收到非有限值: min=${min} max=${max}`);
    }
    const lo = Math.min(min, max);
    const hi = Math.max(min, max);
    return Math.floor(this.range(lo, hi + 1));
  }
```

  若不希望抛错（热路径），至少在注释里写明"调用方必须保证 min ≤ max"。

- 影响面：`range(min, max)` 同族，但它是浮点区间，min>max 时语义是"反向区间"，
  危害小得多；`int(n)` 见 R-02。

---

### [R-02] P1 — `int(n)` 无校验，负数/NaN/Infinity 全部放行

- 位置：`RNG.ts:71-73`

- 证据（实证 B）：

```
int(0)        = 0
int(-5)       = -1       ← 返回负数
int(NaN)      = NaN
int(Infinity) = Infinity
```

  `int(-5)` 返回 −1 后，`pick(arr)` 走到 `arr[-1]` → `undefined`。
  而 `pick` 的签名是 `T | undefined`，**调用方无法区分"空数组"和"n 为负"**，
  两者都拿到 `undefined`。

- 后果：`arr.length - k` 算出负数（`k` 常来自配置或已选数量）时，
  `pick` 静默返回 `undefined`，调用方若不解空会走兜底分支或直接崩。
  NaN/Infinity 同理，且 NaN 会继续污染下游运算。

- 建议：

```typescript
  /** [0, n) 整数 */
  int(n: number): number {
    // n 常常是算出来的（如 arr.length - picked），减出负数或 NaN 是常事。
    // 放行会让 pick() 走到 arr[-1] → undefined，而 pick 的签名本来就用
    // undefined 表示"空数组"，调用方无从区分。
    if (!Number.isFinite(n) || n <= 0) return 0;
    return Math.floor(this.next() * n);
  }
```

  `n <= 0` 返回 0 而不是抛错：调用方用 `int(count)` 表达"取 0 个"是合理用法，
  抛错会打断正常流程。

- 影响面：`pick` / `sample` / `shuffle` / `fork` 内部都调 `int`，
  修一处全部受益。

---

### [R-03] P2 — `state` setter 把 NaN 静默变成 0，与构造函数保护不一致

- 位置：`RNG.ts:47-49`（setter）对比 `:38-39`（构造函数）

- 证据（实证 E）：

```
模拟损坏：state = Number(undefined) = NaN → 实际存为 0
模拟损坏：state = Number('abc')     = NaN → 实际存为 0
→ 构造函数对 0 有保护（换成 0x9e3779b9），setter 没有 → 行为不一致
```

  构造函数：`this._s = seed >>> 0; if (this._s === 0) this._s = 0x9e3779b9;`
  setter：`this._s = v >>> 0;`（无 0 保护）

- 后果：存档读取时若 `state` 字段损坏（JSON 里存成 `null`、`"abc"`、缺字段），
  `>>> 0` 一律变 0。**所有损坏的存档收敛到同一个种子**，
  玩家会反馈"读档后地图全都一样"，而没有任何报错。

  严重度定 P2 而非 P1：实测 `state = 0` 后 `next()` 未卡住
  （`next()` 内先做 `_s = (_s + 0x6d2b79f5) >>> 0`，会自动离开 0），
  所以不会死循环，只影响"损坏存档的一致性"。

- 建议：setter 复用与构造函数相同的保护：

```typescript
  set state(v: number) {
    this._s = v >>> 0;
    if (this._s === 0) this._s = 0x9e3779b9; // 与构造函数保持一致
  }
```

  更彻底的做法是让 setter 拒绝非有限值，但那会让"存档损坏"变成抛错，
  是否接受取决于调用方——建议至少保持一致。

- 影响面：仅本文件。

---

### [R-04] P2 — `gaussian` 的 mean / stdDev 无校验

- 位置：`RNG.ts:127-133`

- 证据（实证 C）：

```
gaussian(NaN, 1) = NaN    ← NaN 直接穿透
gaussian(0, NaN) = NaN    ← NaN 直接穿透
gaussian(0, -1)  = 0.049  ← 负标准差：数学合法但语义可疑
gaussian(0, 0)   = 0      ← 恒等于 mean
```

  与 R-01/R-02 同族：NaN 穿透后污染下游（最终表现为属性变 NaN → 血条消失）。

- 后果：mean/stdDev 常来自配置（如"敌人攻击力 ±15%"），
  一个字段写错就是 NaN 扩散。

- 建议：入口收口。stdDev 为负建议取绝对值或直接拒绝：

```typescript
  gaussian(mean = 0, stdDev = 1): number {
    const m = Number.isFinite(mean) ? mean : 0;
    const sd = Number.isFinite(stdDev) ? Math.abs(stdDev) : 1;
    ...
  }
```

- 影响面：仅本方法。

---

### [R-05] P2 — `fork()` 消耗父流状态，README 未说明

- 位置：`RNG.ts:145-147`；README `:98`

- 证据（实证 D）：

```
fork 前  state = 7
fork 1 后 state = 1831565820   ← 父流被消耗
fork 2 后 state = 3663131633   ← 继续消耗
两次 fork 子流是否相同：不同（正确）
```

  `fork()` 内部 `new RNG(this.int(0xffffffff))` 调用了 `this.next()`，
  必然推进父流。

- 后果：**这是必要行为**（不消耗的话连续 fork 会得到同一个子流），
  但 README 只说"派生独立子流，互不干扰"，未提"会消耗父流一个值"。
  用户若在 fork 前后依赖父流确定性（如"先 fork 三个子系统，再用父流做主逻辑"），
  会因不知道消耗顺序而算错存档回放。

- 建议：README 补一句：

  > `fork()` 会消耗父流一个随机数（否则连续 fork 会得到同一子流）。
  > 因此**必须先 fork 完所有子系统，再使用父流**。

- 影响面：文档问题，代码行为正确。

---

### [R-06] P2 — `RNG` 未 `implements IRandomSource`

- 位置：`RNG.ts:32`

- 证据：`_core/types.ts:224` 定义了 `IRandomSource { next(): number }`，
  但 `export class RNG {` 未声明实现，仅靠结构兼容。

- 后果：缺少编译期保障。若将来改 `next()` 签名（如加参数），
  所有依赖 `IRandomSource` 的调用点不会报错，只在运行时失效。

- 建议：加一行 `implements IRandomSource`。
  注意 `_core/types.ts:210` 的注释明确说明 `_core` **不能** import `rng`
  （会造成反向依赖），所以是 `rng` 单向 import `_core`——方向正确，可以安全加。

- 影响面：仅本文件，改动一行。

---

## 历史 round01 遗留项复核

| 历史项 | 状态 | 本轮结论 |
|---|---|---|
| `sample(arr,-1)` 返回几乎整个数组 | ✅ **已修** | 实测 `sample([1..5],-1)` → `[]`；`Math.max(0, ...)` 生效 |
| `Seed.daily()` 只有 3200 个桶 | ⚠️ **需修正描述** | `daily()` 返回 32 位，**不受 CAPACITY 约束**，直接喂 RNG 无碰撞问题。只有"用 `encode()` 分享每日种子"时才折叠——实测 365 天折叠后有 13 天重复（约 3.6%）。见下节 |
| `Seed.random()` 用 `Math.random` | ⚠️ **可接受** | 生成种子本身不需要复现，且与头注释"禁止 Math.random"的建议确实矛盾。实测 32000 次生成覆盖全部 3200 桶，分布均匀（min=1 max=22，期望≈10） |
| `RNG` 未 `implements IRandomSource` | ⏳ **未修** | 见 R-06 |
| `rangeInt(5,1)` 静默返回区间外 | ⚠️ **描述有偏差** | 实测**不越界**，真实危害是**丢端点**（值域只剩 3/5 档）。见 R-01 |

### `daily` 折叠的实际风险（补充历史结论）

```
daily() 返回 32 位 → 直接喂 RNG：无碰撞
若经 encode() 分享：365 天中 13 天会撞（约 3.6%）
```

历史建议"给 daily 单独一条不受 CAPACITY 约束的通路"——
**代码本来就是这样的**（`daily` 直接返回 `h >>> 0`）。
真正的风险只在调用方用 `Seed.encode(Seed.daily(d))` 分享时。
建议 README 的 `daily` 行补一句：不要 encode 它的结果，直接把数字喂 RNG。

---

## 验证过没问题的部分（避免重复报）

| 项 | 结果 |
|---|---|
| mulberry32 实现 | ✅ 与标准一致 |
| 可复现性 | ✅ 同种子同序列（50 项逐一比对） |
| `next()` 分布 | ✅ 10 万次十分位 9785~10195（期望 10000），全部落在 [0,1) |
| `next()` 周期 | ✅ 前 20 万次未重现首值 |
| Fisher-Yates 无偏 | ✅ 4 元素 × 3000 次，首元素 731/756/762/751 |
| `shuffle` 保持元素集合 | ✅ |
| `gaussian` 有限性 | ✅ 1000 次全部有限，均值 −0.0049 |
| `gaussian` 的 u/v 非零循环 | ✅ `while (u === 0)` / `while (v === 0)` 正确 |
| `fork()` 零碰撞 | ✅ 10000 次 fork 去重 10000 |
| `fork()` 可复现 | ✅ 同种子 fork 得同子流 |
| 种子 0 / 负数 / 超 2^32 | ✅ 均可用，未卡住 |
| `sample` 边界 | ✅ −1/−100 → 空；n>长度 → 全部 |
| `pick` 空数组 | ✅ 返回 undefined |
| Seed 编解码往返 | ✅ 0..3199 全部一致 |
| Seed 大数字有损 | ✅ 符合文档声明（`decode(encode(4294967295))=895`） |
| Seed 非法输入 | ✅ 空串/无校验位/未知词/三位校验 → null；大小写容错 |
| `daily` 确定性 | ✅ 同日期同值，不同日期不同值 |
| `daily` 时区语义 | ✅ offset 只影响"算哪一天"，UTC 23:00 时 offset=8 已算次日 |
| 依赖合规 | ✅ 零 import（除 `_core` 的类型，且为单向） |
| 三件套 | ✅ README + 测试 + 示例齐全 |

---

## 全局议题

**R-01 / R-02 / R-04 是同一个根因：数值入口无收口。**

这与全库 A02（520 处）、A01（215 处）是同一族问题在 `rng` 单元的具体实例。
`rng` 的特殊性在于：**它是全库随机性的源头，一个 NaN 从这里扩散到所有下游单元**
（地图生成、掉落、AI 抖动、属性波动），且因为输出"看起来仍是随机数"而极难定位。

建议把 `rng` 的数值收口作为 A 族修复的**首个试点**——
改动集中在 3 个方法，收益覆盖全库。

---

## 复现脚本

```
audit/probe_rng.ts    12 组 · 历史修复复核 + 可复现性 + 10 万次分布检验
audit/probe_rng2.ts   7 组实证 · R-01 ~ R-05 的直接证据
```

运行：

```bash
tsc --outDir audit/build --module commonjs --target ES2019 \
    --skipLibCheck --lib ES2019,DOM audit/probe_rng.ts
node audit/build/audit/probe_rng.js
```
