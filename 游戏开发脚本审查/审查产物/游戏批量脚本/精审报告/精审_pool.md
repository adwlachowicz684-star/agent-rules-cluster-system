# 精审报告 · pool

> 审计对象：`AI-cocos-` main 分支（2026-09-08 拉取），`pool/Pool.ts` 275 行
> 基线：`tsc --noEmit` 0 错误；`npm test` 3697 项全过
> 审查日期：2026-09-08
> 审查方式：通读源码 275 行 + 比对 README + 探针实测（2 组 26 项 + 4 组实证）
> 历史：round01 已覆盖（修 1 个 `active` 变负缺陷，留 3 项"仅报告"）

---

## 结论

**核心机制正确**——历史修复的 `active` 变负已实测确认修好（destroy→put 不再为负），
重复归还拦截有效（同引用只入池一次）、复用时 `onGet` 正常重置、
`clear`/`destroy` 语义与文档一致、`prewarm` 的 Infinity/NaN OOM 风险已被 `needCount` 收口。

**但"泄漏检测唯一指标 `active`"仍然会说谎**，且有两条历史未修的路径 + 一条新路径：

- 配置侧：`maxSize` 传 NaN → 池彻底退化为工厂（100 轮 get/put 创建了 100 个对象）
- 调用侧：`put()` 无归属校验 → 外部对象也能扣 `active`，**实测可被"刷"成 0**
- 异常侧：`onGet` / `onPut` 抛异常 → 对象永久丢失，计数永久错乱

其中 **`put()` 无归属校验是本轮新发现**，且它比历史修掉的"active 变负"更隐蔽——
因为 0 看起来完全正常。

| 等级 | 数量 |
|---|---|
| P0 | 1 |
| P1 | 2 |
| P2 | 2 |

---

## 问题

### [PL-01] P0 — `put()` 无归属校验：任意对象都能归还，`active` 可被刷成 0

- 位置：`Pool.ts:178-225`（`put`），关键行 `:211`

- 证据（探针 `audit/probe_pool2.ts` 实证 A）：

```
借出 3 个后                          active = 3
put 5 个外部对象后                   active = 0
  → 那 3 个真实借出的对象根本没还
归还真实 3 个后                      active = 0
  → 全程恒为 0
```

  `put()` 对 `obj` 只做一件事：判断它是否**已在空闲池**（`_inIdle.has`）。
  这个判定查的是"是否已空闲"，方向与"是否来自本池"**相反**。
  `active` 的扣减是无条件的：

```typescript
    this.active = Math.max(0, this.active - 1);   // :211 —— 不在任何 if 内
```

- 后果：`active` 是源码注释自己写明的**"泄漏检测的唯一指标"**（`:95`、`:207`）。
  任何外部对象（另一个池的对象、手写的 mock、误传的 `{}`）都能把它扣下去。
  实测中真实借出 3 个未归还，指标却显示 0——**比历史修掉的"变负"更隐蔽，
  因为 0 看起来完全正常，而负数至少会让人起疑。**

  常见触发：复制粘贴时 `bulletPool.put(enemy)`、单元测试传 mock、
  或对象在两个池之间流动（`putAll` 混入非本池元素）。

- 建议：借出时无条件登记，归还时校验：

```typescript
  // get() 里：无条件登记（原来只在 trackLeaks 时记 _out）
  private readonly _borrowed = new Set<T>();

  get(): T {
    const obj = this._idle.length > 0 ? this._idle.pop()! : this._createNew();
    this._inIdle?.delete(obj);
    this._borrowed.add(obj);          // ← 新增：无条件登记
    this.active++;
    ...
  }

  put(obj: T): void {
    // 归属校验：不是从这里借出的，直接拒绝并警告
    if (!this._borrowed.delete(obj)) {
      if (this._warnDup) {
        console.warn('[Pool] 归还了非本池借出的对象，已忽略。');
      }
      return;
    }
    if (this._trackLeaks) this._out.delete(obj);
    this.active = Math.max(0, this.active - 1);
    ...
  }
```

  **注意顺序**：先 `_borrowed.delete(obj)` 成功才扣 `active`，
  这样 `active` 恒等于"真实借出未归还数"。

  若担心 `Set` 开销（文档已声明 `guardDuplicate` 的 Set 是可接受的），
  可与 `_inIdle` 合并考虑，或复用现有的 `_out`（把它从"仅 trackLeaks"改为默认登记，
  `dump()` 时才决定是否记录 stack）。

- 影响面：`putAll` 经 `put` 实现，自动覆盖。

- **已沉淀为 skill 模式**：Q04「对象池缺归属校验」此前只检测
  `prewarm` 上界与 `active` 下限，**归属校验这一半从未实现**（本轮补全）。
  判据从"有没有 `has()`"改为"**扣减是否无条件**"——
  因为重复归还拦截也用 `has()`，按前者判会漏掉（实测踩过）。

---

### [PL-02] P1 — `maxSize` 无收口，NaN 让池彻底退化为工厂

- 位置：`Pool.ts:111`（`this._maxSize = opts.maxSize ?? 1000`）

- 证据（实证 B）：

```
maxSize=NaN，100 轮 get/put：
  created = 100      ← 每次都在新建
  idle    = 0        ← 从不复用
对照 maxSize=1000：
  created = 1
```

  `??` 只挡 `undefined`，不挡 NaN。`_idle.length < NaN` 恒为 false（`:220`），
  于是**每一次 `put` 都走"超容丢弃"分支**。

- 后果：池静默失效——功能完全正确，但**零复用、持续新建对象**。
  在子弹/粒子池上就是持续的 GC 压力，表现为周期性卡顿。
  无任何报错、无警告，`created` 会一直涨（唯一线索，但没人会盯着它看）。

- 建议：

```typescript
    this._maxSize = clampNum(opts.maxSize, 0, 1e6, 1000);
```

  （`clampNum` 在 `_core/math.ts`，非有限值走 fallback。）

- 影响面：仅构造函数一行。历史 round01 已列为"仅报告"，本轮仍未修。

---

### [PL-03] P1 — `onGet` / `onPut` 抛异常 → 对象永久丢失 + 计数永久错乱

- 位置：`Pool.ts:174`（`_onGet?.(obj)`）与 `:218`（`_onPut?.(obj)`）

- 证据（实证 C）：

```
基线：get+put 后                    active/idle = 0/1

onGet 抛 5 次：                     active/idle = 5/0
  → 5 个对象已出池、已从 idle 摘除，却从未交付调用方 → 永久丢失
  → 而 active 虚高 5（这 5 个永远不会被归还，指标永远降不回来）

onPut 抛 5 次：                     active/idle = 0/0
  → 借出 5 个、全部"归还"失败，active 应为 5，实为 0
  → 对象同样丢失，且计数少 5
```

  两处都是**先改状态、再调钩子**，钩子一抛就留下不一致。
  `onPut` 这条历史 round01 已列为"仅报告"，本轮仍未修；
  **`onGet` 这条是本轮新发现的镜像问题**（历史报告只提了 `onPut`）。

- 后果：`active` 是泄漏检测的唯一指标，一旦虚高或少计就**永久错乱**
  （除非 `destroy()`）。异常虽然会冒给调用方，但"池已损坏"这件事没有任何信号。

- 建议：用 `try/finally` 保证账本完成：

```typescript
  get(): T {
    const obj = this._idle.length > 0 ? this._idle.pop()! : this._createNew();
    this._inIdle?.delete(obj);
    try {
      this._onGet?.(obj);          // 抛出时对象已被借出，账本保持"借出"状态是诚实的
    } catch (e) {
      // 选择：① 记入 borrowed 后抛出（active 正确，对象确实丢了）
      //       ② 归还进池后抛出（对象不丢，但语义是"取用失败"）
      this._borrowed?.add(obj);
      this.active++;
      throw e;
    }
    this._borrowed?.add(obj);
    this.active++;
    ...
  }
```

  `put()` 同理：把 `this.active = Math.max(0, ...)` 与入池放进 `finally`，
  确保即使 `_onPut` 抛出，对象也进池（或至少计数正确）。

- 影响面：两处方法。优先级低于 PL-01/PL-02——需要钩子抛异常才触发。

---

### [PL-04] P2 — `dump()` 硬编码 `Date.now()`，时间源不可注入

- 位置：`Pool.ts:168`（`time: Date.now()`）、`:255`（`const now = Date.now()`）

- 证据：扫描命中 N01 × 2。

- 后果：泄漏判定阈值基于真实时间，**单测只能真 `sleep`**，
  无法构造"已借出 10 秒"的确定性场景。与全库铁律（时间源可注入）不一致。

- 建议：与 `scheduler` 单元一致，加可选注入口：

```typescript
  constructor(create, onGet, onPut, opts = {}, now: () => number = Date.now) { ... }
```

  或在 `PoolOptions` 加 `readonly now?: () => number`（默认 `Date.now`）。

- 影响面：仅 `dump` 与泄漏追踪；不影响池的核心行为。全库 N01 共 23 处，属共性议题。

---

### [PL-05] P2 — `console.warn` 硬编码

- 位置：`Pool.ts:191`（重复归还警告）

- 证据：扫描命中 O03。

- 后果：宿主无法接管日志（分级、上报、静音）。

- 建议：加 `onWarn?: (msg: string) => void` 选项，默认 `console.warn`。

- 影响面：**全库共性问题**（O03 全库 41 处），建议作为独立议题统一处理。

---

## 历史 round01 遗留项复核

| 历史项 | 状态 | 本轮结论 |
|---|---|---|
| `active` 被减成负数 | ✅ **已修** | 实测 `get×2 → destroy → put×2` → `active === 0`；`Math.max(0, ...)` 生效 |
| `maxSize` 无有限性校验，NaN → 池静默失效 | ⏳ **未修** | 见 PL-02。实测 confirmed：100 轮 get/put 创建 100 个对象 |
| `prewarm(n)` 不受 `maxSize` 限制 | ✅ **已解决（且是设计契约）** | 源码 `:121-144` 有长注释说明：曾误夹到 `maxSize`，已回退。既有测试断言 `prewarm(20)` 配 `maxSize:3` → `idle === 20`，实测通过。**且 OOM 风险已由 `needCount` 收口**——实测 `prewarm(Infinity)` / `(NaN)` → TypeError，`(-1)` / `(1e9)` → RangeError |
| `put` 里先 `active--` 再 `_onPut`，`_onPut` 抛异常留不一致 | ⏳ **未修** | 见 PL-03。并新发现镜像问题 `onGet` 抛异常 |

---

## 验证过没问题的部分（避免重复报）

| 项 | 结果 |
|---|---|
| `active` 不变负 | ✅ destroy→put 实测为 0 |
| 重复归还拦截 | ✅ 同引用第二次 put 被忽略，`idle` 保持 1 |
| 复用时 `onGet` 重置 | ✅ 引用相同、`onGet` 被调用、状态被重置 |
| `created` 统计 | ✅ 正常池 100 轮只创建 1 个 |
| `prewarm` 上界 | ✅ Infinity/NaN → TypeError；−1/1e9 → RangeError；无 OOM |
| `prewarm` 不被 `maxSize` 截断 | ✅ 符合既有契约（注释+测试双重确认） |
| `clear()` 只清空闲、不动 `active` | ✅ 借出的仍在外部，语义正确 |
| `destroy()` 幂等 | ✅ 重复调用安全，清空 `_out` |
| `destroy` 无 `_destroyed` 标记 | ⚪ 非缺陷——README 明确 destroy 语义是"清空"，之后可继续 get/put |
| `guardDuplicate:false` 时两相同引用入池 | ✅ 符合文档声明（文档已警告"两颗子弹一起飞"） |
| `Pool<number>` 两个 0 被当同一对象 | ✅ 符合文档声明（文档已警告装原始值无意义） |
| `putAll([x,y,x])` 去重 | ✅ 第三个 x 被拦截，`idle=2` |
| `trackLeaks` 的 `_out` 记账 | ✅ get 记入、put 移除、destroy 清空 |
| 依赖合规 | ✅ 仅 import `_core/guard`，合规 |
| 三件套 | ✅ README + 测试 + 示例齐全 |

---

## 全局议题

**PL-01 与 PL-03 指向同一件事：计数型字段必须与"真实状态"绑定，不能靠无条件自增/自减。**

`active` 目前是纯计数器（get+1 / put−1），三个方向都能说谎：
外部对象（PL-01）、钩子抛异常（PL-03）、destroy 后归还（历史已修，靠 `Math.max(0,...)` 兜住）。

根治办法是把它变成**派生值**而非计数器：

```typescript
get active(): number { return this._borrowed.size; }
```

这样它不可能与真实状态不一致。代价是每次读都要 `Set.size`（O(1)，可忽略）。
同类问题在全库所有"计数型字段"上都值得查（历史 batch1 提过 `Pool.active` 被减成负数，
并提示"任何计数型字段（泄漏检测的命脉）都要查是否可能变负"）。

---

## 复现脚本

```
audit/probe_pool.ts    12 组 26 项 · 历史修复复核 + 边界 + 语义
audit/probe_pool2.ts    4 组实证 · PL-01 / PL-02 / PL-03 的直接证据
```

运行：

```bash
tsc --outDir audit/build --module commonjs --target ES2019 \
    --skipLibCheck --lib ES2019,DOM audit/probe_pool2.ts
node audit/build/audit/probe_pool2.js
```
