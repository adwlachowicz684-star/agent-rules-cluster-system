# 正确写法 · 数据族（I–O）

修 I–O 族缺陷时从这里取代码。A–H 族见 `fix-code-core.md`，P–W 族见 `fix-code-advanced.md`。

## I / J / K 族 · 资源、原子性、清理

```typescript
// 容量收口 + 裁剪
const limit = clampNum(opts.historyLimit ?? 50, 1, 500, 50);
if (this._history.length > limit) this._history.splice(0, this._history.length - limit);

// 先全量预检，再统一动账
exchange(from: string, to: string, amount: number): boolean {
  if (!this.has(from, amount)) return false;
  const got = this._convert(from, to, amount);
  if (!Number.isFinite(got)) return false;
  this._spend(from, amount);
  this._add(to, got);
  return true;
}

// 或捕获回滚
try { this._spend(from, amount); this._add(to, got); }
catch (e) { this._add(from, amount); throw e; }

// catch 必须记日志
catch (e) { this._log('warn', 'undo 失败', e); }

// 布尔状态必须能复位
this._degraded = true;   // 置 true 处须配对置 false

// clear/reset 覆盖全部容器
clear(): void {
  this._items.length = 0;
  this._cache.clear();     // 不要漏
}
```

## L / M / N / O 族 · 完整性与确定性

```typescript
// 空 if 块：补处理体或删除整个 if
if (this._onConflict === 'error') {
  throw new Error(`[X] 冲突: ${a} vs ${b}`);
}

// fail-closed（安全/经济/权限链路）
if (!this._evaluator) throw new Error('[X] 未注入 evaluator');

// 判定前校验
canUnlock(id: string): boolean {
  const bal = this._balance;
  if (!Number.isFinite(bal)) return false;   // 污染状态下不放行
  return bal >= cost;
}

// 时间源注入
export interface Options { readonly now?: () => number; }
private readonly _now: () => number;
constructor(opts: Options = {}) { this._now = opts.now ?? (() => Date.now()); }

// 随机源注入
constructor(rng: IRandomSource = MathRandomSource) { this._rng = rng; }

// 位宽
const max = Math.pow(2, bits) - 1;      // 不是 1 << bits

// 除法
const ratio = total > 0 ? value / total : 0;

// 返回副本
dump(attr: string): readonly Entry[] { return [...(this._map.get(attr) ?? [])]; }
```
