# 05 第三方 SDK 与 UGC 治理（合规域）

> **本步交付**：SDK 清单与责任人 + UGC 服务端审核 + 处置留痕
> **对应**：流程 `howto/godot/compliance.md` · 审核 `audit/godot/compliance.md`

## 0. 交付物定义

1. 每个 SDK 都有责任人与数据流说明
2. ⛔ 新增 SDK 未更新隐私清单时 CI 阻止合入
3. UGC 审核能力在服务端，不只在客户端
4. 屏蔽词库版本进构建元数据
5. 举报与处置留痕，可举证

## 1. 前置检查清单

- [ ] SDK 清单含责任人与数据流
- [ ] CI 能拦截未更新清单的 SDK 变更
- [ ] UGC 审核在服务端
- [ ] 屏蔽词库版本进元数据
- [ ] 处置记录可导出举证

## 2. 工序

### Step 1　SDK 清单进治理，每个都有责任人与数据流　`[compliance/05#S1]`

【读】`howto/godot/compliance.md#5. UGC 与 SDK：合规能力要进服务端治理`

【做】
建立 SDK 清单：名称、版本、用途、收集的数据、责任人。
⛔ 没有清单——没人知道线上到底接了哪些 SDK，
⛔ 于是数据地图不可能完整，商店问卷必然有遗漏，
⛔ 而这个缺口只在审核被拒时才暴露。

【产出】SDK 清单（含责任人与数据流）

【判据】随机抽一个 SDK，能说出它收集什么、谁负责。

【审】`audit/godot/compliance.md#45`

### Step 2　⛔ 合规能力要进服务端治理，不能只在客户端　`[compliance/05#S2]`

【读】`howto/godot/compliance.md#5. UGC 与 SDK：合规能力要进服务端治理`

【做】
UGC 的审核、屏蔽、处置在服务端完成。
⛔ 只在客户端过滤——改包即可绕过，
⛔ 而且服务端从未见过违规内容，也就没有违规记录，
⛔ 无法举证"已经治理了"。

【产出】服务端 UGC 审核与处置链路

【判据】改包绕过客户端过滤后，服务端仍拦下并记录。

【审】`audit/godot/compliance.md#46`

### Step 3　屏蔽词库版本要进构建元数据　`[compliance/05#S3]`

【读】`howto/godot/compliance.md#8. 构建元数据里应该写进去的东西`

【做】
屏蔽词库版本写入构建元数据，与包版本一起发布。
⛔ 不进元数据——出事时无法回答"当时用的是哪版词库"，
⛔ 而举证需要的正是这个对应关系。

【产出】元数据中屏蔽词库版本字段

【判据】任一历史包都能查到它当时的词库版本。

【审】`audit/godot/compliance.md#47`

### Step 4　举报与处置留痕，可举证　`[compliance/05#S4]`

【读】`howto/godot/compliance.md#7. 商店：隐私声明是可验证事实，不是营销文案`

【做】
举报、审核、处置全链路留痕，可导出。
⛔ 处置不留痕——监管问到"处理了多少违规内容"时无法回答，
⛔ 而且无法证明处置是及时的。

【产出】处置留痕记录（可导出）

【判据】能导出某时间段内的举报量与处置量。

【审】`audit/godot/compliance.md#48`

### Step 5　⛔ 新增 SDK 未更新隐私清单，CI 必须阻止　`[compliance/05#S5]`

【读】`howto/godot/compliance.md#7. 商店：隐私声明是可验证事实，不是营销文案`

【做】
CI 校验：SDK 清单变更必须同步更新隐私清单与数据地图。
⛔ 靠人工记住——SDK 由不同人在不同分支接入，
⛔ 一次漏更新就把未声明的数据流带上线，且要等到审核才发现。

【产出】CI 校验规则

【判据】故意新增 SDK 而不更新清单，CI 拦截成功。

【审】`audit/godot/compliance.md#49`

## 3. 参考实现

```gdscript
# ⓘ 承接本步产出：屏蔽词库版本进构建元数据
const WORDLIB_VERSION_KEY := "compliance/wordlib_version"

func current_wordlib_version() -> String:
    return str(ProjectSettings.get_setting(WORDLIB_VERSION_KEY, ""))

func check_ugc(text: String) -> bool:
    # ⛔ 客户端过滤只是提示；真正的审核在服务端
    # ⛔ 服务端未见过的内容无法留痕，也就无法举证
    return _server_check(text)
```

## 4. 验收清单

- [ ] SDK 清单含责任人与数据流
- [ ] 改包绕过客户端后服务端仍拦下并记录
- [ ] 历史包能查到当时的词库版本
- [ ] 举报与处置可导出举证
- [ ] ⛔ CI 能拦截未更新清单的 SDK 变更

## 5. 常见返工

| 症状 | 原因 | 回到 |
|---|---|---|
| 说不清线上接了哪些 SDK | 无 SDK 清单 | S1 |
| 改包即可发违规内容 | 审核只在客户端 | S2 |
| 无法回答当时用的哪版词库 | 版本未进元数据 | S3 |
| 无法证明处置及时 | 处置不留痕 | S4 |
| 审核阶段发现 SDK 漏报 | 靠人工记住更新 | S5 |

## 6. 下一步

→ 06 商店提交与构建元数据

## 7　整体审核（功能点级收尾）

【审】`audit/godot/compliance.md#45`、`audit/godot/compliance.md#46`、`audit/godot/compliance.md#47`、`audit/godot/compliance.md#48`、`audit/godot/compliance.md#49`
