# Godot 4.x 项目配置与工程实践

项目设置、导出、调试、性能排查。这些不直接是"功能"，但配错了后面全歪。

## 1. 项目设置关键项

**项目 → 项目设置**：

| 设置 | 推荐 | 说明 |
|---|---|---|
| `application/config/name` | 游戏名 | 窗口标题、user:// 目录名 |
| `application/run/main_scene` | 起始场景 | 没设会提示选一个 |
| `display/window/size/window_width/height` | 1280×720 | 逻辑分辨率 |
| `display/window/stretch/mode` | `canvas_items` | 2D 用这个；3D 用 `viewport` |
| `display/window/stretch/aspect` | `expand` | 不裁切不变形 |
| `physics/common/physics_ticks_per_second` | 60 | 改了要同步调所有力/速度参数 |
| `rendering/renderer/rendering_method` | 见下 | forward_plus / mobile / gl_compatibility |

### 渲染后端选择

| 后端 | 适用 | 代价 |
|---|---|---|
| `forward_plus` | 桌面端，画质优先 | 需要独显，老硬件不行 |
| `mobile` | 移动端 / 集成显卡 | 功能略少 |
| `gl_compatibility` | 老设备 / Web | 功能最少，但兼容性最好 |

⚠ Web 导出**必须**用 `gl_compatibility`，其它两个在浏览器跑不起来。

⚠ 改了 `physics_ticks_per_second` 后，所有重力/速度参数都要重新调 ——
它们是以"每 tick"为单位累加的。

### 层命名（强烈建议）

项目设置 → Layer Names → 2D Physics / 2D Render / 3D Physics / 3D Render。

给层起名字（`Player` / `Enemy` / `World` / `Item`），代码里配合
`physics.md` 里的 `Layers` 常量类使用。不命名的话全是"Layer 1/2/3"，
三个月后没人记得哪层是什么。

## 2. Autoload（全局单例）

**项目设置 → Autoload**，加脚本后全局可用：

```
Events        → res://autoload/events.gd
SaveManager   → res://autoload/save_manager.gd
AudioManager  → res://autoload/audio_manager.gd
GameState     → res://autoload/game_state.gd
```

加载顺序 = 列表顺序。**被依赖的排前面**（Events 一般最前）。

⚠ Autoload 节点**不会随场景切换销毁** —— 它的生命周期是整个程序运行期。
所以订阅 Autoload 的信号**必须手动断开**（同树父子会自动断，Autoload 不会）。

```gdscript
func _ready() -> void:
    Events.player_died.connect(_on_died)

func _exit_tree() -> void:
    Events.player_died.disconnect(_on_died)     # 不断 = 本节点被吊住，永远不释放
```

## 3. 调试与诊断

### 输出

```gdscript
print("普通输出")            # release 也执行
print_debug("调试输出")       # release 自动剥离 ← 调试用这个
push_warning("警告")          # 编辑器黄色，release 也留
push_error("错误")            # 编辑器红色，会进日志
assert(cond, "msg")           # 仅 debug，release 被移除
print_stack()                 # 打印调用栈
```

⚠ **不要用 `assert` 做运行时校验** —— release 导出模板下 assert 不被求值，
校验整段消失（审查 GD71）。运行时校验用 `if + push_error()`。

⚠ `print()` 留在正式代码里有 I/O 开销，且可能泄露信息（审查 GD74）。

### Performance 监视器

排查内存泄漏最有用的两个：

```gdscript
func _on_check_pressed() -> void:
    print("对象总数: %d" % Performance.get_monitor(Performance.OBJECT_COUNT))
    print("孤儿节点: %d" % Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT))
    print("DrawCall: %d" % Performance.get_monitor(
        Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
```

**用法**：进关卡前记一次，出关卡后记一次。

- `OBJECT_COUNT` 不下降 → 有东西没释放
- `OBJECT_ORPHAN_NODE_COUNT` > 0 → 有节点没进树但被持有（典型是 `remove_child` 后忘了 `queue_free`）

⚠ 部分监视器在 release 构建下返回 0 —— **不能把 0 当成"没问题"**，
要用 debug 构建测。

### 调试快捷键

| 键 | 功能 |
|---|---|
| F5 | 运行 |
| F6 | 运行当前场景 |
| F8 | 停止 |
| F7 | 暂停 |
| F12 | 截图 |
| 运行时切到 Remote 面板 | 实时看节点树，改属性 |

**Debug → Visible Collision Shapes**：显示碰撞体，排查碰撞问题必备。
**Debug → Visible Navigation**：显示导航网格。

## 4. 性能排查顺序

**先定位再优化**，别凭感觉：

```
1. 打开 Debugger → Profiler，跑起来看哪一栏高
   ├─ Script 高  → 脚本逻辑问题（每帧查找节点？每帧重建文本？）
   ├─ Render 高  → DrawCall 太多（材质不共享？没合批？）
   └─ Physics 高 → 物理体太多？每帧空间查询？
2. 针对性改，改完再测
```

### 常见错误直觉

| 直觉 | 实际 |
|---|---|
| 节点太多导致卡 | 节点数本身很少是瓶颈 |
| 贴图太大 | 通常是 DrawCall（合批被打断） |
| 物理太重 | 先确认是不是每帧 `intersect_shape` |

### 立即可做的优化

| 场景 | 做法 |
|---|---|
| 大量重复对象 | 对象池（见 `systems.md`） |
| 屏幕外对象 | `visible = false` 或加 `VisibilityNotifier` 自动开关 |
| 每帧查找节点 | `@onready` 缓存 |
| 每帧改 Label.text | 只在变化时改 |
| 粒子多 | 设 `fixed_fps` 限更新率 |
| DrawCall 高 | 共享材质、用图集、减少材质切换 |

## 5. 导出

**项目 → 导出**，添加预设（Windows / Linux / macOS / Android / iOS / Web）。

### 各平台要点

| 平台 | 注意 |
|---|---|
| Windows | 需 `rcedit` 改图标（可选） |
| macOS | 需要 Xcode 命令行工具；导出的是 .app |
| Android | 需装 Android SDK + 导出模板；**要先在编辑器里"安装 Android 构建模板"** |
| iOS | 需 macOS + Xcode |
| Web | 渲染后端必须 `gl_compatibility`；不支持线程 |

### 导出前检查清单

- [ ] 渲染后端与目标平台匹配（Web → gl_compatibility）
- [ ] `main_scene` 已设置
- [ ] 没有 `print()` 残留（或确认可接受）
- [ ] 没有 `assert` 做运行时校验
- [ ] 存档路径用 `user://`，没有写 `res://`
- [ ] 光照的 `editor_only` 已关闭
- [ ] 资源文件都在 `res://` 内（外部引用的不会被打包）
- [ ] 跑一次 release 导出测试（debug 能跑不代表 release 能跑）

⚠ **导出后最常见的两类问题**：
1. 读 `res://` 的文件失败（用了 `FileAccess` 列目录、或写盘到 res://）
2. debug 能跑 release 崩（通常是 assert 消失后暴露的空引用）

`.tscn`/`.tres` 之外的文件（如 `.json`、`.txt`）默认会被打包，
但**用 `DirAccess` 列目录在导出后可能拿不到内容**（PCK 里是虚拟文件系统）。

## 6. 版本控制

`.gitignore` 至少排除：

```
.godot/          # 编辑器缓存与导入产物，必须忽略
*.translation    # 导入产物
.mono/
builds/          # 导出产物
export_presets.cfg   # 含 keystore 密码等，视情况忽略
```

⚠ `.godot/` 一定要忽略 —— 里面有导入缓存，几 GB 很常见，且不同机器会冲突。

⚠ `export_presets.cfg` 里可能有 Android keystore 密码，公开仓库要忽略。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/project.md`

