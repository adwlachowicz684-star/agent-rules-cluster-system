# 02 Chunk 划分与状态机（openworld 域）

> **前置**：`01-世界规模与坐标方案定性.md`
> **本步交付**：**三条半径构成滞回 + 六态加载状态机**
> **对应**：做法 `howto/godot/openworld.md#1. Chunk 流式加载`
> 　　　审核 `audit/godot/openworld.md`

## 0. 交付物定义

⚠ **本步最容易"看起来做完了"：一个半径 + 加载/卸载两态。**

⛔ 常见假完成：半径设了，但 `unload_radius == load_radius`，
于是玩家在 chunk 边界来回走会**抖动式加载**——
表现为周期性卡顿，⛔ 极易被当成"资源太大"去优化。

做完这一步，应该能**当场演示**：

1. 三条半径已设且 `unload_radius > load_radius`
2. ⛔ 超出半径后**不是立刻卸载**，有 `unload_delay`
3. 状态机六态齐全（不是只有加载/卸载）
4. ⛔ 加载失败有独立失败态，不会反复重试
5. 装饰物已按 chunk 归属登记

**产出物**（下游按名字对接）：

```text
ChunkManager（三条半径 + 六态状态机）
chunk 归属登记表（装饰物/植被/野怪）
```

## 1. 前置检查清单

- [ ] 世界规模档位已定（01 产出）
- [ ] 已确定 chunk 边长
- [ ] 已盘点 chunk 内包含哪些内容

## 2. 工序

### Step 1　⛔ 三条半径构成滞回，一个半径不够　`[02#S1]`

【读】`howto/godot/openworld.md#三条半径构成滞回（hysteresis）`

【审】`audit/godot/openworld.md#3`

⚠ `load_radius` / `unload_radius`（必须更大）/ `unload_delay`。

### Step 2　⛔ 加载状态机要六态，不是两态　`[02#S2]`

【读】`howto/godot/openworld.md#加载状态机要分开`

【审】`audit/godot/openworld.md#21`

⚠ 请求 → 解码 → 实例化 → 就绪 → 预热 → 卸载。
缺态则状态不一致，表现为"明明加载了却用不了"。

### Step 3　⛔ 超出半径立刻卸载会抖动，要有 delay　`[02#S3]`

【读】`howto/godot/openworld.md#三条半径构成滞回（hysteresis）`

【审】`audit/godot/openworld.md#22`

### Step 4　⛔ 加载失败要有失败态，否则反复重试　`[02#S4]`

【读】`howto/godot/openworld.md#加载状态机要分开`

【审】`audit/godot/openworld.md#35`

⚠ 失败后不记录状态 → 每帧重试 → 卡死。
⛔ 表现为"走到某处游戏就卡住"，而去查一个正常的资源。

### Step 5　⛔ 装饰物要按 chunk 归属登记，否则漏卸　`[02#S5]`

【读】`howto/godot/openworld.md#1. Chunk 流式加载`

【审】`audit/godot/openworld.md#37`

## 3. 参考实现

```gdscript
enum ChunkState { REQUESTED, DECODING, INSTANTIATING, READY, WARMING, UNLOADING, FAILED }
# ⛔ FAILED 必须存在：否则失败 chunk 每帧重试
```

⛔ 不要指望"重试就好了"——失败态缺失导致的重试是**每帧**发生的。

## 4. 验收清单

- [ ] `unload_radius > load_radius`
- [ ] ⛔ 超出半径后有 `unload_delay` 才真卸载
- [ ] 状态机含六态 + 失败态
- [ ] ⛔ 加载失败不会反复重试
- [ ] 装饰物已按 chunk 归属登记

## 5. 常见返工

| 现象 | 回到 |
|---|---|
| 边界来回走周期性卡顿 | Step 1 / Step 3（缺滞回或 delay） |
| 加载了却用不了 | Step 2（状态机缺态） |
| 走到某处卡死 | Step 4（失败态缺失） |
| 卸载后有残留物件 | Step 5（归属没登记） |

## 6. 下一步 → `03-加载预算与节点池.md`

## 7　整体审核（功能点级收尾）

【审】`audit/godot/openworld.md`　全部条目，逐条对照本步产出
