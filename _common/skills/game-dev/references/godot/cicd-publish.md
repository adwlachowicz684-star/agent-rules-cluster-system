# Godot 4.x CI/CD 与导出发布

从"能编译"到"能交付"还差：导入产物、导出模板、签名凭据、平台差异。

## 1. 无头运行

```bash
godot --headless --import --quit          # 导入资源（CI 首次必做）
godot --headless --quit                   # 跑一下再退出
godot --headless --export-release "Linux/X11" build/game.x86_64
godot --headless --script res://tools/build.gd
```

| 能做 | 不能做 |
|---|---|
| 资源导入、跑项目、导出、跑脚本 | 无窗口、无 GPU、无法验证画面 |
| 日志、文件 IO、网络 | 无音频输出 |

⚠ `--script` 的脚本**必须继承 `SceneTree` 或 `MainLoop`**，普通 Node 脚本不跑。

⚠ **Linux 上导出 Windows 包需要 Wine**（图标、版本资源等元数据）。
4.5+ 部分场景不再需要 rcedit。

### 导入产物：CI 必须重新导入

- 导入产物在 `res://.godot/imported/`（隐藏目录）
- **`.import` 文件（导入参数元数据）必须提交到版本控制**
- `.godot/` 整体**不提交**（体积大），所以 CI 首次 clone 后必须重新导入

```bash
godot --headless --import --quit
```

⚠ **忘了 `--import` 是 CI 最常见的失败原因**。
表现为"资源找不到"或"纹理全黑"，而本地完全正常。

⚠ 不提交 `.import` 会导致**每个人导入参数不一致**，
纹理压缩、过滤方式在不同机器上产生不同结果，且 diff 看不出来。

## 2. CI 流水线

### 完整可抄的 GitHub Actions

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    container:
      image: barichello/godot-ci:4.3          # 版本要与本地一致
    steps:
      - uses: actions/checkout@v4

      # 关键：缓存导入产物，否则每次全量导入很慢
      - name: 缓存 .godot
        uses: actions/cache@v4
        with:
          path: .godot
          key: godot-import-${{ hashFiles('**/*.import', '**/*.tscn', 'project.godot') }}

      - name: 导入资源
        run: godot --headless --import --quit

      - name: 静态检查
        run: gdtoolkit --check . || true      # 或你们自己的 lint

      - name: 跑测试
        run: godot --headless --script res://test/cli_runner.gd
        # GUT 可输出 JUnit XML，供 CI 展示

  export:
    needs: test
    runs-on: ubuntu-latest
    container:
      image: barichello/godot-ci:4.3
    strategy:
      matrix:
        preset: ["Linux/X11", "Windows Desktop", "Web"]
    steps:
      - uses: actions/checkout@v4
      - name: 导入
        run: godot --headless --import --quit
      - name: 导出
        run: |
          mkdir -p build
          godot --headless --export-release "${{ matrix.preset }}" build/out
      # 关键：必须校验产物非空
      - name: 校验产物
        run: |
          if [ ! -s build/out* ]; then
            echo "导出产物为空或不存在"
            exit 1
          fi
      - uses: actions/upload-artifact@v4
        with:
          name: build-${{ matrix.preset }}
          path: build/
```

⚠ **导出后必须校验产物存在且非空**。
`--export-release` 拼错参数会**静默以退出码 0 退出** —— CI 全绿但产物不存在。
（注意是 `--export-release`，不是 `--export-realese`）

⚠ **容器镜像的 Godot 版本必须与本地一致**，
否则行为差异会让"本地能跑 CI 红"或更糟的"CI 绿但产物不对"。

⚠ **`export_presets.cfg` 必须入库**，否则 CI 无法导出。
但它可能含路径信息，团队里路径不同的人会冲突 —— 用相对路径。

### 凭据一律走 Secret

⚠ **绝不在仓库里放签名密钥、商店令牌、密码**。

- PR 事件**默认不注入 Secret**（防止 fork PR 窃取）
- 二进制 keystore 不能直接存 Secret（Secret 是文本）→ **先 base64**

```yaml
- name: 还原 keystore
  env:
    KEYSTORE_B64: ${{ secrets.ANDROID_RELEASE_KEYSTORE_B64 }}
  run: |
    echo "$KEYSTORE_B64" | base64 -d > $HOME/release.keystore
```

## 3. 导出

### 3.1 模板版本必须严格匹配

```
模板版本 == 编辑器版本（含 beta/rc/dev）
```

⚠ **升级引擎后必须重新下载对应模板**。
用 stable 模板导 dev 构建会失败或产出异常。

⚠ beta/rc 也要匹配。别拿 `4.3.stable` 的模板去导 `4.3.rc1`。

### 3.2 各平台要点

| 平台 | 产物 | 关键差异 |
|---|---|---|
| **Windows** | `.exe` | 图标/版本资源需 Wine（4.5+ 多数免）；代码签名可选 |
| **Linux** | `.x86_64` | 注意可执行权限；无系统级签名 |
| **macOS** | `.app`（导出为 `.dmg`/`.zip`） | **Bundle ID 必填**；签名 + 公证 |
| **Android** | `.apk` / `.aab` | Gradle；keystore；minSdk/targetSdk |
| **iOS** | Xcode 项目 | 需 macOS + Xcode |
| **Web** | `.html`+`.js`+`.wasm`+`.pck` | **单线程默认**、WebGL2、**不支持 C#** |

⚠ **在 macOS 上导出得到 `.dmg`，Linux/Windows 上得到 `.zip`**，两者都含 `.app`。
别因为"CI 上产物扩展名不一样"就去改配置。

⚠ **macOS 是三步：签名 → 公证 → 装订票证（staple）**。
只签名不公证，Gatekeeper 仍会拦截。

### 3.3 Android 高频坑

```bash
# 签名可用环境变量覆盖（CI 友好）
GODOT_ANDROID_KEYSTORE_DEBUG_PATH
GODOT_ANDROID_KEYSTORE_DEBUG_PASSWORD
GODOT_ANDROID_KEYSTORE_DEBUG_USER
```

| 配置项 | 说明 |
|---|---|
| `gradle_build/use_gradle_build` | 是否用 Gradle 构建 |
| `gradle_build/export_format` | `.apk` 或 `.aab` |
| `gradle_build/min_sdk` / `target_sdk` | 对应 `minSdkVersion`/`targetSdkVersion` |

⚠ **纹理压缩格式漏选会导致运行时纹理全黑**。
Android 预设里要为每种架构选 ETC2 / ASTC / DXT。

⚠ **联网游戏需要 `INTERNET` 权限**，不加的话真机上网络请求全部失败，
而编辑器里正常（编辑器默认有权限）。

### 3.4 Web 的限制

- **单线程是默认**（线程需特殊构建）
- WebGL2
- **不支持 C#**
- 不支持 Forward+ / Mobile 之外的某些渲染特性
- 需要 HTTP 服务（不能直接 file:// 打开）
- 注意 COOP/COEP 头（多线程需要）

⚠ **立项时就要定平台**。如果目标是 Web，就不能用 C# 作主语言，
且这个决定后期无法低成本更改。

## 4. 发布与版本

### 版本号

```gdscript
# project.godot 里
config/version="1.2.3"
```

```gdscript
# 代码里读
var v := ProjectSettings.get_setting("application/config/version")
```

⚠ 版本号要有**单一数据源**。散落在 `project.godot`、CI、商店后台三处必然不同步。

### 发布检查清单

- [ ] 导出模板版本与编辑器严格一致
- [ ] `export_presets.cfg` 已入库且用相对路径
- [ ] 所有平台的产物都实际启动过（不是只导出成功）
- [ ] Android 纹理格式已选，INTERNET 权限已加
- [ ] macOS 已完成签名 + 公证 + 装订
- [ ] 凭据全部走 Secret，仓库里没有密钥
- [ ] 导出后校验产物非空（防止静默失败）
- [ ] release 版跑过一遍（不是只测 debug）
- [ ] 版本号单一数据源
- [ ] 变更日志已更新

> **反模式清单（不能怎么做，审核用）** → `code-audit: godot-antipatterns/cicd-publish.md`


## 5. 相关文档

- 项目设置与 Autoload → `project.md`
- 导出预设配置 → `project.md`
- 移动端适配 → `mobile.md`
- C# 平台限制 → `csharp.md`
