# 正确写法 · 核心族（A–H）

修 A–H 族缺陷时从这里取代码。I–O 族见 `fix-code-data.md`，P–W 族见 `fix-code-advanced.md`。

## A 族 · 数值收口

```typescript
// 守卫：用 !(x > 0) 同时挡 NaN / 负数 / 0
if (!(interval > 0)) throw new Error(`[X] 间隔必须是正有限数: ${interval}`);
if (!Number.isFinite(v)) return;

// 配置收口
const n = clampNum(opts.x, 0, 1e6, 50);        // 有显式上下界
const n = numOr(opts.x, 50);                    // 只需挡非法值
const octaves = needCount(opts.octaves ?? 4, 'opts.octaves', 64);

// clamp 不挡 NaN —— 入参来自外部时必须前置
const v = Number.isFinite(raw) ? clamp(raw, 0, 1) : DEFAULT;

// 累加 / EMA：脏样本丢弃，不要兜底
const p = computePerformance();
if (!Number.isFinite(p)) return;                // 这一帧不更新
this._smooth = lerp(this._smooth, p, 0.1);

// 种子：显式校验后再取位
const seed = Number.isFinite(opts.seed) ? opts.seed >>> 0 : defaultSeed;
```

## B 族 · 循环与递归

```typescript
// 上界收口
const n = Math.min(Math.max(1, Math.floor(opts.n ?? 4)), 64);
for (let i = 0; i < n; i++) { /* ... */ }

// while 双重保险
let guard = 0;
while (radius < maxRadius && guard++ < 64) { radius *= 2; /* ... */ }
if (guard >= 64) this._log('warn', 'radius 搜索未收敛');

// 递归传访问集
function roll(id: string, visiting = new Set<string>()): Result {
  if (visiting.has(id)) throw new Error(`[X] 循环引用: ${id}`);
  visiting.add(id);
  try { /* ... */ } finally { visiting.delete(id); }
}
```

## C 族 · 原型链安全

```typescript
// 查表三选一
const TABLE = new Map<string, T>();                    // 推荐
const TABLE: Record<string, T> = Object.create(null);
if (Object.prototype.hasOwnProperty.call(TABLE, k)) { }

// 累加
const tally = new Map<string, number>();
tally.set(k, (tally.get(k) ?? 0) + 1);

// 合并外部 JSON
for (const [k, v] of Object.entries(parsed)) {
  if (k === '__proto__' || k === 'constructor' || k === 'prototype') continue;
  target[k] = v;
}
```

## D 族 · 死契约

```typescript
// 接口字段：要么实现它，要么连同 README/JSDoc 声明一起删
// 参数：要么用起来，要么删
register(type: string, fn: Handler, overwrite = false): void {
  if (!overwrite && this._map.has(type)) {
    throw new Error(`[X] 重复注册: ${type}`);
  }
  this._map.set(type, fn);
}
```

## E 族 · 遍历安全

```typescript
[...this._listeners].forEach(fn => fn(result));          // 快照（推荐）
for (let i = arr.length - 1; i >= 0; i--) arr[i]();      // 倒序
for (const t of snapshot) { if (t.dead) continue; t.fn(); }  // 标记删除

// 注册返回唯一句柄，取消按句柄定位
on(fn: Handler): () => void {
  const id = this._nextId++;
  this._map.set(id, fn);
  return () => { this._map.delete(id); };
}
```

## F / G / H 族 · 入口校验对齐

```typescript
// 抽公共归一化，所有入口共用（含 import）
private _normalize(raw: Raw): Entry {
  return {
    ...raw,
    remain: clampNum(raw.remain, 0, 1e9, 0),
    stacks: clampNum(raw.stacks, 1, 99, 1),
  };
}
add(raw: Raw)          { this._set(this._normalize(raw)); }
import(list: Raw[])    { for (const r of list) this._set(this._normalize(r)); }
```

```typescript
// 多订阅者
private readonly _handlers = new Set<Handler>();
on(fn: Handler): () => void {
  this._handlers.add(fn);
  return () => { this._handlers.delete(fn); };
}
```

**规律**：后加的便捷入口（`import` / `snapTo` / `upgrade` / `evaluate`）最容易漏校验。
修的时候抽一个公共归一化函数，让所有入口都过它。

## destroy 幂等（通用）

```typescript
private _destroyed = false;

destroy(): void {
  if (this._destroyed) return;
  this._destroyed = true;
  this._tasks.clear();
  this._listeners.clear();
}

private _assertAlive(): void {
  if (this._destroyed) throw new Error('[X] 实例已销毁');
}
update(): void { this._assertAlive(); /* ... */ }
```

## 补测写法

```typescript
// 好：失败时一眼看出期望
test('repeat(NaN) 应拒绝注册，而非每帧执行', () => {
  const s = new Scheduler();
  let n = 0;
  s.repeat(NaN, () => n++);
  for (let i = 0; i < 5; i++) s.update(0.1);
  eq(n, 0, 'NaN 间隔不得执行');
});

// 坏：失败时不知道哪里错
test('scheduler repeat', () => { ... assert(n); });
```

**每个数值入口补九类**：正常值、0、负数、NaN、Infinity、null、''、小数、超大有限值。
