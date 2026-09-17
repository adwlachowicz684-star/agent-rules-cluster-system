#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
route.py —— 代码审查场景路由（精确辅助，非结论）

做什么：按**确定性信号**扫一遍仓库，输出「可能命中哪些风险场景 + 证据」。
不做什么：不替你下结论。输出必须经人工审核——可以剔、可以补、可以改优先级。

为什么要有它：AI 靠"这项目像有插件"是猜，脚本扫到 plugins/ 是事实。
脚本按目录/文件/正则机械扫一遍不会漏，人负责判断这些信号对不对。

信号分三级：
    [结构]  目录/文件/构建配置      —— 几乎不会错，直接采信
    [特征]  正则命中代码            —— 有命中即相关，但要看密度
    [文档]  README / 配置里的关键词  —— 弱信号，仅作提示

用法：
    python3 route.py --src=<根>
    python3 route.py --src=<根> --json
    python3 route.py --src=<根> --all          # 列出全部场景（含未命中）
    python3 route.py --src=<根> --min-hits=2   # 提高命中门槛（默认 1）
    python3 route.py --src=<根> --batch=6      # 每批加载数（默认 4）

输出示例：
    sandbox   [结构] plugins/(8) src-tauri/
              [特征] createObjectURL×3
    boundary  [特征] postMessage×12 addEventListener('message')×5
    ---
    命中 7 个 —— 全部都要审，分 2 批加载（每批 ≤4）

设计要点：**不设命中上限**。截断会漏检——大项目命中 10+ 是正常的。
改为分批：一批审完再加载下一批，既不漏又能保证每批读得深。
"""

import os
import re
import sys
import json

_args = [a for a in sys.argv[1:] if not a.startswith('--')]
_flags = [a for a in sys.argv[1:] if a.startswith('--')]

ROOT = None
for f in _flags:
    if f.startswith('--src='):
        ROOT = os.path.abspath(os.path.expanduser(f.split('=', 1)[1]))
if ROOT is None:
    ROOT = os.path.abspath('.')
AS_JSON = '--json' in _flags
SHOW_ALL = '--all' in _flags
MIN_HITS = 1
BATCH = 4
ITEMS = '--items' in _flags
LEVEL = ''
LIMIT = 0
for _f in _flags:
    if _f.startswith('--level='):
        LEVEL = _f.split('=', 1)[1].strip()
    elif _f.startswith('--limit='):
        try:
            LIMIT = int(_f.split('=', 1)[1])
        except ValueError:
            LIMIT = 0
for f in _flags:
    if f.startswith('--min-hits='):
        MIN_HITS = int(f.split('=', 1)[1])
    if f.startswith('--batch='):
        BATCH = int(f.split('=', 1)[1])

SKIP_DIRS = {'node_modules', 'dist', 'build', 'target', 'vendor', 'third_party',
             '.git', '.idea', '.vscode', '__pycache__', 'coverage', 'audit',
             '.next', '.cache', 'bin', 'obj'}
# .gd（GDScript）早先漏了 —— 于是 Godot 项目里 route.py 扫描到 0 个文件，
# 输出「未命中任何场景」，看起来像"这个项目没什么可审的"，
# 实际是路由压根没看 GDScript。与「扫描器不认某语言输出 0 命中」同一类失效。
SOURCE_EXT = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.rs', '.py',
              '.go', '.cpp', '.cc', '.c', '.h', '.java', '.kt', '.cs',
              '.gd')
MAX_BYTES = 600 * 1024
SCAN_LIMIT = 400          # 超过这个文件数就抽样，避免大仓库卡住

# ---------------------------------------------------------------- 场景定义
# signals: (信号类型, 判据, 展示名)
# ---- 条目级索引（可选依赖）----
# 索引缺失时路由照常工作，只是不输出条目建议——不因缺索引而报错。
# 场景 → 能精确定位的扫描器（有扫描器的场景不必整列条目）
SCENE_SCANNER = {
    's-numerics': 'scan-ts.py', 's-structures': 'scan-ts.py',
    's-lifecycle': 'scan-ts.py', 's-atomicity': 'scan-ts.py',
    's-state': 'scan-ts.py', 's-contracts': 'scan-ts.py',
    's-sandbox': 'scan-app.py', 's-boundary': 'scan-app.py',
    's-backend': 'scan-app.py', 's-build': 'scan-app.py',
    'p-python': 'scan-py.py', 'p-go': 'scan-go.py',
    's-architecture': 'scan-py.py',
    'p-java': 'scan-java.py', 'p-cpp': 'scan-cpp.py',
    'p-rust': 'scan-rust.py',
}

ITEM_IDX = None


def load_items():
    """读 rules/items.json。没有就返回 {}（不报错、不影响路由本身）。"""
    global ITEM_IDX
    if ITEM_IDX is not None:
        return ITEM_IDX
    p = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'rules', 'items.json'))
    try:
        ITEM_IDX = json.load(open(p, encoding='utf-8')) if os.path.isfile(p) else {}
    except (ValueError, OSError):
        ITEM_IDX = {}
    return ITEM_IDX


def items_for_scene(scene, level=None, limit=None, feats=None):
    """某场景的条目清单（只给 id/level/name，不含正文）。

    feats：路由在本场景命中的特征名（如 ['clamp', 'while', '除法/乘法']）。
    给了就**只返回与这些特征相关**的条目——否则一个场景动辄 12~19 条，
    全列出来等于整文件读，条目级索引就白做了。

    匹配方式：特征名 / 条目名 / 判据字段 / keywords 做子串匹配。
    """
    d = load_items()
    if not d or not d.get('items'):
        return []
    out = [i for i in d['items'] if i['scene'] == scene]
    if level:
        out = [i for i in out if i['level'] == level]

    # 无特征信号（只有结构命中，如 package.json）时不整列：
    # 也走 P0 起步集，跟「特征对不上」同一处理。
    if not feats:
        out = [i for i in out if i['level'] == 'P0']
    elif feats:
        # 只用「判据 / 特征 / 典型 / 正确」四个字段匹配。
        # 早先版本把 keywords 和所有字段都算进去，结果一个场景命中 13 条——
        # 因为 keywords 里全是 `loop` `size` 这类通用词，等于没筛。
        MATCH_FIELDS = ('判据', '特征', '典型', '正确')
        # feat 形如 `clamp×3` / `循环上界非字面量×1`——必须剥掉 `×N` 计数后缀。
        # 早先没剥，拿 `clamp×3` 去匹配条目，一条都对不上，
        # 于是静默回退到「全 P0」（13 条），条目级索引等于没生效。
        keys = [f.split('×')[0].strip().lower() for f in feats if f]
        keys = [k for k in keys if k]
        scored = []
        for i in out:
            parts = [i['name']]
            for k in MATCH_FIELDS:
                for v in (i.get('fields') or {}).get(k, []):
                    parts.append(v if isinstance(v, str) else ' '.join(v))
            hay = ' '.join(parts).lower()
            sc = sum(1 for k in keys if k and k in hay)
            if sc:
                scored.append((sc, i))
        if scored:
            scored.sort(key=lambda t: (-t[0], t[1]['level'], t[1]['id']))
            out = [i for _, i in scored]
        else:
            # 特征对不上任何条目 → 不瞎猜，给 P0 做起步集
            out = [i for i in out if i['level'] == 'P0']

    out.sort(key=lambda i: (i['level'], i['id']))
    return out[:limit] if limit else out


SCENES = [
    ('s-numerics', '数值与边界', 'P0 密度最高的一类，TS/JS 库几乎必中',
     [('dir', None, None),
      ('rx', r'\b(?:clamp|clamp01|Math\.max|Math\.min)\s*\(', 'clamp'),
      ('rx', r'\bfor\s*\(\s*let\s+i\s*=\s*\w+\s*;\s*i\s*<\s*[A-Za-z_]', '循环上界非字面量'),
      ('rx', r'\bwhile\s*\(', 'while'),
      ('rx', r'Number\.isFinite|isNaN', '有限性校验'),
      ('rx', r'(?:Math\.)?(?:PI|sin|cos|atan2|sqrt|pow|hypot)\b', '浮点运算'),
      ('rx', r'>>>\s*0|\|\s*0\b', '位运算取整'),
      ('rx', r'(?:/\s*\w+\s*|\*\s*\w+)\s*[;,)]', '除法/乘法')]),
    ('s-structures', '数据结构与内存', 'TypedArray / 对象池 / 分桶 / 裸对象查表',
     [('rx', r'new\s+(?:Float\d+Array|Uint\d+Array|Int\d+Array|ArrayBuffer)\s*\(', 'TypedArray'),
      ('rx', r'\b(?:prewarm|acquire|release)\s*\(|objectPool|ObjectPool', '对象池'),
      ('rx', r'new\s+Map\s*\(\s*\)', '分桶 Map'),
      ('rx', r'\b\w+\s*\[\s*\w*\s*\]\s*[+\-]?=', '裸对象查表'),
      ('rx', r'\.(?:split|join)\s*\(\s*[\'"]\.', '路径/复合 key'),
      ('rx', r'Object\.assign\s*\(|\.\.\.\w+', '对象合并')]),
    ('s-lifecycle', '生命周期与资源', '订阅 / 定时器 / 句柄 / 每帧回调',
     [('rx', r'addEventListener\s*\(|\.on\s*\(\s*[\'"]|subscribe\s*\(', '订阅'),
      ('rx', r'setInterval\s*\(|setTimeout\s*\(|schedule\s*\(', '定时器'),
      ('rx', r'createObjectURL\s*\(', 'objectURL'),
      ('rx', r'\b(?:update|tick|lateUpdate|onFrame)\s*\(', '每帧回调'),
      ('rx', r'\b(?:dispose|destroy|release|close|disconnect)\s*\(', '释放')]),
    ('s-contracts', '契约与承诺', '对外 API / 接口声明 / 文档承诺',
     [('file', 'README.md', 'README'),
      ('rx', r'\bexport\s+(?:interface|type|class|function|const)', '对外导出'),
      ('rx', r'@param|@returns|\* @', 'JSDoc'),
      ('dir', 'docs', 'docs 目录')]),
    ('s-state', '状态与配置', 'store / 序列化 / 快照',
     [('rx', r'localStorage|sessionStorage|JSON\.parse\s*\(', '持久化'),
      ('rx', r'\b(?:store|state|config|settings)\b', '状态字段'),
      ('rx', r'\b(?:store|Store|persist|hydrate)\s*[.(\[]', 'store 对象')]),
    ('s-atomicity', '原子性与安全判定', '多步写 / 批处理 / 权限判定',
     [('rx', r'\b(?:can|is|should|check|has)\w+\s*\([^)]*\)\s*(?::\s*boolean)?\s*\{', '判定函数'),
      ('rx', r'catch\s*\(\s*\w*\s*\)\s*\{\s*\}', '空 catch'),
      ('rx', r'\b(?:buy|sell|craft|transfer|deduct|add)\w*\s*\(', '交易类'),
      ('rx', r'(?:enabled|debug|cheat|devMode)\s*[:=]\s*true', '调试默认开')]),
    ('s-boundary', '跨边界通信', 'postMessage / IPC / 桥接 / iframe',
     [('rx', r'postMessage\s*\(', 'postMessage'),
      ('rx', r'addEventListener\s*\(\s*[\'"]message[\'"]', 'message 监听'),
      ('rx', r'\biframe\b|contentWindow|contentDocument', 'iframe'),
      ('rx', r'\b(?:invoke|listen|emit)\s*\(\s*[\'"]', 'IPC'),
      ('rx', r'\bbridge\b|__TAURI|__ELECTRON', '桥接')]),
    ('s-sandbox', '沙箱与权限', '插件 / 扩展 / 隔离 / CSP / 凭据',
     [('dir', 'plugins', 'plugins/'),
      ('dir', 'extensions', 'extensions/'),
      ('rx', r'Content-Security-Policy', 'CSP'),
      ('rx', r'sandbox\s*=|allow-scripts', 'sandbox 属性'),
      ('rx', r'\b(?:token|secret|password|credential|encrypt|decrypt)\b', '凭据'),
      ('rx', r'\b(?:isolat|隔离)\w*', '隔离')]),
    ('s-backend', '原生后端', 'Rust / C++ / Go、fs、进程、本地服务',
     [('dir', 'src-tauri', 'src-tauri/'),
      ('file', 'Cargo.toml', 'Cargo.toml'),
      ('rx', r'Command::new\s*\(|std::process', '进程执行'),
      ('rx', r'std::fs::|fs::read|std::fs::File', '文件操作'),
      ('rx', r'TcpListener|thread::spawn|tokio', '网络/线程')]),
    ('s-build', '构建与交付', '构建 / 打包 / CI / 依赖',
     [('file', 'package.json', 'package.json'),
      ('file', 'vite.config.*', 'vite 配置'),
      ('dir', '.github', 'CI'),
      ('file', '.gitignore', '忽略清单'),
      ('rx', r'frontendDist|\bfiles\s*:\s*\[', '打包范围')]),
    ('p-cocos', 'Cocos 平台', 'Cocos Creator 项目',
     [('file', 'cc.config.json', 'cc.config'),
      ('file', 'project.json', 'cocos project'),
      ('dir', 'assets', 'assets/'),
      ('rx', r"from\s+['\"]cc['\"]|cc\.Class|_decorator", 'cc 导入')]),
    ('p-godot', 'Godot 平台', 'Godot 4.x 项目（GDScript / C#）',
     [('file', 'project.godot', 'Godot 工程'),
      ('ext', '.gd', 'GDScript 文件'),
      ('rx', r'extends\s+(Node|Node2D|Node3D|Control|CharacterBody|RigidBody)\b',
       'Godot 脚本'),
      ('rx', r'using\s+Godot\s*;', 'Godot C#')]),
    ('p-python', 'Python 语言包', 'Python 语义特有缺陷（默认参数/异常隔离/资源配对）',
     [('ext', '.py', 'Python 文件'),
      ('file', 'requirements.txt', '依赖声明'),
      ('file', 'pyproject.toml', 'Python 项目'),
      ('file', 'setup.py', '打包配置'),
      ('rx', r'^\s*def\s+\w+\s*\([^)]*=\s*\[|^\s*def\s+\w+\s*\([^)]*=\s*\{',
       '可变默认参数'),
      ('rx', r'except\s*:|except\s+Exception\s*:', '宽泛异常')]),
    ('s-concurrency', '并发与生命周期', '共享状态 / 取消传播 / 任务泄漏 / 重试幂等',
     [('rx', r'\bThread\s*\(|threading\.|ThreadPoolExecutor|multiprocessing',
       'Python 线程'),
      ('rx', r'\bgo\s+func\s*\(|sync\.WaitGroup|context\.Context|\bchan\s',
       'Go 并发'),
      ('rx', r'\basyncio\.|await\s+\w+|create_task|ensure_future', 'Python 协程'),
      ('rx', r'new\s+Thread\s*\(|ExecutorService|CompletableFuture|synchronized',
       'Java 并发'),
      ('rx', r'std::thread|std::mutex|std::async|pthread_create', 'C++ 并发'),
      ('rx', r'\b(?:Lock|RLock|Semaphore|Condition|Event)\s*\(|mutex|atomic',
       '锁/同步原语')]),
    ('s-architecture', '架构可演进性',
     '改不动：防护顺序无保障 / 判定与输出耦合 / 跨实例串档 / 退出码不分类 / 测试焊死实现',
     [('rx', r'\bSystemExit\s*\(|sys\.exit\s*\(', '就地终止（非 CLI 层错误出口）'),
      ('rx', r'\b(?:OWNER|REPO|ROOT|STATE_PATH|BASE_DIR)\s*=', '模块级目标常量'),
      ('rx', r'if\s+__name__\s*==\s*["\']__main__["\']', 'CLI 入口'),
      ('rx', r'ALL PASS', '自定义测试通过标记'),
      ('rx', r'\bmod\.\w+\s*=|monkeypatch|mock\.patch', '打补丁替换模块全局'),
      ('file', 'conftest.py', 'pytest fixture 目录')]),
    ('p-rust', 'Rust 语言包',
     'Rust 语义特有缺陷（panic 静默化 / 整数回绕 / unsafe 契约 / 跨 await 持锁）',
     [('ext', '.rs', 'Rust 文件'),
      ('file', 'Cargo.toml', 'Rust 项目'),
      ('dir', 'src-tauri', 'Tauri 后端'),
      ('rx', r'#\[tauri::command\]|#\[command\]', 'Tauri 命令'),
      ('rx', r'\.unwrap\s*\(\s*\)|\.expect\s*\(', 'unwrap/expect'),
      ('rx', r'\bunsafe\s*(?:\{|\bfn\b)', 'unsafe 块')]),
    ('p-go', 'Go 语言包', 'Go 语义特有缺陷（goroutine 泄漏 / context 传播 / channel）',
     [('ext', '.go', 'Go 文件'),
      ('file', 'go.mod', 'Go 模块'),
      ('rx', r'\bgo\s+func\s*\(|\bgo\s+\w+\s*\(', 'goroutine'),
      ('rx', r'\bchan\s|make\s*\(\s*chan', 'channel')]),
    ('p-java', 'Java 语言包', 'Java 语义特有缺陷（资源关闭 / 线程池 / 中断语义）',
     [('ext', '.java', 'Java 文件'),
      ('file', 'pom.xml', 'Maven'),
      ('file', 'build.gradle', 'Gradle'),
      ('rx', r'ExecutorService|newFixedThreadPool|synchronized', '并发'),
      ('rx', r'catch\s*\(\s*(?:final\s+)?Exception\b', '宽泛异常')]),
    ('p-cpp', 'C/C++ 语言包', 'C/C++ 语义特有缺陷（所有权 / 越界 / 虚假唤醒）',
     [('ext', '.cpp', 'C++ 文件'),
      ('ext', '.c', 'C 文件'),
      ('file', 'CMakeLists.txt', 'CMake'),
      ('rx', r'\bnew\s+\w+|malloc\s*\(|std::thread|pthread_create', '分配/线程'),
      ('rx', r'strcpy\s*\(|sprintf\s*\(|memcpy\s*\(', '不安全内存函数')]),
]

# 结构信号：目录/文件存在即命中（最强）
STRUCT_DIRS = {'plugins': 's-sandbox', 'extensions': 's-sandbox',
               'src-tauri': 's-backend', 'docs': 's-contracts',
               '.github': 's-build', 'assets': 'p-cocos'}
STRUCT_FILES = {'Cargo.toml': 's-backend', 'README.md': 's-contracts',
                'package.json': 's-build', '.gitignore': 's-build',
                'cc.config.json': 'p-cocos',
                'project.godot': 'p-godot'}


# Godot API 领域二级路由。
#
# 为什么需要：八份 Godot API 查表文档（physics/ui/io/anim/3d/lang/navigation/render2d）合计约 7000 行，
# 命中 p-godot 就全读不现实。按代码里**实际出现**的 API 名只加载对应领域。
# 这是文档细化之后必须配套的收敛机制——否则"越详细"会变成"越贵"。
#
# 与 references/godot-api/index.md 的路由表保持一致，改一边要同步改另一边。
GODOT_API_DOMAINS = [
    ('物理', r'move_and_slide|CharacterBody|RigidBody|Area2D|AnimatableBody|StaticBody'
             r'|collision_layer|collision_mask|intersect_ray|intersect_shape|RayCast'
             r'|apply_impulse|apply_force|is_on_floor',
     'godot-api/physics.md'),
    ('UI/2D渲染', r'\bControl\b|\bLabel\b|\bButton\b|TextureRect|CanvasItem|CanvasGroup'
                  r'|CanvasLayer|Camera2D|Parallax2D|TileMap|Sprite2D|ShaderMaterial|queue_redraw',
     'godot-api/ui.md'),
    ('资源/IO/网络', r'ResourceLoader|ResourceSaver|FileAccess|DirAccess|PackedScene'
                     r'|instantiate|HTTPRequest|ConfigFile|JSON\.parse|var_to_bytes|bytes_to_var'
                     r'|user://|res://',
     'godot-api/io.md'),
    ('输入/音频/动画/Tween', r'Input\.|InputEvent|InputMap|AudioStreamPlayer|AudioServer'
                             r'|AnimationPlayer|AnimationTree|Tween|create_tween|SceneTreeTimer'
                             r'|\bTimer\b|_unhandled_input',
     'godot-api/anim.md'),
    ('3D/渲染', r'Node3D|MeshInstance3D|BaseMaterial3D|StandardMaterial3D|Camera3D'
               r'|Light3D|DirectionalLight3D|OmniLight3D|SpotLight3D|Environment'
               r'|WorldEnvironment|ReflectionProbe|VoxelGI|LightmapGI|SubViewport'
               r'|GPUParticles3D|ParticleProcessMaterial|\bShader\b'
               r'|set_shader_parameter',
     'godot-api/3d.md'),
    ('语言/工程/调试', r'@export|@onready|@tool|@rpc|class_name|emit\(|await\s'
                      r'|ProjectSettings|OS\.|Engine\.|Performance\.'
                      r'|change_scene|push_error|push_warning|print_debug'
                      r'|is_instance_valid|SceneTree',
     'godot-api/lang.md'),
]


def godot_domains(blob):
    """按 blob 里出现的 API 名，返回 [(领域, 命中数, 文件)]。只保留命中的。"""
    out = []
    for name, pat, doc in GODOT_API_DOMAINS:
        n = len(re.findall(pat, blob))
        if n:
            out.append((name, n, doc))
    out.sort(key=lambda x: -x[1])
    return out


def walk_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn.startswith('.'):
                continue
            p = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(p) > MAX_BYTES:
                    continue
            except OSError:
                continue
            if p.endswith(SOURCE_EXT) or fn in STRUCT_FILES or fn.endswith('.json'):
                out.append(p)
    return out


def route(root):
    files = walk_files(root)
    sampled = files
    if len(files) > SCAN_LIMIT:
        step = len(files) // SCAN_LIMIT
        sampled = files[::step][:SCAN_LIMIT]

    text = []
    for p in sampled:
        try:
            text.append(open(p, encoding='utf-8', errors='replace').read())
        except OSError:
            pass
    blob = '\n'.join(text)

    # 结构信号（目录名 / 文件名）
    top_dirs = set()
    for p in files:
        rel = os.path.relpath(p, root).replace('\\', '/')
        parts = rel.split('/')
        if len(parts) > 1:
            top_dirs.add(parts[0])
    top_files = {os.path.basename(p) for p in files}

    result = {}
    for sid, name, desc, signals in SCENES:
        ev_struct, ev_feat, ev_doc = [], [], []
        for kind, pat_or_name, label in signals:
            if kind == 'dir':
                if pat_or_name and pat_or_name in top_dirs:
                    n = len([p for p in files
                             if os.path.relpath(p, root).replace('\\', '/').startswith(pat_or_name + '/')])
                    ev_struct.append('%s/ (%d)' % (pat_or_name, n))
                elif pat_or_name is None:
                    continue
                elif pat_or_name in top_dirs:
                    ev_struct.append('%s/' % pat_or_name)
            elif kind == 'file':
                if pat_or_name in top_files:
                    ev_struct.append(pat_or_name)
                elif pat_or_name.startswith('*') and any(f.endswith(pat_or_name[1:]) for f in top_files):
                    ev_feat.append('%s（普遍存在，弱信号）' % pat_or_name)
            elif kind == 'ext':
                # 按扩展名计数：语言包靠它命中（.py 有多少个）
                n = len([p for p in files if p.endswith(pat_or_name)])
                if n:
                    ev_struct.append('%s (%d 个文件)' % (pat_or_name, n))
            elif kind == 'rx':
                n = len(re.findall(pat_or_name, blob))
                if n:
                    ev_feat.append('%s×%d' % (label, n))
        if ev_struct or ev_feat or ev_doc:
            result[sid] = {'name': name, 'desc': desc,
                           'struct': ev_struct, 'feat': ev_feat, 'doc': ev_doc}

    # p-godot 命中后才做 API 领域细分（否则白扫）。
    # 不能塞进 result：main() 会把 result 每项当场景打分，领域条目是 tuple 不是 dict。
    domains = godot_domains(blob) if 'p-godot' in result else []
    return files, sampled, result, domains


# 结构信号分级：目录/构建配置是强信号，README 这类几乎每个项目都有的是弱信号
STRONG_STRUCT = {'plugins/', 'extensions/', 'src-tauri/', 'Cargo.toml', 'cc.config.json'}

def score(item):
    """排序用。

    为什么**不**按特征命中总数排：`\b(?:store|state|config)\b` 这类宽泛正则
    在任何项目都能命中几百次，会把真正的项目特征（plugins/、src-tauri/）压下去。
    所以：结构信号 >> 特征种类数 >> 特征命中数（且对数压缩）。
    """
    st = sum(1000 if any(x.startswith(k) for k in STRONG_STRUCT) else 100
             for x in item['struct'])
    kinds = len(item['feat'])                                  # 命中几种不同特征
    n = sum(int(m.group(1)) for f in item['feat']
            for m in [re.search(r'\u00d7(\d+)', f)] if m)
    return st + kinds * 30 + int(10 * (1 + (n / 100.0 if n else 0)) ** 0.5)


def cmd_self_test():
    """路由条目建议的自检。

    为什么单独测：`--items` 的收窄逻辑踩过两个坑（feat 带 ×N 后缀、
    keywords 太宽泛），两者都表现为「静默回退到全 P0」——
    输出看起来正常，实际条目级索引完全没生效。不测根本发现不了。
    """
    ok = fail = 0

    def chk(cond, msg):
        nonlocal ok, fail
        print(('  ✓ ' if cond else '  ✗ ') + msg)
        if cond:
            ok += 1
        else:
            fail += 1

    d = load_items()
    chk(bool(d and d.get('items')), 'items.json 可读且有条目')

    # 1) feat 的 ×N 后缀必须被剥掉
    its = items_for_scene('s-numerics', None, None, ['clamp×3', '循环上界非字面量×1'])
    ids = [i['id'] for i in its]
    chk(0 < len(ids) < 13, '带 ×N 后缀的特征能收窄（得到 %d 条，未回退到全 P0 的 13 条）' % len(ids))

    # 2) 无特征信号时给 P0 起步集，不是全列
    its2 = items_for_scene('s-numerics', None, None, [])
    chk(all(i['level'] == 'P0' for i in its2) and len(its2) > 0,
        '无特征信号 → P0 起步集（%d 条，非全列 %d 条）'
        % (len(its2), len([i for i in d['items'] if i['scene'] == 's-numerics'])))

    # 3) 场景 → 扫描器映射覆盖所有有扫描器的场景
    miss = [k for k in SCENE_SCANNER
            if not os.path.isfile(os.path.join(os.path.dirname(
                os.path.abspath(__file__)), SCENE_SCANNER[k]))]
    chk(not miss, '场景→扫描器映射的文件都存在（缺: %s）' % (miss or '无'))

    print()
    print('自检：%d 通过 / %d 失败' % (ok, fail))
    if not fail:
        print('结论：路由条目建议工作正常')
    return 1 if fail else 0


def main():
    if '--self-test' in _flags:
        sys.exit(cmd_self_test())
    files, sampled, hits, godom = route(ROOT)
    ranked = sorted(hits.items(), key=lambda kv: -score(kv[1]))
    ranked = [(k, v) for k, v in ranked if score(v) >= MIN_HITS or v['struct']]

    if AS_JSON:
        out = [{'scene': k, 'name': v['name'], 'struct': v['struct'],
                'feat': v['feat'], 'score': score(v)}
               for k, v in ranked]
        if ITEMS:
            for o in out:
                o['items'] = [{'id': i['id'], 'level': i['level'], 'name': i['name']}
                              for i in items_for_scene(o['scene'], LEVEL,
                                                       LIMIT or None, o.get('feat'))]
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return

    print('route · 代码审查场景路由')
    print('根: %s   扫描文件: %d%s' % (ROOT, len(sampled),
                                    '（抽样，共 %d）' % len(files) if len(files) > len(sampled) else ''))
    print()
    if not ranked:
        print('未命中任何场景。跑 --all 看判据，或手工指定场景。')
        return
    for sid, v in ranked:
        print('%-14s %s' % (sid, v['name']))
        if v['struct']:
            print('   [结构] %s' % ' · '.join(v['struct'][:5]))
        if v['feat']:
            print('   [特征] %s' % ' · '.join(v['feat'][:6]))
    print()
    print('─' * 56)
    print('命中 %d 个 —— **全部都要审**，不设上限（截断会漏检）' % len(ranked))

    # Godot API 领域细分：八份查表文档约 7000 行，按实际 API 只加载命中的
    if godom:
        print()
        print('Godot API 领域（按代码里实际出现的 API 名，只加载这些）：')
        for name, n, doc in godom:
            print('  %-22s %3d 处 → references/%s' % (name, n, doc))
        print('  （未列出的领域说明代码里没用到，不必加载）')
    if len(ranked) <= BATCH:
        print('一批加载：%s' % ', '.join(k for k, _ in ranked))
    else:
        n = (len(ranked) + BATCH - 1) // BATCH
        print('分 %d 批加载（每批 ≤%d，避免一次读太多导致都读不深）：' % (n, BATCH))
        for i in range(n):
            chunk = ranked[i * BATCH:(i + 1) * BATCH]
            print('   第 %d 批  %s' % (i + 1, ', '.join(k for k, _ in chunk)))
        print('每批审完再加载下一批；审的过程中发现新特征 → 回头补加载（增量路由）')
    if ITEMS:
        print()
        print('─' * 56)
        print('判据条目建议：')
        allids, p0ids, scan_cmds = [], [], []
        for sid, v in ranked:
            its = items_for_scene(sid, LEVEL, LIMIT or None, v['feat'])
            sc = SCENE_SCANNER.get(sid)
            if sc:
                scan_cmds.append((sid, sc))
            if not its:
                continue
            ids = [i['id'] for i in its]
            allids += ids
            p0ids += [i['id'] for i in its if i['level'] == 'P0']
            print('  %-14s %s%s' % (sid, ' '.join(ids),
                                    '' if not sc else '   ← 可精确定位'))
        if scan_cmds:
            print()
            print('  更精准的做法（扫描器报哪条取哪条，比整列更省）：')
            for sid, sc in scan_cmds:
                print('    python3 scripts/%s --src=<根> --json > /tmp/%s.json' % (sc, sid))
                print('    python3 scripts/item-index.py --scan /tmp/%s.json' % sid)
        if allids:
            print()
            print('  直接取（%d 条）：' % len(allids))
            print('    python3 scripts/item-index.py --get %s' % ' '.join(allids))
            if p0ids and len(p0ids) < len(allids):
                print('  只看 P0（%d 条）：' % len(p0ids))
                print('    python3 scripts/item-index.py --get %s' % ' '.join(p0ids))
    print()
    print('⚠ 脚本只按信号机械扫描，输出的是候选。必须人工审核：')
    print('   · 可能漏（相关代码在没扫到的路径）→ 手动补')
    print('   · 可能多（只审前端却探测到 src-tauri/）→ 手动剔')
    print('   · 不设命中上限：大项目命中 10+ 是正常的，分批审完，不要截断')


if __name__ == '__main__':
    main()
