# 正确写法 · 进阶族（P–W）

修 P–W 族缺陷时从这里取代码。A–H 族见 `fix-code-core.md`，I–O 族见 `fix-code-data.md`，X–Y 族见 `fix-code-lifecycle.md`。

## P 族 · 值域与类型收口

```typescript
// 收口函数：先判类型，再判有限性
function clampNum(v: unknown, min: number, max: number, def: number): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) return def;
  return v < min ? min : (v > max ? max : v);
}

// 空集判定：用 length，不用 ±Infinity 哨兵
function maxOf(xs: number[], def: number): number {
  if (xs.length === 0) return def;
  let m = xs[0];
  for (let i = 1; i < xs.length; i++) if (xs[i] > m) m = xs[i];
  return m;                                    // 合法极值原样返回
}

// 不要用 Math.max 收口
const n = clampNum(opts.count ?? 4, 1, 64, 4);

// 数量先转有限非负整数
const k = Math.max(0, Math.floor(numOr(opts.n, 0)));

// 数值 op：两个操作数都要校验
case 'add': {
  if (typeof oldVal !== 'number' || typeof p.value !== 'number'
      || !Number.isFinite(oldVal) || !Number.isFinite(p.value)) {
    throw new Error('[Patch] add 的两个操作数必须是有限 number');
  }
  return oldVal + p.value;                     // 避免 "10" + "5" = "105"
}
```

## Q 族 · 内存分配与数据结构

```typescript
// 尺寸收口 + 总量上限
const w = clampNum(opts.width, 1, 4096, 64);
const h = clampNum(opts.height, 1, 4096, 64);
if (w * h > 4_000_000) throw new Error(`[X] 尺寸过大: ${w}x${h}`);
const data = new Float32Array(w * h);

// 惰性删除：维护有效计数
class LazyHeap<T> {
  private _live = 0;
  get size() { return this._live; }             // 不是物理条目数
  get isEmpty() { return this._live === 0; }
  remove(h: Handle) {
    if (!h || h.removed) return;
    h.removed = true; this._live--;              // 幂等
  }
}

// 空桶回收
remove(id: number): void {
  const bucket = this._cells.get(this._keyOf(id));
  if (!bucket) return;
  bucket.delete(id);
  if (bucket.size === 0) this._cells.delete(this._keyOf(id));   // 关键
}

// 对象池归属 + 容量
class Pool<T> {
  private readonly _out = new Set<T>();
  get active() { return this._out.size; }        // 不可能为负
  release(o: T): void {
    if (!this._out.has(o)) return;               // 拒绝 foreign put
    this._out.delete(o); this._idle.push(o);
  }
  prewarm(n: number): void {
    const k = clampNum(n, 0, 10_000, 0);         // 有限整数上限
    for (let i = 0; i < k; i++) this._idle.push(this._create());
  }
}

// 循环归约，不用 spread
let m = xs[0];
for (let i = 1; i < xs.length; i++) if (xs[i] > m) m = xs[i];
```

## R 族 · 路径与 key 编码

```typescript
// 路径写入：拒绝危险段
const DANGER = new Set(['__proto__', 'prototype', 'constructor']);
function setByPath(root: unknown, parts: Array<string | number>, value: unknown): void {
  let cur: any = root;
  for (const p of parts) {
    if (typeof p === 'string' && DANGER.has(p)) {
      throw new Error(`[Patch] 非法路径段: ${p}`);
    }
    cur = cur[p];
  }
}

// 批量删除：同层按索引降序
const byParent = groupBy(removals, r => r.parent);
for (const group of byParent) {
  group.sort((a, b) => b.index - a.index);      // 降序
  for (const r of group) arr.splice(r.index, 1);
}

// 可逆路径协议：JSON Pointer（RFC 6901），~1 转义 / ，~0 转义 ~
function escapeToken(s: string): string {
  return s.replace(/~/g, '~0').replace(/\//g, '~1');
}
const pointer = parts.map(p => '/' + escapeToken(String(p))).join('');

// 复合 key：长度前缀编码，杜绝碰撞
function makeKey(id: string, tags: Record<string, string>): string {
  const parts = [String(id.length) + ':' + id];
  for (const k of Object.keys(tags).sort()) {
    parts.push(String(k.length) + ':' + k, String(tags[k].length) + ':' + tags[k]);
  }
  return parts.join('');
}
```

## S 族 · 安全默认值

```typescript
export interface Options { readonly enabled?: boolean; }
constructor(opts: Options = {}) {
  this._enabled = opts.enabled ?? false;        // 默认 false
}
execute(cmd: string): void {
  if (!this._enabled) throw new Error('[X] 未启用');
}

// 生产构建加固
if (process.env.NODE_ENV === 'production' && this._enabled) {
  throw new Error('[X] 生产构建不得启用调试/作弊功能');
}
```

## T 族 · 角度与周期归一化

```typescript
// 常数时间取模，先拒非有限
function normalizeAngle(a: number): number {
  if (!Number.isFinite(a)) throw new Error('[X] 角度必须有限');
  const r = a % (Math.PI * 2);
  return r < 0 ? r + Math.PI * 2 : r;
}
// 禁止 while (diff > PI) diff -= 2 * PI;

// 循环上下界都要收口
const from = clampNum(opts.from, -1e6, 1e6, 0);
const to   = clampNum(opts.to,   -1e6, 1e6, 0);
for (let i = from; i < to; i++) { /* ... */ }
```

## U 族 · 展示层

```typescript
// 不要掩盖损坏值
display(id: string): string {
  const raw = this._raw(id);
  if (!Number.isFinite(raw)) return '—';        // 或抛错，不要返回 0
  return format(raw);
}
```

## W 族 · 交易与批量数量

```typescript
function assertPositiveInt(n: number, field: string): number {
  if (!Number.isFinite(n) || !Number.isInteger(n) || n <= 0) {
    throw new Error(`[X] ${field} 必须是正整数: ${n}`);
  }
  return Math.min(n, MAX_BATCH);
}

buy(id: string, quantity: number, wallet: Wallet): TradeResult {
  const n = assertPositiveInt(quantity, 'quantity');   // 负数被挡住
  const total = this._totalPriceOf(id, n);
  if (!Number.isFinite(total)) return { ok: false, reason: 'bad_price' };
  if (!this._canAfford(wallet, total)) return { ok: false, reason: 'poor' };
  // 全部预检通过后才动账
}
```
