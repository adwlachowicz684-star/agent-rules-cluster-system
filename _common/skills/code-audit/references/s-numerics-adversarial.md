# 对抗性输入详解

速查卡见 `assets/adversarial-inputs-card.md`（写探针时对照）。
本文件解释**为什么**要测这九类，以及复现脚本怎么写。

## 核心事实

某 119 单元库 `npm test` 3,451/3,451 全绿，人工精审仍发现 39 个 P0。
原因是现有用例只覆盖正常路径，**没有覆盖对抗性边界**。

所以审查时不要只看「有没有测试」，要看「测试覆盖了哪些输入」。

## 九类输入

| # | 输入 | 期望行为 |
|---|---|---|
| 1 | `NaN` | 拒绝或收口，**不得静默穿透** |
| 2 | `Infinity` / `-Infinity` | 拒绝（绝不能当循环上界、数组尺寸） |
| 3 | `null` / `undefined` | 走 fallback 或抛错，**不得被 `Number()` 变成 0** |
| 4 | `''` / 空白串 | 同上 |
| 5 | 负数 | 明确拒绝或明确支持，不得反向操作（如负数量购买变增钱） |
| 6 | 小数 | 要求整数处必须拒绝 |
| 7 | 原型键：`__proto__` / `constructor` / `toString` / `valueOf` / `hasOwnProperty` | 查表/写入必须当作**普通不存在的键**处理 |
| 8 | 含分隔符的动态键：`'a.b'` / `'a,b'` / `'a|b'` | 路径与复合 key 必须能正确往返 |
| 9 | 超大有限值（如 `1e9`） | 容量/尺寸类必须有上限并拒绝 |

## 按入口类型的对照表

| 入口类型 | 必须拒绝 | 特别检查 |
|---|---|---|
| 循环上界（count/times/octaves/samples） | NaN / Infinity / 负数 | Infinity 会**挂死主线程** |
| 数组 / TypedArray 尺寸 | NaN / Infinity / 小数 / 负数 / 超大有限值 | 底层 `RangeError` 或瞬时 OOM |
| 交易数量（buy/sell/craft 的 quantity） | 非整数 / 非正数 / NaN | 负数会**反向增钱** |
| 时间（dt / duration） | NaN / 负数 / Infinity | dt=0 要能正确处理（不要污染速度） |
| 质量 / 分母 | 0 / NaN | 除零产生 Infinity 坐标 |
| 配置数值 | NaN / Infinity / null / '' | `??` 挡不住 NaN，需用 `clampNum` |
| 外部键（表名/状态名/指标名/事件名） | 原型键 | 用 `Map` 或 `Object.hasOwn` |
| 路径（JSON Patch / 点分路径） | `__proto__` 段 | 写入前过滤危险段 |
| 复合 key | 含分隔符的值 | 长度前缀编码或结构化 tuple |

## 两个反直觉的陷阱

### 陷阱一：Math.max / Math.min 不是有效的收口手段

```typescript
Math.max(1, NaN)       // NaN      —— 最常见的一种"写了守卫但没用"
Math.max(1, Infinity)  // Infinity  —— 拿它当数组尺寸会崩
Math.max(1, -5)        // 1        —— 只有这个是符合预期的
```

正确做法：`clampNum(x, min, max, def)` 或先 `Number.isFinite(x)`。

### 陷阱二：0 和负数往往安全，唯独 NaN 失效

以 `historyLimit` 为例：

```typescript
if (this._history.length > limit) this._history.splice(0, ...);
// limit = 0    → length>0 为真 → 会裁剪 → 安全
// limit = -1   → 同上          → 安全
// limit = NaN  → NaN 比较恒 false → 永不裁剪 → 无限增长
```

**所以只测 0 / 负数 / 正常值测不出 NaN 类缺陷。** 每个数值入口都要单独加一条 NaN 用例。

## 复现脚本的写法

把每个可疑行为写成独立 probe，输出结构化结果：

```javascript
const rows = [];
function probe(name, fn) {
  try {
    rows.push({ name, result: fn() });
  } catch (error) {
    rows.push({ name, threw: String(error && error.message || error) });
  }
}

probe('core.invalid-coercion', () => ({
  clampNull: math.clampNum(null, 1, 9, 7),   // 期望 7，实际 1
  numEmpty:  math.numOr('', 7),               // 期望 7，实际 0
}));
probe('shop.negative-quantity', () => {
  const s = new Shop();
  s.defineItem({ id: 'potion', basePrice: 10 });
  s.stock('potion', 5);
  const wallet = { gold: 0 };
  const result = s.buy('potion', -2, wallet);
  return { result, wallet, stock: s.stockOf('potion') };
});

// 输出时把非有限数与函数序列化成可读字符串，否则 JSON.stringify 会丢信息
console.log(JSON.stringify(rows, (_k, v) => {
  if (typeof v === 'number' && !Number.isFinite(v)) return String(v);
  if (typeof v === 'function') return `[Function ${v.name || 'anonymous'}]`;
  return v;
}, 2));
```

**要点**：

- 每个 probe 独立 try/catch，一个崩溃不影响其他
- 序列化时特殊处理 `NaN`/`Infinity`/函数（`JSON.stringify` 默认会把 NaN 变成 null，丢掉关键信息）
- 异步 probe 要 await 后再统一输出
- 污染类 probe 测完要 `delete Object.prototype.xxx` 清理

## 污染类测试的清理

```javascript
probe('snapshot.prototype-pollution', () => {
  snapshot.applyPatch({}, { set: { '__proto__.snapshotPolluted': true }, remove: [] });
  const polluted = ({}).snapshotPolluted;
  delete Object.prototype.snapshotPolluted;   // 必须清理，否则污染后续 probe
  return polluted;
});
```

不清理会污染同一进程内的其他测试，产生假阳性/假阴性。

## 审查时的用法

1. 拿到一个单元，先列出它所有的**公开入口**
2. 对每个入口，按九类输入逐一问「传进去会怎样」
3. 把答案未知或可疑的写成 probe 跑一遍
4. 能复现的就定级入报告

不要靠推理下结论 —— 推理在这类问题上错得很多。
