# Godot 4.x 开发索引

**版本**：Godot 4.x。3.x 大量不兼容，模板不可直接套用。

## 按功能域入口

| 我要做… | 看哪个文件 | 关键 API |
|---|---|---|
| **角色移动 / 跳跃 / 手感** | `character.md` | `CharacterBody2D/3D` · `velocity` · `move_and_slide()` · 土狼时间 · 跳跃缓冲 |
| **UI / 菜单 / HUD / 背包 / 对话** | `ui.md` | `Control` 锚点 · `CanvasLayer` · `GridContainer` · `RichTextLabel` |
| **存档 / 设置 / 场景切换 / 事件总线 / 对象池** | `systems.md` | `ResourceSaver` · `user://` · `change_scene_to_file` · Autoload signal |
| **动画 / 状态机 / Tween** | `animation.md` | `AnimationPlayer` · `AnimationTree` 状态机 · `Tween` 链式 · `kill()` |
| **输入绑定 / 音效 / BGM** | `input-audio.md` | Input Map 动作 · 四回调顺序 · `AudioServer` 总线 · 音效池 |
| **碰撞 / 射线 / 触发区 / 施力 / 移动平台** | `physics.md` | 碰撞层位掩码 · `intersect_ray` 参数对象 · `Area2D` · `AnimatableBody` |
| **3D 场景 / 相机 / 材质 / 光照 / 粒子** | `3d.md` | 坐标系 · 第三人称相机 · 共享材质陷阱 · `Environment` |
| **敌人 AI / 寻路 / 状态机** | `ai-navigation.md` | NavigationAgent2D 模板 · 巡逻追击攻击 FSM · AStarGrid2D · 视线检测 |
| **TileMap 关卡 / 地形 / 程序生成** | `tilemap.md` | 4.3+ vs 4.2 两套 API · 坐标转换 · 地形拼接 · FastNoiseLite |
| **移动端触控 / 虚拟摇杆 / 适配** | `mobile.md` | ScreenTouch/Drag · 浮动摇杆 · 手势识别 · 安全区 · 返回键 · 移动端性能 |
| **性能诊断 / 优化** | `performance.md` | 先测量再优化 · Monitors 排查泄漏 · 屏幕外停处理 · 线程池 · 性能预算 |
| **GDScript 热路径 / 生命周期** | `gdscript-advanced.md` | 类型系统 · 热路径禁止清单 · await 三坑 · 回调时机 · @tool 隔离 |
| **架构 / 规范** | `architecture.md` | 17 步成员顺序 · call down signal up · 组件组合 · Resource 数据驱动 |
| **测试 / CI** | `testing.md` | GUT · 无框架最小方案 · 静态检查进 CI · 存档回归测试 |
| **存档加密 / 防作弊** | `security.md` | 客户端加密的边界 · AES+HMAC 存档 · 随机 IV · 内存值混淆 · 时间作弊 · 服务端权威 |
| **本地化技术实现** | `i18n.md` | `tr()`/`tr_n()` · CSV 工作流 · 语言切换 · 字体回退 · RTL |
| **2D 渲染 / 着色器 / 屏幕特效** | `2d-rendering.md` | Y-Sort 结构 · Parallax2D · shader 配方 · trauma 抖动 · hitstop |
| **资源加载 / HTTP / 多人联机** | `io-network.md` | `load`/`preload` · 线程加载 · `HTTPRequest` · ENet · `@rpc` |
| **项目设置 / 导出 / 调试 / 性能** | `project.md` | 项目设置关键项 · Autoload · `Performance` · 导出清单 |

## 本地化：本目录只放技术

`i18n.md` 只讲引擎侧实现（`tr()`、CSV、切语言、字体回退）。
**翻译流程、文案管理、术语表、翻译 QA 属于独立 skill `localization`**，
那边目前是占位壳子，内容待真实项目需求驱动填充。

两边不重复写 —— 重复必然只改一处，另一处过期。

## 项目结构约定

推荐的目录组织（不强制，但这样最不容易乱）：

```
my_game/
├── project.godot
├── scenes/              # .tscn 场景文件
│   ├── main.tscn
│   └── levels/
├── scripts/             # .gd 脚本
│   ├── player/
│   ├── enemies/
│   └── ui/
├── autoload/            # 全局单例（Events / SaveManager / SceneManager）
├── assets/              # 美术音频原始资源
│   ├── sprites/
│   ├── audio/
│   └── fonts/
└── ui/                  # UI 场景（.tscn）
```

**Autoload 配置**：项目设置 → Autoload，加载顺序有讲究
（被依赖的先加载，如 Events 要在其他之前）。

## Godot 特有的心智模型

从 Unity/Unreal 转过来最容易踩的：

| 你以为 | 实际 |
|---|---|
| 场景 = 关卡 | 场景是**可复用的节点树**，任何子树都能存成场景再实例化 |
| 预制体（Prefab） | 就是场景（`.tscn`）+ `instantiate()` |
| 组件挂载 | 节点组合 + 脚本 `extends`，一个节点只能挂一个脚本 |
| 烘焙光照进场景 | 需要 `LightmapGI` / `VoxelGI` 节点显式烘焙 |
| GameObject.Find | `get_node()` 路径查找，或 `@onready` 缓存 |

**节点树即架构** —— Godot 里"父子关系"既是层级也是生命周期。
子节点会随父节点一起释放，这是设计上的便利，也是泄漏的来源
（父节点不释放，子节点就永远在）。

## 常见漏写速查

写完对照一遍：

| 漏写 | 审查规则 |
|---|---|
| Autoload 信号未断开 | GD15 |
| `remove_child` 后没 `queue_free` | GD01 |
| `create_tween()` 未保存引用 | GD02 |
| `FileAccess` 未 `close()` | GD41 |
| 存档写 `res://` | GD43 |
| `instantiate()` 后未 `add_child()` | GD46 |
| 动态 `AudioStreamPlayer` 未 `queue_free()` | GD52 |
| `assert` 做运行时校验 | GD71 |
| `duplicate()` 浅拷贝 | GD73 |
| `print()` 留在正式代码 | GD74 |
| `await` 后未判 `is_instance_valid` | GD75 |
| 每帧赋值 `Label.text` | GD13 |
| `move_and_slide(...)` 带参 | GD09 |
| `velocity *= delta` | GD21 |

完整判据见 `../../code-audit/references/p-godot.md`。

## 验证方式

写完代码后：

```bash
# 审查侧：跑规则
python3 ../../code-audit/scripts/godot-audit.py --src=<项目根>

# 运行时：对象计数是否单调增长（切场景前后对比）
print(Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT))
```
