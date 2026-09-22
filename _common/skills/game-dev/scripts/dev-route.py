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
import glob
import os as _os
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
     'references/howto/godot/index.md'),
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
    ('角色控制', ['跳跃', '移动', '控制器', 'platformer', '冲刺', '角色', 'controller', 'movement', 'jump', '第一人称', 'fps', 'tps', '第三人称角色'],
     'references/howto/godot/character.md',
     'CharacterBody2D/3D · velocity · move_and_slide · 土狼时间 · 跳跃缓冲'),
    ('UI/菜单', ['ui', '界面', '菜单', 'hud', '血条', '物品栏', '对话框', '按钮', '设置面板', 'dialog', 'menu', '背包ui', 'inventory ui'],
     'references/howto/godot/ui.md',
     '锚点约束 · CanvasLayer · GridContainer · 打字机 · 分辨率自适应'),
    ('存档/设置', ['存档', '读档', '保存', '设置', '进度', 'save', 'load', 'config', '持久化'],
     'references/howto/godot/systems.md',
     'Resource + ResourceSaver · 原子写盘 · user:// · ConfigFile'),
    ('场景/流程', ['场景切换', '关卡', 'scene', 'level', 'transition'],
     'references/howto/godot/systems.md',
     'change_scene_to_file · CanvasLayer 过场 · 切换时保留数据'),
    ('事件/架构', ['事件总线', '信号', '解耦', 'autoload', '单例', 'events', 'signal', '通信'],
     'references/howto/godot/systems.md',
     'Events Autoload · 连接与断开配对 · 避免引用环'),
    ('对象池', ['对象池', '大量生成', '复用', 'pool', 'bullet', '子弹池'],
     'references/howto/godot/systems.md',
     'acquire/release · 状态重置 · 不用 queue_free 回收'),
    ('物理', ['碰撞', '射线', '射线检测', '物理', '推动', '重力', 'trigger', 'raycast', 'collision', '刚体', '爆炸', '层'],
     'references/howto/godot/physics.md',
     '碰撞层位掩码 · intersect_ray 参数对象 · Area 触发 · 施力 · AnimatableBody'),
    ('动画/缓动', ['动画', 'tween', '缓动', '过渡', '补间', 'animation', '淡入淡出', 'animationplayer'],
     'references/howto/godot/animation.md',
     'AnimationPlayer · AnimationTree 状态机 · Tween 链式 API · kill/bind_node'),
    ('输入/音频', ['输入', '按键', '手柄', '音频', '声音', 'audio', 'input', 'bgm', 'sfx', '音量', '音效', '音乐'],
     'references/howto/godot/input-audio.md',
     'Input Map 动作 · 四回调顺序 · 输入缓冲 · AudioServer 总线 · BGM 交叉淡入'),
    ('3D/渲染', ['3d', '材质', 'material', '环境', '3d粒子'],
     'references/howto/godot/3d.md',
     '坐标系 · 第三人称相机 · 共享材质陷阱 · 三光源 · Environment · GPUParticles3D'),
    ('资源/IO/网络', ['资源加载', 'http', 'download', '加载界面', '线程加载', 'api', '文件读写', 'json', '存档文件'],
     'references/howto/godot/io-network.md',
     'load/preload · 线程加载带进度 · HTTPRequest · 文件读写 · JSON'),
    ('AI/寻路', ['ai', '敌人', '寻路', '巡逻', '追击', '状态机', 'navigation', 'pathfinding', 'astar', '群体'],
     'references/howto/godot/ai-navigation.md',
     'NavigationAgent2D 模板 · 状态机巡逻追击攻击 · AStarGrid2D · 视线检测 · RVO 避障'),
    ('关卡/TileMap', ['tilemap', '图块', '瓦片', 'autotile', 'terrain', 'tile', '地形'],
     'references/howto/godot/tilemap.md',
     '4.3+ TileMapLayer vs 4.2 TileMap · 坐标转换 · 地形拼接 · 运行时生成'),
    ('2D渲染/特效', ['视差', 'parallax', 'ysort', '排序', '屏幕抖动', '转场', '扭曲', '闪白', '2d渲染', '2D渲染', 'y sort', 'ysort'],
     'references/howto/godot/2d-rendering.md',
     'Y-Sort 结构 · Parallax2D · canvas_item shader 配方 · trauma 抖动 · hitstop'),
    ('移动端/触控', ['移动端', '手机', '平板', '触屏', '触控', '虚拟摇杆', '手势', 'android', '多点触控', '摇杆', 'joystick', '安全区', '刘海', '返回键', '竖屏', '横屏', '权限', '软键盘', '息屏', '虚拟按键', '触摸', '双指捏合'],
     'references/howto/godot/mobile.md',
     'ScreenTouch/Drag · 浮动虚拟摇杆 · 手势识别 · 安全区 · 返回键 · 移动端性能'),
    ('本地化技术', ['本地化', '多语言', '翻译', '国际化', 'i18n', 'l10n', 'tr(', 'trn', 'locale', '语言', '切换语言', '语言包', '语种', '字体回退', '缺字', '方块', '豆腐块', 'rtl'],
     'references/howto/godot/i18n.md',
     'tr()/tr_n() · CSV 工作流 · 语言切换与刷新 · 字体回退 · RTL（流程与术语表见独立 skill: localization）'),
    ('存档安全/防作弊', ['加密', '存档加密', '防作弊', '反作弊', '篡改', 'hmac', '抄档', '修改器', '作弊', '内存保护', '密钥', '时间作弊', '倍速', '服务端校验', 'pck加密', '改存档', '防改', '存档安全', '刷奖励', '每日奖励', '系统时间', '改时间', '加固', '反外挂', 'hmac签名', '存档签名'],
     'references/howto/godot/security.md',
     '客户端加密的边界 · AES+HMAC 存档 · 每文件随机 IV · 内存值混淆 · 检测后静默处理'),
    ('性能/优化', ['性能', '卡顿', '优化', 'drawcall', '合批', '多线程', '线程池', 'workerthreadpool', '剔除', '帧率'],
     'references/howto/godot/performance.md',
     '先测量再优化 · Monitors 排查泄漏 · 屏幕外停处理 · StringName · 平方距离 · 线程池'),
    ('GDScript进阶', ['gdscript', '静态类型', '类型注解', 'stringname', 'await', '生命周期', 'tool脚本', '信号写法', 'duplicate', '类型转换', '热路径', 'onready'],
     'references/howto/godot/gdscript-advanced.md',
     '类型系统 · 热路径禁止清单 · await 三坑 · 回调时机 · @tool 隔离 · 信号 4.x 写法'),
    ('架构/规范', ['架构', '项目结构', '成员顺序', '代码顺序', '组件', '组合', '依赖注入', '代码组织', '规范', '重构', '耦合'],
     'references/howto/godot/architecture.md',
     '17 步成员顺序 · call down signal up · 组件组合 · Resource 数据驱动 · 依赖注入'),
    ('测试/CI', ['测试', '单元测试', 'gut', 'ci', '回归', '自动化测试', '覆盖率'],
     'references/howto/godot/testing.md',
     'GUT 用法 · 无框架最小方案 · 静态检查进 CI · 存档回归测试 · 上线清单'),
    ('多人/网络', ['多人', '联机', '网络', 'rpc', '服务器', '服务端', '权威', '同步', '延迟', 'peer', 'enemy', '专用服务器', 'authority', 'headless服务器'],
     'references/howto/godot/multiplayer.md',
     '服务器权威 · @rpc 参数 · 输入上报+序号 · 预测回滚 · 快照插值 · authority 迁移 · 专用服务器'),
    ('游戏系统', ['对话', '任务', '库存', '背包', '物品', 'inventory', 'dialogue', '支线', '奖励', '对话基础', '任务基础'],
     'references/howto/godot/game-systems.md',
     '命令解释器白名单 · 对话图+Runner · 任务定义/进度分离 · 库存四层 · 奖励幂等'),
    ('高级主题', ['地牢', '噪声', 'plugin', '导入管线', '资源导入', '波前'],
     'references/howto/godot/advanced-topics.md',
     '确定性生成 · BSP+连通性校验 · EditorPlugin 生命周期 · 资源三层隔离 · XR 性能预算'),
    ('渲染进阶', ['shader预热', '着色器预热', '变体预热', '管线编译', '分块', 'hloD', '自动lod', 'lod生成', 'lod分层'],
     'references/howto/godot/rendering-advanced.md',
     'XR 手部/抓握/传送 · LOD 四层 · visibility_range · 着色器管线预热 · 分块流式'),
    ('AI行为/决策', ['行为树', 'bt', 'goap', '效用', 'limboai', 'beehave', '黑板', 'blackboard', '决策', 'selector', 'sequence'],
     'references/howto/godot/ai-behavior.md',
     'FSM/BT/GOAP/效用选型 · 最小行为树实现 · 黑板 · RUNNING 语义 · 插件对比'),
    ('高级测试', ['属性测试', '模糊测试', 'fuzz', '视觉回归', '截图对比', '性能基准', 'benchmark', '确定性测试'],
     'references/howto/godot/testing-advanced.md',
     '属性/不变量 · 存档模糊 · 截图 diff · p99 帧时间基准 · 确定性回放'),
    ('调试/排错', ['调试', '断点', 'debugger', '卡死', '卡住', '空引用', 'null', '排查', '定位问题', 'stderr', 'push_error', '瓶颈', '内存泄漏', '日志'],
     'references/howto/godot/debugging.md',
     '断点两种断点区别 · 多线程断点失效 · release 日志差异 · CPU/GPU 瓶颈判定 · 故障定位流程'),
    ('CI/发布', ['持续集成', 'github action', '流水线', 'pipeline', 'artifact', '无头', '打包体积', 'ci签名', 'ci导出', '自动构建', '构建产物', 'headless构建', 'ci发布'],
     'references/howto/godot/cicd-publish.md',
     '无头导入 · 完整 Actions 配置 · 产物非空校验 · 模板版本匹配 · 各平台签名 · 凭据走 Secret'),
    ('C#/.NET', ['c#', 'csharp', '.net', 'dotnet', 'nuget', 'net8', 'msbuild', 'rider', 'visual studio', 'marshalling', 'c#还是gdscript', 'gdscript还是c#', '语言选型', '该用c#', '选c#'],
     'references/howto/godot/csharp.md',
     'C#/GDScript 选型 · .NET 版本政策表 · PascalCase 生命周期 · Signal 委托命名 · await 守卫'),
    ('版本/迁移', ['迁移', '升级', '版本兼容', 'godot4.3', 'godot4.4', '3.x', 'tilemaplayer', 'deprecated', '弃用', '改名', 'randomize', 'tilemap迁移', '升级tilemap', '节点改名', 'api变化', '引擎升级'],
     'references/howto/godot/version-migration.md',
     '4.x 各版本结构变化 · TileMap 三重迁移 · 3→4 改名对照 · 锁 commit · 升级检查清单'),
    ('插件生态', ['插件', 'dialogic', '第三方库', '轮子', '依赖引入', '许可证', 'mit', '是否该自己写'],
     'references/howto/godot/plugins.md',
     '决策口诀 · 按环节取舍表 · 绝不引入的 8 种情况 · 引入检查清单 · 锁 commit'),
    ('着色器', ['shader', 'gdshader', '着色器', 'glsl', 'spirv', 'uniform', 'varying', 'fragment', 'vertex shader', '卡通渲染', 'toon', '描边', '溶解', '边缘光', 'rim', 'post process', 'hint_', 'source_color', 'visualshader', '三平面', 'triplanar', 'shader怎么写', '着色器性能', 'render_mode', '精度限定符', 'compute shader', '深度纹理', '自定义后处理'],
     'references/howto/godot/shaders.md',
     'GDShader 方言 · uniform 提示清单 · 2D/3D 九个配方 · 坐标空间 · 变体与预热 · 调试颜色 mask'),
    ('动画高级', ['animationtree', 'blendspace', 'blend tree', '混合空间', '根运动', 'root motion', 'skeletonik', '分层动画', '动画遮罩', 'switch_mode', 'travel', '动画状态机深入', 'animationtree状态机', '动画树', '混合空间', '动画状态机', '动画树状态机'],
     'references/howto/godot/animation-advanced.md',
     'StateMachine/BlendSpace/BlendTree 分工 · travel vs start · switch_mode 是过渡时机 · 根运动双倍位移 · IK 开销'),
    ('音频高级', ['audioserver', '音频总线', 'bus', 'linear_to_db', '分贝', '音效池', '交叉淡入', '动态音乐', '空间音效', '3d音效', 'ogg', 'wav', '混响', '响度'],
     'references/howto/godot/audio-advanced.md',
     '总线架构 · 音量是分贝不是 0-1 · 音效池轮转 · 动态音乐分层 · 暂停 process_mode'),
    ('开放世界', ['开放世界', '大世界', '流式加载', 'chunk', 'lod', '大世界坐标', '原点重置', 'floating origin', '精度', 'culling', '卸载半径', '双精度', '开放世界地形', '大型地形', '地形系统', '大地形'],
     'references/howto/godot/openworld.md',
     'chunk 三半径滞回 · 分帧预算 · 节点池 · Terrain3D · 大世界坐标精度 · 原点重置实现'),
    ('XR/VR', ['xr', 'vr', 'ar', 'openxr', '头显', '传送', 'xrorigin', 'xrcamera', 'xr基础', 'xr场景', '头显基础', 'quest头显', 'meta quest', 'xr控制器', 'xr手柄'],
     'references/howto/godot/xr.md',
     '内置节点四件套 · 不能接管相机 · 无速度 API 需自算 · 抓取速度传递 · 晕动症规避'),
    ('4.7/4.8版本', ['4.7', '4.8', '版本', 'breaking', 'breaking change', 'arealight', '面光源', 'hdr输出', 'offset_transform', 'virtualjoystick', 'drawabletexture', '纹理流送', 'texture streaming', 'tween_await', 'device_id', 'jolt', '升级到4.7'],
     'references/howto/godot/version-47-48.md',
     '4.7.2 当前稳定 / 4.8 仍 dev · AreaLight3D · HDR 输出 · Control offset_transform · 内置 VirtualJoystick · break changes'),
    ('网络同步进阶', ['预测', '回滚', 'reconciliation', '插值', '插值延迟', '锁步', 'lockstep', 'tick', '快照', 'enet', 'websocket', 'webrtc', 'nat', '打洞', 'multiplayersynchronizer', '服务器回滚', '锁步同步', '确定性锁步', '客户端预测', '实体插值', '同步模型', '状态同步', '网络预测', '预测回滚', '锁定步进', '快照插值', 'jitter', '抖动缓冲', '输入编号', '权威回滚'],
     'references/howto/godot/netsync-advanced.md',
     '同步模型选型 · 客户端预测+输入历史 · 服务器回滚重放(固定dt+阈值) · 远端插值 · rpc 默认 reliable · 传输层取舍'),
    ('GDExtension/插件', ['c++', 'cpp', 'abi', '绑定', 'native', '热重载', '自定义导入器', '自定义检视器插件', 'rust', 'gdext'],
     'references/howto/godot/gdext-plugin.md',
     '先 profile 再换语言 · 版本+浮点精度是 ABI · 4.0→4.1 硬断裂 · 热重载仅编辑器 · @tool 必备 + _exit_tree 对称注销'),
    ('战斗系统', ['战斗', '伤害', '命中判定', 'hitbox', 'hurtbox', '帧数据', '暴击', '格挡', '闪避', 'buff', 'debuff', 'dot', '技能', '冷却', '连招', '取消', 'combat', 'damage', 'attack', 'knockback',
      '硬直', '受击硬直', '霸体', '韧性', 'poise', '破防', '架势', '招架', '弹反', '处决', '部位破坏', '断尾',
      'hitstun', 'super_armor', 'parry', 'guard_break', 'execution', '取消窗口', 'cancel_table', '输入缓冲', '对抗层'],
     'references/howto/godot/combat.md',
     '四层分离 · AttackContext 去重 · 判定放物理帧 · hitbox 默认关 · hitstop 不用 await · 对抗层=争夺行动权不是数值增减 · 硬直两来源分开且按真实时间衰减 · 霸体是延迟硬直不是减伤 · 招架先于伤害结算且不能概率 · 处决期间攻击方无敌目标不可打断 · 部位是独立实体'),
    ('数据分析/埋点', ['埋点', '数据分析', 'analytics', 'telemetry', '事件上报', '漏斗', '留存', '流失', '难度调优', '热力图', 'session', 'player_id', '批量上报', '埋点ab'],
     'references/howto/godot/analytics.md',
     'object_verb 命名 · 离线优先缓存 · 批量上报 · 不用设备ID · 每步引导埋点'),
    ('渲染管线', ['渲染器', '渲染管线', 'forward+', 'mobile渲染', 'compatibility', 'glow', 'dof', 'ssr', '批处理', 'compositor', '色调映射', '渲染管线后处理', '渲染'],
     'references/howto/godot/render-pipeline.md',
     '三渲染器能力矩阵 · Web只能Compatibility · 性能曲线反直觉 · 自动实例化仅Forward+'),
    ('光照', ['光照', 'gi', '烘焙', 'lightmap', 'voxelgi', 'sdfgi', '阴影', 'shadow', 'acne', 'peter-panning', 'bias', 'pssm', 'cascade', '体积雾', '体积光', 'fog', 'light'],
     'references/howto/godot/lighting.md',
     '三种GI选型 · 烘焙六步与失败码 · bias权衡 · 体积雾仅Forward+'),
    ('美术资产', ['美术', '资产管线', '纹理', '导入设置', 'filter', 'repeat', 'mipmap', '像素', '图集', 'atlas', '纹理压缩', 'basis universal', 'pbr', '法线贴图', '字体', '子集化', 'msdf', '九宫格', 'asset'],
     'references/howto/godot/art-assets.md',
     'Filter/Repeat/Mipmap 三开关 · 像素糊的五个原因 · 压缩按用途分层 · 中文要子集化'),
    ('相机/过场', ['相机', 'camera', '跟随', '死区', '前瞻', '屏震', 'springarm', '过场', 'cutscene', '黑边', 'letterbox', '跳过大', '控制权移交', '第三人称相机'],
     'references/howto/godot/camera-cutscene.md',
     '相机分层 · 帧率无关lerp · trauma平方衰减 · 过场三要素同状态机'),
    ('引导/成就', ['新手引导', '引导', 'tutorial', 'onboarding', '成就', 'achievement', '排行榜', 'leaderboard', '统计', '高亮遮罩', '挖洞', '解锁'],
     'references/howto/godot/onboarding-meta.md',
     '引导必须超时兜底 · 九宫格挖洞 · 成就定义与状态分离 · Godot无内置Steam成就'),
    ('平台导出/发布', ['导出', '发布', '上线', '打包', 'export', 'apk', 'aab', '公证', 'notarize', 'staple', 'provisioning', '证书', 'app store', 'google play', 'web导出', 'ios', 'ios导出', 'ios上架', 'android导出', 'wasm', 'coop', 'coep', 'sharedarraybuffer', 'ndk', 'gradle', '导出模板', 'keystore', 'windows导出', 'macos导出', 'linux导出', 'android签名', 'ios签名', 'android导出', 'ios导出', 'ios上架', 'windows签名', 'macos签名', '导出签名', '打包签名', '上架签名', '发布签名', '代码签名'],
     'references/howto/godot/platform-export.md',
     '各平台速查表 · Web仅Compatibility · 多线程需COOP+COEP · NDK必须r28b · keystore丢了包名报废'),
    ('GDExtension实战', ['gdextension', 'godot-cpp', 'sconstruct', 'entry_symbol', 'bind_method', 'add_property', 'gdclass', 'gdregister', 'register_types', 'ref<T>', 'memnew', 'c++扩展', 'native扩展', '编译扩展', '.gdextension', 'cpp扩展'],
     'references/howto/godot/gdextension-deep.md',
     'pin到4.7同步commit · entry_symbol严格匹配 · 只在SCENE层注册 · RefCounted必须Ref<T>'),
    ('编辑器插件开发', ['编辑器插件', 'editorplugin', 'undoredo', '撤销', '自定义检视器', 'inspectorplugin', '自定义导入', 'importplugin', 'editordock', 'add_dock', 'tool注解', '插件发布', 'asset library'],
     'references/howto/godot/editor-plugin.md',
     'enter/exit_tree对称注销 · is_editor_hint≠跑游戏 · get_undo_redo按对象选历史 · 4.7统一EditorDock'),
    ('项目/工程', ['项目设置', 'debug', 'publish'],
     'references/howto/godot/project.md',
     '项目设置关键项 · Autoload · 导出清单 · gitignore'),
    ('XR深入/手部交互', ['xr深入', '手部追踪', '手部', '捏合', 'pinch', '抓取', 'grab', 'xrtools', 'steamvr', '晕动症', 'snap turn', '隧道视野', '空间ui', 'xr性能', '6dof', 'xrcontroller', '手部追踪', '手部交互', '捏合检测', '抓取物体', 'grab系统', 'xr抓取', '手部关节', '关节追踪', 'quest手部'],
     'references/howto/godot/xr-deep.md',
     'XRCamera3D会滞后几毫秒 · 抓取不能reparent刚体 · 控制器无速度API需自己差分 · 优先传送'),
    ('性能剖析/平台差异', ['性能剖析', 'profiler', '剖析', 'monitors', '监视器', '帧预算', 'p99', '掉帧', '热节流', 'throttling', 'tile gpu', 'gpu bound', 'cpu bound', 'drawcall预算', '显存', 'vram', '性能优化深入', '瓶颈定位', '过温', '降频', 'profiler怎么用', '性能剖析', '剖析器', '热节流', 'throttling', 'drawcall预算', 'gpu bound', 'cpu bound', '瓶颈定位', 'p99', '掉帧分析'],
     'references/howto/godot/perf-profiling.md',
     '编辑器FPS不代表目标设备 · P99才是卡顿指标 · Profiler不覆盖C# · 移动端要测10分钟'),
    ('程序化生成', ['程序化生成', 'pcg', 'procedural', '随机地图', '关卡生成', '地图生成', '地牢生成', 'bsp', '迷宫', '元胞自动机', 'wfc', 'wave function', '泊松', 'poisson', '种子', 'seed', '随机种子', '连通性', 'flood fill', '无尽关卡', '地牢生成', '随机地牢'],
     'references/howto/godot/procedural-generation.md',
     '没seed无法维护 · 全局randi是全局状态 · 元胞自动机最易不可达 · 分帧要先纯数据算完 · ±10⁷是精度问题'),
    ('AI感知', ['ai感知', '感知系统', '视锥', '视野', '视线', '遮挡检测', '听觉', '声音传播', '察觉',  '最后已知位置', '目标选择', '感知记忆', '敌人发现玩家', 'vision cone', 'perception', '敌人视野', '敌人发现', '察觉玩家', '感知目标'],
     'references/howto/godot/ai-perception.md',
     '感知≠寻路 · 输出不是bool要有置信度 · 遮挡必须射线 · 4.x要PhysicsRayQueryParameters3D · 检测10Hz够'),
    ('AI战术/协同', ['战术', '阵型', '编队', '敌人编队', '槽位', '掩体点', '战术位置', '攻击令牌', '仇恨', '威胁表', '群体协作', '侧翼', 'ai性能', 'ai预算', 'ai lod', 'ai调试', 'ai可视化', '难度自适应', '攻击间隔', '待机', '同时攻击', '抢掩体', '让路'],
     'references/howto/godot/ai-tactics.md',
     '战术层是第四层 · 目标选择要迟滞 · 仇恨表不可省 · 槽位固定分配 · 掩体预烘焙+预约 · 令牌防集体发呆 · LOD要迟滞'),
    ('骨骼动画/IK', ['骨骼', 'skeleton', '蒙皮', 'skinning', 'ik', '反向动力学', 'two bone', 'twoBone', 'lookat modifier', 'ragdoll', 'spring bone', '重定向', 'retarget', 'bone', '骨骼动画', '布娃娃'],
     'references/howto/godot/animation-skeletal.md',
     '骨骼是有序数组非节点 · 4.7无PoleModifier3D/SplineIK3D · modifier顺序由子节点列表定 · 每帧回滚'),
    ('数据驱动/配表', ['配表', '策划配表', '数据表', '配置表', 'csv导入', 'excel导入', '数据驱动', 'resource配表', 'tres', 'id常量', '外键校验', '导入器', '热重载配表', 'sqlite'],
     'references/howto/godot/datatable.md',
     '数值写代码=程序员成瓶颈 · duplicate()默认浅拷贝共享子资源 · 外键存ID不存引用 · 导入期要校验 · load_threaded才是异步'),
    ('VFX/游戏感', ['vfx', '特效', '粒子', 'cpuparticles', '打击感', '游戏感', 'juice', '命中反馈', '屏幕震动', '震屏', 'trauma', '顿帧', 'hitstop', '拖尾', '残影', '白闪', '伤害数字', '打击感', '顿帧', 'hitstop实现', '命中感'],
     'references/howto/godot/vfx-feel.md',
     'GPU粒子不是默认答案(Web/兼容渲染器选CPU) · 震动要trauma+噪声不是随机偏移 · time_scale=0时定时器也停需ignore_time_scale'),
    ('经济/长线系统', ['经济', '经济系统', '货币', '钱包', '掉落', '掉落表', '商店', '限购', '养成', '天赋树', '技能树', '属性加成', '乘区', '数值崩坏', '洗点', '赛季', '抽卡经济', '掉落保底'],
     'references/howto/godot/economy.md',
     '货币不能只一个int · 保底计数必须持久化且绑定卡池 · 洗点要同一事务 · 三种叠加结果不同 · 时间源用UTC'),
    ('输入重绑定', ['输入重绑定', '按键重映射', '改键', '键位', '改按键', 'remap', 'inputmap', '重绑定', '手柄振动', '振动', 'haptic', '触觉', 'joy vibration', '按键冲突', '捕获按键', '改键', '自定义按键', '键位设置'],
     'references/howto/godot/input-remap.md',
     '4.x用action_get_events非get_action_list · 键位以physical_keycode为主键 · 振动不会自己停需显式stop'),
    ('无障碍/字幕', ['无障碍', 'accessibility', '色盲', '色觉', '字幕', 'subtitle', '闪烁', '光敏', '对比度', '文字缩放', '单声道', '辅助瞄准', '屏幕阅读器', 'screen reader'],
     'references/howto/godot/accessibility.md',
     '无障碍≠难度选项 · 颜色即信息时滤镜无效要形状冗余 · 字幕要含非语音线索 · 闪烁每秒≤3次且面积≤1/4'),
    ('回放/录像', ['回放', 'replay', 'demo录制', '确定性', 'determinism', '固定步长', 'fixed timestep', '幽灵车', 'ghost', 'moviemaker', 'write-movie', '精彩回放', '复现', '回放系统', '确定性重放', '录像功能'],
     'references/howto/godot/replay.md',
     'Godot物理官方不保证确定性 · 录的是每tick动作状态非按键流 · MovieMaker是离线逐帧非实时录屏'),
    ('关卡设计', ['关卡设计', 'level design', '白盒', 'blockout', '关卡编辑', '场景组装', 'csg', '关卡结构', '复活点', '关卡流程', '心流曲线', '关卡卡表', '关卡检查点'],
     'references/howto/godot/level-design.md',
     '白盒直接上美术更贵 · CSG官方定位是原型非资产 · tscn是文本≠可安全合并 · 关卡不硬编码逻辑 · 跳关入口决定迭代速度'),
    ('云存档/跨端', ['云存档', '云同步', '跨端进度', '跨平台存档', 'cloud save', 'steam cloud', '存档冲突', 'icloud', '进度同步', '多设备存档', '存档槽'],
     'references/howto/godot/cloud-save.md',
     '核心是冲突不是传输 · 不能用文件修改时间判冲突 · Godot无内置云存档要平台SDK · iOS Caches不备份 · HTML5用IndexedDB'),
    ('调试工具/GM', ['gm命令', '作弊码', '调试面板', '调试工具', 'devtools', '跳关', '无敌', '控制台', 'console', 'debug draw', '启动参数', '命令行参数', 'performance', '编辑器工具', 'editorscript', 'editor script', '一次性脚本', '批量改资源', '批量处理资源', '资源批量', 'resourcesaver批量'],
     'references/howto/godot/devtools.md',
     '自定义参数要放--后用get_cmdline_user_args · Performance部分监控release恒为0且有1秒延迟 · 作弊要视觉标识+审计日志 · 无内置DebugDraw3D'),
    ('玩家Mod', ['模组', '玩家mod', 'mod加载', 'mod支持', '创意工坊', 'modding', 'load_resource_pack', 'pck覆盖', 'zip-slip', 'mod冲突', 'mod卸载', 'mod'],
     'references/howto/godot/modding.md',
     'Mod≠编辑器插件 · 后来加载的覆盖先加载的 · replace_files=false是不覆盖非沙箱 · Mod脚本无法沙箱隔离 · 手动解压要防zip-slip'),
    ('存档迁移', ['存档迁移', 'save migration', '存档版本', 'schema version', '旧存档', '存档兼容', '版本迁移', '字段兼容', '降级读取', '存档损坏'],
     'references/howto/godot/save-migration.md',
     '格式版本≠游戏版本≠构建号 · VERSION要第一天写 · 迁移前必须备份 · 后要重算HMAC · 降级get_value静默返回默认值'),
    ('热更新/DLC', ['热更新', '热更', '资源热更', 'hot update', '资源分包', 'dlc', '增量补丁', '补丁包', '强制更新', 'ab包', '分包', '热更灰度'],
     'references/howto/godot/hotupdate.md',
     '资源热更≠代码热更差一个量级 · 已缓存资源不会自动换血 · iOS审核2.5.2禁止动态代码 · 配置热更也要版本校验 · DLC未购买要占位'),
    ('平台服务', ['token', 'refresh token', '双令牌', '账号令牌', 'steam', '云函数', '平台sdk', 'godotsteam', 'eos', 'game center', 'play games', '账号体系', '平台账号', '鉴权', '排行榜提交', 'steam排行榜', 'steam成就', '平台成就', '平台排行榜', '平台内购'],
     'references/howto/godot/platform-services.md',
     'Godot无内置成就/排行榜/内购 · 要统一异步接口+离线桩 · 发布包不要带steam_appid.txt · 无Steam客户端要降级不崩 · token秘密留服务端'),
    ('画质/超分', ['超分', 'fsr', 'fsr2', 'dlss', 'xess', 'metalfx', '抗锯齿', 'taa', 'fxaa', 'msaa', 'smaa', '后处理', 'bloom', 'tonemap', '景深', 'ssao', '画质', '渲染分辨率', '拉伸', 'stretch'],
     'references/howto/godot/upscaling.md',
     'stretch与3D缩放是两套机制 · 内置只有FSR2.2无FSR3/DLSS · TAA仅Forward+ · 2D MSAA在Compatibility不可用 · HDR只在部分tonemap下响应'),
    ('载具/物理进阶', ['载具', 'vehicle', 'vehiclebody', '车辆', '赛车', '翻车', '质心', '关节', 'joint', 'hingejoint', '物理关节', '链条', 'physicsmaterial', '物理材质', '穿模', 'ccd', '物理布娃娃', '软体'],
     'references/howto/godot/vehicle-physics.md',
     'VehicleBody是街机求解器非高保真 · 翻车多是质心非碰撞形状 · SoftBody3D官方存在建议Jolt · 摩擦默认取最低 · 卡帧物理最多追8步'),
    ('角色自定义', ['捏脸', '角色自定义', '换装', '装备系统', '外观', '染色', 'blend shape', 'blendshape', 'morph', '合并网格', '部件换装', '装备槽'],
     'references/howto/godot/character-customization.md',
     '捏脸/换装/染色三套生命周期别混设计 · 无官方合并网格API · 合并与BlendShape不能混用 · 合并网格无自动LOD · 4.6起skeleton默认路径变'),
    ('环境系统', ['海洋', 'water', '浮力', '波浪', '天空', 'sky', 'weather', '昼夜循环', '下雨', '下雪', '风', '闪电', 'proceduralsky', 'physicalsky', '水下', '水面', '天气', '昼夜'],
     'references/howto/godot/environment-systems.md',
     '无官方Water节点但apply_force能做浮力 · Gerstner采样CPU/GPU必须一致否则船漂错高度 · 天空/雾/环境光/GI联动 · Static烘焙完全锁定不能做昼夜 · 雨要跟随相机'),
    ('UI进阶', ['ui框架', '富文本', 'richtext', 'richtextlabel', 'bbcode', '虚拟列表', '滚动容器', 'scrollcontainer', 'tooltip', '拖拽ui', '键盘导航', 'focus_neighbor', 'grab_focus', '剪贴板', 'clipboard', '输入法', 'ime', '字距', '海量列表', '列表性能', 'ui无障碍', '焦点链', '焦点导航'],
     'references/howto/godot/ui-advanced.md',
     '无内置虚拟列表Tree也不虚拟化70k项1.21GiB · BBCode有注入风险要escape · 拖拽预览不能free引擎接管 · 鼠标能点≠手柄能选 · 4.7 AccessibilityServer独立成单例'),
    ('诊断与稳定性', ['错误处理', '崩溃上报', '崩溃', 'crash', '断言', 'assert', '日志分级', '日志系统', 'logger', 'add_logger', '录像', 'movie maker', 'watchdog', '孤儿节点', '健康检查', 'sentry', '符号化', 'minidump'],
     'references/howto/godot/diagnostics.md',
     'GDScript无try/catch · print崩溃时可能没刷盘用stderr · assert在release不求值 · 原生崩溃进程没机会上报 · MovieMaker不是玩家录像器'),
    ('商业化/变现', ['内购', '支付', 'iap', '商城', '商店定价', '抽卡', 'gacha', '扭蛋', '保底', 'pity', '概率公示', '礼包', '月卡', '订阅制', '广告', '激励视频', '变现', 'billing', 'storekit', '收据验证', '掉单', '未成年限额'],
     'references/howto/godot/monetization.md',
     'Godot 4.x 全系列无内置 IAP/支付/广告 API · 客户端只是发起支付的遥控器 · 合规优先于体验 · 中国抽卡是四件套（含替代获取途径）· 概率公示必须与实现同源 · 保底存服务器防清档 · 掉单幂等'),
    ('投射物/弹道', ['投射物', '弹道', '子弹', '抛射',  '穿透问题', 'tunneling', '弹道预测', '瞄准线', '追踪弹', '穿透弹', 'shapecast', '命中框', '弹射', 'homing'],
     'references/howto/godot/projectile.md',
     '无专门子弹节点 · CCD 官方称"有时有效"不替代射线扫描 · 预测线必须复用真实弹道函数否则显示与落点不一致 · 网络应同步开火事件而非逐帧 transform · 一帧多次命中要去重'),
    ('进阶移动', ['二段跳', '爬墙', '抓墙', '抓边', '蹬墙跳', '摆荡', '游泳', '潜水', '滑翔', '攀爬', '可变重力', '重力方向', 'up_direction', '传送门', '水下移动', 'ledge', 'wall jump'],
     'references/howto/godot/movement-advanced.md',
     '特殊移动不能堆 if 要状态机 · 抓边要两条射线且分吸附悬停攀爬三阶段 · 不要直接赋坐标会穿薄墙 · 改 up_direction 不必然失效真正原因是那 5 个 · 改重力要 up/相机/移动平面一起变'),
    ('多人社交', ['大厅', 'lobby', '房间系统', '匹配', '好友', '组队', '聊天', '公会', '邮件系统', '公告', '举报', '敏感词', '审核ugc', '房主迁移', 'host migration',
      '阵营', '势力', '声望', '荣誉', '战力', '战报', '师徒', '结拜', '婚姻', '聊天频道', '世界频道', 'faction', 'reputation', 'gvg', '势力战', '据点', '占领', '阵营切换', 'match_report', '战斗回放'],
     'references/howto/godot/social.md',
     'Godot 不内置任何社交服务 · ENet 只是 UDP 传输层 · 房主是临时协调者要能迁移 · 聊天必须服务器过滤并留存 · 举报要存证据快照 · 阵营关系是非对称有向图不能镜像 · 切换要时间关系经济三重代价防身份套利 · 战力只展示不能当匹配依据 · 战报存最小事件集且跨版本要隔离 · 战绩默认最小展示'),
    ('生存/角色状态', ['生命值', '血量', '耐力', 'stamina', '饥饿', 'hunger', '体温', '负重', '死亡', '重生', '复活', '存档点', '检查点', 'checkpoint', '属性系统', '资源再生', '体力恢复', 'survival'],
     'references/howto/godot/survival.md',
     '引擎没有 HealthComponent 要自己定义 · 数值四层必须分开且存输入不存计算结果 · 死亡是四阶段状态机不是 bool · 重生要清 Tween/Timer/信号/飞行投射物 · 检查点只覆盖重生事实不覆盖手动存档 · 死亡播放期间禁止保存'),
    ('叙事/进程', ['叙事', '任务链', '任务系统', '对话树', '好感度', '分支', '多结局', '结局', '章节', '关卡选择', '周目', '新游戏+', '动态难度', '剧情flag', 'dialogue tree', 'story', '任务链设计'],
     'references/howto/godot/narrative.md',
     'flag 必须集中在 StoryState 否则后期无法重构 · 三段式命名防撞车 · 结局要判定表不是 if elif · 优先级显式配置且检查可达性 · 隐形前置要可查询否则卡关 · 周目继承策略各不同'),
    ('谜题/机关', ['谜题', '机关', '交互物', 'interactable', '压力板', '拉杆', '钥匙锁', '开门', '门', '传送器', '可破坏物', '推箱子', '反射谜题', '镜子', '光线反射', '重力谜题', 'puzzle', '开关组合'],
     'references/howto/godot/puzzle.md',
     'Godot 没有谜题系统要自己定协议 · 交互要抽象成意图而非绑按键 · 状态与运行时分开（读档 seek 到终点）· 组合逻辑数据驱动 · 反射必须硬上限 8 次且用 bounce 不是 reflect · 推箱子用网格才能校验与 undo · 防卡关是生死线'),
    ('时间操控', ['慢动作', '子弹时间', '时间缩放', 'time_scale', '倒带', '时间回溯', '暂停', 'pause', 'process_mode', '本地时间倍率', 'bullettime', 'slow motion', 'rewind'],
     'references/howto/godot/timescale.md',
     '时间至少五层不是单一旋钮 · 音频不受 time_scale 影响要单独处理 · 暂停与慢放是两件事 · process_mode 与 Tween 忽略缩放正交 · Tween.set_ignore_time_scale 是 4.7 新增 · 倒带是快照+冻结不是物理倒流'),
    ('运营服务端', ['运营', 'ab测试', 'A/B', '灰度', '配置下发', '远程配置', '停服', '维护', '补偿', 'cdk', '兑换码', '邀请码', '活动系统', '活动时间', 'liveops', '分桶', 'experiment', '签到', '七日签到', '战令', '通行证', '礼包码', '公告系统', '赛季结算', 'ops'],
     'references/howto/godot/ops.md',
     '客户端只能展示转发不能当事实来源 · 分组必须服务端算否则样本污染 · 配置下发要有版本灰度校验默认值回滚 · 活动时间必须服务端给不能用本地时间 · 活动五态含常被漏的结算中 · 补偿必须幂等否则刷道具 · 兑换必须服务端校验'),
    ('塔防', ['塔防', 'tower defense', 'td', '建塔', '波次', '刷怪', 'wave', '塔', '索敌', '路径点', '怪物波'],
     'references/howto/godot/genres-tower-defense.md',
     'Wave Resource · 路径缓存 · map_force_update · 降频 shape query 索敌'),
    ('RTS/即时战略', ['rts', '即时战略', '框选', '编队指令', '编队快捷键', '指令队列', '战争迷雾', '迷雾', '单位选择', '战略'],
     'references/howto/godot/genres-rts.md',
     '命令模式 · Rect2.has_point · 编队偏移位 · 迷雾格子脏区批量提交'),
    ('卡牌/桌游', ['卡牌', '卡组', '牌库', '抽牌', '洗牌', '弃牌', '连锁', '效果栈', 'card', 'deck', '桌游'],
     'references/howto/godot/genres-card.md',
     'CardData Resource · 显式效果栈 · rng 洗牌 · .tres 存档'),
    ('Roguelike', ['roguelike', 'roguelite', '肉鸽', '房间生成', '道具池', '元进度', 'meta progression', '种子生成'],
     'references/howto/godot/genres-roguelike.md',
     '四阶段 RNG 分支 · 纯数据中间表示 · AStar2D 房间图 · 原子写盘'),
    ('自走棋/战棋', ['自走棋', '战棋', '六边形', 'hex', '行动点', '棋盘', '回合制战斗', '站位', '朝向'],
     'references/howto/godot/genres-tactics.md',
     '轴向坐标 · 离散朝向枚举 · 事件队列结算 · 棋盘与渲染双表示'),
    ('模拟经营/放置', ['模拟经营', '放置', '挂机', '离线收益', 'idle', '建筑放置', '资源产出', '经营'],
     'references/howto/godot/genres-idle-sim.md',
     '固定步长累加器 · 离线跑完整 tick · Unix 时间基准 · 数组格子校验'),
    ('平台跳跃手感', ['土狼时间', 'coyote', '跳跃缓冲', 'jump buffer', '可变跳跃', '手感', '落地判定', '移动平台'],
     'references/howto/godot/platformer-feel.md',
     'get_real_velocity · _input 捕获缓冲 · CUT_SPEED 截断 · was_on_floor'),
    ('弹幕射击', ['弹幕', 'bullet hell', 'shmup', 'stg', '射击游戏弹幕', '擦弹', 'graze', '弹幕图案'],
     'references/howto/godot/genres-bullet-hell.md',
     'MultiMesh 定容量 · 只查判定点 · 固定逻辑步长 · 图案数据化'),
    ('破坏/布料/软体', ['破坏', '可破坏', '破碎', '碎片', 'destruction', '布料', 'cloth', 'softbody', '绳索'],
     'references/howto/godot/destruction-cloth.md',
     '预切分凸碎片 · 碎片池与预算 · SoftBody3D 只用于旗帜/果冻 · Jolt'),
    ('遮挡剔除/实例化', ['遮挡剔除', 'occlusion', 'occluder', '实例化', 'multimesh', 'gpu粒子', 'gpuparticles', 'compute', '计算着色器'],
     'references/howto/godot/occlusion-instancing.md',
     'OccluderInstance3D 烘焙 · visible_instance_count · RenderingDevice 仅 Forward+'),
    ('版本控制/资源组织', ['git', '版本控制', 'gitignore', 'uid', '命名规范', '目录结构', 'lfs', '场景冲突', '合并冲突'],
     'references/howto/godot/vcs-collab.md',
     '.uid 必须入库 · 移动带侧车 · 文本可 diff ≠ 可合并 · LFS 白名单'),
    ('性能预算/CI/评审', ['性能预算', 'perf budget', '代码评审', 'review', '技术债', '导出流水线', '预算台账', '门禁', '评审清单', '符号归档'],
     'references/howto/godot/project-governance.md',
     'P95/P99 而非均值 · Profiler 有开销 · 符号一一对应 · 高影响重构分 PR'),
    ('观战/重连/延迟补偿', ['观战', 'spectator', '断线重连', '重连', '主机迁移', 'migration', '延迟补偿', 'lag compensation', '服务端回溯', 'rewind判定', '插值缓冲', 'interpolation buffer', '预测纠正', '观战延迟'],
     'references/howto/godot/spectate-reconnect.md',
     '关战者是纯接收端不参与判定 · Peer ID是会话ID不是身份 · close()不发射peer_disconnected · 重连以收到连续权威快照为准 · 角色保留+AI托管不能queue_free · 仲裁要quorum否则双主 · 缓冲与延迟是同一枚货币'),
    ('群集/避障', ['群集', 'boids', 'boid', '群体行为', 'flock', 'swarm', '鱼群', '鸟群', 'avoidance', '避障', 'rvo', 'velocity_computed', 'set_velocity', '动态障碍'],
     'references/howto/godot/boids-swarm.md',
     'avoidance_enabled默认false · 收到velocity_computed要自己移动 · 静态障碍不能每帧移动 · 邻居查询要用网格裁剪避免On² · Navigation定去哪boids定怎么一起走'),
    ('分服/合服/匹配', ['分区分服', '分服', '跨服', '合服', '合区', 'shard', '匹配机制', 'matchmaking', 'elo', 'glicko', 'trueskill', '技能分', '匹配池', '全局id', '雪花id'],
     'references/howto/godot/sharding-matchmaking.md',
     '没有分服匹配API全在服务端 · 各服自增ID会撞车要全局ID · 合服要快照dry-run幂等保留回滚 · 邮件附件要幂等且会满 · 匹配判定必须服务端'),
    ('自动战斗/扫荡/回放', ['自动战斗', '挂机战斗', '扫荡', '快速战斗', '离线挂机', '重玩', '托管ai', 'auto_battle', 'sweep', 'offline_battle', '战力推算', '扫荡预览', '战斗托管'],
     'references/howto/godot/auto-battle.md',
     '同一战斗模拟器在四种输入源下的复用而非四套实现 · 扫荡是不带位置碰撞动画的结算函数不是加速战斗 · 预告与发放必须同一笔事务 · 自动AI只见玩家可见信息否则托管客观强于手动 · 离线一次性分段推导不能按真实时间跑循环 · 固定tick是回放基础 · 五个确定性杀手浮点随机遍历时间源外部输入 · 跨版本不兼容是产品约束 · 观战延迟首先是信息安全'),
    ('外观与个性化', ['时装', '捏人', '称号', '头像框', '表情动作', '坐骑皮肤', '限时时装', '外观资产', '外观槽位', '外观实例', 'ugc皮肤', 'cosmetic', 'outfit', 'title', 'emote', 'avatar_frame', 'appearance_slot', '外观到期'],
     'references/howto/godot/cosmetic.md',
     '客户端只持可展示缓存服务端保存拥有权有效期优先级授权 · 显示用A属性用B是第一道隔离 · 外观与装备实例必须分离 · 骨骼名相同不等于可换网格 · 染色必须实例材质改共享材质会污染所有同材质对象 · 称号可伪造会冒充GM · 坐骑皮肤不能改移速碰撞 · 默认外观要零外部依赖 · 增量丢包不自愈要全量校正 · 限时时装到期两种承诺必须购买前明确'),
    ('玩家交易/拍卖行', ['拍卖行', '摆摊', '玩家交易', '交易行', '市场', '寄售', '挂单', '一口价', '竞价', '交易税', '手续费', '延迟到账', '邮件附件', '公会仓库', '资产转移', '防刷', '洗金', '撤销交易', 'escrow', 'auction', 'listing', 'buyout', 'bid', 'trading', 'C2C', '定价', '托管', '装备绑定'],
     'references/howto/godot/player-trading.md',
     '客户端请求交易服务端决定一切 · 资产离开一个位置前必须先建立另一个位置的权威暂存 · 流转的是实例不是模板 · 绑定是迁移函数的输入每次重新求值 · 上架即用托管把物品从背包拿走否则双卖 · 一口价服务端重读价格 · 竞价本质是冻结领先者资金 · 价格显示是缓存成交必须实时 · 税三种模式不可混用且销毁比进系统钱包可控 · 延迟到账是盗号止损唯一窗口 · 撤销全有或全无不能只回滚货币 · 风控看关系链不是单笔 · 日志要写请求前快照加意图加结果'),
    ('潜行/侦察AI', ['潜行', '暗杀', '侦察', '搜查', '警戒', '警戒等级', '视野锥', '怀疑度', '尸体', '藏尸', '伪装', '潜行掩体', '脱战', '脱战冷却', '潜行脱战', 'suspicion', 'stealth', 'takedown', 'alert_state', 'search_ai', 'evidence'],
     'references/howto/godot/stealth-ai.md',
     '潜行不是发现未发现的布尔而是连续怀疑度加离散警戒等级加可观察行为三层 · 警戒要拆证据等级与行动状态两段 · 降级不能从HOSTILE直接跳UNSEEN · 单源怀疑度要有软上限否则一次落地直接进战斗 · 搜查是覆盖区域不是访问噪声点且要能被玩家利用 · 可见度是连续值采样头躯干脚三点 · 视野锥要让玩家看得见否则变猜谜 · 暗杀是六项状态条件不是处决换皮 · 尸体是持久证据要进对象预算'),
    ('枪械/射击', ['枪械', '射击', '后坐力', '弹道下坠', '武器切换', '换弹', '载弹量', '弹药', '瞄准', 'ads', '开镜', '扩散', '准星', '枪口', '探头', '射击掩体', 'recoil', 'reload', 'spread', 'hitscan', 'firearm', 'weapon_switch', 'peek', '射击延迟补偿', '穿透'],
     'references/howto/godot/firearms.md',
     '枪械是射击状态与规则层不是动画层 · 后坐力要拆视觉模式扩散三个独立变量不能是镜头抖动 · 扩散必须可读准星要显示命中半径但不参与命中 · 预测线必须和真实弹道共用一个积分器 · 换弹的逻辑装填门限早于动画结束 · 战术换弹枪膛留一发统一扣会让玩家白丢一发 · 切换是disable不是销毁 · 命中射线要归一到统一socket · 命中判定绝不能客户端定'),
    ('构筑/词条系统', ['构筑', '卡组构筑', '构筑校验', 'deckbuilding', '词条', '词条选择', '词缀', '词缀系统', 'affix', 'affix_id', '互斥组', '依赖组', '唯一组', '协同', 'trigger协同', '三选一', '遗物', 'build', '赛制', '禁用表', '限用表', 'banlist', '轮换', '减伤上限', '属性管线', 'generation_version', 'balance_version'],
     'references/howto/godot/build-affix.md',
     '构筑与词条是两条独立规则不要写进同一对象 · 词条存最终值会失去重算能力要存affix_id加roll加双version · generation与balance版本要分开 · 减伤两条75%相乘得93.75%逼近无敌人要组内求和组间相乘再clamp · 互斥要在生成换装局内选择属性聚合四个入口检查 · 协同分数值与触发两种 · 构筑要组卡保存开局三层校验且服务端重跑并签名 · 脏标记快照不是每帧遍历'),
    ('生活职业/采集生产/家园', ['生活职业', '采集', '采集点', '挖矿', '采矿', '钓鱼', '农场', '种植', '烹饪', '炼金', '锻造', '家园', '领地', '家具', '家具摆放', '占格', 'footprint', '配方', '配方发现', '熟练度', '加工链', '副产物', '损耗', '制作', '工作台', '材料绑定', '净产出', '通货膨胀'],
     'references/howto/godot/lifeskill-housing.md',
     '采集加工家园是同一材料闭环的三个闸门不是四个玩法 · 采集点是模板加世界实例不是一个节点 · 刷新要绝对锚点不能相对倒计时 · 开放世界共享池随机占槽与个人领地独立节点两套 · 配方是多级DAG要检查循环依赖否则无限增值 · 入队不等于消耗要开始时原子扣 · 家园用整数占格表不能用物理碰撞校验 · 要home.version防多人摆放冲突 · 家具加成要per_stat_cap'),
    ('账号安全/生命周期', ['账号安全', '账号安全体系', '盗号', '账号被盗', '账号找回', '找回密码', '密码存储', '密码安全', '密码怎么存储', '密码哈希存储', '二次验证', '2fa', 'mfa', 'totp', '密码存储', '密码哈希', 'argon2', 'bcrypt', 'refresh轮换', 'refresh token 轮换', '令牌撤销', '会话固定', '封禁', '封号', '解封', '申诉', '账号冻结', '风控', '异常登录', '转服', '角色转移', '账号合并', '注销状态机', '注销宽限期', '封禁申诉', '登录日志', 'account'],
     'references/howto/godot/account-security.md',
     'Godot是客户端不是安全边界user://不是凭据库 · 密码要Argon2id快速摘要加盐不算密码哈希 · access短命refresh要轮换且重用撤销整个family · TOTP30秒窗口最多1步 · 短信是RESTRICTED不能当唯一强验证 · 找回不能靠客服跳过第二因素 · 风控信号只增信不能当认证因子 · 注销不能只删角色 · 转服要同一幂等键'),
    ('服务端稳定性/事故响应', ['稳定性', '限流', '熔断', '降级', '服务降级', '超时', '重试', '重试风暴', '幂等键', '容量', '容量规划', '压测', '扩容', '监控', '告警', '告警降噪', '值班', 'oncall', '事故', '事故响应', '事故分级', '复盘', '灾备', '容灾', '备份', '备份验证', 'rpo', 'rto', '分库分表', '分片键', '冷数据', '缓存穿透', '缓存击穿', '缓存雪崩', 'slo', '熔断降级'],
     'references/howto/godot/backend-stability.md',
     '无超时无限流无熔断无界重试会把抖动放大成雪崩 · 限流按突发与排队选算法 · 熔断要统计超时 · 重试要退避抖动幂等键且jitter覆盖首次重连 · 分片键贴合访问路径 · 压测要测受控失败 · 告警必须可执行且要降噪 · 先恢复再查根因 · 备份副本数不能证明能恢复要演练 · 数据回滚常不可行要向前修'),
    ('宠物/坐骑/召唤', ['宠物', '坐骑', '骑乘', '上马', '下马', '召唤物', '召唤', '孵化', '合成台', '合成', '伙伴系统', '随从', '出战', '助战', '忠诚度', '饱食度', '宠物ai', '鞍点', '召唤物对象池', '召唤物上限', 'mount', 'summon', 'companion'],
     'references/howto/godot/companion.md',
     '没有Pet/Mount/Summon节点 · 宠物不是会动的装备要三层分离 · SpeciesTemplate共享Resource改一只影响所有同类 · 骑乘只有一个CharacterBody3D驱动 · reparent要call_deferred且保留全局变换 · 孵化/合成结果必须开始时roll · 召唤物要对象池且服务端强制上限'),
    ('时间推进/离线结算', ['时间推进', '离线结算', '生产队列', '建造队列', '体力', '精力', '体力时间戳', '每日重置', '周期重置', '赛季重置', '重置边界', '立即完成', '加速完成', '封顶', '挂机封顶', '时间锚点', 'last_settled', '离线补算'],
     'references/howto/godot/time-progression.md',
     '内核只有elapsed=now-last_settled_at · 存档存绝对锚点不存剩余秒数 · 余数必须写回锚点float累加器禁止 · 离线速率按事件日志分段不能按回来那一刻倒推 · 封顶是留存节奏 · 重置是硬边界要能补算 · PAUSED只做持久化iOS约5秒'),
    ('合规/法务/版号', ['版号', '出版物号', '实名认证', '实名', '防沉迷', '适龄', '适龄提示', '隐私政策', '用户协议', '数据删除', '删除账号', '注销账号', '账号注销', '被遗忘权', '个人信息', '个人信息保护', 'gdpr', 'ccpa', '数据出境', '未成年人', '未成年', '出海合规', '合规审核', '内容审核', '屏蔽词', '敏感词库', 'ugc', '隐私清单', '数据安全表单', '版号申请'],
     'references/howto/godot/compliance.md',
     'Godot无任何合规API · 版号80工作日是受理后不含补正 · 防沉迷现行是周五六日及法定节假日20-21时1小时(2019口径已作废) · 实名是登录前置含游客模式 · 未满8岁禁付8-16岁50/200、16-18岁100/400 · 注销是状态机不是DELETE · 数据出境按当年累计人数'),
        
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
            # 大小写不敏感：实测 'ai感知' 在域名 'AI感知' 里，
            # 但 'ai感知' in 'AI感知' 为 False（小写 ai ≠ 大写 AI），
            # 导致平局打破器失效，被列表里更靠前的通用域抢走。
            bonus = 1 if max(uniq, key=len).lower() in name.lower() else 0
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
    # 注意：不能用含领域词的句子做"无关"断言 —— 环境系统域上线后
    # "今天天气怎么样" 会正确命中它，断言本身就过期了。用真正无领域词的句子。
    chk(match_domains('今天中午吃什么') == [], '无关需求不误匹配')
    d = match_domains('今天天气怎么样')
    chk(bool(d) and d[0][0] == '环境系统', '"今天天气怎么样" → 环境系统（领域词应命中）')

    # 关键词子串碰撞：'移动' ⊆ '移动端'
    # 按命中个数排会让"移动端性能"路由到「角色控制」，输出看起来正常但全错
    d = match_domains('移动端性能')
    chk(bool(d) and d[0][0] == '移动端/触控',
        '"移动端性能" → 移动端/触控（长词压过"移动"，得到 %s）'
        % (d[0][0] if d else '无'))

    d = match_domains('角色移动')
    chk(bool(d) and d[0][0] == '角色控制', '"角色移动" → 角色控制（未被"移动端"抢走）')

    # ---- 观战/重连/延迟补偿（与「回放/录像」「网络同步进阶」分层） ----
    d = match_domains('怎么做观战模式')
    chk(bool(d) and d[0][0] == '观战/重连/延迟补偿',
        '"观战模式" → 观战/重连/延迟补偿（得到 %s）' % (d[0][0] if d else '无'))

    d = match_domains('玩家断线重连后怎么恢复')
    chk(bool(d) and d[0][0] == '观战/重连/延迟补偿',
        '"断线重连" → 观战/重连/延迟补偿（得到 %s）' % (d[0][0] if d else '无'))

    d = match_domains('spectator 延迟补偿怎么做')
    chk(bool(d) and d[0][0] == '观战/重连/延迟补偿',
        '"spectator 延迟补偿" → 观战/重连/延迟补偿（得到 %s）' % (d[0][0] if d else '无'))

    d = match_domains('主机迁移 migration')
    chk(bool(d) and d[0][0] == '观战/重连/延迟补偿',
        '"主机迁移" → 观战/重连/延迟补偿（得到 %s）' % (d[0][0] if d else '无'))

    # 分层：确定性/回放录制归「回放/录像」，不归观战域
    d = match_domains('回放的确定性怎么保证')
    chk(bool(d) and d[0][0] == '回放/录像',
        '"回放确定性" → 回放/录像（不归观战域，得到 %s）' % (d[0][0] if d else '无'))

    d = match_domains('时间倒带 rewind 玩法')
    chk(bool(d) and d[0][0] == '时间操控',
        '"倒带 rewind" → 时间操控（玩法层，得到 %s）' % (d[0][0] if d else '无'))

    # 所有域指向的文档必须真实存在。
    # 教训：群集/避障域曾被改名（physics-constraints.md → boids-swarm.md），
    # 但路由里的路径没跟着改 —— 关键词命中、自检全绿，用户却拿到一个不存在的文件名。
    # 关键词冲突检查抓不到这错，必须显式验证路径。
    _bad = []
    for _d in DOMAINS:
        _fp = _os.path.join(_os.path.dirname(HERE), _d[2])
        if not _os.path.isfile(_fp):
            _bad.append('%s → %s' % (_d[0], _d[2]))
    chk(not _bad, '所有域指向的文档都存在（缺 %d: %s）' % (len(_bad), _bad[:3]))

    # ---- 群集/避障 与 分服/合服/匹配 ----
    for q, want in (('boids 群集怎么做', '群集/避障'),
                    ('鱼群鸟群群体行为', '群集/避障'),
                    ('NavigationAgent avoidance 避障', '群集/避障'),
                    ('合服数据怎么合并', '分服/合服/匹配'),
                    ('跨服战场 ID 冲突', '分服/合服/匹配'),
                    ('matchmaking elo 匹配', '分服/合服/匹配')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：载具/关节归「载具/物理进阶」，浮力归「环境系统」，都不归群集域
    for q, want in (('VehicleBody3D 翻车', '载具/物理进阶'),
                    ('水面浮力怎么做', '环境系统'),
                    ('账号登录 token', '平台服务'),
                    ('反外挂加速检测', '存档安全/防作弊')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # ---- 合规/法务/版号 ----
    # 裸「敏感词」留给多人社交（聊天过滤场景），合规侧用「屏蔽词/敏感词库/ugc审核」，
    # 避免两边抢同一个词导致输出看着正常却指向错文档。
    for q, want in (('游戏版号怎么申请', '合规/法务/版号'),
                    ('防沉迷时段怎么实现', '合规/法务/版号'),
                    ('未成年人充值限额', '合规/法务/版号'),
                    ('实名认证接入', '合规/法务/版号'),
                    ('隐私政策和 GDPR', '合规/法务/版号'),
                    ('玩家要求删除账号', '合规/法务/版号'),
                    ('账号注销流程', '合规/法务/版号'),
                    ('敏感词库怎么维护', '合规/法务/版号'),
                    ('屏蔽词送审', '合规/法务/版号'),
                    ('数据出境合规', '合规/法务/版号'),
                    ('适龄提示 8+', '合规/法务/版号')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 裸「敏感词」必须仍归多人社交（聊天过滤），不能被合规域抢走
    d = match_domains('聊天敏感词过滤')
    chk(bool(d) and d[0][0] == '多人社交',
        '裸「敏感词」仍归多人社交（得到 %s）' % (d[0][0] if d else '无'))

    # ---- 宠物/坐骑/召唤 与 时间推进/离线结算 ----
    for q, want in (('宠物系统怎么做', '宠物/坐骑/召唤'),
                    ('坐骑上下马实现', '宠物/坐骑/召唤'),
                    ('召唤物对象池', '宠物/坐骑/召唤'),
                    ('孵化计时与结果', '宠物/坐骑/召唤'),
                    ('合成台配方', '宠物/坐骑/召唤'),
                    ('离线结算余数怎么处理', '时间推进/离线结算'),
                    ('生产队列建造队列', '时间推进/离线结算'),
                    ('每日重置怎么定', '时间推进/离线结算'),
                    ('赛季重置边界', '时间推进/离线结算'),
                    ('立即完成怎么计费', '时间推进/离线结算'),
                    ('挂机封顶时长', '时间推进/离线结算')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：裸「挂机/离线收益」归放置品类，裸「体力恢复」归生存状态，
    # 深层的「离线结算/每日重置」才归时间推进 —— 避免品类域被架空
    # ---- 自动战斗/扫荡 与 外观与个性化 ----
    for q, want in (('自动战斗怎么设计', '自动战斗/扫荡/回放'),
                    ('扫荡流程', '自动战斗/扫荡/回放'),
                    ('离线挂机结算', '自动战斗/扫荡/回放'),
                    ('战力推算扫荡', '自动战斗/扫荡/回放'),
                    ('托管ai', '自动战斗/扫荡/回放'),
                    ('时装系统', '外观与个性化'),
                    ('称号显示', '外观与个性化'),
                    ('头像框', '外观与个性化'),
                    ('表情动作', '外观与个性化'),
                    ('坐骑皮肤', '外观与个性化'),
                    ('限时时装到期', '外观与个性化')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：回放/观战仍归专门文档，染色换装仍归角色自定义
    for q, want in (('回放确定性', '回放/录像'),
                    ('观战延迟', '观战/重连/延迟补偿'),
                    ('换装染色怎么做', '角色自定义')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # ---- 玩家交易/拍卖行 ----
    for q, want in (('拍卖行怎么设计', '玩家交易/拍卖行'),
                    ('挂单流程', '玩家交易/拍卖行'),
                    ('一口价与竞价', '玩家交易/拍卖行'),
                    ('交易税怎么算', '玩家交易/拍卖行'),
                    ('延迟到账', '玩家交易/拍卖行'),
                    ('防刷金', '玩家交易/拍卖行'),
                    ('公会仓库', '玩家交易/拍卖行'),
                    ('邮件附件交易', '玩家交易/拍卖行'),
                    ('摆摊寄售', '玩家交易/拍卖行'),
                    ('装备绑定能不能交易', '玩家交易/拍卖行')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：产出与消耗侧仍归经济/长线，商业化仍归 monetization
    for q, want in (('货币产出与消耗', '经济/长线系统'),
                    ('抽卡概率公示', '商业化/变现')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # ---- 潜行/侦察AI 与 枪械/射击 ----
    for q, want in (('潜行警戒等级怎么设计', '潜行/侦察AI'),
                    ('搜查行为', '潜行/侦察AI'),
                    ('视野锥渲染', '潜行/侦察AI'),
                    ('暗杀条件', '潜行/侦察AI'),
                    ('尸体被发现', '潜行/侦察AI'),
                    ('伪装系统', '潜行/侦察AI'),
                    ('脱战冷却', '潜行/侦察AI'),
                    ('后坐力怎么实现', '枪械/射击'),
                    ('换弹逻辑', '枪械/射击'),
                    ('扩散与准星', '枪械/射击'),
                    ('武器切换', '枪械/射击'),
                    ('ads瞄准', '枪械/射击'),
                    ('掩体探头', '枪械/射击'),
                    ('弹道下坠', '枪械/射击')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：裸「感知/视野/听觉/记忆」仍归 AI 感知（机制层），
    # 「延迟补偿/rewind」仍归观战·重连（同步层）—— 避免新域架空既有域
    for q, want in (('敌人视野检测', 'AI感知'),
                    ('延迟补偿怎么做', '观战/重连/延迟补偿')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # ---- 战斗对抗层 与 阵营/声望/战力/战报 ----
    for q, want in (('硬直怎么递减', '战斗系统'),
                    ('霸体与韧性', '战斗系统'),
                    ('破防窗口', '战斗系统'),
                    ('招架窗口怎么定', '战斗系统'),
                    ('处决触发条件', '战斗系统'),
                    ('部位破坏', '战斗系统'),
                    ('取消窗口与输入缓冲', '战斗系统'),
                    ('阵营关系怎么存', '多人社交'),
                    ('声望衰减', '多人社交'),
                    ('战力能不能当匹配依据', '多人社交'),
                    ('战报存什么', '多人社交'),
                    ('阵营切换代价', '多人社交'),
                    ('据点占领', '多人社交'),
                    ('师徒结拜关系', '多人社交')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：观战/断线重连 仍归 spectate-reconnect（不掉线重连本身），
    # 「战斗回放/战报」才归社交 —— 避免新词架空既有域
    for q, want in (('断线重连', '观战/重连/延迟补偿'),):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # ---- 构筑/词条 与 生活职业/采集生产/家园 ----
    for q, want in (('词条怎么存', '构筑/词条系统'),
                    ('构筑校验要做几次', '构筑/词条系统'),
                    ('减伤词条相乘无敌', '构筑/词条系统'),
                    ('互斥组怎么声明', '构筑/词条系统'),
                    ('三选一词条选择', '构筑/词条系统'),
                    ('禁用表与轮换', '构筑/词条系统'),
                    ('采集点刷新怎么做', '生活职业/采集生产/家园'),
                    ('加工链配方', '生活职业/采集生产/家园'),
                    ('家园家具摆放校验', '生活职业/采集生产/家园'),
                    ('挖矿钓鱼农场', '生活职业/采集生产/家园'),
                    ('熟练度与配方发现', '生活职业/采集生产/家园'),
                    ('材料绑定规则', '生活职业/采集生产/家园')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：裸「卡组/牌库/洗牌」仍归卡牌对战（牌堆与效果栈），
    # 「构筑校验/词条」才归构筑域；「合成台/孵化」仍归宠物域 —— 避免架空既有域
    for q, want in (('洗牌与牌库回收', '卡牌/桌游'),
                    ('合成台配方', '宠物/坐骑/召唤')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # ---- 账号安全 与 服务端稳定性 ----
    for q, want in (('账号被盗怎么找回', '账号安全/生命周期'),
                    ('密码怎么存储', '账号安全/生命周期'),
                    ('二次验证 TOTP', '账号安全/生命周期'),
                    ('refresh token 轮换', '账号安全/生命周期'),
                    ('封禁与申诉流程', '账号安全/生命周期'),
                    ('转服角色转移', '账号安全/生命周期'),
                    ('风控异常登录', '账号安全/生命周期'),
                    ('限流熔断降级', '服务端稳定性/事故响应'),
                    ('容量规划与压测', '服务端稳定性/事故响应'),
                    ('告警降噪与值班', '服务端稳定性/事故响应'),
                    ('事故分级与复盘', '服务端稳定性/事故响应'),
                    ('灾备备份与回滚', '服务端稳定性/事故响应'),
                    ('分片键怎么选', '服务端稳定性/事故响应')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # 分层：基础 token/鉴权 归平台服务；隐私删除权归合规；
    # 稳定性与运营侧（补偿幂等）分开 —— 避免新域架空既有域
    for q, want in (('平台账号 token 接入', '平台服务'),
                    ('玩家要求删除账号', '合规/法务/版号'),
                    ('补偿发放幂等', '运营服务端')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    for q, want in (('挂机游戏怎么做', '模拟经营/放置'),
                    ('体力恢复机制', '生存/角色状态')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

    # ---- 运营服务端补关键词 ----
    for q, want in (('七日签到怎么做', '运营服务端'),
                    ('战令通行证赛季结算', '运营服务端'),
                    ('礼包码生成', '运营服务端'),
                    ('公告系统', '运营服务端')):
        d = match_domains(q)
        chk(bool(d) and d[0][0] == want,
            '"%s" → %s（得到 %s）' % (q, want, d[0][0] if d else '无'))

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

    # UI进阶 / 诊断 不被旧域抢走，且既有 accessibility.md 不被抢
    for need, want in (('富文本', 'UI进阶'), ('虚拟列表', 'UI进阶'), ('拖拽UI', 'UI进阶'),
                       ('键盘导航', 'UI进阶'), ('剪贴板', 'UI进阶')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('错误处理', '诊断与稳定性'), ('崩溃上报', '诊断与稳定性'),
                       ('assert', '诊断与稳定性'), ('日志分级', '诊断与稳定性')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    # 呈现层无障碍仍归 accessibility.md，不被 UI进阶 抢走
    for need, want in (('无障碍', '无障碍/字幕'), ('字幕', '无障碍/字幕'), ('色盲', '无障碍/字幕')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（呈现层未被抢）' % (need, want))
    for need, want in (('ui无障碍', 'UI进阶'), ('焦点导航', 'UI进阶')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（交互层）' % (need, want))
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ('ui-advanced.md', 'diagnostics.md', 'accessibility.md'):
        chk(os.path.exists(os.path.join(here, 'references/howto/godot', fn)), '%s 存在' % fn)

    # 反向检查：常用短词必须能匹配到域
    # 为什么需要：清理关键词冲突时容易把短词删光（实测删到"音效"/"音乐"/"mod"
    # 都在任何域里都不存在了），用户用最常见说法问反而没结果 —— 这比指错文档更糟。
    for _w in ('音效', '音乐', 'mod', '物理', '动画', 'UI', '存档', '网络', '渲染',
               '光照', '相机', '音频', '输入', '手柄', '地形', '粒子', '碰撞'):
        chk(bool(match_domains(_w)), '"%s" 至少匹配到一个域（未被清理过头）' % _w)

    # 全局：不允许任何关键词被别的域抢走
    # 为什么固化成断言（而不是只提供 --check-conflicts 命令）：
    # 新域上线时关键词重叠是常态，靠人工试需求词覆盖不全（75 个域）。
    # 让它进自检，冲突在提交时就暴露，而不是等用户问了才发现指错文档。
    stolen = []
    for _name, _kws, _e, _d in DOMAINS:
        for _w in _kws:
            _r = match_domains(_w)
            if _r and _r[0][0] != _name:
                stolen.append((_w, _name, _r[0][0]))
    chk(not stolen, '无关键词被别的域抢走（当前 %d 个：%s）' % (
        len(stolen), '、'.join('%s→%s' % (w, win) for w, _, win in stolen[:5])))

    # 商业化 / 投射物 不被旧域抢走，且相关旧域仍可达
    for need, want in (('支付', '商业化/变现'), ('激励视频', '商业化/变现'), ('内购', '商业化/变现'),
                       ('抽卡', '商业化/变现'), ('保底', '商业化/变现'), ('概率公示', '商业化/变现')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('弹道', '投射物/弹道'), ('hitscan', '枪械/射击'), ('弹道预测', '投射物/弹道')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('经济', '经济/长线系统'), ('掉落保底', '经济/长线系统'),
                       ('hitbox', '战斗系统'), ('子弹池', '对象池')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（邻近域未被抢）' % (need, want))
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ('monetization.md', 'projectile.md'):
        chk(os.path.exists(os.path.join(here, 'references/howto/godot', fn)), '%s 存在' % fn)

    # 进阶移动 / 多人社交 不被旧域抢走，且基础域仍可达
    for need, want in (('二段跳', '进阶移动'), ('爬墙', '进阶移动'), ('抓边', '进阶移动'),
                       ('游泳', '进阶移动'), ('重力方向', '进阶移动')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    # 注意：'matchmaking' 已迁至「分服/合服/匹配」专门域（匹配判定必须服务端、
    # 分服合服与匹配是同一套服务端职责），多人社交不再持有该词。
    for need, want in (('大厅', '多人社交'), ('好友', '多人社交'),
                       ('聊天', '多人社交'), ('公会', '多人社交'), ('举报', '多人社交')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('角色移动', '角色控制'), ('跳跃', '角色控制'), ('载具', '载具/物理进阶')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（基础域未被抢）' % (need, want))
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ('movement-advanced.md', 'social.md'):
        chk(os.path.exists(os.path.join(here, 'references/howto/godot', fn)), '%s 存在' % fn)

    # 生存 / 叙事 不被旧域抢走，且基础域仍可达
    for need, want in (('生命值', '生存/角色状态'), ('耐力', '生存/角色状态'),
                       ('死亡重生', '生存/角色状态'), ('检查点', '生存/角色状态'),
                       ('负重', '生存/角色状态')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('任务链', '叙事/进程'), ('对话树', '叙事/进程'), ('好感度', '叙事/进程'),
                       ('多结局', '叙事/进程'), ('周目', '叙事/进程'), ('动态难度', '叙事/进程')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('对话', '游戏系统'), ('任务', '游戏系统'), ('关卡检查点', '关卡设计')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（基础域未被抢）' % (need, want))
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ('survival.md', 'narrative.md'):
        chk(os.path.exists(os.path.join(here, 'references/howto/godot', fn)), '%s 存在' % fn)

    # 谜题 / 时间操控 不被旧域抢走
    for need, want in (('谜题', '谜题/机关'), ('机关', '谜题/机关'), ('压力板', '谜题/机关'),
                       ('推箱子', '谜题/机关'), ('反射谜题', '谜题/机关'), ('可破坏物', '谜题/机关')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('慢动作', '时间操控'), ('子弹时间', '时间操控'), ('倒带', '时间操控'),
                       ('暂停', '时间操控'), ('process_mode', '时间操控')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ('puzzle.md', 'timescale.md'):
        chk(os.path.exists(os.path.join(here, 'references/howto/godot', fn)), '%s 存在' % fn)

    # 镜像一致性：每个功能域的「怎么做」在开发侧，「不能怎么做」在审查侧
    # 两边必须 1:1 同名，否则会出现"有做法没约束"或"有约束没做法"的孤儿。
    import os
    _skill = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _dev = os.path.join(_skill, 'references', 'howto', 'godot')
    _audit = os.path.join(_skill, 'references', 'audit', 'godot')
    chk(os.path.isdir(_audit), '本 skill 审核部分 audit/godot/ 目录存在')
    if os.path.isdir(_audit):
        _devset = {f for f in os.listdir(_dev) if f.endswith('.md')}
        _audset = {f for f in os.listdir(_audit) if f.endswith('.md')}
        # 允许审查侧少几份（不是每个域都有坑表），但不能有审查侧独有
        _orphan = sorted(_audset - _devset)
        chk(not _orphan, '审核部分无孤儿（有约束没做法）: %s' % _orphan[:3])
        _covered = len(_audset & _devset)
        chk(_covered >= 70, '流程↔审核 镜像覆盖 ≥70 个域（当前 %d）' % _covered)
        # 开发侧每个域都要指向自己的反模式清单
        _missing = [f for f in sorted(_devset & _audset)
                    if 'audit/godot/%s' % f not in open(
                        os.path.join(_dev, f), encoding='utf-8').read()]
        chk(not _missing, '流程侧各域都有指向审核部分（缺 %d: %s）'
            % (len(_missing), _missing[:3]))

        # ⚠ howto ↔ audit 对称性：审核项里出现的技术点，做法侧必须讲过。
        #   否则这条审核项无处可依 —— 审核时无法确认为什么不能这么做，
        #   改的时候也不知道该怎么做。这类断链会随文档增多而累积。
        try:
            import importlib.util as _ilu
            _sp = _ilu.spec_from_file_location(
                '_sym', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'check-symmetry.py'))
            _sym = _ilu.module_from_spec(_sp)
            _sp.loader.exec_module(_sym)
            _gaps = _sym.scan()
            chk(not _gaps, 'howto↔audit 对称：审核项的技术点都在做法侧讲过'
                           '（缺 %d: %s）' % (
                               sum(len(g['miss']) for g in _gaps),
                               [(g['file'], sorted(g['miss'])[:2]) for g in _gaps[:2]]))
        except Exception as _e:      # ⓘ 扫描器自身出错不应静默放行
            chk(False, 'howto↔audit 对称扫描器可运行（%s）' % _e)

    # ⚠ 全局层多对多索引：common/ 里的块是"不可能每个功能单独写"的内容，
    #   必须能被多个域索引到，否则就是"放着该有用的时候用不上"。
    #   ⛔ 单向登记不算索引：表里写了但文档里没有，做的时候照样找不到。
    _cmn = os.path.join(_skill, 'references', 'common')
    chk(os.path.isdir(_cmn), '全局层 common/ 目录存在')
    if os.path.isdir(_cmn):
        try:
            import importlib.util as _ilu2
            _sp2 = _ilu2.spec_from_file_location(
                '_cidx', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'check-common-index.py'))
            _ci = _ilu2.module_from_spec(_sp2)
            _sp2.loader.exec_module(_ci)
            _bad = _ci.scan()
            chk(not _bad, '全局层多对多索引成立（表↔文档双向、无孤儿、无断链）'
                          '：%d 个问题 %s' % (len(_bad), _bad[:2]))
        except Exception as _e2:     # ⓘ 检查器自身出错不应静默放行
            chk(False, '全局层索引检查器可运行（%s）' % _e2)
        # ⚠ 待核对机制必须真的能收集到条目。
        #   上一次迁移把 flow/godot → howto/godot，而 verify.py 里仍是旧路径：
        #   目录存在但没有 .md → 收集到 0 条而**不报错**，整套机制形同虚设。
        #   ⛔ 这类"路径失效静默变成空结果"必须靠"结果数 > 0"来兜，
        #      只检查"脚本能跑通"是查不出来的。
        try:
            _sp3 = _ilu2.spec_from_file_location(
                '_vfy', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     'verify.py'))
            _vf = _ilu2.module_from_spec(_sp3)
            _sp3.loader.exec_module(_vf)
            _n = len(_vf.collect())
            chk(_n > 0, '待核对机制能收集到条目（当前 %d 条；0 条说明扫描路径指错层）' % _n)
            _nohow = _vf.collect_nohow()
            chk(not _nohow,
                '所有待核对项都写了验证方法（缺 %d: %s）'
                % (len(_nohow), [x['claim'][:20] for x in _nohow[:2]]))
        except Exception as _e3:     # ⓘ 检查器自身出错不应静默放行
            chk(False, '待核对项检查器可运行（%s）' % _e3)
        # ⚠ 扫描器「输入语料」守卫 —— 四个扫描器统一经过 corpus_guard。
        #   为什么不断言"输出非空"：0 断链 / 0 问题 都是**好状态**，
        #   ⛔ 断言输出 > 0 会让"修完问题"反而自检失败，判据方向是反的。
        #   真正的失败信号是"输入语料为 0" —— 那只可能是路径指错层。
        _here = os.path.dirname(os.path.abspath(__file__))
        _mods = []
        for _fn in ('verify.py', 'scan-gaps.py', 'check-symmetry.py',
                    'check-common-index.py'):
            try:
                _sp = _ilu2.spec_from_file_location(
                    '_cg_' + _fn[:-3], os.path.join(_here, _fn))
                _m = _ilu2.module_from_spec(_sp)
                _sp.loader.exec_module(_m)
                _mods.append(_m)
            except Exception as _e:
                chk(False, '可加载扫描器 %s（%s）' % (_fn, _e))
        try:
            sys.path.insert(0, _here)
            import corpus_guard as _cg
            _ok, _cf = _cg.run(_mods)
            chk(not _cf, '扫描器输入语料非空（%s）' % '；'.join(_cf[:3]))
            chk(_ok == len(_mods),
                '全部 %d 个扫描器通过语料守卫（通过 %d）' % (len(_mods), _ok))
        except Exception as _e:
            chk(False, '语料守卫可运行（%s）' % _e)
        finally:
            if _here in sys.path:
                sys.path.remove(_here)
        # common.md 必须指向全局块，否则它是个没人能到达的孤岛
        _cm = os.path.join(_skill, 'references', 'common.md')
        if os.path.isfile(_cm):
            _t = open(_cm, encoding='utf-8').read()
            chk('common/howto/principles.md' in _t and 'common/audit/global.md' in _t,
                'common.md 指向全局块（否则全局层无人可达）')

    # ⚠ 迁移防回流：三层目录名必须正确，且不得残留旧名。
    #   改名后若有人按旧记忆加文件/写链接，会从这里冒出来。
    _ref = _os.path.join(_skill, 'references')
    chk(_os.path.isdir(_os.path.join(_ref, 'flow')), '流程层 flow/ 存在')
    chk(_os.path.isdir(_os.path.join(_ref, 'howto')), '做法层 howto/ 存在')
    chk(_os.path.isdir(_os.path.join(_ref, 'audit')), '审核层 audit/ 存在')
    chk(not _os.path.exists(_os.path.join(_ref, 'procedure')),
        '旧名 procedure/ 已不存在（防迁移回流）')
    chk(not _os.path.isdir(_os.path.join(_ref, 'howto', 'character')),
        '做法层不含功能点子目录（按域组织，不是按功能点）')
    # 全库扫旧串：任何文件里出现 references/flow/godot 都是漏改
    _old = []
    for _r, _ds, _fss in _os.walk(_os.path.dirname(_skill)):
        if '.git' in _r:
            continue
        for _fn in _fss:
            if not (_fn.endswith('.md') or _fn.endswith('.py')):
                continue
            _t = open(_os.path.join(_r, _fn), encoding='utf-8', errors='ignore').read()
            if re.search(r'references/flow/godot/[\w-]+\.md', _t):
                _old.append(_os.path.join(_r, _fn).split('skills/')[-1])
    chk(not _old, '无残留旧串 references/flow/godot（漏改 %d: %s）' % (len(_old), _old[:2]))

    # 工序层 flow/ 的一致性：铺开后最容易退化的是"模板缺节"和"索引断链"。
    # ⚠ 这两类问题不会报错——文件在、链接也在，但按它开发会漏掉验收环节。
    _ORPHAN_FILE_MAX = 88   # ⓘ 基线：当前未铺流程的域数；铺一个域应下降
    _proc = _os.path.join(_skill, 'references', 'flow')
    # ⚠ 全库文件必须是合法 UTF-8。
    #   ⓘ 为什么查：曾出现某个 .md 中间一段字节被截断（写入时损坏），
    #     而流程层的读取用严格 utf-8 会抛 UnicodeDecodeError；
    #     若某处用了 errors='ignore' 就会**静默丢字**，检查全绿但内容已残。
    #     这类损坏不报错、不崩溃，只表现为"文档里少了一句话"。
    _badenc = []
    for _r7, _d7, _f7 in _os.walk(_os.path.join(_skill, 'references')):
        for _fn7 in sorted(_f7):
            if not _fn7.endswith('.md'):
                continue
            _p7 = _os.path.join(_r7, _fn7)
            try:
                _b7 = open(_p7, 'rb').read().decode('utf-8')
            except UnicodeDecodeError as _e7:
                _badenc.append('%s@%d' % (_fn7, _e7.start)); continue
            if '\ufffd' in _b7:
                _badenc.append('%s(含替换符)' % _fn7)
    chk(not _badenc, 'references 全部为合法 UTF-8（坏 %d: %s）'
        % (len(_badenc), _badenc[:3]))

    chk(_os.path.isdir(_proc), '工序层 flow/ 目录存在')
    if _os.path.isdir(_proc):
        # ⚠ 三类文件套三种模板，⛔ 不能一刀切：
        #   00-总览 是入口（没有参考实现），*-验收 是验收步（同样没有），
        #   其余才是功能点（七节齐全）。早期一刀切把前两类误判为缺节。
        _REQ_FP = ['## 0.', '## 1. 前置检查清单', '## 2. 工序',
                   '## 3. 参考实现', '## 4. 验收清单', '## 5. 常见返工', '## 6. 下一步']
        _REQ_ENTRY = ['## 0.', '## 1. 功能点拆解']
        _REQ_ACCEPT = ['## 0.', '## 2. 工序', '## 3. 验收清单']
        _bad = []
        _n_fp = _n_entry = _n_acc = 0
        for _root, _dirs, _files in _os.walk(_proc):
            for _f in sorted(_files):
                if not _f.endswith('.md'):
                    continue
                # ⓘ README.md / index.md 是层说明与索引，_ 前缀是层内基础件
                #   （如 _骨架.md），三者都不是功能点，不套功能点模板
                if _f in ('README.md', 'index.md') or _f.startswith('_'):
                    continue
                _txt = open(_os.path.join(_root, _f), encoding='utf-8').read()
                if _f.startswith('00-'):
                    _req, _n_entry, _kind = _REQ_ENTRY, _n_entry + 1, '总览'
                elif '验收' in _f:
                    _req, _n_acc, _kind = _REQ_ACCEPT, _n_acc + 1, '验收'
                else:
                    _req, _n_fp, _kind = _REQ_FP, _n_fp + 1, '功能点'
                _miss = [h for h in _req if h not in _txt]
                if _miss:
                    _bad.append('%s(%s) 缺 %s' % (_f, _kind, _miss[:2]))
        chk(not _bad, '工序文件按类型模板齐全（缺 %d: %s）' % (len(_bad), _bad[:2]))
        chk(_n_fp >= 10, '工序功能点数 ≥10（当前 %d）' % _n_fp)
        chk(_n_entry >= 2, '域总览入口 ≥2（当前 %d）' % _n_entry)

        # 每个域都要有 00-域流程总览（入口），否则调用方不知道从哪开始
        _no_entry = []
        for _d in sorted(_os.listdir(_proc)):
            _dd = _os.path.join(_proc, _d)
            if not _os.path.isdir(_dd):
                continue
            for _eng in sorted(_os.listdir(_dd)):
                _ed = _os.path.join(_dd, _eng)
                if not _os.path.isdir(_ed):
                    continue
                if not any(f.startswith('00-') for f in _os.listdir(_ed)):
                    _no_entry.append('%s/%s' % (_d, _eng))
        chk(not _no_entry, '每个域都有 00-域流程总览（缺 %s）' % _no_entry[:2])

        # index.md 里的链接必须真实存在 —— 断链时用户点进去是 404
        _idx = _os.path.join(_proc, 'index.md')
        if _os.path.exists(_idx):
            _itxt = open(_idx, encoding='utf-8').read()
            _links = re.findall(r'\]\(([^)]+\.md)\)', _itxt)
            _broken = [l for l in _links
                       if not _os.path.exists(_os.path.join(_proc, l))]
            chk(not _broken, 'flow/index.md 链接无断链（断 %d: %s）'
                % (len(_broken), _broken[:2]))
            chk(len(_links) >= 10, 'flow/index.md 索引条目 ≥10（当前 %d）' % len(_links))

            # ⚠ Markdown 表格列数必须一致。
            #   上一版 index.md 的"已铺域"表里，AI 那一行被脚本拼接时
            #   把后面几个域的覆盖格**全部并进了同一行** → 渲染出来是一张
            #   长到看不见末尾的畸形表，而**链接检查、条目计数全都是绿的**。
            #   ⛔ 断链检查查不出这种"结构正确、内容错位"的问题。
            _rows = [l for l in _itxt.split('\n')
                     if l.startswith('|') and not l.startswith('|---')]
            # ⓘ 按**连续块**分组：一个文件里可以有多张不同列数的表，
            #   但同一张表内部列数必须一致。
            #   ⛔ 第一版我写成"全文件取占多数的列数为正常" ——
            #      结果把合法的 2 列表（框架设施表）判成异常（假阳性）。
            #   ⚠ 假阳性会诱导人去放宽判据；正确做法是收紧到"连续块"。
            _blocks, _cur = [], []
            for _l in _itxt.split('\n'):
                if _l.startswith('|'):
                    _cur.append(_l)
                else:
                    if _cur:
                        _blocks.append(_cur); _cur = []
            if _cur:
                _blocks.append(_cur)
            _odd = []
            for _b in _blocks:
                _body = [l for l in _b if not l.startswith('|---')]
                if not _body:
                    continue
                _ncol = _body[0].count('|')
                for _l in _body[1:]:
                    if _l.count('|') != _ncol:
                        _odd.append(_l)
            chk(not _odd,
                'flow/index.md 表格列数一致（异常 %d 行: %s）'
                % (len(_odd), [r[:40] for r in _odd[:2]]))

        # 框架设施：结构总纲 + 通用骨架。
        # ⚠ 骨架是兜底设施 —— 110 个域只有少数有细化流程，其余全靠它，
        #   它丢了就退回"凭记忆开工"。
        chk(_os.path.exists(_os.path.join(_skill, 'references', 'structure.md')),
            '结构框架总纲 references/structure.md 存在')
        _skel = _os.path.join(_proc, '_骨架.md')
        chk(_os.path.exists(_skel), '通用骨架 _骨架.md 存在')
        if _os.path.exists(_skel) and _os.path.exists(_os.path.join(_proc, 'index.md')):
            _it = open(_os.path.join(_proc, 'index.md'), encoding='utf-8').read()
            chk('_骨架.md' in _it, 'index.md 指向通用骨架（未细化的域有兜底入口）')

        # 节点规范：Step 要有稳定 ID（后续流程工具按节点记进度）、
        # 要有【读】howto（按需取用，不通读）、功能点要有整体审核节（两级审核）。
        # ⓘ 现有 12 个功能点已补齐，故可直接强检。
        _no_id, _no_read, _no_audit_sec = [], [], []
        for _root, _dirs, _files in _os.walk(_proc):
            for _f in sorted(_files):
                if _f in ('README.md', 'index.md') or _f.startswith('_'):
                    continue
                if not _f.endswith('.md') or _f.startswith('00-') or '验收' in _f:
                    continue
                _txt = open(_os.path.join(_root, _f), encoding='utf-8').read()
                _steps = re.findall(r'^### Step \d+', _txt, flags=re.M)
                _ids = re.findall(r'^### Step \d+[^\n]*`\[[^\]]+\]`', _txt, flags=re.M)
                if len(_steps) != len(_ids):
                    _no_id.append('%s(%d/%d)' % (_f, len(_ids), len(_steps)))
                if _steps and '【读】' not in _txt:
                    _no_read.append(_f)
                if '整体审核' not in _txt:
                    _no_audit_sec.append(_f)
        chk(not _no_id, '每个 Step 有稳定节点 ID（缺 %d: %s）' % (len(_no_id), _no_id[:2]))
        chk(not _no_read, '功能点有【读】howto 锚点（缺 %s）' % _no_read[:2])
        chk(not _no_audit_sec, '功能点有整体审核节（两级审核）（缺 %s）' % _no_audit_sec[:2])

        # ⚠ 【读】锚点必须真实存在。这一条是框架的核心收益——
        #   "流程告诉你读哪一段"只有在锚点没写错时才成立。
        #   写错章节名不报错、不崩溃，只会让人读到错误的地方，是最隐蔽的退化。
        _badref = []
        for _root2, _d2, _f2 in _os.walk(_proc):
            for _fn in sorted(_f2):
                if not _fn.endswith('.md') or _fn.startswith('_'):
                    continue
                _txt = open(_os.path.join(_root2, _fn), encoding='utf-8').read()
                # ⚠ 原来只匹配 `howto/godot/xxx.md#章节` 一种写法。
                #   实际库里还有 structure.md、flow/godot/<域>/、audit/godot/ 等写法，
                #   它们**完全没被检查** —— 上一轮手工扫才发现 8 处断链/基准混用。
                #   ⛔ 自检只覆盖一类写法 = 声称"锚点已校验"实际只校验了一部分。
                #   ✅ 改为：任何 【读】`...` 都校验，路径基准统一为 references/。
                for _m in re.finditer(r'【读】`([^`]+)`', _txt):
                    _raw = _m.group(1)
                    _fp, _ref = (_raw.split('#', 1) + [None])[:2] \
                        if '#' in _raw else (_raw, None)
                    if _fp.startswith('howto/godot/'):
                        _doc = _fp[len('howto/godot/'):]
                        if not _doc.endswith('.md'):
                            _doc += '.md'
                        _hp = _os.path.join(_skill, 'references', 'howto',
                                            'godot', _doc)
                    else:
                        _hp = _os.path.join(_skill, 'references', _fp)
                    if _os.path.isdir(_hp):
                        continue            # ⓘ 指向域目录是合法写法
                    if not _os.path.exists(_hp):
                        _badref.append('%s→%s(文件缺)' % (_fn, _raw)); continue
                    if _ref is None:
                        continue            # ⓘ 无章节锚点，文件存在即通过
                    _hds = [x.strip() for x in
                            re.findall(r'^#{1,4}\s+(.*)$',
                                       open(_hp, encoding='utf-8').read(),
                                       flags=re.M)]
                    if not any(_ref.strip() in _h for _h in _hds):
                        _badref.append('%s→%s' % (_fn, _raw))
                    continue
                for _m in re.finditer(r'【读】`howto/godot/([\w-]+)\.md#([^`]+)`', _txt):
                    _doc, _ref = _m.group(1), _m.group(2).strip()
                    _hp = _os.path.join(_skill, 'references', 'howto', 'godot', _doc + '.md')
                    if not _os.path.exists(_hp):
                        _badref.append('%s→%s(文件缺)' % (_fn, _doc)); continue
                    _hds = [x.strip() for x in
                            re.findall(r'^#{2,3}\s+(.*)$',
                                       open(_hp, encoding='utf-8').read(), flags=re.M)]
                    if not any(_h == _ref or _h.startswith(_ref) for _h in _hds):
                        _badref.append('%s→%s' % (_fn, _ref))
        chk(not _badref, '【读】锚点指向的 howto 章节真实存在（错 %d: %s）'
            % (len(_badref), _badref[:3]))

        # ⚠ 每个 Step 都必须有【读】和【审】。
        #   ⓘ 为什么查：上一轮"弱引用清零"只统计了**出现过**的【审】，
        #     结果 narrative 域有 14 个 Step **压根没有【审】**，
        #     既不算弱引用也不报错 —— 静默地没有审核链接。
        #     同理，删掉某个 Step 的【读】也不会让任何现有检查变红。
        _nostep = []
        for _root3, _d3, _f3 in _os.walk(_proc):
            for _fn3 in sorted(_f3):
                if not _fn3.endswith('.md') or _fn3.startswith('_'):
                    continue
                _t3 = open(_os.path.join(_root3, _fn3), encoding='utf-8').read()
                for _b3 in re.split(r'\n(?=### Step )', _t3):
                    if not _b3.startswith('### Step'):
                        continue
                    _m3 = re.search(r'#S(\d+)\]', _b3)
                    if not _m3:
                        continue
                    if '【读】' not in _b3:
                        _nostep.append('%s S%s 缺【读】' % (_fn3, _m3.group(1)))
                    if '【审】' not in _b3:
                        _nostep.append('%s S%s 缺【审】' % (_fn3, _m3.group(1)))
        chk(not _nostep, '每个 Step 都有【读】与【审】（缺 %d: %s）'
            % (len(_nostep), _nostep[:3]))

        # ⚠【读】/【审】必须是"反引号包裹 + 带锚点"的精确引用。
        #   ⓘ 为什么查：早期域（character / save）写成了裸文本
        #     `【读】howto/godot/character.md —— 只查本步涉及的章节`，
        #     既没有反引号也没有 `#章节`。而锚点校验的正则
        #     「`【读】\`([^\`]+)\``」要求紧跟反引号 →
        #     ⛔ 这些**从未被校验过**，也从未被统计为弱/强引用。
        #     这又是一个"只统计存在项"的盲区：文件级引用不在任何口径里。
        _BARE_MAX = 0        # ⓘ 修完应为 0
        _bare = []
        for _r6, _d6, _f6 in _os.walk(_proc):
            for _fn6 in sorted(_f6):
                if not _fn6.endswith('.md') or _fn6.startswith('_'):
                    continue
                _t6 = open(_os.path.join(_r6, _fn6), encoding='utf-8').read()
                for _tg in ('【读】', '【审】'):
                    for _m6 in re.finditer(_tg + r'([^\n]*)', _t6):
                        _v6 = _m6.group(1).strip()
                        if _v6.startswith('`'):
                            continue        # ✅ 反引号包裹
                        # ⓘ【审】后接说明文字是合法写法（"是**步骤级…**"、
                        #   "列过的条目再过一遍"）。只有**含 .md 的裸文本**
                        #   才是真问题——它是文件级引用，指向不够精确。
                        if '.md' not in _v6:
                            continue
                        _bare.append('%s %s→%s' % (_fn6, _tg, _v6[:34]))
        chk(len(_bare) <= _BARE_MAX,
            '【读】/【审】必须是反引号包裹的精确引用（裸 %d > %d: %s）'
            % (len(_bare), _BARE_MAX, _bare[:3]))

        # ⚠ 孤儿 audit 文件：既没被任何 Step 的【审】引用，
        #   也没有任何功能点在「整体审核」节里做全表复查。
        #   ⓘ 这是"该有用时索引不到"最直接的一种：条目存在、规则也对，
        #     但没有任何流程会让人去看它。
        _refd_files = set()
        for _r4, _d4, _f4 in _os.walk(_proc):
            for _fn4 in _f4:
                if not _fn4.endswith('.md') or _fn4.startswith('_'):
                    continue
                _t4 = open(_os.path.join(_r4, _fn4), encoding='utf-8').read()
                for _m4 in re.finditer(r'`(?:audit/godot/)?([\w-]+)\.md#\d+`', _t4):
                    _refd_files.add(_m4.group(1))
                _mz = re.search(r'##\s*\d+\s*　?整体审核.*$', _t4, re.S)
                if _mz:
                    for _m5 in re.finditer(r'`(?:audit/godot/)?([\w-]+)\.md(?:#\d+)?`',
                                           _mz.group(0)):
                        _refd_files.add(_m5.group(1))
        _orphan_file = []
        _adir = _os.path.join(_skill, 'references', 'audit', 'godot')
        for _f5 in sorted(_os.listdir(_adir)):
            _p5 = _os.path.join(_adir, _f5)
            if not _f5.endswith('.md'):
                continue
            _d5 = _os.path.basename(_p5)[:-3]
            if _d5 in _refd_files:
                continue
            _has = any(re.match(r'^\|\s*\d+\s*\|', _l)
                       for _l in open(_p5, encoding='utf-8'))
            if _has:
                _orphan_file.append(_d5)
        chk(len(_orphan_file) <= _ORPHAN_FILE_MAX,
            'audit 孤儿文件数不增长（当前 %d / 上限 %d: %s）'
            % (len(_orphan_file), _ORPHAN_FILE_MAX, _orphan_file[:3]))

        # ⚠【审】锚点校验 —— 上一轮只校验了【读】，【审】完全没有。
        #   而【审】才是"这一步特有的坑"，写错条目号 = 审到不相干的条目上，
        #   表现为"我审过了，但审的不是这一步的坑"。
        _badsec = []
        for _root3, _d3, _f3 in _os.walk(_proc):
            for _fn in sorted(_f3):
                if not _fn.endswith('.md') or _fn.startswith('_'):
                    continue
                _txt = open(_os.path.join(_root3, _fn), encoding='utf-8').read()
                for _m in re.finditer(r'【审】`([^`]+)`', _txt):
                    _raw = _m.group(1)
                    _fp, _sec = (_raw.split('#', 1) + [None])[:2] \
                        if '#' in _raw else (_raw, None)
                    _hp = _os.path.join(_skill, 'references', _fp)
                    if not _os.path.exists(_hp):
                        _badsec.append('%s→%s(文件缺)' % (_fn, _raw)); continue
                    if _sec is None or not _os.path.isfile(_hp):
                        continue        # ⓘ 指向文件/目录：文件存在即通过
                    _n = _sec.strip()
                    _hds2 = [x.strip() for x in
                             re.findall(r'^#{1,4}\s+(.*)$',
                                        open(_hp, encoding='utf-8').read(),
                                        flags=re.M)]
                    if not _n.isdigit():
                        # ⓘ 非数字 = **章节锚点**（如全局审查块 GA-01），不是表格条目号。
                        #   ⚠ 此前一律判"条目号非数字"，导致全局块在流程层**永远用不上**
                        #   —— howto/audit 引用了 24 次，流程层 0 次，就是这个校验挡的。
                        if not any(_h == _n or _h.startswith(_n) for _h in _hds2):
                            _badsec.append('%s→%s(章节锚点不存在)' % (_fn, _raw))
                        continue
                    # ⚠ 按**连续块**取编号：一个 audit 文件可以有多张表，
                    #   全文件统计会把"第二张表从 11 重新编号"判成重复（假阳性）。
                    _rows, _cur = [], []
                    for _l in open(_hp, encoding='utf-8').read().split('\n'):
                        if _l.startswith('|'):
                            _cur.append(_l)
                        else:
                            if _cur:
                                _rows.append(_cur); _cur = []
                    if _cur:
                        _rows.append(_cur)
                    _hit = 0
                    for _b in _rows:
                        for _l in _b:
                            _mm = re.match(r'^\|\s*(\d+)\s*\|', _l)
                            if _mm and _mm.group(1) == _n:
                                _hit += 1
                    if _hit == 0:
                        _badsec.append('%s→%s(条目号不存在)' % (_fn, _raw))
                    elif _hit > 1:
                        # ⚠ 同一编号在多张表里出现 → #N 指向歧义
                        _badsec.append('%s→%s(条目号歧义×%d)' % (_fn, _raw, _hit))
        chk(not _badsec, '【审】锚点指向的 audit 条目存在且不歧义（错 %d: %s）'
            % (len(_badsec), _badsec[:3]))

        # ⚠ audit 条目编号：同一张表内必须连续、不重复、不跳号。
        #   为什么查这个：【审】用 #N 引用，编号漂了就指向错误条目，
        #   而这种漂移**没有任何报错** —— 只是审错了地方。
        #   ⓘ 同样按连续块处理（多张表的文件各自独立编号是合法的）。
        _badnum = []
        for _ap in sorted(glob.glob(_os.path.join(
                _skill, 'references', 'audit', '*', '*.md'))):
            _rows, _cur = [], []
            for _l in open(_ap, encoding='utf-8').read().split('\n'):
                if _l.startswith('|'):
                    _cur.append(_l)
                else:
                    if _cur:
                        _rows.append(_cur); _cur = []
            if _cur:
                _rows.append(_cur)
            for _b in _rows:
                _ns = [int(_mm.group(1)) for _l in _b
                       for _mm in [re.match(r'^\|\s*(\d+)\s*\|', _l)] if _mm]
                if len(_ns) < 2:
                    continue
                _dup = sorted({x for x in _ns if _ns.count(x) > 1})
                _miss = sorted(set(range(min(_ns), max(_ns) + 1)) - set(_ns))
                if _dup or _miss:
                    _badnum.append('%s(重复%s缺%s)' % (
                        _os.path.basename(_ap), _dup[:2], _miss[:3]))
        chk(not _badnum, 'audit 表格编号连续无重复（错 %d: %s）'
            % (len(_badnum), _badnum[:3]))

        # ⚠ 节点 ID 三查。ID 是给流程工具用的稳定标识（structure.md 节点规范），
        #   ID 一改进度就断 —— 所以这三类错误必须自动拦，不能靠肉眼。
        #   ① 域内不重复  ② 反引号闭合  ③ 每文件从 S1 连续
        #   ⓘ ② 尤其值得自动化：我已连续 7 个功能点文件漏写闭合反引号
        #     （combat/07、inventory/07、ui/07、netsync/07、datatable/04、
        #      audio/07、ai/07），每次都是写完才发现 —— 说明肉眼不可靠。
        _dupid, _seen = [], {}
        _badq = []
        _badseq = []
        for _root5, _d5, _f5 in _os.walk(_proc):
            for _fn in sorted(_f5):
                if not _fn.endswith('.md') or _fn.startswith('_'):
                    continue
                _p5 = _os.path.join(_root5, _fn)
                _t5 = open(_p5, encoding='utf-8').read()
                # ① 唯一性（域内）
                for _m in re.finditer(r'`\[([a-z]+)/(\d+)#(S\d+)\]`', _t5):
                    _k = (_m.group(1), _m.group(2), _m.group(3))
                    if _k in _seen and _seen[_k] != _fn:
                        _dupid.append('%s' % '/'.join(_k))
                    _seen[_k] = _fn
                # ② 闭合（跳过代码块，否则 ``` 会被当成未闭合）
                _incode = False
                for _i5, _l5 in enumerate(_t5.split('\n'), 1):
                    if _l5.strip().startswith('```'):
                        _incode = not _incode
                        continue
                    if _incode:
                        continue
                    if _l5.count('`') % 2:
                        _badq.append('%s:%d' % (_fn, _i5))
                # ③ 连续性（00 总览无 Step，跳过）
                if _fn.startswith('00'):
                    continue
                _ns = sorted({int(_m.group(1))
                              for _m in re.finditer(r'`\[[a-z]+/\d+#S(\d+)\]`', _t5)})
                if _ns and _ns != list(range(1, max(_ns) + 1)):
                    _badseq.append('%s%s' % (_fn, _ns))
        chk(not _dupid, '节点 ID 域内唯一（重复 %d: %s）' % (len(_dupid), _dupid[:3]))
        chk(not _badq, '节点 ID 反引号闭合（未闭合 %d: %s）'
            % (len(_badq), _badq[:3]))
        chk(not _badseq, '功能点 Step 从 S1 连续（不连续 %d: %s）'
            % (len(_badseq), _badseq[:2]))

        # ⚠【审】必须指向具体条目，⛔ 不许只指向整个 audit 文件。
        #   框架要求【审】指向"这一步特有的坑"；指向整张表等于没指 ——
        #   调用方拿到 30 条清单，不知道哪条跟当前 Step 有关。
        #
        #   ⓘ 历史：曾取「基线 ≤237 不增长」的增量判据（237 是早期域遗留）。
        #     2026-09 已**全部收敛为 0**，因此判据收紧为必须为 0 ——
        #     ⛔ 增量判据有个陷阱：它允许"旧的永远不改"，
        #        而弱引用正是最该被改掉的那批（它们指向最老的域）。
        _weak_bad = []
        for _root4, _d4, _f4 in _os.walk(_proc):
            for _fn in sorted(_f4):
                if not _fn.endswith('.md') or _fn.startswith('_'):
                    continue
                _t4 = open(_os.path.join(_root4, _fn), encoding='utf-8').read()
                # ⓘ 豁免：**显式声明的全表复查**是有意为之，与"懒得指"是两回事。
                #   两种合法场合：① 功能点级收尾的「整体审核」节；
                #               ② 验收域（07-*）里的"域级总验 / 接缝复查"步骤。
                #   它们的语义本就是"把这张表整体过一遍"。
                #   ⛔ 判据是**显式写"全部"**：写 `xxx.md` 什么都不加 = 没声明，仍算弱引用。
                for _m in re.finditer(r'【审】`([^`]+)`([^\n（(]*)', _t4):
                    if '#' in _m.group(1):
                        continue
                    _tail = _m.group(2)
                    _cut = re.search(r'^##\s*7[^\n]*整体审核', _t4, flags=re.M)
                    _in_review = (_cut is not None and _m.start() > _cut.start())
                    if '全部' in _tail and (_in_review or _fn.startswith('07')):
                        continue
                    _weak_bad.append('%s→%s' % (_fn, _m.group(1).split('/')[-1]))
        chk(not _weak_bad,
            '【审】必须指向具体条目（弱引用 %d: %s）'
            % (len(_weak_bad), _weak_bad[:3]))

        # 工序文件要指回 flow/（知识）与 audit/（自审），否则调用方查不到细节和坑表
        _no_ref = []
        for _root, _dirs, _files in _os.walk(_proc):
            for _f in sorted(_files):
                if _f in ('README.md', 'index.md') or not _f.endswith('.md'):
                    continue
                _txt = open(_os.path.join(_root, _f), encoding='utf-8').read()
                if 'howto/godot/' not in _txt and 'audit/godot/' not in _txt:
                    _no_ref.append(_f)
        chk(not _no_ref, '工序文件都指向 flow/ 或 audit/（缺 %s）' % _no_ref[:2])

    # 环境系统 不被旧域抢走（网络同步进阶是既有域，不新建）
    for need, want in (('水面', '环境系统'), ('浮力', '环境系统'), ('天空', '环境系统'),
                       ('昼夜循环', '环境系统'), ('天气', '环境系统')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    # 注意：'延迟补偿' 已迁至「观战/重连/延迟补偿」专门域（该域有完整章节：
    # rewind、预测纠正、插值缓冲、缓冲调节），网络同步进阶不再持有该关键词。
    for need, want in (('状态同步', '网络同步进阶'), ('预测回滚', '网络同步进阶'),
                       ('快照插值', '网络同步进阶'), ('延迟补偿', '观战/重连/延迟补偿')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('多人联网', '多人/网络'), ('rpc', '多人/网络')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（基础域未被进阶域抢）' % (need, want))
    # 环境系统文档必须存在（防止与既有文档重复或丢失）
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chk(os.path.exists(os.path.join(here, 'references/howto/godot/environment-systems.md')),
        'environment-systems.md 存在')
    chk(os.path.exists(os.path.join(here, 'references/howto/godot/netsync-advanced.md')),
        'netsync-advanced.md 存在（不新建重复文档）')

    # 画质 / 载具物理 / 角色自定义 不被旧域抢走
    for need, want in (('超分', '画质/超分'), ('FSR2', '画质/超分'), ('抗锯齿', '画质/超分'),
                       ('TAA', '画质/超分'), ('后处理', '画质/超分'), ('bloom', '画质/超分')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('载具', '载具/物理进阶'), ('翻车', '载具/物理进阶'),
                       ('软体', '载具/物理进阶'), ('关节', '载具/物理进阶')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('捏脸', '角色自定义'), ('换装', '角色自定义'), ('合并网格', '角色自定义')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('手部关节', 'XR深入/手部交互'), ('自定义后处理', '着色器'),
                       ('渲染管线', '渲染管线'), ('物理', '物理'), ('骨骼', '骨骼动画/IK')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（邻近域未被抢）' % (need, want))

    # 热更新 / 平台服务 不被旧域抢走
    for need, want in (('热更新', '热更新/DLC'), ('DLC', '热更新/DLC'), ('资源分包', '热更新/DLC')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('steam成就', '平台服务'), ('steam排行榜', '平台服务'), ('平台内购', '平台服务')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s' % (need, want))
    for need, want in (('成就系统', '引导/成就'), ('排行榜', '引导/成就'), ('作弊', '存档安全/防作弊'),
                       ('玩家mod', '玩家Mod'), ('云存档', '云存档/跨端')):
        d = match_domains(need)
        chk(bool(d) and d[0][0] == want, '"%s" → %s（邻近域未被抢）' % (need, want))

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
                       ('货币系统', '经济/长线系统')):
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
    chk(bool(d) and d[0][0] != '着色器', '"材质与光照" 不被着色器抢走（得到 %s）' % (d[0][0] if d else '无'))
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

        # ⚠ 仓库内禁止明文凭据：token 统一走 gh_auth（环境变量 / 库外凭据文件）。
        #   ⛔ 有人图省事把 token 粘回脚本 → 推送即公开泄露。这条防回潮。
        try:
            import importlib.util as _ilu2
            _sp2 = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 'check-no-secret.py')
            _sp2c = _ilu2.spec_from_file_location('cns', _sp2)
            _cns = _ilu2.module_from_spec(_sp2c)
            _sp2c.loader.exec_module(_cns)
            _badsec2 = []
            _orig = _cns.ROOT
            for _rd, _dd, _ff in _os.walk(_orig):
                _dd[:] = [x for x in _dd if x not in _cns.SKIP_DIR]
                for _f in _ff:
                    if _os.path.splitext(_f)[1].lower() in _cns.SKIP_EXT:
                        continue
                    _fp2 = _os.path.join(_rd, _f)
                    try:
                        _tt = open(_fp2, encoding='utf-8').read()
                    except (OSError, UnicodeDecodeError):
                        continue
                    if any(rx.search(_tt) for _, rx in _cns.PATS):
                        _badsec2.append(_os.path.relpath(_fp2, _orig))
            chk(not _badsec2, '仓库内无明文凭据（发现 %d: %s）'
                % (len(_badsec2), _badsec2[:3]))
        except Exception as _e2:
            chk(False, '凭据扫描可执行（%s）' % str(_e2)[:60])

        # ⚠【审】映射相关性：弱引用清零后，"指到了"已能自动校验，
        #   但"指对了没有"仍不能 —— 这条补上后半段。
        #   ⛔ 指错的后果是"我审过了，但审的不是这一步的坑"，比弱引用更隐蔽。
        try:
            # ⓘ 文件名带连字符（check-map-relevance.py）**不能直接 import**，
            #   要用 importlib 按路径加载。
            import importlib.util as _ilu
            _sp = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                'check-map-relevance.py')
            _spec = _ilu.spec_from_file_location('cmr', _sp)
            _cmr = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_cmr)
            _tot, _susp, _stale = _cmr.scan()
            chk(_tot > 0, '【审】映射扫描能取到样本（当前 %d 个强引用）' % _tot)
            chk(not _susp,
                '【审】映射与所在 Step 相关（零交集 %d: %s）'
                % (len(_susp), ['%s %s %s' % x[:3] for x in _susp[:3]]))
            chk(not _stale,
                '【审】映射豁免未过期（过期 %d: %s）'
                % (len(_stale), ['%s %s %s' % x for x in _stale[:3]]))
        except Exception as _e:
            chk(False, '【审】映射相关性扫描可执行（%s）' % str(_e)[:60])

    print()
    print('自检：%d 通过 / %d 失败' % (ok, fail))
    if not fail:
        print('结论：开发路由工作正常')
    return 1 if fail else 0


def cmd_check_conflicts():
    """列出「关键词被别的域抢走」的冲突。

    为什么需要这个命令：
    新域上线时，它的关键词常与既有域重叠，而路由按命中长度排序。
    结果是输出完全正常、只是指向了错的文档 —— 不报错，最难发现。
    靠人工试需求词去碰，75 个域已经覆盖不全了。

    为什么用「关键词本身当探针」而不是字符串比较：
    - 纯子串比较会有大量噪音（ai ⊂ await / ar ⊂ artifact），
      而路由对 ASCII 词有边界逻辑，那些根本不会命中。
    - 用关键词当探针走真实的 match_domains，语义与线上完全一致，
      报出来的就是真会被抢的词。
    """
    stolen = []
    for name, kws, entry, desc in DOMAINS:
        for w in kws:
            r = match_domains(w)
            if r and r[0][0] != name:
                stolen.append((w, name, r[0][0]))
    if not stolen:
        print('无冲突：每个关键词都路由回自己所属的域。')
        return 0
    print('关键词被别的域抢走：%d 个' % len(stolen))
    print('（注意：被「更专门」的域拿走是正确行为，需人工判断哪些要修）')
    print()
    from collections import defaultdict
    g = defaultdict(list)
    for w, loser, winner in stolen:
        g[loser].append((w, winner))
    for name in sorted(g, key=lambda x: -len(g[x])):
        print('%-20s 被抢 %d 个：' % (name, len(g[name])))
        for w, win in g[name]:
            print('    %-20s → %s' % (w, win))
    print()
    print('修法：从「被抢的域」删掉该词（让专门域独占），')
    print('      或给两个域各自换成更长的区分词（如 成就 → steam成就 / 游戏成就）。')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default='', help='项目根目录')
    ap.add_argument('--need', default='', help='需求描述，如"角色跳跃""存档"')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    ap.add_argument('--check-conflicts', action='store_true',
                    help='列出关键词被别的域抢走的冲突（新域上线后应跑一次）')
    a = ap.parse_args()

    if a.self_test:
        sys.exit(cmd_self_test())

    if a.check_conflicts:
        sys.exit(cmd_check_conflicts())

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
