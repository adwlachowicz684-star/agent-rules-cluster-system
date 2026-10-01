# 02 LightmapGI 烘焙与 UV2 地基（光照域）

> **本步交付**：gi_mode / UV2 / bake mode / 失败码处理 + 探针
> **对应**：流程 `howto/godot/lighting.md` · 审核 `audit/godot/lighting.md`

## 0. 交付物定义

1. 静态几何体的 `GeometryInstance3D.gi_mode` 已设为 **Static**
2. **UV2 已生成**且每个面在 UV 里有独立位置
3. 参与烘焙与否由 **`light_bake_mode`** 控制，⛔ 不是 `visible`
4. 烘焙失败码**已被处理**，⛔ 不是只看"有没有出图"
5. 动态物体的探针已布置**并重烘**
6. 烘焙数据落盘为 `.lmbake`

## 1. 前置检查清单

- [ ] 静态几何体 gi_mode = Static
- [ ] 导入面板已设 Static Lightmaps，UV2 存在
- [ ] 没有任何一盏灯靠 `visible = false` 排除在烘焙外
- [ ] 烘焙返回值被检查，失败码有对应提示
- [ ] 探针已摆且已重烘
- [ ] light data 存为外部 `.lmbake`

## 2. 工序
### Step 1　gi_mode 与节点层级：只烘同级或子级　`[lighting/02#S1]`

【读】`howto/godot/lighting.md#1. LightmapGI 烘焙`

【做】
把静态几何体的 `GeometryInstance3D.gi_mode` 设为 **Static**，
并确认它们与 `LightmapGI` **同级或是其子级**。
⛔ 节点放错位置 = 烘出来全黑，
而光源、材质、纹素密度**全部正确**。

ⓘ 官方允许用**多个** LightmapGI 分段烘焙不同区域，
这是"只烘同级或子级"这条约束的直接推论。
【审】`audit/godot/lighting.md#3`
### Step 2　UV2 唯一且连续：最容易卡住的一步　`[lighting/02#S2]`

【读】`howto/godot/lighting.md#1. LightmapGI 烘焙`

【做】
在导入面板选中 3D 场景，把 `Meshes → Light Baking` 设为
**Static Lightmaps**，让引擎生成 UV2。
确认**每个面在 UV 里有独立位置、不共享像素**。

⛔ 复用网格时 Godot 只为找到的**第一个**实例生成 UV2；
若实例缩放差异超过一半或两倍，纹素密度会低效 ——
缩放差异大的资产应做成**独立网格资源**。
【审】`audit/godot/lighting.md#5`
### Step 3　排除灯用 bake mode，⛔ 不能用 visible　`[lighting/02#S3]`

【读】`howto/godot/lighting.md#7. ⛔ 烘焙的静默失效：三类不报错的错`

【做】
把不参与烘焙的灯设为
`Light3D.light_bake_mode = BAKE_MODE_DISABLED`。

⛔ 官方 WARNING：*"Hiding a light has no effect on the resulting
lightmap bake. This means you must use the Disabled bake mode instead
of hiding the Light node by disabling its Visible property."*

⛔ 把灯 `visible = false` 以为它不参与烘焙 —— **照样烘进去**。
表现为"烘完场景里多了一块不该有的光"，
排查必然被引向漏光或反弹次数，
⛔ 不会想到是那盏"看不见的灯"。
【审】`audit/godot/lighting.md#18`
### Step 4　处理失败码，⛔ 不能只看有没有出图　`[lighting/02#S4]`

【读】`howto/godot/lighting.md#1. LightmapGI 烘焙`

【做】
检查 `bake()` 的返回值，把每个失败码映射成人能读的提示，
并对"纹理过大"这一类**主动降规格重试**。

⛔ 官方：烘焙可能**耗尽显存导致引擎崩溃** ——
即使显存很大的系统也可能。
⛔ 崩溃前没有任何温和的降级提示，
表现为"别人机器上能烘、我这儿直接崩"。
【审】`audit/godot/lighting.md#23`
### Step 5　探针：动态物体的间接光，摆完必须重烘　`[lighting/02#S5]`

【读】`howto/godot/lighting.md#7. ⛔ 烘焙的静默失效：三类不报错的错`

【做】
为动态物体活动的区域布探针：自动（`generate_probes_subdiv`）
或手动摆 `LightmapProbe` 节点。

⛔ 官方：手动放置后**必须重新烘焙才生效**；
自动生成的探针**在场景树不可见、烘焙后无法修改**。

ⓘ **直接光永远由 Light3D 实时施加在动态物体上**，
即使该灯 bake mode 是 Static —— 探针只存**间接光**。
ⓘ 烘焙后编辑器里的白色球体**不在运行项目中显示**。
【审】`audit/godot/lighting.md#19`
### Step 6　烘焙数据存为外部 .lmbake　`[lighting/02#S6]`

【读】`howto/godot/lighting.md#7. ⛔ 烘焙的静默失效：三类不报错的错`

【做】
把 `LightmapGI` 的 `Data → Light Data` 存成外部二进制 `.lmbake`。

⛔ 留在 `.tscn` 里会用 Base64 内联，
表现为"场景文件莫名变大、版本库 diff 全是乱码"，
⛔ 而光照本身完全正常，不会有任何警告。
【审】`audit/godot/lighting.md#22`

## 3. 参考实现

```gdscript
# 编辑器工具脚本里触发烘焙并处理失败码
# ⓘ BAKE_ERROR_* 为引擎内置常量，见 LightmapGI.BakeError
func bake_with_report(gi: LightmapGI) -> bool:
    var err := gi.bake()
    if err != OK:
        push_error("烘焙失败，错误码 %d（见 LightmapGI.BakeError）" % err)
        return false
    return true

# ⛔ 排除灯的正确写法
func exclude_from_bake(l: Light3D) -> void:
    l.light_bake_mode = Light3D.BAKE_MODE_DISABLED
    # ⛔ 不是 l.visible = false —— 官方明确那不影响烘焙
```

## 4. 验收清单

- [ ] 静态几何体 gi_mode = Static
- [ ] UV2 已生成，缩放差异大的资产已拆成独立网格
- [ ] 无一盏灯靠 visible 排除烘焙
- [ ] 失败码有映射且"纹理过大"会降规格重试
- [ ] 探针已摆且已重烘
- [ ] light data 是外部 .lmbake

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 烘出来全黑 | gi_mode 不是 Static 或节点层级错 | S1 |
| 纹素密度忽疏忽密 | 复用网格只给第一个实例生成 UV2 | S2 |
| 多出一块不该有的光 | 用 visible 隐藏了灯 | S3 |
| 别人能烘我这儿崩溃 | 显存耗尽 | S4 |
| 动态物体没有间接光 | 探针摆了没重烘 | S5 |
| 场景文件异常大 | light data 内联在 .tscn | S6 |

## 6. 下一步

→ 03 GI 方案与动态物体

## 7　整体审核（功能点级收尾）

【审】`audit/godot/lighting.md#3`、【审】`audit/godot/lighting.md#5`、【审】`audit/godot/lighting.md#18`、【审】`audit/godot/lighting.md#23`、【审】`audit/godot/lighting.md#19`、【审】`audit/godot/lighting.md#22`、【审】`audit/godot/lighting.md#21`