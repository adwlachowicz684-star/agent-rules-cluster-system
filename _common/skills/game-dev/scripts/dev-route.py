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
    ('角色控制', ['跳跃', '移动', '控制器', 'platformer', '手感', '冲刺', '爬墙', '二段跳', '角色', 'controller', 'movement', 'jump', '第一人称', '第三人称', 'fps', 'tps'],
     'references/godot/character.md',
     'CharacterBody2D/3D · velocity · move_and_slide · 土狼时间 · 跳跃缓冲'),
    ('UI/菜单', ['ui', '界面', '菜单', 'hud', '血条', '背包', '物品栏', '对话框', '按钮', '设置面板', 'inventory', 'dialog', 'menu'],
     'references/godot/ui.md',
     '锚点约束 · CanvasLayer · GridContainer · 打字机 · 分辨率自适应'),
    ('存档/设置', ['存档', '读档', '保存', '设置', '进度', 'save', 'load', 'config', '持久化'],
     'references/godot/systems.md',
     'Resource + ResourceSaver · 原子写盘 · user:// · ConfigFile'),
    ('场景/流程', ['场景切换', '关卡', '过场', '淡入淡出', '加载界面', 'scene', 'level', 'transition'],
     'references/godot/systems.md',
     'change_scene_to_file · CanvasLayer 过场 · 切换时保留数据'),
    ('事件/架构', ['事件总线', '信号', '解耦', 'autoload', '单例', 'events', 'signal', '通信'],
     'references/godot/systems.md',
     'Events Autoload · 连接与断开配对 · 避免引用环'),
    ('对象池', ['对象池', '子弹', '大量生成', '复用', 'pool', 'bullet'],
     'references/godot/systems.md',
     'acquire/release · 状态重置 · 不用 queue_free 回收'),
    ('物理', ['碰撞', '射线', '射线检测', '物理', '推动', '重力', 'trigger', 'raycast', 'collision', '刚体', '移动平台', '爆炸', '层'],
     'references/godot/physics.md',
     '碰撞层位掩码 · intersect_ray 参数对象 · Area 触发 · 施力 · AnimatableBody'),
    ('动画/缓动', ['动画', 'tween', '缓动', '过渡', '补间', 'animation', '淡入淡出', 'animationplayer'],
     'references/godot/animation.md',
     'AnimationPlayer · AnimationTree 状态机 · Tween 链式 API · kill/bind_node'),
    ('输入/音频', ['输入', '按键', '手柄', '音频', '声音', 'audio', 'input', 'bgm', 'sfx', 'inputmap', '音量'],
     'references/godot/input-audio.md',
     'Input Map 动作 · 四回调顺序 · 输入缓冲 · AudioServer 总线 · BGM 交叉淡入'),
    ('3D/渲染', ['3d', '材质', '光照', '相机', '粒子', 'material', 'light', 'camera', '环境', '阴影', 'gi'],
     'references/godot/3d.md',
     '坐标系 · 第三人称相机 · 共享材质陷阱 · 三光源 · Environment · GPUParticles3D'),
    ('资源/IO/网络', ['资源加载', 'http', 'download', '加载界面', '线程加载', 'api', '文件读写', 'json', '存档文件'],
     'references/godot/io-network.md',
     'load/preload · 线程加载带进度 · HTTPRequest · 文件读写 · JSON'),
    ('AI/寻路', ['ai', '敌人', '寻路', '巡逻', '追击', '状态机', '避障', 'navigation', 'pathfinding', 'astar', '视线', '感知', '群体'],
     'references/godot/ai-navigation.md',
     'NavigationAgent2D 模板 · 状态机巡逻追击攻击 · AStarGrid2D · 视线检测 · RVO 避障'),
    ('关卡/TileMap', ['tilemap', '图块', '瓦片', 'autotile', 'terrain', 'tile', '地形'],
     'references/godot/tilemap.md',
     '4.3+ TileMapLayer vs 4.2 TileMap · 坐标转换 · 地形拼接 · 运行时生成'),
    ('2D渲染/特效', ['视差', 'parallax', 'ysort', '排序', '光照', '着色器', '屏幕抖动', 'hitstop', '溶解', '描边', '转场', '扭曲', '闪白', '2d渲染', '2D渲染', 'y sort', 'ysort'],
     'references/godot/2d-rendering.md',
     'Y-Sort 结构 · Parallax2D · canvas_item shader 配方 · trauma 抖动 · hitstop'),
    ('移动端/触控', ['移动端', '手机', '平板', '触屏', '触控', '虚拟摇杆', '手势', 'android', '多点触控', '摇杆', 'joystick', '捏合', '安全区', '刘海', '返回键', '竖屏', '横屏', '权限', '软键盘', '息屏', '虚拟按键', '触摸'],
     'references/godot/mobile.md',
     'ScreenTouch/Drag · 浮动虚拟摇杆 · 手势识别 · 安全区 · 返回键 · 移动端性能'),
    ('本地化技术', ['本地化', '多语言', '翻译', '国际化', 'i18n', 'l10n', 'tr(', 'trn', 'locale', '语言', '切换语言', '语言包', '语种', '字体回退', '缺字', '方块', '豆腐块', 'rtl'],
     'references/godot/i18n.md',
     'tr()/tr_n() · CSV 工作流 · 语言切换与刷新 · 字体回退 · RTL（流程与术语表见独立 skill: localization）'),
    ('存档安全/防作弊', ['加密', '存档加密', '防作弊', '反作弊', '篡改', '签名', 'hmac', '抄档', '修改器', '作弊', '内存保护', '密钥', '时间作弊', '倍速', '排行榜', '服务端校验', 'pck加密', '改存档', '防改', '存档安全', '刷奖励', '每日奖励', '系统时间', '改时间', '加固', '反外挂'],
     'references/godot/security.md',
     '客户端加密的边界 · AES+HMAC 存档 · 每文件随机 IV · 内存值混淆 · 检测后静默处理'),
    ('性能/优化', ['性能', '卡顿', '掉帧', '优化', 'profiler', 'drawcall', '合批', '多线程', '线程池', 'workerthreadpool', '剔除', '显存', '纹理压缩', '性能预算', '帧率'],
     'references/godot/performance.md',
     '先测量再优化 · Monitors 排查泄漏 · 屏幕外停处理 · StringName · 平方距离 · 线程池'),
    ('GDScript进阶', ['gdscript', '静态类型', '类型注解', 'stringname', 'await', '生命周期', 'tool脚本', '信号写法', 'duplicate', '类型转换', '热路径', 'onready'],
     'references/godot/gdscript-advanced.md',
     '类型系统 · 热路径禁止清单 · await 三坑 · 回调时机 · @tool 隔离 · 信号 4.x 写法'),
    ('架构/规范', ['架构', '项目结构', '成员顺序', '代码顺序', '组件', '组合', '依赖注入', '通信', '代码组织', '规范', '重构', '耦合'],
     'references/godot/architecture.md',
     '17 步成员顺序 · call down signal up · 组件组合 · Resource 数据驱动 · 依赖注入'),
    ('测试/CI', ['测试', '单元测试', 'gut', 'ci', '回归', '自动化测试', '覆盖率', '存档兼容'],
     'references/godot/testing.md',
     'GUT 用法 · 无框架最小方案 · 静态检查进 CI · 存档回归测试 · 上线清单'),
    ('多人/网络', ['多人', '联机', '网络', 'rpc', '服务器', '服务端', '权威', '同步', '延迟', 'peer', 'enemy', '专用服务器', 'headless', 'authority'],
     'references/godot/multiplayer.md',
     '服务器权威 · @rpc 参数 · 输入上报+序号 · 预测回滚 · 快照插值 · authority 迁移 · 专用服务器'),
    ('游戏系统', ['对话', '任务', '库存', '背包', '物品', '对话树', 'quest', 'inventory', 'dialogue', '支线', '奖励', '掉落'],
     'references/godot/game-systems.md',
     '命令解释器白名单 · 对话图+Runner · 任务定义/进度分离 · 库存四层 · 奖励幂等'),
    ('高级主题', ['程序化生成', '随机地图', '地牢', '噪声', 'plugin', '导入管线', '资源导入', '波前'],
     'references/godot/advanced-topics.md',
     '确定性生成 · BSP+连通性校验 · EditorPlugin 生命周期 · 资源三层隔离 · XR 性能预算'),
    ('渲染进阶', ['传送', 'lod', 'shader预热', '着色器预热', '变体预热', '头显', '管线编译', '大世界', '分块', 'chunk', '流式加载', 'hloD'],
     'references/godot/rendering-advanced.md',
     'XR 手部/抓握/传送 · LOD 四层 · visibility_range · 着色器管线预热 · 分块流式'),
    ('AI行为/决策', ['行为树', 'bt', 'goap', '效用', 'limboai', 'beehave', '黑板', 'blackboard', '决策', 'selector', 'sequence'],
     'references/godot/ai-behavior.md',
     'FSM/BT/GOAP/效用选型 · 最小行为树实现 · 黑板 · RUNNING 语义 · 插件对比'),
    ('高级测试', ['属性测试', '模糊测试', 'fuzz', '视觉回归', '截图对比', '性能基准', 'benchmark', '确定性测试'],
     'references/godot/testing-advanced.md',
     '属性/不变量 · 存档模糊 · 截图 diff · p99 帧时间基准 · 确定性回放'),
    ('调试/排错', ['调试', '断点', 'debugger', '崩溃', '卡死', '卡住', '空引用', 'null', '排查', '定位问题', 'stderr', 'push_error', 'profiler', '瓶颈', '内存泄漏', '日志'],
     'references/godot/debugging.md',
     '断点两种断点区别 · 多线程断点失效 · release 日志差异 · CPU/GPU 瓶颈判定 · 故障定位流程'),
    ('CI/发布', ['ci', '持续集成', 'github action', '流水线', 'pipeline', 'artifact', '无头', 'headless', '打包体积', 'ci签名', 'ci导出', '自动构建', '构建产物'],
     'references/godot/cicd-publish.md',
     '无头导入 · 完整 Actions 配置 · 产物非空校验 · 模板版本匹配 · 各平台签名 · 凭据走 Secret'),
    ('C#/.NET', ['c#', 'csharp', '.net', 'dotnet', 'nuget', 'net8', 'msbuild', 'rider', 'visual studio', 'marshalling', 'c#还是gdscript', 'gdscript还是c#', '语言选型', '该用c#', '选c#'],
     'references/godot/csharp.md',
     'C#/GDScript 选型 · .NET 版本政策表 · PascalCase 生命周期 · Signal 委托命名 · await 守卫'),
    ('版本/迁移', ['迁移', '升级', '版本兼容', 'godot4.3', 'godot4.4', '3.x', 'tilemaplayer', 'deprecated', '弃用', '改名', 'randomize', 'tilemap迁移', '升级tilemap', '节点改名', 'api变化', '引擎升级'],
     'references/godot/version-migration.md',
     '4.x 各版本结构变化 · TileMap 三重迁移 · 3→4 改名对照 · 锁 commit · 升级检查清单'),
    ('插件生态', ['插件', 'asset library', 'dialogic', '第三方库', '轮子', '依赖引入', '许可证', 'mit', '是否该自己写'],
     'references/godot/plugins.md',
     '决策口诀 · 按环节取舍表 · 绝不引入的 8 种情况 · 引入检查清单 · 锁 commit'),
    ('着色器', ['shader', 'gdshader', '着色器', 'glsl', 'spirv', 'uniform', 'varying', 'fragment', 'vertex shader', '卡通渲染', 'toon', '描边', '溶解', '边缘光', 'rim', '后处理', 'post process', 'hint_', 'source_color', 'visualshader', '三平面', 'triplanar', 'shader怎么写', '着色器性能', 'render_mode', '精度限定符', 'compute shader', '深度纹理'],
     'references/godot/shaders.md',
     'GDShader 方言 · uniform 提示清单 · 2D/3D 九个配方 · 坐标空间 · 变体与预热 · 调试颜色 mask'),
    ('动画高级', ['animationtree', 'blendspace', 'blend tree', '混合空间', '根运动', 'root motion', 'ik', '反向动力学', 'skeletonik', '骨骼动画', '分层动画', '动画遮罩', 'switch_mode', 'travel', '动画状态机深入', 'animationtree状态机', '动画树', '混合空间', '动画状态机', '动画树状态机'],
     'references/godot/animation-advanced.md',
     'StateMachine/BlendSpace/BlendTree 分工 · travel vs start · switch_mode 是过渡时机 · 根运动双倍位移 · IK 开销'),
    ('音频高级', ['audioserver', '音频总线', 'bus', 'linear_to_db', '分贝', '音效池', '交叉淡入', '动态音乐', '空间音效', '3d音效', 'ogg', 'wav', '混响', '响度'],
     'references/godot/audio-advanced.md',
     '总线架构 · 音量是分贝不是 0-1 · 音效池轮转 · 动态音乐分层 · 暂停 process_mode'),
    ('开放世界', ['开放世界', '大世界', '流式加载', 'chunk', '地形', 'terrain', 'lod', '大世界坐标', '原点重置', 'floating origin', '精度', '剔除', 'culling', '卸载半径', '双精度', '开放世界地形', '大型地形', '地形系统'],
     'references/godot/openworld.md',
     'chunk 三半径滞回 · 分帧预算 · 节点池 · Terrain3D · 大世界坐标精度 · 原点重置实现'),
    ('XR/VR', ['xr', 'vr', 'ar', 'openxr', '头显', 'quest', '手柄', '控制器', '传送', 'xrorigin', 'xrcamera', '手部追踪', 'xr基础', 'xr场景', '头显基础'],
     'references/godot/xr.md',
     '内置节点四件套 · 不能接管相机 · 无速度 API 需自算 · 抓取速度传递 · 晕动症规避'),
    ('4.7/4.8版本', ['4.7', '4.8', '版本', '升级', '迁移', 'breaking', 'breaking change', 'arealight', '面光源', 'hdr输出', 'offset_transform', 'virtualjoystick', '虚拟摇杆', 'drawabletexture', '纹理流送', 'texture streaming', 'tween_await', 'device_id', 'jolt'],
     'references/godot/version-47-48.md',
     '4.7.2 当前稳定 / 4.8 仍 dev · AreaLight3D · HDR 输出 · Control offset_transform · 内置 VirtualJoystick · break changes'),
    ('网络同步进阶', ['预测', '回滚', 'reconciliation', '插值', '插值延迟', '锁步', 'lockstep', 'tick', '快照', 'enet', 'websocket', 'webrtc', 'nat', '打洞', '服务器权威', '延迟补偿', 'multiplayersynchronizer', '服务器回滚', '锁步同步', '确定性锁步', '客户端预测', '实体插值', '同步模型'],
     'references/godot/netsync-advanced.md',
     '同步模型选型 · 客户端预测+输入历史 · 服务器回滚重放(固定dt+阈值) · 远端插值 · rpc 默认 reliable · 传输层取舍'),
    ('GDExtension/插件', ['c++', 'cpp', 'abi', '绑定', 'native', '热重载', '自定义导入器', '自定义检视器插件', 'rust', 'gdext'],
     'references/godot/gdext-plugin.md',
     '先 profile 再换语言 · 版本+浮点精度是 ABI · 4.0→4.1 硬断裂 · 热重载仅编辑器 · @tool 必备 + _exit_tree 对称注销'),
    ('战斗系统', ['战斗', '伤害', '命中判定', 'hitbox', 'hurtbox', '帧数据', '打击感', 'hitstop', '暴击', '格挡', '闪避', 'buff', 'debuff', 'dot', '技能', '冷却', '连招', '取消', 'combat', 'damage', 'attack', 'knockback'],
     'references/godot/combat.md',
     '四层分离 · AttackContext 去重 · 判定放物理帧 · hitbox 默认关 · hitstop 不用 await'),
    ('数据分析/埋点', ['埋点', '数据分析', 'analytics', 'telemetry', '事件上报', '漏斗', '留存', '流失', '难度调优', 'ab测试', '热力图', 'session', 'player_id', '批量上报'],
     'references/godot/analytics.md',
     'object_verb 命名 · 离线优先缓存 · 批量上报 · 不用设备ID · 每步引导埋点'),
    ('渲染管线', ['渲染器', '渲染管线', 'forward+', 'mobile渲染', 'compatibility', '后处理', 'post process', 'bloom', 'glow', 'dof', 'ssao', 'ssr', 'drawcall', '批处理', '实例化', 'compositor', '色调映射'],
     'references/godot/render-pipeline.md',
     '三渲染器能力矩阵 · Web只能Compatibility · 性能曲线反直觉 · 自动实例化仅Forward+'),
    ('光照', ['光照', 'gi', '烘焙', 'lightmap', 'voxelgi', 'sdfgi', '阴影', 'shadow', 'acne', 'peter-panning', 'bias', 'pssm', 'cascade', '体积雾', '体积光', 'fog', 'arealight', '面光源', 'light'],
     'references/godot/lighting.md',
     '三种GI选型 · 烘焙六步与失败码 · bias权衡 · 体积雾仅Forward+'),
    ('美术资产', ['美术', '资产管线', '纹理', '导入设置', 'filter', 'repeat', 'mipmap', '像素', '图集', 'atlas', '纹理压缩', 'basis universal', 'pbr', '法线贴图', '字体', '子集化', 'msdf', '九宫格', 'asset'],
     'references/godot/art-assets.md',
     'Filter/Repeat/Mipmap 三开关 · 像素糊的五个原因 · 压缩按用途分层 · 中文要子集化'),
    ('相机/过场', ['相机', 'camera', '跟随', '死区', '前瞻', '屏震', 'trauma', 'springarm', '第三人称', '过场', 'cutscene', '黑边', 'letterbox', '跳过大', '控制权移交'],
     'references/godot/camera-cutscene.md',
     '相机分层 · 帧率无关lerp · trauma平方衰减 · 过场三要素同状态机'),
    ('引导/成就', ['新手引导', '引导', 'tutorial', 'onboarding', '成就', 'achievement', '排行榜', 'leaderboard', '统计', 'mod', '模组', '高亮遮罩', '挖洞', '解锁'],
     'references/godot/onboarding-meta.md',
     '引导必须超时兜底 · 九宫格挖洞 · 成就定义与状态分离 · Godot无内置Steam成就'),
    ('平台导出/发布', ['导出', '发布', '上线', '打包', 'export', 'apk', 'aab', '签名', '公证', 'notarize', 'staple', 'provisioning', '证书', 'app store', 'google play', 'web导出', 'ios', 'ios导出', 'ios上架', 'android导出', 'wasm', 'coop', 'coep', 'sharedarraybuffer', 'ndk', 'gradle', '导出模板', 'keystore', 'windows导出', 'macos导出', 'linux导出', 'android签名', 'ios签名', 'android导出', 'ios导出', 'ios上架', 'windows签名', 'macos签名', '导出签名', '打包签名', '上架签名', '发布签名'],
     'references/godot/platform-export.md',
     '各平台速查表 · Web仅Compatibility · 多线程需COOP+COEP · NDK必须r28b · keystore丢了包名报废'),
    ('GDExtension实战', ['gdextension', 'godot-cpp', 'sconstruct', 'entry_symbol', 'bind_method', 'add_property', 'gdclass', 'gdregister', 'register_types', 'ref<T>', 'memnew', 'c++扩展', 'native扩展', '编译扩展', '.gdextension', 'cpp扩展'],
     'references/godot/gdextension-deep.md',
     'pin到4.7同步commit · entry_symbol严格匹配 · 只在SCENE层注册 · RefCounted必须Ref<T>'),
    ('编辑器插件开发', ['编辑器插件', 'editorplugin', 'undoredo', '撤销', '自定义检视器', 'inspectorplugin', '自定义导入', 'importplugin', 'editordock', 'add_dock', 'tool注解', '插件发布', 'asset library'],
     'references/godot/editor-plugin.md',
     'enter/exit_tree对称注销 · is_editor_hint≠跑游戏 · get_undo_redo按对象选历史 · 4.7统一EditorDock'),
    ('项目/工程', ['项目设置', '导出', 'debug', '断言', 'autoload', 'git', 'publish', '打包', 'gitignore'],
     'references/godot/project.md',
     '项目设置关键项 · Autoload · 导出清单 · gitignore'),
    ('XR深入/手部交互', ['xr深入', '手部追踪', '手部', '关节', '捏合', 'pinch', '抓取', 'grab', 'openxr', 'xrtools', 'steamvr', 'quest', '头显', '晕动症', '传送', 'snap turn', '隧道视野', '空间ui', 'xr性能', '6dof', 'xrcontroller', '手部追踪', '手部交互', '捏合检测', '抓取物体', 'grab系统', 'xr抓取'],
     'references/godot/xr-deep.md',
     'XRCamera3D会滞后几毫秒 · 抓取不能reparent刚体 · 控制器无速度API需自己差分 · 优先传送'),
    ('性能剖析/平台差异', ['性能剖析', 'profiler', '剖析', 'monitors', '监视器', '帧预算', 'p99', '掉帧', '热节流', 'throttling', 'tile gpu', 'gpu bound', 'cpu bound', 'drawcall预算', '显存', 'vram', '性能优化深入', '瓶颈定位', '过温', '降频', 'profiler怎么用', '性能剖析', '剖析器', '热节流', 'throttling', 'drawcall预算', 'gpu bound', 'cpu bound', '瓶颈定位', 'p99', '掉帧分析'],
     'references/godot/perf-profiling.md',
     '编辑器FPS不代表目标设备 · P99才是卡顿指标 · Profiler不覆盖C# · 移动端要测10分钟'),
    ('程序化生成', ['程序化生成', 'pcg', 'procedural', '随机地图', '关卡生成', '地图生成', '地牢生成', 'bsp', '迷宫', '元胞自动机', 'wfc', 'wave function', '泊松', 'poisson', '种子', 'seed', '随机种子', '连通性', 'flood fill', 'roguelike', '无尽关卡', '随机地牢', '地牢生成'],
     'references/godot/procedural-generation.md',
     '没seed无法维护 · 全局randi是全局状态 · 元胞自动机最易不可达 · 分帧要先纯数据算完 · ±10⁷是精度问题'),
    ('AI感知', ['ai感知', '感知系统', '视锥', '视野', '视线', '遮挡检测', '听觉', '声音传播', '察觉', '警戒等级', '最后已知位置', '目标选择', '感知记忆', '敌人发现玩家', 'vision cone', 'perception', '敌人视野', '敌人发现', '察觉玩家', '感知目标'],
     'references/godot/ai-perception.md',
     '感知≠寻路 · 输出不是bool要有置信度 · 遮挡必须射线 · 4.x要PhysicsRayQueryParameters3D · 检测10Hz够'),
    ('骨骼动画/IK', ['骨骼', 'skeleton', '蒙皮', 'skinning', 'ik', '反向动力学', 'two bone', 'twoBone', 'lookat modifier', '布娃娃', 'ragdoll', 'spring bone', '重定向', 'retarget', 'bone', '骨骼动画'],
     'references/godot/animation-skeletal.md',
     '骨骼是有序数组非节点 · 4.7无PoleModifier3D/SplineIK3D · modifier顺序由子节点列表定 · 每帧回滚'),
    ('数据驱动/配表', ['配表', '策划配表', '数据表', '配置表', 'csv导入', 'excel导入', '数据驱动', 'resource配表', 'tres', 'id常量', '外键校验', '导入器', 'importplugin', '热重载配表', 'sqlite'],
     'references/godot/datatable.md',
     '数值写代码=程序员成瓶颈 · duplicate()默认浅拷贝共享子资源 · 外键存ID不存引用 · 导入期要校验 · load_threaded才是异步'),
    ('VFX/游戏感', ['vfx', '特效', '粒子', 'gpuparticles', 'cpuparticles', '打击感', '游戏感', 'juice', '命中反馈', '屏幕震动', '震屏', 'trauma', '顿帧', 'hitstop', '拖尾', '残影', '白闪', '伤害数字', '打击感', '顿帧', 'hitstop实现', '命中感'],
     'references/godot/vfx-feel.md',
     'GPU粒子不是默认答案(Web/兼容渲染器选CPU) · 震动要trauma+噪声不是随机偏移 · time_scale=0时定时器也停需ignore_time_scale'),
    ('经济/长线系统', ['经济系统', '货币', '钱包', '掉落', '掉落表', '保底', 'pity', '抽卡', '商店', '限购', '养成', '天赋树', '技能树', '属性加成', '乘区', '数值崩坏', '洗点', '每日重置', '赛季', '通行证', '成就系统'],
     'references/godot/economy.md',
     '货币不能只一个int · 保底计数必须持久化且绑定卡池 · 洗点要同一事务 · 三种叠加结果不同 · 时间源用UTC'),
    ('输入重绑定', ['输入重绑定', '按键重映射', '改键', '键位', '改按键', 'remap', 'inputmap', '重绑定', '手柄振动', '振动', 'haptic', '触觉', 'joy vibration', '按键冲突', '捕获按键', '改键', '自定义按键', '键位设置'],
     'references/godot/input-remap.md',
     '4.x用action_get_events非get_action_list · 键位以physical_keycode为主键 · 振动不会自己停需显式stop'),
    ('无障碍/字幕', ['无障碍', 'accessibility', '色盲', '色觉', '字幕', 'subtitle', '闪烁', '光敏', '对比度', '文字缩放', '单声道', '辅助瞄准', '屏幕阅读器', 'screen reader'],
     'references/godot/accessibility.md',
     '无障碍≠难度选项 · 颜色即信息时滤镜无效要形状冗余 · 字幕要含非语音线索 · 闪烁每秒≤3次且面积≤1/4'),
    ('回放/录像', ['回放', '录像', 'replay', 'demo录制', '确定性', 'determinism', '固定步长', 'fixed timestep', '幽灵车', 'ghost', 'moviemaker', 'write-movie', '精彩回放', '复现', '回放系统', '确定性重放', '录像功能'],
     'references/godot/replay.md',
     'Godot物理官方不保证确定性 · 录的是每tick动作状态非按键流 · MovieMaker是离线逐帧非实时录屏'),
    ('关卡设计', ['关卡设计', 'level design', '白盒', 'blockout', '关卡编辑', '场景组装', 'csg', '关卡结构', '检查点', '复活点', '关卡流程', '心流曲线', '关卡卡表'],
     'references/godot/level-design.md',
     '白盒直接上美术更贵 · CSG官方定位是原型非资产 · tscn是文本≠可安全合并 · 关卡不硬编码逻辑 · 跳关入口决定迭代速度'),
    ('云存档/跨端', ['云存档', '云同步', '跨端进度', '跨平台存档', 'cloud save', 'steam cloud', '存档冲突', 'icloud', '进度同步', '多设备存档', '存档槽'],
     'references/godot/cloud-save.md',
     '核心是冲突不是传输 · 不能用文件修改时间判冲突 · Godot无内置云存档要平台SDK · iOS Caches不备份 · HTML5用IndexedDB'),
    ('调试工具/GM', ['gm命令', '作弊码', '调试面板', '调试工具', 'devtools', '跳关', '无敌', '控制台', 'console', 'debug draw', '启动参数', '命令行参数', 'performance', '刷怪'],
     'references/godot/devtools.md',
     '自定义参数要放--后用get_cmdline_user_args · Performance部分监控release恒为0且有1秒延迟 · 作弊要视觉标识+审计日志 · 无内置DebugDraw3D'),
    ('玩家Mod', ['mod', '模组', '玩家mod', 'mod加载', 'mod支持', '创意工坊', 'modding', 'load_resource_pack', 'pck覆盖', 'zip-slip', 'mod冲突', 'mod卸载'],
     'references/godot/modding.md',
     'Mod≠编辑器插件 · 后来加载的覆盖先加载的 · replace_files=false是不覆盖非沙箱 · Mod脚本无法沙箱隔离 · 手动解压要防zip-slip'),
    ('存档迁移', ['存档迁移', 'save migration', '存档版本', 'schema version', '旧存档', '存档兼容', '版本迁移', '字段兼容', '降级读取', '存档损坏'],
     'references/godot/save-migration.md',
     '格式版本≠游戏版本≠构建号 · VERSION要第一天写 · 迁移前必须备份 · 后要重算HMAC · 降级get_value静默返回默认值'),
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


def _is_word_char(c: str) -> bool:
    """ASCII 词内字符。非 ASCII（中文等）一律视为边界。"""
    return c.isascii() and (c.isalnum() or c == '_')


def _is_ascii_kw(k: str) -> bool:
    """纯 ASCII 关键词（英文术语）：需要按词边界匹配，不能纯子串。"""
    return all(ord(c) < 128 for c in k)


def _kw_hit(k: str, low_need: str) -> bool:
    """判断关键词是否命中需求（need 已转小写）。

    ASCII 关键词用词边界：避免 "quest" 命中 "request"、
    "api" 命中 "rapid"、"ui" 命中 "build" 这类子串误匹配。
    中文关键词没有词边界，仍用子串（"移动端性能" 要能命中 "性能"）。
    """
    if _is_ascii_kw(k):
        for m in re.finditer(re.escape(k), low_need):
            i, j = m.start(), m.end()
            # 只有 ASCII 字母/数字/下划线算"词内字符"。中文一律算边界：
            # Python 里 '调'.isalnum() 为 True，照搬会让 "rpc调用"、
            # "VR开发"、"authority迁移" 全部匹配不到。
            before_ok = i == 0 or not _is_word_char(low_need[i - 1])
            after_ok = j >= len(low_need) or not _is_word_char(low_need[j])
            if before_ok and after_ok:
                return True
        return False
    return k in low_need


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
        # ASCII 短词必须按「词」匹配，否则纯子串会误命中：
        # 实测 "HTTP request" 里含 "quest" → 被路由到「游戏系统」。
        # 这类 bug 输出完全正常，只是指向了错的文档，最难发现。
        hit = [k for k in kws if _kw_hit(k, low)]
        if hit:
            # 同一域内去掉被更长命中词包含的短词，避免重复计分
            uniq = [k for k in hit if not any(k != o and k in o for o in hit)]
            # 域名重合度加分：只认「该域最长的命中词」是否出现在域名里。
            # 为什么需要：多个域共用同一个词时（"程序化生成" 同时属于
            # 「高级主题」和「程序化生成」），纯长度加权得分相同，
            # 结果按列表顺序让通用域排前面 —— 输出正常，只是指错文档。
            # 为什么只给 1 分（平局打破器而非加权）：实测给 100 时，
            # "authority迁移" 会让「版本/迁移」(2+100) 压过「多人/网络」(9)，
            # 可该需求的主词是 authority 不是迁移。加分只能用于
            # 长度得分完全相同的情况，不能逆转长度优势。
            # 为什么只认最长词：命中的短词可能是多义词的副作用。
            bonus = 1 if max(uniq, key=len) in name else 0
            out.append((name, hit, entry, desc, sum(len(k) for k in uniq), bonus))
    out.sort(key=lambda x: (-x[4], -x[5]))
    return [(n, h, e, d) for n, h, e, d, _, _ in out]


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

    # ASCII 短词按词边界匹配，不能纯子串
    d = match_domains('HTTP request')
    chk(bool(d) and d[0][0] == '资源/IO/网络',
        '"HTTP request" → 资源/IO/网络（"request" 里的 quest 不算命中游戏系统）')

    # ASCII 词后紧跟中文必须能命中（CJK 是边界，不是词内字符）
    d = match_domains('rpc调用')
    chk(bool(d) and d[0][0] == '多人/网络', '"rpc调用" → 多人/网络（中文不阻断 ASCII 词）')
    d = match_domains('VR开发')
    chk(bool(d) and d[0][0] == 'XR/VR', '"VR开发" → XR/VR（XR 已独立成域）')
    d = match_domains('authority迁移')
    chk(bool(d) and d[0][0] == '多人/网络', '"authority迁移" → 多人/网络')

    # 新增三域
    d = match_domains('手部追踪抓握')
    chk(bool(d) and d[0][0] == 'XR深入/手部交互', '"手部追踪抓握" → XR深入/手部交互')
    d = match_domains('shader预热卡顿')
    chk(bool(d) and d[0][0] == '渲染进阶', '"shader预热卡顿" → 渲染进阶')
    d = match_domains('LOD分层')
    chk(bool(d) and d[0][0] == '渲染进阶', '"LOD分层" → 渲染进阶')

    d = match_domains('行为树')
    chk(bool(d) and d[0][0] == 'AI行为/决策', '"行为树" → AI行为/决策')
    d = match_domains('LimboAI 插件')
    chk(bool(d) and d[0][0] == 'AI行为/决策', '"LimboAI 插件" → AI行为/决策')
    d = match_domains('敌人寻路')          # 不该被行为树域抢走
    chk(bool(d) and d[0][0] == 'AI/寻路', '"敌人寻路" → AI/寻路（未被行为树抢走）')

    d = match_domains('属性测试')
    chk(bool(d) and d[0][0] == '高级测试', '"属性测试" → 高级测试（长词压过裸"测试"）')
    d = match_domains('模糊测试')
    chk(bool(d) and d[0][0] == '高级测试', '"模糊测试" → 高级测试')
    d = match_domains('视觉回归截图')
    chk(bool(d) and d[0][0] == '高级测试', '"视觉回归截图" → 高级测试')
    d = match_domains('单元测试')           # 不该被高级测试抢走
    chk(bool(d) and d[0][0] == '测试/CI', '"单元测试" → 测试/CI（未被高级测试抢走）')

    # 跨域竞争：更长的"精确组合词"应压过通用词
    d = match_domains('内存泄漏')
    chk(bool(d) and d[0][0] == '调试/排错', '"内存泄漏" → 调试/排错（排查症状，非性能优化）')
    d = match_domains('Android签名')
    chk(bool(d) and d[0][0] == '平台导出/发布', '"Android签名" → 平台导出/发布（签名归导出，不归 CI 流程）')
    d = match_domains('C#还是GDScript')
    chk(bool(d) and d[0][0] == 'C#/.NET', '"C#还是GDScript" → C#/.NET（选型问法压过 gdscript）')
    d = match_domains('TileMap迁移')
    chk(bool(d) and d[0][0] == '版本/迁移', '"TileMap迁移" → 版本/迁移（长组合词压过 tilemap）')

    # 高级主题不被基础域抢走
    d = match_domains('动画状态机')
    chk(bool(d) and d[0][0] == '动画高级', '"动画状态机" → 动画高级（不被 AI/寻路 抢走）')
    d = match_domains('AnimationTree状态机')
    chk(bool(d) and d[0][0] == '动画高级', '"AnimationTree状态机" → 动画高级')
    d = match_domains('音效池')
    chk(bool(d) and d[0][0] == '音频高级', '"音效池" → 音频高级')
    d = match_domains('大世界坐标精度')
    chk(bool(d) and d[0][0] == '开放世界', '"大世界坐标精度" → 开放世界')
    d = match_domains('开放世界地形')
    chk(bool(d) and d[0][0] == '开放世界', '"开放世界地形" → 开放世界（不被关卡/TileMap 抢走）')
    d = match_domains('VR抓取')
    chk(bool(d) and d[0][0] == 'XR/VR', '"VR抓取" → XR/VR')
    d = match_domains('XR传送')
    chk(bool(d) and d[0][0] == 'XR/VR', '"XR传送" → XR/VR（不被渲染进阶抢走）')

    # 玩家Mod / 存档迁移 不被旧域抢走
    for need, want in (('玩家mod', '玩家Mod'), ('mod加载', '玩家Mod'), ('创意工坊', '玩家Mod')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('存档迁移', '存档迁移'), ('旧存档兼容', '存档迁移'), ('降级读取', '存档迁移')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('编辑器插件', '编辑器插件开发'), ('云存档', '云存档/跨端')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（邻近域未被抢）' % (need, want))

    # 关卡设计 / 云存档 / 调试工具 不被旧域抢走
    for need, want in (('关卡设计', '关卡设计'), ('白盒', '关卡设计'), ('关卡编辑', '关卡设计')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('云存档', '云存档/跨端'), ('存档冲突', '云存档/跨端'),
                       ('跨端进度', '云存档/跨端')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('GM命令', '调试工具/GM'), ('调试面板', '调试工具/GM'),
                       ('作弊码', '调试工具/GM')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('存档', '存档/设置'), ('调试', '调试/排错'), ('测试', '测试/CI')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（基础域未被新域抢走）' % (need, want))

    # 输入重绑定 / 无障碍 / 回放 不被旧域抢走
    for need, want in (('按键重映射', '输入重绑定'), ('改键', '输入重绑定'),
                       ('手柄振动', '输入重绑定')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('色盲模式', '无障碍/字幕'), ('字幕系统', '无障碍/字幕'),
                       ('闪烁', '无障碍/字幕')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('回放系统', '回放/录像'), ('确定性', '回放/录像'),
                       ('幽灵车', '回放/录像')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('输入', '输入/音频'), ('网络同步', '多人/网络'), ('测试', '测试/CI')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（基础域未被新域抢走）' % (need, want))

    # 配表 / VFX / 经济 不被旧域抢走
    for need, want in (('配表怎么做', '数据驱动/配表'), ('策划数据表', '数据驱动/配表'),
                       ('csv导入', '数据驱动/配表')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('粒子特效', 'VFX/游戏感'), ('屏幕震动', 'VFX/游戏感'),
                       ('打击感', 'VFX/游戏感'), ('顿帧', 'VFX/游戏感')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('掉落保底', '经济/长线系统'), ('天赋树', '经济/长线系统'),
                       ('货币系统', '经济/长线系统'), ('每日重置', '经济/长线系统')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('2D渲染', '2D渲染/特效'), ('战斗数值', '战斗系统')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（基础域未被新域抢走）' % (need, want))

    # 程序化生成 / AI感知 / 骨骼IK 不被旧域抢走
    for need, want in (('程序化地图生成', '程序化生成'), ('随机地牢', '程序化生成'),
                       ('迷宫生成', '程序化生成'), ('种子复现', '程序化生成')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('敌人视野', 'AI感知'), ('视锥检测', 'AI感知'),
                       ('目标选择', 'AI感知')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（不被 AI/寻路 抢走）' % (need, want))
    for need, want in (('骨骼IK', '骨骼动画/IK'), ('布娃娃', '骨骼动画/IK'),
                       ('重定向', '骨骼动画/IK')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（不被动画域抢走）' % (need, want))
    d = match_domains('寻路')
    chk(bool(d) and d[0][0] == 'AI/寻路', '"寻路" → AI/寻路（基础域未被感知域抢走）')

    # XR深入 / 性能剖析 不被基础域抢走
    for need, want in (('手部追踪', 'XR深入/手部交互'), ('抓取物体', 'XR深入/手部交互'),
                       ('晕动症', 'XR深入/手部交互'), ('XR性能', 'XR深入/手部交互')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('profiler怎么用', '性能剖析/平台差异'), ('热节流', '性能剖析/平台差异'),
                       ('drawcall预算', '性能剖析/平台差异')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（不被通用性能域抢走）' % (need, want))
    d = match_domains('XR基础场景')
    chk(bool(d) and d[0][0] == 'XR/VR', '"XR基础场景" → XR/VR（基础域未被深入域抢走）')
    d = match_domains('性能优化')
    chk(bool(d) and d[0][0] == '性能/优化', '"性能优化" → 性能/优化（通用域未被剖析域抢走）')

    # 平台导出 / GDExtension实战 / 编辑器插件 不被旧域抢走
    for need, want in (('iOS上架', '平台导出/发布'), ('签名公证', '平台导出/发布'),
                       ('keystore', '平台导出/发布'), ('导出模板', '平台导出/发布'),
                       ('安卓导出', '平台导出/发布')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（不被 CI/发布 抢走）' % (need, want))
    for need, want in (('gdextension', 'GDExtension实战'), ('godot-cpp编译', 'GDExtension实战')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('编辑器插件', '编辑器插件开发'), ('自定义检视器', '编辑器插件开发'),
                       ('UndoRedo', '编辑器插件开发')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（不被插件生态抢走）' % (need, want))
    d = match_domains('第三方插件')
    chk(bool(d) and d[0][0] == '插件生态', '"第三方插件" → 插件生态（未被新域抢走）')

    # 进阶主题不被基础域抢走
    d = match_domains('客户端预测')
    chk(bool(d) and d[0][0] == '网络同步进阶', '"客户端预测" → 网络同步进阶（不被多人/网络抢走）')
    d = match_domains('服务器回滚')
    chk(bool(d) and d[0][0] == '网络同步进阶', '"服务器回滚" → 网络同步进阶')
    d = match_domains('锁步同步')
    chk(bool(d) and d[0][0] == '网络同步进阶', '"锁步同步" → 网络同步进阶')
    d = match_domains('gdextension')
    chk(bool(d) and d[0][0] == 'GDExtension实战', '"gdextension" → GDExtension实战（实战域优先于概览域）')
    d = match_domains('编辑器插件')
    chk(bool(d) and d[0][0] == '编辑器插件开发', '"编辑器插件" → 编辑器插件开发（开发域优先于概览域）')
    d = match_domains('第三方插件')
    chk(bool(d) and d[0][0] == '插件生态', '"第三方插件" → 插件生态')
    d = match_domains('程序化生成')
    chk(bool(d) and d[0][0] == '程序化生成', '"程序化生成" → 程序化生成（专业域压过概览域「高级主题」）')

    # shader 语言类问题归着色器域，不被 3D/2D 域的裸 shader 抢走
    d = match_domains('shader怎么写')
    chk(bool(d) and d[0][0] == '着色器', '"shader怎么写" → 着色器（不被 3D/渲染 抢走）')
    d = match_domains('compute shader')
    chk(bool(d) and d[0][0] == '着色器', '"compute shader" → 着色器')
    d = match_domains('材质与光照')            # 场景词仍归 3D
    chk(bool(d) and d[0][0] == '3D/渲染', '"材质与光照" → 3D/渲染（场景词未被着色器抢走）')
    d = match_domains('视差滚动')
    chk(bool(d) and d[0][0] == '2D渲染/特效', '"视差滚动" → 2D渲染/特效')


    # 程序化生成归专业域，不被概览域「高级主题」或 TileMap 抢走
    d = match_domains('程序化生成地图')
    chk(bool(d) and d[0][0] == '程序化生成', '"程序化生成地图" → 程序化生成')

    # 性能优化不被对象池抢走
    d = match_domains('性能优化')
    chk(bool(d) and d[0][0] == '性能/优化', '"性能优化" → 性能/优化')

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
