# 04 LOD 与可见距离（植被域）

> **前置**：`01-实例化与分块.md` 已完成
> **本步交付**：远处植被**变稀疏而不是突然消失**
> **对应**：做法 `howto/godot/vegetation.md#6. LOD 与可见距离`
> 　　　审核 `audit/godot/vegetation.md#17`

## 0. 交付物定义

⚠ **这一节的默认值全是"不检查"，而 fade 又需要 margin > 0——
两个默认值叠在一起会让"设了但没生效"变得极难发现。**

⛔ 两个常见误读：

| 误读 | 实际 |
|---|---|
| `visibility_range_begin = 0` 表示距离 0 | 官方：默认 0 = **不做范围检查** |
| 设了 fade 就有过渡 | 官方：FADE 模式下 margin **必须 > 0** |

做完这一步，应该能**当场演示**：

1. 拉远时远处植被**渐隐**，不是硬弹消失
2. ⚠ 每档的 margin **> 0**（不是留默认值）
3. 近高模与远低模/billboard **有交叉区间**，不空档
4. 用 `lod_bias = 0` 能一眼看到最低档长什么样
5. ⚠ 帧时间随距离**下降**，不是恒定

**产出物**（下游按名字对接）：

```text
visibility_range_begin / _end          # 非 0 才生效
visibility_range_end_margin            # ⚠ FADE 模式下必须 > 0
visibility_range_fade_mode = FADE_SELF
near_mesh / far_mesh                   # 两套 MultiMesh 交叉
```

## 1. 前置检查清单

- [ ] 分块已完成（01），每块可单独设 range
- [ ] ⚠ 已确认目标平台的填充率/顶点预算
- [ ] 已准备低模或 billboard 资源
- [ ] 已知 `lod_bias = 0` 是调试手段

## 2. 工序

### Step 1　⚠ 确认 range 非 0 才生效　`[vegetation/04#S1]`

【读】`howto/godot/vegetation.md#6.1 visibility range 的 margin 语义会变`

【做】`visibility_range_begin/end` 必须显式设非 0。

⛔ **官方：*"The default value of 0 is used to disable the range check."***
留默认值 = 完全没做 LOD，而**不报错**。

【产出】各档的 range 值

【判据】⚠ 拉远到 end 之外，植被**确实消失**

【审】`audit/godot/vegetation.md#18`

### Step 2　⛔ FADE 模式下 margin 必须 > 0　`[vegetation/04#S2]`

【读】`howto/godot/vegetation.md#6.1 visibility range 的 margin 语义会变`

【做】`visibility_range_fade_mode = FADE_SELF` 时，margin 设 > 0。

⛔ **官方：*"If visibility_range_fade_mode is ... FADE_SELF ... this acts as
a fade transition distance and must be set to a value greater than 0.0 for
the effect to be noticeable."***

⚠ 设了 fade 却留 margin = 0 → **硬弹**，而你会以为"fade 没生效"。

【产出】每档 margin 值

【判据】⚠ 缓慢拉远，能看到**渐变过程**而非瞬间切换

【审】`audit/godot/vegetation.md#17`

### Step 3　⚠ 近高模与远低模交叉，不留空档　`[vegetation/04#S3]`

【读】`howto/godot/vegetation.md#6.2 ⚠ 远距离不能只靠 visibility range`

【做】两套 MultiMesh：`end` 与下一档 `begin` **有重叠**。

⛔ 不重叠 → 中间距离**两边都不显示**，
表现为"某个距离上植被整圈消失"，而移动时会一闪一闪。

【产出】两套的 range 数值（含重叠区）

【判据】⚠ 从近到远连续移动，**任何距离都有植被**

【审】`audit/godot/vegetation.md#19`

### Step 4　ⓘ 用 lod_bias=0 先看最低档　`[vegetation/04#S4]`

【读】`howto/godot/vegetation.md#6.3 ⓘ lod_bias = 0 是调试工具`

【做】调试期把 `lod_bias` 设 0 强制最低 LOD，先看效果。

ⓘ **官方：`lod_bias` 为 0 会强制最低 LOD。**
先看"最差长什么样"，比反复改距离试快得多。

【产出】最低档的视觉确认

【判据】⚠ 最低档在目标距离下**可接受**

【审】`audit/godot/vegetation.md#18`

### Step 5　⚠ 实测帧时间随距离下降　`[vegetation/04#S5]`

【读】`howto/godot/vegetation.md#1. ⚠ MultiMesh 是一个 AABB，不是一万个`

【做】拉远时测 `Vertices Drawn` 与帧时间。

⛔ 恒定不变 → 说明 range 没生效（回到 Step 1）或 AABB 还是错的（回到 01/S2）。

【产出】距离—帧时间曲线

【判据】⚠ 拉远后帧时间**可测地下降**

【审】`audit/godot/vegetation.md#23`

## 3. 参考实现

margin 的两种语义见
`howto/godot/vegetation.md#6.1 visibility range 的 margin 语义会变`。

## 4. 验收清单

- [ ] range 非 0，确实生效
- [ ] ⛔ FADE 模式 margin > 0，有渐变
- [ ] 两档有重叠，无空档
- [ ] 最低档已目视确认
- [ ] 拉远帧时间可测下降

## 5. 常见返工

**① range 留默认 0。** 完全没生效且不报错。

**② margin 留 0。** 硬弹，以为 fade 坏了。

**③ 两档不重叠。** 中间距离整圈消失。

**④ 只看参数不看实测。** 改半天帧率不动。

## 6. 下一步 → `05-交互与可采集.md`

## 7　整体审核（功能点级收尾）

【审】`audit/godot/vegetation.md`　全部条目，逐条对照本步产出
