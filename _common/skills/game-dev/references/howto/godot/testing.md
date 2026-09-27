# Godot 4.x 测试与 CI

大型项目没有测试 = 每次改动都靠手动点一遍，改动越大越不敢动。

## 1. 测试分层

```
单元测试   单个函数/类的逻辑（伤害计算、背包容量、寻路）
集成测试   多个系统协作（存档→读档→状态一致）
冒烟测试   能不能启动、主流程能不能走完
回归测试   存档兼容性（旧版本存档能否被新版读取）
```

⚠ 游戏项目不需要 100% 覆盖率。**优先测纯逻辑**（可测、易测、价值高），
UI 和渲染靠手动。

## 2. GUT（Godot 单元测试框架）

Godot 社区最常用的测试框架。

```
addons/gut/
tests/
├── test_health.gd
└── test_inventory.gd
```

```gdscript
# tests/test_health.gd
extends GutTest

func test_take_damage_reduces_hp():
    var h := HealthComponent.new()
    h.max_hp = 100
    add_child_autofree(h)

    h.take_damage(30)
    assert_eq(h.hp, 70, "扣血后应为 70")

func test_hp_never_below_zero():
    var h := HealthComponent.new()
    h.max_hp = 50
    add_child_autofree(h)

    h.take_damage(999)
    assert_eq(h.hp, 0, "血量不应为负")

func test_died_signal_emitted():
    var h := HealthComponent.new()
    h.max_hp = 10
    add_child_autofree(h)
    watch_signals(h)

    h.take_damage(10)
    assert_signal_emitted(h, "died")
```

**运行**：

```bash
# 命令行（CI 用）
godot --headless -s addons/gut/gut_cmdln.gd -gtest=tests/ -gexit
```

⚠ 用 `--headless`，CI 里没有显示器。

⚠ `add_child_autofree()` —— 测试结束自动释放，避免测试间互相污染。

⚠ GUT 的具体 API 以所用版本为准，本文件给的是通用结构。

## 3. 不装框架的最小方案

Godot 自带 `assert` 和一个简单的测试脚本模式：

```gdscript
# tests/run_tests.gd —— 用 --script 跑
extends SceneTree

var _pass := 0
var _fail := 0

func _init() -> void:
    _test_damage()
    _test_save_roundtrip()
    print("\n通过 %d / 失败 %d" % [_pass, _fail])
    quit(1 if _fail > 0 else 0)

func check(cond: bool, label: String) -> void:
    if cond:
        _pass += 1
    else:
        _fail += 1
        print("  ✗ %s" % label)

func _test_damage() -> void:
    var hp := 100
    hp -= 30
    check(hp == 70, "伤害计算")

func _test_save_roundtrip() -> void:
    var data := {"hp": 50, "gold": 999}
    var json := JSON.stringify(data)
    var p := JSON.new()
    p.parse(json)
    check((p.data as Dictionary)["gold"] == 999, "存档往返")
```

```bash
godot --headless --script tests/run_tests.gd
```

⚠ 退出码很重要：CI 靠它判断成败。失败必须 `quit(1)`。

## 4. 静态检查进 CI

**比测试更早发现问题。**

| 工具 | 用途 |
|---|---|
| `gdlint` (gdtoolkit) | 命名、代码质量、成员顺序 |
| `gdformat --check` | 格式一致性 |
| `gdstyle` | 56 条规则（命名/格式/顺序/质量） |
| `gdeye check` | 正确性 + 性能规则 |
| `godot-correctness-mcp` | Godot 运行时反模式（delta/await/节点查找等） |

```yaml
# .github/workflows/godot-ci.yml
name: Godot CI
on: [push, pull_request]

jobs:
  static:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install "gdtoolkit==4.*"
      - run: gdformat --check .
      - run: gdlint .

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: chickensoft-games/setup-godot@v2
        with: { version: '4.3' }
      - run: godot --headless -s addons/gut/gut_cmdln.gd -gtest=tests/ -gexit
```

⚠ `gdtoolkit` 的**大版本必须和 Godot 大版本一致**（Godot 4 用 4.*）。

⚠ 工具规则会误报。用行内抑制 + 说明原因，别批量关规则：

```gdscript
var _unused_but_needed := 0    # gdlint:ignore=unused-argument  引擎回调需要
```

## 5. 存档回归测试（最值得做的一条）

**旧版本存档能不能被新版正确读取** —— 上线后才发现就是灾难。

```
tests/saves/
├── v1/   （版本1 的存档样本）
├── v2/
└── v3/
```

```gdscript
func test_old_saves_load():
    for dir in ["v1", "v2", "v3"]:
        var path := "res://tests/saves/%s/save.dat" % dir
        var data := SaveManager.load_from(path)
        assert_true(data.size() > 0, "旧存档 %s 应能读取" % dir)
        assert_true(data.has("version"), "旧存档 %s 应有版本字段" % dir)
```

⚠ 每次发版把**当版本的存档样本**存一份进测试目录。
存档格式变动时，这些样本就是回归网。

## 6. 我们自己的审查脚本

仓库里 `code-audit/scripts/godot-audit.py` 可以进 CI：

```bash
python3 ../../code-audit/scripts/godot-audit.py --src=. --format=json > audit.json
# 有 P0 就失败
```

⚠ 先跑一次建立基线，**别一上来就要求 0 问题** —— 老项目会直接被 CI 卡死。
先只对新改动的文件严格，逐步收紧。

## 7. 上线前检查

- [ ] 纯逻辑（伤害、经济、背包、寻路）有单元测试
- [ ] 静态检查进 CI，且**误报已用行内抑制处理并写明原因**
- [ ] 存档回归测试覆盖了所有历史版本格式
- [ ] 冒烟测试：能启动、能进主菜单、能开始新游戏、能存档读档
- [ ] 测试用 `--headless` 跑，退出码正确
- [ ] release 导出后跑一遍（debug 能跑不代表 release 能跑）

## 8. 断言与退出码：测试有效的两个前提

测试写了、跑了、绿了 —— ⛔ **这三件事都不能证明测试在验证东西**。
有两个前提会让它静默失效，且都不报错。

**① ⛔ `assert()` 只在 debug 构建执行。**

官方原话：*"the code inside `assert()` is only executed in debug builds
or when running the project from the editor"*。

⛔ 用 `assert` 写断言、却在 **release 导出包**里跑测试 ——
断言整段被跳过，输出仍是"通过 100 / 失败 0"，
而实际一次都没验证。

ⓘ 注意它与 `push_error()` 的区别：后者是**报告**错误（不会让测试失败），
前者在 debug 下会**中断**。⛔ 用 push_error 替代 assert 并不会让测试变有效。

**② ⛔ `assert()` 内不能有副作用。**

官方原话：*"Don't include code that has side effects in an `assert()` call.
Otherwise, the project will behave differently when exported in release mode."*

⛔ `assert(take_damage(30) == 70)` —— release 下整个表达式不求值，
**被测函数根本没被调用**，而 debug 下完全正常。

**③ ⛔ 退出码要实测，不能假设 `quit(1)` 生效。**

官方仓库有 issue 记录 `--headless --script` 下 `quit(1)` **返回 0**
（GH-88055，4.2.1 / 4.2.2 可复现）。
⛔ 表现为"测试全红但 CI 全绿" —— 信号与事实相反。

ⓘ 该 issue 已关闭，**修复版本需实测确认**。
兜底做法是把失败数写进文件，CI 读文件判成败，⛔ 不单纯依赖进程退出码。

ⓘ 配套一条：回溯（backtrace）默认只在 editor / debug 构建可用，
release 需显式开启 `debug/settings/gdscript/always_track_call_stacks`。
⛔ 未开启时线上崩溃只有一句日志，本地却总能复现出堆栈。

## 9. 流程：按什么顺序做

→ `flow/godot/testing/`（7 个功能点）

⛔ 先定断言机制与退出码（01），再写测试（02）——
顺序反了会写出"跑了但什么都没验证"的测试。

> **反模式清单（不能怎么做，审核用）** → `audit/godot/testing.md`

