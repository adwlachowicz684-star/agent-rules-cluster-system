# 精审报告 · scheduler（Scheduler + TimeScale）

> 审查日期：2026-09-07
> 审查方式：通读源码（2 文件 561 行）+ 比对 README + 3 轮探针实测（S1~S12，含 1 轮纠错重测）
> 单元地位：**全库最关键插件**（README 自述"没有之一"），是"真暂停的唯一实现路径"

---

## 结论先行

**核心时间语义是对的，而且做得相当扎实**——真暂停、双通道、dt clamp、长期无漂移，这几个最容易翻车的点全部实测通过。

问题集中在**参数校验的 NaN 缺口**和**时间源不可注入**上。没有致命缺陷。

| 等级 | 数量 |
|---|---|
| 致命 | 0 |
| 高危 | 4 |
| 中危 | 2 |
| 低危 | 2 |

---

## 一、高危

### H1 · `repeat(NaN, fn)` 退化为「每帧执行且永不停止」

**位置**：`Scheduler.ts:249`

```typescript
repeat(interval: number, fn: TickCallback, times = Infinity): () => void {
    if (interval <= 0) throw new Error(`[Scheduler] 间隔必须为正: ${interval}`);
```

**`NaN <= 0` 恒为 false**，NaN 参数绕过全部校验。

**实测**：

```
repeat(NaN, fn) 未抛错
5 帧内执行次数: 5      ← 每帧一次，永不停止
```

**根因链路**：
1. `interval = NaN` → `_add(fn, false, NaN, NaN, times)`
2. `task.remaining > 0` → `NaN > 0` = **false** → 不跳过，立即执行
3. `task.interval !== null` → `NaN !== null` = true → 走重复分支
4. `task.remaining = NaN + NaN = NaN` → 下帧重复

**危害**：一个配置字段缺失（`interval: undefined` → 运算得 NaN）就会让定时任务变成每帧执行。表现是"某个技能每帧触发一次"，而**没有任何报错**。

**修法**：

```typescript
if (!Number.isFinite(interval) || interval <= 0) {
  throw new Error(`[Scheduler] 间隔必须是有限正数: ${interval}`);
}
```

---

### H2 · `delay(NaN, fn)` 立即执行一次

**位置**：`Scheduler.ts:232`

```typescript
if (seconds < 0) throw new Error(...)   // NaN < 0 = false，绕过
```

**实测**：

```
delay(NaN, fn) 未抛错
3 帧内执行次数: 1      ← 期望 0
```

`remaining = NaN` → `NaN > 0` = false → 不等待，直接执行。

**危害**：延时逻辑静默失效（"3 秒后生成 Boss"变成"下一帧生成"）。

**修法**：同 H1，补 `Number.isFinite`。

> 注：`delay(-1)` 实测**正确抛错** ✓，说明校验意图是对的，只是漏了 NaN 这一支。

---

### H3 · Scheduler 吞掉了 TimeScale 的时间源注入能力

**位置**：`Scheduler.ts:130`

```typescript
this.timeScale.update(Date.now());     // ← 硬编码，无注入点
```

而 `TimeScale` 自己**明明设计了注入**：

```typescript
add(id, scale, durationSeconds?, now = Date.now())   // TimeScale.ts:92
update(now = Date.now())                              // TimeScale.ts:148
```

TimeScale 的注释还专门写了理由：

> `@param now 真实时间戳（毫秒）。由外部传入而非内部取 Date.now()，是为了可测试性——单测里能精确控制"时间"。`

**但 Scheduler 没把这个口子透出来。**

**实测**（快速循环模拟 2 秒游戏时间，真实耗时 <1ms）：

```
刚 hitStop 后 value: 0.05
跑完 2 秒游戏时间后 value: 0.05      ← 期望回到 1
layerCount: 1                        ← 期望 0，顿帧层没过期
```

因为 `Date.now()` 在微秒级的循环里几乎没变，顿帧**永不过期**。

**三重危害**：
1. **单测不可控**：验证顿帧必须真的 `sleep(80ms)`，测试变慢且 flaky
2. **违背本库铁律 2**（依赖注入）：需要外部能力时由调用方传入，内部不得去"找"
3. **确定性回放不可能**：录制的输入序列无法复现时间缩放行为

**修法**：

```typescript
export interface SchedulerOptions extends TimeScaleOptions {
  readonly maxDeltaTime?: number;
  /** 时间源（毫秒）。默认 Date.now，测试时可注入假时钟 */
  readonly now?: () => number;
}

// constructor
this._now = opts.now ?? (() => Date.now());

// update 中
this.timeScale.update(this._now());

// hitStop / slowMotion 也要透传
hitStop(durationSeconds = 0.08, scale = 0.05): void {
  this.timeScale.add('hitstop', scale, durationSeconds, this._now());
}
```

---

### H4 · `repeat(interval, fn, times = 0)` 执行 1 次，期望 0 次

**位置**：`Scheduler.ts:182-190`

**实测**：

| 调用 | 期望 | 实际 |
|---|---|---|
| `repeat(0.5, fn, 0)` | 0 | **1** ❌ |
| `repeat(0.5, fn, 1)` | 1 | 1 ✓ |
| `repeat(0.5, fn, 3)` | 3 | 3 ✓ |
| `repeat(0.5, fn, 5)` | 5 | 5 ✓ |

**根因**：`times` 的递减判定在**执行之后**：

```typescript
task.fn(delta);                    // ← 先执行了
if (task.interval !== null) {
  if (task.times !== Infinity) {
    task.times--;
    if (task.times <= 0) { 删除; continue; }
  }
  ...
}
```

`times = 0` 时不满足 `!== Infinity`，递减成 -1，才判定 `<= 0` 删除——但 `fn` 已经跑过了。

**修法**：注册时拦截。

```typescript
repeat(interval: number, fn: TickCallback, times = Infinity): () => void {
  if (!Number.isFinite(interval) || interval <= 0) throw ...;
  if (times <= 0) return () => {};      // ← 返回空取消函数，不注册
  return this._add(fn, false, interval, interval, times);
}
```

---

## 二、中危

### M1 · `delay(Infinity, fn)` 静默永不触发

`Infinity < 0` = false → 不抛错 → `remaining = Infinity` → 永远不执行。

**实测**：`delay(Infinity)` 未抛错。

语义上"无限延迟 = 永不执行"说得通，但静默挂起比报错更难查。建议：显式拒绝 `Infinity`，或在 README 写明这是合法用法。

### M2 · `destroy()` 无状态标记，销毁后仍可注册并执行

**实测**：

```
destroy 后新任务执行次数: 2      ← 期望 0 或报错
taskCount: 1                      ← 复活了
```

与 damage-pipeline 的 L3 同类。全库 52 个有 `destroy()` 的文件里 **51 个没有状态标记**（见跨切面扫描）。

---

## 三、低危

| # | 问题 | 实测 |
|---|---|---|
| L1 | 首次触发有 ≤ `maxDt`(0.1s) 的偏移 | 前 6 次触发 `[0.6, 1.1, 1.6, 2.1, 2.6, 3.1]`，理想 `[0.5, 1.0, ...]`。**但间隔精确 0.5，无累积漂移** ✓ —— 浮点使 `0.5 - 0.1×5 = 1.4e-17 > 0`，多花一帧 |
| L2 | README 自相矛盾 | 第 8 行批判"偷偷用 `Date.now()`"，而 `Scheduler.update()` 内部就在用（`Scheduler.ts:130`）。用途不同（层过期确需真实时间线），但至少该在文档里说明为什么这里可以用 |

---

## 四、验证过没问题的部分（这些是最容易翻车的，全部通过）

| 检查项 | 实测 |
|---|---|
| **真暂停**：scale=0 时受缩放任务完全不推进 | ✅ 暂停前 n=3，暂停中 5 帧仍 n=3，**d 累积也完全冻结** |
| **unscaled 通道**在暂停时仍走 | ✅ 3 帧 + 暂停 5 帧 = 8 次，正确 |
| **`maxDeltaTime` clamp** | ✅ `dt=10` → 回调收到 `0.1` |
| **脏 dt 防护** | ✅ `dt=-5` → 0；`dt=NaN` → 0；`dt=Infinity` → 0 |
| **长期无漂移** | ✅ 100 次触发，间隔精确 0.5，最大偏差 0.1（仅首帧偏移，不累积） |
| **回调中新增任务** | ✅ 延迟到下一帧执行（避免同帧递归），符合设计 |
| **回调中取消待执行任务** | ✅ `dead` 标记生效，被取消的任务不再执行 |
| **TimeScale 多层相乘** | ✅ `0.05 × 0.5 = 0.025` |
| **TimeScale suspend / resume** | ✅ 挂起后 value 回到 0.5 |
| **TimeScale 到期清理** | ✅ `update(1000+80)` 后 hitstop 层移除，layerCount=1 |
| **顿帧期间游戏时间按 scale 推进** | ✅ `0.1 × 0.05 = 0.005` |
| **`delay(-1)` 参数校验** | ✅ 正确抛错 |
| **依赖合规** | ✅ 只依赖 `_core/types` + 同目录 `TimeScale`，零横向依赖 |

---

## 五、给 TimeScale 单独记一笔

`TimeScale` 本身质量很高：

- 多层独立记录、相乘合成 —— 解决了"顿帧结束该恢复成 0.5 还是 1"的经典难题
- `durationSeconds` 走**真实时间线**而非缩放时间 —— 注释里写明"否则 80ms 顿帧会变成 1600ms 卡顿"，这个判断是对的
- `now` 参数可注入 —— 设计意图正确，**可惜被 Scheduler 截断了**（H3）
- `minScale` 默认 0，但注释建议"需要真暂停用 `pause()` 显式调用" —— 语义分离得好

唯一遗憾：`suspend` / `resume` 这对方法在 README 的 API 表里没列（README 只写了 `add/remove/has/get/update/value`）。

---

## 附：探针脚本

- `/data/workspace/audit/probe2.ts` —— 初测（S1~S10）
- `/data/workspace/audit/probe3.ts` —— **纠错重测**（S1/S7 的初测设计有误：dt 被 clamp、注册顺序反了，已修正）

> 记录这个是因为它本身就是教训：**第一版探针得出"repeat(times=3) 只执行 1 次"的错误结论**，差点误报成致命 bug。实际是 `dt=0.5` 被 `maxDeltaTime` clamp 到 0.1，60 帧才够跑完。审查工具和被测代码一样需要验证。
