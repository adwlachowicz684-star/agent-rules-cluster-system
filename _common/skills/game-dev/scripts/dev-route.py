#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
游戏开发需求路由（dev-route.py）

与 code-audit 的 route.py 的区别：
    那边输入是**代码库**，输出"有哪些风险面"（找毛病）
    这边输入是**需求**，输出"该看哪个方案模板"（找做法）

路由是二维的：
    第 1 维  引擎（project.godot → Godot …）
    第 2 维  功能域（角色控制 / UI / 存档 / 动画 / 音频 / 3D / 网络）

用法：
    python3 scripts/dev-route.py --src=<项目根>              识别引擎 + 列出功能域
    python3 scripts/dev-route.py --src=<根> --need="角色跳跃"  按需求定位
    python3 scripts/dev-route.py --need="存档"                 不指定项目，只看需求
    python3 scripts/dev-route.py --json
    python3 scripts/dev-route.py --self-test

退出码：0
"""

import os
import re
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- 第 1 维：引擎识别 ----------
# 按"文件是否存在"判定，与 code-audit/route.py 的信号保持同源，
# 两边不一致会出现"审查认得出 Godot、开发认不出"。
ENGINES = [
    ('godot', 'Godot 4.x', ['project.godot'], ['.gd'],
     r'using\s+Godot\s*;|extends\s+(Node|Node2D|Node3D|CharacterBody|Control)\b',
     'references/godot/index.md'),
    ('unreal', 'Unreal', ['.uproject'], ['.uasset'],
     r'#include\s+"CoreMinimal\.h"|UCLASS\(|GENERATED_BODY',
     'references/unreal/index.md'),
    ('unity', 'Unity', [], ['.cs'],
     r'using\s+UnityEngine|MonoBehaviour',
     'references/unity/index.md'),
    ('cocos', 'Cocos Creator', ['cc.config.json'], ['.ts'],
     r"from\s+['\"]cc['\"]|_decorator",
     'references/cocos/index.md'),
]

# ---------- 第 2 维：功能域 ----------
# keywords 命中即算相关；命中多的排前面。
DOMAINS = [
    ('角色控制', ['跳跃', '移动', '控制器', 'platformer', '手感', '冲刺',
                 '爬墙', '二段跳', '角色', 'controller', 'movement', 'jump',
                 '第一人称', '第三人称', 'fps', 'tps'],
     'references/godot/character.md',
     'CharacterBody2D/3D · velocity · move_and_slide · 土狼时间 · 跳跃缓冲'),

    ('UI/菜单', ['ui', '界面', '菜单', 'hud', '血条', '背包', '物品栏',
                '对话框', '按钮', '设置面板', 'inventory', 'dialog', 'menu'],
     'references/godot/ui.md',
     '锚点约束 · CanvasLayer · GridContainer · 打字机 · 分辨率自适应'),

    ('存档/设置', ['存档', '读档', '保存', '设置', '进度', 'save', 'load',
                  'config', '持久化'],
     'references/godot/systems.md',
     'Resource + ResourceSaver · 原子写盘 · user:// · ConfigFile'),

    ('场景/流程', ['场景切换', '关卡', '过场', '淡入淡出', '加载界面',
                  'scene', 'level', 'transition'],
     'references/godot/systems.md',
     'change_scene_to_file · CanvasLayer 过场 · 切换时保留数据'),

    ('事件/架构', ['事件总线', '信号', '解耦', 'autoload', '单例', 'events',
                  'signal', '通信'],
     'references/godot/systems.md',
     'Events Autoload · 连接与断开配对 · 避免引用环'),

    ('对象池', ['对象池', '子弹', '大量生成', '复用', 'pool', 'bullet',
               '性能优化'],
     'references/godot/systems.md',
     'acquire/release · 状态重置 · 不用 queue_free 回收'),

    ('物理', ['碰撞', '射线', '射线检测', '物理', '推动', '重力', 'trigger',
             'raycast', 'collision', '刚体', '移动平台', '爆炸', '层'],
     'references/godot/physics.md',
     '碰撞层位掩码 · intersect_ray 参数对象 · Area 触发 · 施力 · AnimatableBody'),

    ('动画/缓动', ['动画', 'tween', '缓动', '过渡', '补间', 'animation',
                 '状态机', 'animationtree', '淡入淡出'],
     'references/godot/animation.md',
     'AnimationPlayer · AnimationTree 状态机 · Tween 链式 API · kill/bind_node'),

    ('输入/音频', ['输入', '按键', '手柄', '音效', '音乐', 'audio', 'input',
                  'bgm', 'sfx', '改键', 'inputmap', '音量'],
     'references/godot/input-audio.md',
     'Input Map 动作 · 四回调顺序 · 输入缓冲 · AudioServer 总线 · BGM 交叉淡入'),

    ('3D/渲染', ['3d', '材质', '光照', '相机', '着色器', '粒子', 'shader',
                'material', 'light', 'camera', '环境', '阴影', 'gi'],
     'references/godot/3d.md',
     '坐标系 · 第三人称相机 · 共享材质陷阱 · 三光源 · Environment · GPUParticles3D'),

    ('资源/IO/网络', ['资源加载', 'http', '网络', '多人', 'rpc', 'download',
                     '联机', '加载界面', '线程加载', 'api'],
     'references/godot/io-network.md',
     'load/preload · 线程加载带进度 · HTTPRequest · ENet 多人 · @rpc 校验'),

    ('AI/寻路', ['ai', '敌人', '寻路', '巡逻', '追击', '状态机', '避障',
                'navigation', 'pathfinding', 'astar', '视线', '感知', '群体'],
     'references/godot/ai-navigation.md',
     'NavigationAgent2D 模板 · 状态机巡逻追击攻击 · AStarGrid2D · 视线检测 · RVO 避障'),

    ('关卡/TileMap', ['tilemap', '图块', '地图', '关卡', '地形', '瓦片',
                     'tile', 'autotile', '程序化生成', '噪声', 'terrain'],
     'references/godot/tilemap.md',
     '4.3+ TileMapLayer vs 4.2 TileMap · 坐标转换 · 地形拼接 · 运行时生成'),

    ('2D渲染/特效', ['视差', 'parallax', 'ysort', '排序', '光照', '着色器',
                   'shader', '屏幕抖动', 'hitstop', '打击感', '溶解', '描边',
                   '转场', '扭曲', '闪白'],
     'references/godot/2d-rendering.md',
     'Y-Sort 结构 · Parallax2D · canvas_item shader 配方 · trauma 抖动 · hitstop'),

    ('移动端/触控', ['移动端', '手机', '平板', '触屏', '触控', '虚拟摇杆', '手势',
                   'android', 'ios', '多点触控', '摇杆', 'joystick', '捏合',
                   '安全区', '刘海', '返回键', '竖屏', '横屏', '权限',
                   '软键盘', '息屏', '虚拟按键', '触摸'],
     'references/godot/mobile.md',
     'ScreenTouch/Drag · 浮动虚拟摇杆 · 手势识别 · 安全区 · 返回键 · 移动端性能'),

    ('本地化技术', ['本地化', '多语言', '翻译', '国际化', 'i18n', 'l10n',
                  'tr(', 'trn', 'locale', '语言', '切换语言', '语言包',
                  '语种', '字体回退', '缺字', '方块', '豆腐块', 'rtl'],
     'references/godot/i18n.md',
     'tr()/tr_n() · CSV 工作流 · 语言切换与刷新 · 字体回退 · RTL'
     '（流程与术语表见独立 skill: localization）'),

    ('存档安全/防作弊', ['加密', '存档加密', '防作弊', '反作弊', '篡改', '签名',
                      'hmac', '抄档', '修改器', '作弊', '内存保护', '密钥',
                      '时间作弊', '倍速', '排行榜', '服务端校验', 'pck加密',
                      # 与「存档/设置」竞争的词必须更长，否则按长度加权会输
                      '改存档', '防改', '存档安全', '刷奖励', '每日奖励',
                      '系统时间', '改时间', '加固', '反外挂'],
     'references/godot/security.md',
     '客户端加密的边界 · AES+HMAC 存档 · 每文件随机 IV · 内存值混淆 · 检测后静默处理'),

    ('性能/优化', ['性能', '卡顿', '掉帧', '优化', 'profiler', 'drawcall',
                 '合批', '内存泄漏', '多线程', '线程池', 'workerthreadpool',
                 '剔除', '显存', '纹理压缩', '性能预算', '帧率'],
     'references/godot/performance.md',
     '先测量再优化 · Monitors 排查泄漏 · 屏幕外停处理 · StringName · 平方距离 · 线程池'),

    ('GDScript进阶', ['gdscript', '静态类型', '类型注解', 'stringname', 'await',
                    '生命周期', 'tool脚本', '信号写法', 'duplicate', '类型转换',
                    '热路径', 'onready'],
     'references/godot/gdscript-advanced.md',
     '类型系统 · 热路径禁止清单 · await 三坑 · 回调时机 · @tool 隔离 · 信号 4.x 写法'),

    ('架构/规范', ['架构', '项目结构', '成员顺序', '代码顺序', '组件', '组合',
                 '依赖注入', '通信', '代码组织', '规范', '重构', '耦合'],
     'references/godot/architecture.md',
     '17 步成员顺序 · call down signal up · 组件组合 · Resource 数据驱动 · 依赖注入'),

    ('测试/CI', ['测试', '单元测试', 'gut', 'ci', '回归', '自动化测试',
                '覆盖率', '存档兼容'],
     'references/godot/testing.md',
     'GUT 用法 · 无框架最小方案 · 静态检查进 CI · 存档回归测试 · 上线清单'),

    ('项目/工程', ['项目设置', '导出', 'debug', '断言',
                  'autoload', 'git', 'publish', '打包', 'gitignore'],
     'references/godot/project.md',
     '项目设置关键项 · Autoload · 导出清单 · gitignore'),
]

SKIP_DIRS = {'.git', '.godot', 'node_modules', 'build', 'builds', 'dist',
             'bin', 'obj', '.mono', '.vs', '.idea'}


def walk(root, limit=400):
    """采样源码文件，用于正则信号检测。"""
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in fns:
            if fn.startswith('.'):
                continue
            p = os.path.join(dp, fn)
            try:
                if os.path.getsize(p) > 400 * 1024:
                    continue
            except OSError:
                continue
            if re.search(r'\.(gd|cs|ts|cpp|h|tscn|json)$', fn, re.I):
                out.append(p)
                if len(out) >= limit:
                    return out
    return out


def detect_engine(root):
    """返回 [(引擎key, 名称, 入口, 证据)]，按证据强度排序。"""
    if not root or not os.path.isdir(root):
        return []
    top = os.listdir(root)
    files = walk(root)
    exts = set()
    for p in files:
        exts.add(os.path.splitext(p)[1].lower())
    blob = ''
    for p in files[:120]:
        try:
            blob += open(p, encoding='utf-8', errors='replace').read()
        except OSError:
            pass

    hits = []
    for key, name, cfg, sext, rx, entry in ENGINES:
        ev = []
        for c in cfg:
            if c in top:
                ev.append('%s 存在' % c)
        for e in sext:
            n = len([p for p in files if p.lower().endswith(e)])
            if n:
                ev.append('%s (%d 个)' % (e, n))
        m = len(re.findall(rx, blob))
        if m:
            ev.append('代码特征 ×%d' % m)
        if ev:
            hits.append((key, name, entry, ev))
    # 有配置文件的是强信号，排前面
    hits.sort(key=lambda x: (0 if any('存在' in e for e in x[3]) else 1,
                             -sum(1 for _ in x[3])))
    return hits


def match_domains(need):
    """按需求描述匹配功能域，返回 [(域名, 命中词, 入口, 说明)]。

    排序用「命中关键词的总长度」而不是「命中个数」。
    为什么：关键词之间有包含关系（"移动" ⊆ "移动端"），按个数排会让
    "移动端性能" 命中 "移动" 而路由到「角色控制」—— 用户想问移动端，
    却拿到角色移动模板，而且输出看起来完全正常。
    按长度加权后 "移动端"(3) 压过 "移动"(2)，指向正确。
    """
    if not need:
        return []
    low = need.lower()
    out = []
    for name, kws, entry, desc in DOMAINS:
        hit = [k for k in kws if k in low]
        if hit:
            # 同一域内去掉被更长命中词包含的短词，避免重复计分
            uniq = [k for k in hit if not any(k != o and k in o for o in hit)]
            out.append((name, hit, entry, desc, sum(len(k) for k in uniq)))
    out.sort(key=lambda x: -x[4])
    return [(n, h, e, d) for n, h, e, d, _ in out]


def cmd_self_test():
    ok = fail = 0

    def chk(cond, msg):
        nonlocal ok, fail
        print(('  ✓ ' if cond else '  ✗ ') + msg)
        if cond:
            ok += 1
        else:
            fail += 1

    # 需求路由：中文与英文都要能命中
    d = match_domains('我想做角色跳跃，手感要好')
    chk(bool(d) and d[0][0] == '角色控制', '中文"角色跳跃" → 角色控制')

    d = match_domains('做个 save 功能')
    chk(bool(d) and d[0][0] == '存档/设置', '英文"save" → 存档/设置')

    d = match_domains('背包界面怎么布局')
    chk(bool(d) and d[0][0] == 'UI/菜单', '"背包界面" → UI/菜单')

    # 多命中时按命中词数排序，不是固定顺序
    d = match_domains('角色移动和跳跃，还要碰撞检测')
    chk(len(d) >= 2, '复合需求能命中多个域（得到 %d 个）' % len(d))

    # 无关需求不该硬匹配
    chk(match_domains('今天天气怎么样') == [], '无关需求不误匹配')

    # 关键词子串碰撞：'移动' ⊆ '移动端'
    # 按命中个数排会让"移动端性能"路由到「角色控制」，输出看起来正常但全错
    d = match_domains('移动端性能')
    chk(bool(d) and d[0][0] == '移动端/触控',
        '"移动端性能" → 移动端/触控（长词压过"移动"，得到 %s）'
        % (d[0][0] if d else '无'))

    d = match_domains('角色移动')
    chk(bool(d) and d[0][0] == '角色控制', '"角色移动" → 角色控制（未被"移动端"抢走）')

    # 英文关键词大小写不敏感
    d = match_domains('HTTP request')
    chk(bool(d) and d[0][0] == '资源/IO/网络', '大写 HTTP 也能命中')

    # 引擎识别：Godot 目录
    import tempfile
    import shutil
    tmp = tempfile.mkdtemp(prefix='devroute-')
    try:
        open(os.path.join(tmp, 'project.godot'), 'w').write('config_version=5\n')
        os.makedirs(os.path.join(tmp, 'scripts'))
        open(os.path.join(tmp, 'scripts', 'a.gd'), 'w').write('extends Node2D\n')
        e = detect_engine(tmp)
        chk(bool(e) and e[0][0] == 'godot', 'project.godot + .gd → godot（排第一）')

        # 空目录不崩
        empty = tempfile.mkdtemp(prefix='devroute-empty-')
        chk(detect_engine(empty) == [], '空目录不误判引擎')
        shutil.rmtree(empty, ignore_errors=True)

        # 不存在的路径不崩
        chk(detect_engine('/nonexistent/path/xyz') == [], '路径不存在不崩')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print('自检：%d 通过 / %d 失败' % (ok, fail))
    if not fail:
        print('结论：开发路由工作正常')
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default='', help='项目根目录')
    ap.add_argument('--need', default='', help='需求描述，如"角色跳跃""存档"')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    a = ap.parse_args()

    if a.self_test:
        sys.exit(cmd_self_test())

    root = a.src
    if root and not os.path.isdir(root):
        sys.exit('路径不存在或不是目录：%s' % root)

    engines = detect_engine(root)
    domains = match_domains(a.need)

    if a.json:
        print(json.dumps({
            'engines': [{'key': k, 'name': n, 'entry': e, 'evidence': ev}
                        for k, n, e, ev in engines],
            'domains': [{'name': n, 'hits': h, 'entry': e, 'desc': d}
                        for n, h, e, d in domains],
        }, ensure_ascii=False, indent=2))
        return

    print('=' * 60)
    print('游戏开发路由')
    if root:
        print('根: %s' % root)
    if a.need:
        print('需求: %s' % a.need)
    print('=' * 60)

    print('\n【第 1 维】引擎')
    if engines:
        for k, n, entry, ev in engines:
            print('  %-8s %-12s %s' % (k, n, ' · '.join(ev[:3])))
            print('           入口: %s' % entry)
    else:
        print('  未识别。没有 --src 或项目里没有已知引擎的配置文件。')
        print('  → 先问用户用什么引擎，别猜。猜错整套模板作废。')

    print('\n【第 2 维】功能域')
    if domains:
        for n, hits, entry, desc in domains:
            print('  %-12s 命中 %s' % (n, '·'.join(hits[:4])))
            if entry:
                print('               → %s' % entry)
            else:
                print('               → %s' % desc)
            if entry:
                print('               %s' % desc)
    else:
        print('  （未给 --need，或需求没匹配到）')
        print('  可用功能域：%s' % ' · '.join(d[0] for d in DOMAINS))

    print('\n' + '-' * 60)
    print('模板是起点不是终点：必须按项目实际约束调整（2D/3D、单人/联网、目标平台）。')
    print('写完代码想检查有没有坑 → 用 code-audit。')


if __name__ == '__main__':
    main()
