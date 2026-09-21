<!-- oversize-exempt: 反模式清单，审核用 -->
# cicd-publish — 反模式清单（审核用）

> 本文件**只写「不能怎么做」**，用于流程结束后审核自己的产出、约束边界。
> 「怎么做」见同 skill 的流程部分：`howto/godot/cicd-publish.md`

## 常见坑

| 坑 | 后果 |
|---|---|
| CI 忘记 `--import` | 资源找不到/纹理全黑，本地正常 |
| 不提交 `.import` | 各机器导入参数不一致，diff 看不出 |
| 拼错 `--export-realese` | 静默退出码 0，CI 绿但无产物 |
| 导出后不校验产物 | 上面那条发现不了 |
| 模板版本不匹配 | 导出失败或产物异常 |
| 升级引擎不重下模板 | 同上 |
| keystore 直接存 Secret | Secret 是文本，二进制损坏 |
| 密钥放仓库 | 泄露，且 Git 历史里删不掉 |
| macOS 只签名不公证 | Gatekeeper 拦截 |
| Android 漏选纹理格式 | 真机纹理全黑 |
| Android 漏 INTERNET 权限 | 真机网络全失败，编辑器正常 |
| 只测 debug 不测 release | assert 被剥离后行为不同 |
| CI 镜像版本与本地不一致 | 本地能跑 CI 红，或更糟 |
| 版本号散落三处 | 必然不同步 |
