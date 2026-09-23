<!-- oversize-exempt: 审核部分索引 -->
# 审核清单索引（不能怎么做）

> 本目录**只写「不能怎么做」**：反模式、坑表、漏写清单、约束边界。
> 「怎么做」见同 skill 的流程部分 `howto/godot/<同名>.md`。

**用法**：流程走完（实现完某个功能）后，打开**同名**文件逐条对照自己的产出。

| 功能域 | 审核清单 |
|---|---|
| `2d-rendering` | `audit/godot/2d-rendering.md` |
| `3d` | `audit/godot/3d.md` |
| `accessibility` | `audit/godot/accessibility.md` |
| `advanced-topics` | `audit/godot/advanced-topics.md` |
| `ai-behavior` | `audit/godot/ai-behavior.md` |
| `ai-navigation` | `audit/godot/ai-navigation.md` |
| `ai-perception` | `audit/godot/ai-perception.md` |
| `analytics` | `audit/godot/analytics.md` |
| `animation-advanced` | `audit/godot/animation-advanced.md` |
| `animation-skeletal` | `audit/godot/animation-skeletal.md` |
| `animation` | `audit/godot/animation.md` |
| `architecture` | `audit/godot/architecture.md` |
| `art-assets` | `audit/godot/art-assets.md` |
| `audio-advanced` | `audit/godot/audio-advanced.md` |
| `camera-cutscene` | `audit/godot/camera-cutscene.md` |
| `character-customization` | `audit/godot/character-customization.md` |
| `character` | `audit/godot/character.md` |
| `class-awaken` | `audit/godot/class-awaken.md` |
| `cicd-publish` | `audit/godot/cicd-publish.md` |
| `cloud-save` | `audit/godot/cloud-save.md` |
| `combat` | `audit/godot/combat.md` |
| `csharp` | `audit/godot/csharp.md` |
| `datatable` | `audit/godot/datatable.md` |
| `debugging` | `audit/godot/debugging.md` |
| `devtools` | `audit/godot/devtools.md` |
| `diagnostics` | `audit/godot/diagnostics.md` |
| `economy` | `audit/godot/economy.md` |
| `gem-rune` | `audit/godot/gem-rune.md` |
| `editor-plugin` | `audit/godot/editor-plugin.md` |
| `environment-systems` | `audit/godot/environment-systems.md` |
| `gdext-plugin` | `audit/godot/gdext-plugin.md` |
| `gdextension-deep` | `audit/godot/gdextension-deep.md` |
| `gdscript-advanced` | `audit/godot/gdscript-advanced.md` |
| `hotupdate` | `audit/godot/hotupdate.md` |
| `i18n` | `audit/godot/i18n.md` |
| `input-audio` | `audit/godot/input-audio.md` |
| `input-remap` | `audit/godot/input-remap.md` |
| `io-network` | `audit/godot/io-network.md` |
| `level-design` | `audit/godot/level-design.md` |
| `lighting` | `audit/godot/lighting.md` |
| `mobile` | `audit/godot/mobile.md` |
| `modding` | `audit/godot/modding.md` |
| `monetization` | `audit/godot/monetization.md` |
| `movement-advanced` | `audit/godot/movement-advanced.md` |
| `multiplayer` | `audit/godot/multiplayer.md` |
| `narrative` | `audit/godot/narrative.md` |
| `netsync-advanced` | `audit/godot/netsync-advanced.md` |
| `onboarding-meta` | `audit/godot/onboarding-meta.md` |
| `openworld` | `audit/godot/openworld.md` |
| `perf-profiling` | `audit/godot/perf-profiling.md` |
| `performance` | `audit/godot/performance.md` |
| `physics` | `audit/godot/physics.md` |
| `platform-export` | `audit/godot/platform-export.md` |
| `platform-services` | `audit/godot/platform-services.md` |
| `plugins` | `audit/godot/plugins.md` |
| `procedural-generation` | `audit/godot/procedural-generation.md` |
| `project` | `audit/godot/project.md` |
| `projectile` | `audit/godot/projectile.md` |
| `puzzle` | `audit/godot/puzzle.md` |
| `render-pipeline` | `audit/godot/render-pipeline.md` |
| `rendering-advanced` | `audit/godot/rendering-advanced.md` |
| `replay` | `audit/godot/replay.md` |
| `save-migration` | `audit/godot/save-migration.md` |
| `security` | `audit/godot/security.md` |
| `shaders` | `audit/godot/shaders.md` |
| `social` | `audit/godot/social.md` |
| `survival` | `audit/godot/survival.md` |
| `systems` | `audit/godot/systems.md` |
| `testing-advanced` | `audit/godot/testing-advanced.md` |
| `testing` | `audit/godot/testing.md` |
| `tilemap` | `audit/godot/tilemap.md` |
| `timescale` | `audit/godot/timescale.md` |
| `ui-advanced` | `audit/godot/ui-advanced.md` |
| `ui` | `audit/godot/ui.md` |
| `upscaling` | `audit/godot/upscaling.md` |
| `vehicle-physics` | `audit/godot/vehicle-physics.md` |
| `version-migration` | `audit/godot/version-migration.md` |
| `vfx-feel` | `audit/godot/vfx-feel.md` |
| `xr-deep` | `audit/godot/xr-deep.md` |
| `xr` | `audit/godot/xr.md` |

## 常见漏写速查

写完对照一遍：

| # | 漏写 | 审查规则 |
|---|---|---|
| 1 | Autoload 信号未断开 | GD15 |
| 2 | `remove_child` 后没 `queue_free` | GD01 |
| 3 | `create_tween()` 未保存引用 | GD02 |
| 4 | `FileAccess` 未 `close()` | GD41 |
| 5 | 存档写 `res://` | GD43 |
| 6 | `instantiate()` 后未 `add_child()` | GD46 |
| 7 | 动态 `AudioStreamPlayer` 未 `queue_free()` | GD52 |
| 8 | `assert` 做运行时校验 | GD71 |
| 9 | `duplicate()` 浅拷贝 | GD73 |
| 10 | `print()` 留在正式代码 | GD74 |
| 11 | `await` 后未判 `is_instance_valid` | GD75 |
| 12 | 每帧赋值 `Label.text` | GD13 |
| 13 | `move_and_slide(...)` 带参 | GD09 |
| 14 | `velocity *= delta` | GD21 |
| 15 | **塔防 / 波次 / 索敌** | `genres-tower-defense.md` | 反模式条目数：见文件内表格 |
| 16 | **RTS / 框选 / 编队 / 战争迷雾** | `genres-rts.md` | 反模式条目数：见文件内表格 |
| 17 | **卡牌 / 效果栈 / 连锁** | `genres-card.md` | 反模式条目数：见文件内表格 |
| 18 | **Roguelike / 元进度** | `genres-roguelike.md` | 反模式条目数：见文件内表格 |
| 19 | **自走棋 / 战棋 / 六边形** | `genres-tactics.md` | 反模式条目数：见文件内表格 |
| 20 | **模拟经营 / 放置 / 离线收益** | `genres-idle-sim.md` | 反模式条目数：见文件内表格 |
| 21 | **平台跳跃手感** | `platformer-feel.md` | 反模式条目数：见文件内表格 |
| 22 | **弹幕射击 / SHMUP** | `genres-bullet-hell.md` | 反模式条目数：见文件内表格 |
| 23 | **破坏 / 布料 / 软体** | `destruction-cloth.md` | 反模式条目数：见文件内表格 |
| 24 | **遮挡剔除 / 实例化 / GPU 粒子** | `occlusion-instancing.md` | 反模式条目数：见文件内表格 |
| 25 | **版本控制 / 资源组织** | `vcs-collab.md` | 反模式条目数：见文件内表格 |
| 26 | **性能预算 / CI / 评审 / 技术债** | `project-governance.md` | 反模式条目数：见文件内表格 |
| 27 | **观战 / 断线重连 / 主机迁移 / 延迟补偿** | `spectate-reconnect.md` | 反模式条目数：见文件内表格 |
| 28 | **群集行为（boids）与避障** | `boids-swarm.md` | 反模式条目数：见文件内表格 |
| 29 | **分区分服 / 跨服 / 合服 / 匹配** | `sharding-matchmaking.md` | 反模式条目数：见文件内表格 |
| 30 | `compliance` | `audit/godot/compliance.md` |
| 31 | `companion` | `audit/godot/companion.md` |
| 32 | `time-progression` | `audit/godot/time-progression.md` |
| 33 | `account-security` | `audit/godot/account-security.md` |
| 34 | `backend-stability` | `audit/godot/backend-stability.md` |
| 35 | `player-trading` | `audit/godot/player-trading.md` |
| 36 | `auto-battle` | `audit/godot/auto-battle.md` |
| 37 | `cosmetic` | `audit/godot/cosmetic.md` |
| 38 | `stealth-ai` | `audit/godot/stealth-ai.md` |
| 39 | `firearms` | `audit/godot/firearms.md` |
| 40 | `build-affix` | `audit/godot/build-affix.md` |
| 41 | `lifeskill-housing` | `audit/godot/lifeskill-housing.md` |

完整判据见 `../../../../code-audit/references/p-godot.md`。
