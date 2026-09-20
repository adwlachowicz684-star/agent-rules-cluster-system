<!-- oversize-exempt: 反模式清单，审核用 -->
# rendering-advanced — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`flow/godot/rendering-advanced.md`

## 用最近 N 个样本平均估计速度，避免抖动尖峰
func _sample_velocity(delta: float) -> void:
    var now := global_transform
    if _has_prev:
        var dp := now.origin - _prev_transform.origin
        _vel_samples.push_back(dp / delta)
        if _vel_samples.size() > sample_count:
            _vel_samples.pop_front()
    _prev_transform = now
    _has_prev = true

func _linear_velocity() -> Vector3:
    if _vel_samples.is_empty():
        return Vector3.ZERO
    var sum := Vector3.ZERO
    for v in _vel_samples:
        sum += v
    return sum / _vel_samples.size()

func grab() -> void:
    if _held or _candidates.is_empty():
        return
    var body := _candidates[0]
    # 冻结物理，避免约束建立瞬间弹飞
    body.linear_velocity = Vector3.ZERO
    body.angular_velocity = Vector3.ZERO
    _joint = Generic6DOFJoint3D.new()
    get_tree().current_scene.add_child(_joint)
    _joint.global_transform = grab_anchor.global_transform
    _joint.node_a = _joint.get_path_to(self)
    _joint.node_b = body.get_path()
    _held = body
    grabbed.emit(body)

func release() -> void:
    if not _held:
        return
    var body := _held
    if _joint:
        _joint.queue_free()
        _joint = null
    _held = null
    # 释放时把估计的速度写回去
    body.linear_velocity = _linear_velocity()
    released.emit(body)
```

⚠ **直接每帧 `global_transform.origin - prev.origin` 会产生尖峰**
（大抖动、重投影、120Hz 头显）。必须对最近若干样本做平均或时间衰减。

⚠ 抓握不要只改 `owner` —— 物理所有权、父子关系、约束是三件事。

### 世界空间 UI

把 Control 挂到 3D 空间要用 `SubViewport` + `SubViewportContainer`，
注意分辨率和可读性：

- UI 放在**舒适阅读距离**（约 1–3 米），不能贴脸也不能太远
- `SubViewport` 尺寸要够，否则文字糊
- 更新模式按需（`UPDATE_ALWAYS` 很贵）

⚠ 世界空间 UI 是**每帧渲染的额外视口**，会显著增加开销。

### 传送移动

抛物线射线指示落点。⚠ 待核对：是否存在 `ArcCast3D` 节点 · 验证：4.7.2 编辑器节点搜索框输入 ArcCast3D
若无，用多段 `RayCast3D` 或自己算抛物线采样点。

⚠ **至少提供一种无晕选项**（传送）。只有平滑移动会让部分玩家无法游玩。

### 性能是硬约束

VR **必须稳定 90fps**（或设备刷新率）。掉帧直接导致晕动症。

| 预算项 | 目标 |
|---|---|
| 帧时间 | ≤ 11ms（90fps） |
| 双眼渲染 | 所有开销 ×2 |
| 分辨率/渲染缩放 | 最大的性能杠杆 |

⚠ **先满足刷新率，再谈画质**。VR 里"好看但晕"是负分。
性能预算**没有官方统一 draw call / 三角形上限**，必须按目标头显实测。

## 常见漏写

| 域 | 漏写 | 后果 |
|---|---|---|
| XR | 手部模型一出现就吸附 | 模型乱飞 |
| XR | 用单帧差分算控制器速度 | 抖动尖峰，抓取物乱飞 |
| XR | 抓握只改 owner | 刚体锁死世界坐标 |
| XR | 只有平滑移动 | 部分玩家晕到无法游玩 |
| XR | 掉帧 | 晕动症，比难看严重得多 |
| LOD | 以为 OBJ 也有自动 LOD | 该资产从不降面 |
| LOD | 只按距离估算收益 | 实际收益与预期不符 |
| LOD | HLOD 不关远处阴影 | 阴影开销没降 |
| LOD | 大世界不分块 | 内存爆、加载卡顿 |
| Shader | `load()` 当预热完成 | 首次出现仍卡顿 |
| Shader | 只 instantiate 不渲染 | 不触发管线生成 |
| Shader | 动态资源不预热 | 玩家换皮肤时卡一下 |
