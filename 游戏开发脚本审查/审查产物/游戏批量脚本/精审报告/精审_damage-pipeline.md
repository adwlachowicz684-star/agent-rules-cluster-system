# 精审报告 · damage-pipeline

> 审查方式：通读源码（3 文件 548 行）+ 逐条比对 README + 写探针实测（10 组）
> 审查日期：2026-09-07
> 结论：**代码可放心用的核心是对的，问题集中在边界守卫和文档漂移**

---

## 一、致命（必修）

### C1 · `onResult` 回调内取消订阅会吞掉下一个订阅者

**位置**：`DamagePipeline.ts:155`

```typescript
this._listeners.forEach((fn) => fn(result, ctx, target));
```

`forEach` + 回调内 `splice` 的经典组合：删掉索引 i 后，原索引 i+1 的元素前移到 i，而 `forEach` 的游标已经走到 i+1 —— **它被跳过了**。

**实测**（三个订阅者 A/B/C，A 在回调里调自己的退订函数）：

```
期望 A/B/C 都执行，实际: ["A","C"]     ← B 静默丢失
```

**为什么危险**：飘字、音效、打击感、统计、成就通常各自订阅一次。只要有一个在回调里退订（"这次播完就不再播了"是很自然的写法），另一个就永久失效，**不报错、无日志**。

**修法**（二选一）：

```typescript
// ① 遍历副本（最省事，推荐）
[...this._listeners].forEach((fn) => fn(result, ctx, target));

// ② 倒序索引遍历（无额外分配）
for (let i = this._listeners.length - 1; i >= 0; i--) {
  this._listeners[i](result, ctx, target);
}
```

---

### C2 · 自定义 stage 返回 NaN → 出口无守卫，血量永久变 NaN

**位置**：`DamagePipeline.ts:112-115`

入口第 96 行有 `Number.isFinite(ctx.raw)` 守卫，但 stage 循环之后、取整之前**没有任何守卫**。

**实测**（插入一个 `() => NaN` 的 stage）：

```
value: NaN
```

`apply()` 会把它写进 `target.hp` → 角色血量永久 NaN → 血条消失。

**最讽刺的一点**：入口那段注释恰好写明了这条危害——

> `raw = NaN` 一路穿过所有 stage、取整、保底，最终写进 target.hp。一次 `undefined` 参与运算就能让角色血量永久变成 NaN——不报错，症状是「血条消失」

但只堵了入口，没堵出口。自定义 stage 里一次 `undefined` 字段运算就能复现同样的症状。

**修法**：

```typescript
for (const s of this._stages) {
  const next = s.fn(value, ctx, target);
  // 精确定位到是哪个 stage 出问题
  if (!Number.isFinite(next)) {
    // 建议：走 logger 或 console.warn，别静默
    value = 0;
    break;
  }
  value = next;
  if (s.record) stages.push({ name: s.name, value });
}
```

---

## 二、高危

### C3 · `hitId` 声明了，但管线完全不做去重 —— README 却说"用 hitId 去重"

**位置**：`IDamageable.ts:51` 声明；`DamagePipeline.ts` 全文**没有一行读 `ctx.hitId`**

**实测**（同 `hitId` 打 3 次）：

```
同 hitId 打 3 次后扣血: 30     ← 一次都没挡
```

README 的坑表写的是：

> **多段伤害没去重** → 一刀秒杀 Boss。用 `hitId` + 已命中集合

实际上去重是在**上层**各自实现的：`skill-caster`（`c.hitIds`）、`projectile`（`p.hitIds`）、`hitbox` 的注释示例。分层上这合理，但 `DamagePipeline` 的文档把责任推给了一个**它自己不提供的能力**。

**危害**：照 README 以为 `apply()` 自带幂等，直接踩"一刀秒杀 Boss"。

**修法**：文档改口径，明确写"`hitId` 只是透传字段，去重由调用方维护已命中集合（见 `skill-caster` / `projectile`）"；或者给 `DamagePipelineOptions` 加一个可选的 `dedupe?: boolean` 内部维护 `Set<string>`。

---

### C4 · `Modifier.get` 的 NaN 缓存守卫是死代码

**位置**：`Modifier.ts:116`

```typescript
if (cached !== undefined && cached !== Number.NaN && this._baseMatch(attr, base))
```

**`NaN !== NaN` 恒为 true**（NaN 不等于任何值，包括它自己）。这个条件永远成立，等于没写。

> 注：编译器抓不到它 —— TS 的 TS2845 只对 `NaN` **字面量**比较报警，写 `Number.NaN` 就绕过去了。源码 `npm run typecheck` 实测通过，EXIT=0。

**实测**：

```
加 NaN 后 get(atk,10): NaN
再 get(atk,10): NaN          ← 被缓存住了
```

**修法**：

```typescript
if (cached !== undefined && !Number.isNaN(cached) && this._baseMatch(attr, base))
```

更根本的做法是在源头拦：`add()` 里校验 `Number.isFinite(entry.value)`，脏数据不许进。

---

## 三、中危（文档漂移，照抄会崩）

### C5 · README §ModifierSet 整节签名与源码不符

| README 写的 | 源码实际 | 实测 |
|---|---|---|
| `add(attr, entry)` 返回**移除函数** | `add(...): void` | 返回 `undefined` |
| `remove(attr, id)` 按 id 移除 | `remove(attr, predicate: (e) => boolean): number` | 传字符串 → `TypeError: predicate is not a function` |

而且 README 专门用一段 ⚠️ 警告：

> **`add` 返回的移除函数优先于 `remove(id)`**
> 闭包捕获了确切的那一条，不会误删；`remove(id)` 在 id 重复时会删错对象，而这种重复**不报错**

—— 这是在警告一个**不存在的问题**。源码的谓词版 `remove` 恰恰修掉了"删错对象"（谓词可以精确匹配引用）。文档没说清真实签名，却在警告虚构的缺陷。

**另**：`removeBySource` / `clearByTag` / `clearTagEverywhere` / `count` / `dump` / `clear` 签名与文档一致 ✓；`dump()` 返回内部引用那条警告**是准确的** ✓。

**修法**：整节按源码重写，把谓词签名和"返回移除数量"写进去。

### C6 · 章节标题写"同文件的第二个类"，实际是两个文件

README §`### ModifierSet（同文件的第二个类）` —— `ModifierSet` 在 `Modifier.ts`，`DamagePipeline` 在 `DamagePipeline.ts`。

---

## 四、低危

| # | 问题 | 说明 |
|---|---|---|
| L1 | `simulate` 无随机性 | 纯函数 + 固定 ctx → 实测 `[20,20,20,20,20]`。用它"验证 DPS 期望"必须调用方每轮自己重掷 `crit`。文档示例 `for(10000次) calculate({raw:20})` 会得到 10000 个 20。**不是 bug，但极易误用** |
| L2 | `critMul` 无 clamp | `critMul=-1` → `value:0` 且被判 `immune:true`；`critMul=NaN` → NaN 穿透（C2 的子类，但**不需要自定义 stage 就能构造**） |
| L3 | `destroy()` 无状态标记 | 销毁后仍可 `addStage` / `apply`，不报错。同类库通常加 `_destroyed` 并早退 |
| L4 | `removeStage` 只删第一个同名 | `addStage` 允许重名（无去重、无警告），两个同名 stage 时删不干净 |
| L5 | `DamageContext` 可变性不一致 | `raw/type/source/meta` 是 `readonly`，`crit/critMul/armorPen/resistPen/part/hitId` 可变。注释说"crit 由暴击判定阶段填写"，但**没有内置暴击判定 stage**，实际是调用方填 |

---

## 五、验证过没问题的部分（这些坑已经修好了）

| 检查项 | 结果 |
|---|---|
| 免疫判定在取整**之前** | ✅ 实测 stage 给 0.02 → `value:1, immune:false`（历史 bug 已修） |
| 护甲用**除法**不用减法 | ✅ `v * (100/(100+armor))` |
| 护甲穿透 `clamp01` | ✅ 注释提到的"破甲点成负数敌人护甲翻倍"已修 |
| 抗性 clamp 到 `[-1, 0.9]` | ✅ 上限 < 1，不会无敌 |
| 抗性穿透只削弱正抗性 | ✅ `resist > 0 ? resist * (1-pen) : resist` |
| 入口 NaN 守卫 | ✅ `!Number.isFinite(ctx.raw)` |
| 最低伤害保底 | ✅ raw>0 且非免疫且 < min → 补到 min |
| 真实伤害 `'true'` 无视抗性与护甲 | ✅ 两个 stage 都提前 return |
| 零引擎依赖 | ✅ 只 import `../_core/math` |
| 文件名唯一 | ✅ 全库 208 个 .ts 零重名 |

---

## 六、一个结构性发现

**`damage-pipeline` 目录里没有任何自己的测试文件**（`tests/` 下 grep 无结果），只有 `examples/batch8-usage.ts` 里被间接用到。

上面 6 个缺陷全部处于"无单测覆盖"状态。对全库自称最值钱、所有游戏都用得上的插件来说，这与其地位不匹配。建议优先补：

1. `onResult` 多订阅者 + 回调内退订
2. stage 返回 NaN / Infinity
3. `Modifier` 的 `add` / `remove` 签名（照 README 写会崩）
4. `simulate` 的确定性

---

## 附：探针脚本位置

`/data/workspace/audit/probe.ts`（10 组，全部可复现）
运行：`tsc --ignoreConfig --outDir build ... && node build/audit/probe.js`
