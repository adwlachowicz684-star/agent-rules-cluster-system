# 05 LOD 与剔除（openworld 域）

> **前置**：`04-地形与网格.md`
> **本步交付**：**按覆盖度的 LOD + 剔除策略（visible + 池化）**
> **对应**：做法 `howto/godot/openworld.md#4. LOD`
> 　　　审核 `audit/godot/openworld.md`

## 0. 交付物定义

⚠ **本步最容易"看起来做完了"：按距离切 LOD 就算完了。**

⛔ 常见假完成：LOD 按距离切，但自动 LOD 实际按**屏幕覆盖度**选，
于是"远 30 米切一级"的收益估算全部落空。

做完这一步，应该能**当场演示**：

1. LOD 按屏幕覆盖度理解，不是距离
2. ⛔ 已确认资源格式支持自动生成 LOD
3. ⛔ LOD 切换用 dither fade 缓解突跳
4. ⚠ 可见距离已按 draw call 实测设定
5. ⛔ 高频切换用 `visible` + 池化，不是 `queue_free`

**产出物**（下游按名字对接）：

```text
LOD 配置（覆盖度驱动 + dither fade）
剔除策略（可见距离 + visible/池化）
```

## 1. 前置检查清单

- [ ] 地形与网格已就绪（04 产出）
- [ ] 已盘点资产格式（glTF/blend/FBX/OBJ）
- [ ] 已能查看 draw call 与对象数

## 2. 工序

### Step 1　⛔ 自动 LOD 按屏幕覆盖度选，不是按距离　`[05#S1]`

【读】`howto/godot/openworld.md#4. LOD`

【审】`audit/godot/openworld.md#10`

⛔ 不能按"远 30 米切一级"估算收益。

### Step 2　⛔ OBJ 不自动生成 LOD　`[05#S2]`

【读】`howto/godot/openworld.md#4. LOD`

【审】`audit/godot/openworld.md#11`

⚠ glTF / blend / FBX 支持自动生成，**OBJ 不自动生成**。

### Step 3　⛔ LOD 突跳要用 dither fade，不要直接切　`[05#S3]`

【读】`howto/godot/openworld.md#4. LOD`

【审】`audit/godot/openworld.md#34`

⚠ 用 dither fade 缓解 popping，代价很小。

### Step 4　⛔ 可见距离设大点不等于看得远　`[05#S4]`

【读】`howto/godot/openworld.md#6. 剔除`

【审】`audit/godot/openworld.md#33`

⚠ 剔除失效 → draw call 暴涨。
⛔ 表现为"明明只看到几棵树，draw call 却上千"。

### Step 5　⛔ 高频切换用 visible + 池化，不要 queue_free　`[05#S5]`

【读】`howto/godot/openworld.md#6. 剔除`

【审】`audit/godot/openworld.md#26`

⚠ `visible=false` 最轻（仍在树里）、`remove_child` 中等、
`queue_free` 最彻底但重建有成本。高频切换要前两者。

## 3. 参考实现

```text
visible=false   最轻，但仍在树里（仍参与 process）
remove_child    中等，但对象还在内存
queue_free      最彻底，但重建有成本
```

⛔ 高频切换用 `visible` + 池化，不要 `queue_free`。

## 4. 验收清单

- [ ] LOD 按覆盖度理解，无"按距离估算"的假设
- [ ] ⛔ 已确认资产格式支持自动生成 LOD
- [ ] ⛔ LOD 切换有 dither fade
- [ ] ⚠ 可见距离已按 draw call 实测设定
- [ ] ⛔ 高频切换走 `visible` + 池化

## 5. 常见返工

| 现象 | 回到 |
|---|---|
| LOD 收益与估算不符 | Step 1（按距离而非覆盖度） |
| 某些模型没有 LOD | Step 2（OBJ 不支持） |
| 远处模型突跳明显 | Step 3（没用 dither fade） |
| draw call 莫名很高 | Step 4（可见距离过大） |
| 切换时卡顿 | Step 5（用了 queue_free） |

## 6. 下一步 → `06-存档与大世界状态.md`

## 7　整体审核（功能点级收尾）

【审】`audit/godot/openworld.md`　全部条目，逐条对照本步产出
