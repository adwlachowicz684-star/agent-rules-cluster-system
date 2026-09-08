# 精审报告 · event-bus

> 审计对象：`AI-cocos-` main 分支（2026-09-08 拉取），`event-bus/EventBus.ts` 176 行
> 基线：`tsc --noEmit` 0 错误；`npm test` 3697 项全过（其中 EventBus 组 16 项）
> 审查日期：2026-09-08
> 审查方式：通读源码 176 行 + 比对 README + 探针实测（2 组 34 项）
> 历史：round01 已覆盖（修 1 个缺陷），本轮为复核 + 深挖

---

## 结论

**核心实现是对的**——历史修复的两个缺陷（取消函数误删同名新监听器、默认值兜反）
实测确认已修好；快照遍历、once 语义、Set 去重、空集合回收、对抗性输入全部正确；
零依赖、README 与 API 完全一致。

**但发现一个根因性缺陷**：`off(name)` / `offAll()` / `destroy()` 只摘掉 Map 条目，
**不清空 Set 内容**。它同时造成两个后果——条件性内存泄漏，以及
「回调内取消单个监听器能拦住、整条 off 拦不住」的语义不一致（实测对比见下）。

修复成本极低（三处各加一行 `set.clear()`）。

| 等级 | 数量 |
|---|---|
| P0 | 0 |
| P1 | 1 |
| P2 | 3 |

---

## 问题

### [E-01] P1 — off / offAll / destroy 只摘 Map 条目，不清空 Set 内容

- 位置：`EventBus.ts:158-165`（`off` / `offAll`），`destroy` 调 `offAll` 因而同源

- 证据（探针 `audit/probe_eventbus2.ts` 实证 A/B）：

```
on 之后          _map.size=1  set.size=1
off(name) 之后   _map.size=0  set.size=1   ← Set 内容未清空

offAll 后  _map.size=0  setA=1 setB=1      ← 同样未清空
```

  语义不一致实测（实证 C）：

```
C1 回调内取消「单个」监听器 → 后续执行次数=0  ✓ 被拦住
C2 回调内 off(name) 整条清空 → 后续执行次数=1  ❌ 未被拦住
```

  C1 生效是因为取消函数走 `set.delete(fn)`，`emit` 里的 `set.has(fn)` 复查能拦住；
  C2 失效是因为 `off(name)` 根本没动 `set` 的内容，复查自然拦不住。

- 后果：

  **① 内存（条件性泄漏）** —— Set 仍持有全部监听器，而 `on` 返回的取消函数闭包
  持有该 Set。只要调用方还持有任何一个 `off`（组件里存着待销毁时调是常态），
  整个 Set 及其中的所有监听器闭包就无法 GC。

  典型场景：全局 bus 调 `destroy()` 清空，但某个仍存活的组件持有 `off`
  → 该组件订阅时捕获的外部引用（节点、数据、闭包链）全部滞留。

  **② 语义不一致** —— 同样是"在回调里取消掉还没执行的监听器"，
  单个取消能拦住，整条 `off(name)` 拦不住。用户若在回调里用 `off(name)`
  表达"紧急停止本轮广播"，后续监听器仍会执行，且不报任何错。

- 建议（三处，均可直接粘贴）：

```typescript
  /** 移除某个事件的所有监听器 */
  off<K extends keyof Events>(name: K): void {
    // 【为什么必须先 clear 再 delete】
    // 只 delete 会让 Set 变成孤儿但仍持有全部监听器：
    // ① 取消函数闭包持有该 Set → 监听器无法 GC（条件性泄漏）
    // ② emit 的 set.has 复查失效 → "整条 off 拦不住本轮"（与单个取消不一致）
    const set = this._map.get(name);
    if (set) set.clear();
    this._map.delete(name);
  }

  /** 移除所有监听器（destroy 时调用） */
  offAll(): void {
    for (const set of this._map.values()) set.clear();
    this._map.clear();
  }
```

- 影响面：`destroy()` 调 `offAll()`，修 `offAll` 即覆盖。
  `on` 返回的取消函数已经正确处理（`set.delete` + `=== set` 校验），无需改。

---

### [E-02] P2 — 无重入保护，同事件递归 emit 无深度上限

- 位置：`EventBus.ts:138-155`

- 证据（实证 E）：

```
同事件递归 emit 深度=5（无深度上限，互递归会栈溢出）
```

  监听器内再次 `emit` 同一事件，会重新取快照并执行——包括那个会再次 emit 的监听器。
  A → emit A → A → emit A …… 直到爆栈。

- 后果：两个监听器互相 emit 对方（或通过中介形成环）时栈溢出崩溃，
  且调用栈被重复帧填满，难以定位源头。

- 建议：与 README「不适合严格顺序依赖」的立场一致，
  可以不加防护，但**README 的「坑」小节应写明**：
  监听器内不得 emit 同一事件，否则无限递归。
  若要防护，`emit` 内加 `_emitting: Set<keyof Events>` 重入集合，
  重入时直接 return 或抛错。

- 影响面：仅本文件。

---

### [E-03] P2 — console.* 硬编码 3 处，未走 logger 注入

- 位置：`EventBus.ts:89`（on trace）、`142`（emit trace）、`152`（catch 输出）

- 证据：扫描命中 O03 × 3。

```
if (this._opts.trace) console.log(`[EventBus] +on ...`);
if (this._opts.trace) console.log(`[EventBus] emit ...`);
console.error(`[EventBus] 监听器执行出错 (${String(name)}):`, e);
```

- 后果：宿主无法接管日志（分级、上报、静音）；
  `swallowErrors: true` 时监听器异常只写 console，生产环境看不到。
  库里已有 `logger` 单元可用。

- 建议：把 `onError?: (e: unknown, name: keyof Events) => void`
  加进 `EventBusOptions`，默认实现走 `console.error`；
  trace 的两处改成 `onTrace?` 回调。保持默认行为不变，向后兼容。

- 影响面：**全库共性问题**（O03 全库 41 处），本单元 3 处。
  建议作为独立议题统一处理，不在此单元单独立项。

---

### [E-04] P2 — `on(name, fn)` 无运行时 fn 类型校验

- 位置：`EventBus.ts:81-87`

- 证据：`set.add(fn as Handler<never>)` 不校验 `typeof fn === 'function'`。
  传 `null` / `undefined`（仅 `as any` 绕过类型系统时可发生）不会在注册时报错，
  而是在 `emit` 时抛 `TypeError: fn is not a function`，
  被 `swallowErrors: true` 吞掉并 console.error。

- 后果：错误延迟到 emit 才暴露，且被吞掉后表现为"这个监听器没执行"，
  排查成本高。症状与 E-01 的"监听器莫名其妙不触发"相似，容易混淆。

- 建议：注册时加一行校验，让错误在订阅点就炸：

```typescript
  if (typeof fn !== 'function') {
    throw new TypeError(`[EventBus] 监听器必须是函数，收到 ${typeof fn} (${String(name)})`);
  }
```

- 影响面：`once` 经 `on` 注册，自动覆盖。优先级低——TypeScript 类型系统
  已在编译期挡住绝大多数情况，仅 `as any` 绕过时可触发。

---

## 验证过没问题的部分（避免重复报）

按 skill 要求逐项实测确认，以下均已通过，**不要再报**：

| 项 | 结果 |
|---|---|
| **历史已修：取消函数误删同名新监听器** | ✅ 实测复现确认已修（off(name)→on→off1()→f2 仍触发） |
| **历史已修：不传 opts 时默认值兜底** | ✅ 实测：不传 opts 时 swallowErrors 为 true，异常不抛出、后续监听器正常 |
| 快照遍历安全（遍历中取消/新增） | ✅ 本轮新增的监听器本次不收到；取消不越界 |
| once 语义 | ✅ 只触发一次、触发后自动清理、重复 off 不复活、未触发即 off 则不执行 |
| Set 去重 | ✅ 同引用只注册一次；不同箭头函数不去重 |
| 空集合回收 | ✅ 最后一个取消会摘掉整条 map 条目；部分取消不会误摘 |
| 对抗性输入 · 事件名 | ✅ `__proto__` / `constructor` / `toString` 作事件名均安全（Map 不查原型链） |
| 对抗性输入 · payload | ✅ `undefined` / `NaN` / `Infinity` 均不抛错 |
| 未注册事件 | ✅ `emit` / `off` / `has` 均不抛错 |
| destroy 幂等 | ✅ 重复调用安全 |
| listenerCount / has 一致性 | ✅ 取消与 off(name) 后计数均正确 |
| destroy 无 `_destroyed` 标记 | ⚪ 非缺陷——README 明确 destroy 语义是"清空"，之后可继续注册，行为与文档一致 |
| 依赖合规 | ✅ 零 import，零依赖，可独立拷贝 |
| README 与 API 一致性 | ✅ 8 个 API 全部对上，无签名漂移 |
| 三件套 | ✅ README + 测试（run_core 16 项）+ 示例（basic-usage）齐全 |

---

## 全局议题

**E-01 是「删容器不清内容」，与既有 Q03「空桶不回收」是反向同类问题。**

历史 batch1 提过：`SpatialHash` 空桶不回收（删元素后不删空容器）→ 已沉淀为 Q03。
本次发现的是反向：删容器（`_map.delete`）时不清理容器内容（`set.clear()`）。

建议 skill 补一条模式（暂定 Q04）：

> **Q04 容器摘除未清内容** — 正确：删除 `Map<K, Set<V>>` 条目时先 `set.clear()`；
> 特征：`_map.delete(k)` / `map.clear()` 附近无 `clear()`；
> 确认：是否有闭包持有该容器（返回的取消函数、迭代器、缓存）。

全库可用该模式回归一次——凡 `Map<K, Set<V>>` 且返回取消函数的单元
（`signal`、`observable`、`reddot` 等）都值得查。

---

## 复现脚本

```
audit/probe_eventbus.ts    34 项 · 历史修复复核 + 边界 + 对抗性输入（29 通过 / 0 失败）
audit/probe_eventbus2.ts   5 组实证 · E-01 E-02 的直接证据
```

运行：

```bash
tsc --outDir audit/build --module commonjs --target ES2019 \
    --skipLibCheck --lib ES2019,DOM audit/probe_eventbus.ts
node audit/build/audit/probe_eventbus.js
```
