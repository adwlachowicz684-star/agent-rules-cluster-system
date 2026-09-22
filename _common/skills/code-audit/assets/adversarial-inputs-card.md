# 对抗性输入速查卡

写探针时对照本表，逐项问「传进去会怎样」。**贴在手边，不要凭记忆。**

## 九类必测输入

```
NaN          → 守卫绕过（x <= 0 恒 false）、clamp 穿透、>>> 0 变 0
Infinity     → 循环挂死、数组 OOM、哨兵冲突
-Infinity    → 自增后仍为 -Infinity，循环永不退出
null         → Number(null) = 0，配置静默变成 0 或下界
undefined    → ?? 能挡，但 NaN 不能
''           → Number('') = 0
负数          → 交易反向增钱、slice 变「去掉末尾 n 个」
小数          → 要求整数处必须拒绝
原型键         → __proto__ / constructor / toString / valueOf / hasOwnProperty
含分隔符的键    → 'a.b' / 'a,b' / 'a|b'（路径与复合 key 往返）
超大有限值      → 1e9 容量类必须有上限并拒绝
```

## 两个反直觉陷阱

```
Math.max(1, NaN)       → NaN       守卫失效
Math.max(1, Infinity)  → Infinity  拿去当数组尺寸会崩
Math.max(1, -5)        → 1         只有这个符合预期

historyLimit = 0       → 安全（length > 0 为真，会裁剪）
historyLimit = -1      → 安全（同上）
historyLimit = NaN     → NaN 比较恒 false，永不裁剪，无限增长
```

**推论**：只测 0 / 负数 / 正常值测不出 NaN 类缺陷。NaN 必须单独立用例。

## 按入口类型的必拒绝清单

| 入口 | 必须拒绝 |
|---|---|
| 循环上界 | NaN / Infinity / 负数 |
| 数组尺寸 | NaN / Infinity / 小数 / 负数 / 超大有限值 |
| 交易数量 | 非整数 / 非正数 / NaN |
| 时间（dt/duration） | NaN / 负数 / Infinity |
| 质量 / 分母 | 0 / NaN |
| 配置数值 | NaN / Infinity / null / '' |
| 外部键 | 原型键 |
| 路径 | `__proto__` 段 |
| 复合 key | 含分隔符的值 |

## 探针序列化注意

`JSON.stringify` 会把 `NaN` / `Infinity` 变成 `null`，函数直接丢弃 ——
**关键信息会静默丢失**。必须自定义 replacer：

```javascript
console.log(JSON.stringify(rows, (_k, v) => {
  if (typeof v === 'number' && !Number.isFinite(v)) return String(v);
  if (typeof v === 'function') return `[Function ${v.name || 'anonymous'}]`;
  return v;
}, 2));
```

## 污染类 probe 必须清理

```javascript
probe('snapshot.prototype-pollution', () => {
  snapshot.applyPatch({}, { set: { '__proto__.polluted': true }, remove: [] });
  const p = ({}).polluted;
  delete Object.prototype.polluted;   // 不清理会污染同进程其他测试
  return p;
});
```
