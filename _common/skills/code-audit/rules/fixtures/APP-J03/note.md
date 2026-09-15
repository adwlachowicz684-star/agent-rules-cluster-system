# APP-J03 · postMessage 目标 origin 通配

**为什么 P1**：`postMessage(data, '*')` 把数据发给任意 origin 的接收方；
消息里若含凭据、本地路径、DOM 结构，就是跨源泄漏。

**注意**：本规则此前**从未进入注册表**——
`rule-registry.py` 提取 scan-app 规则时，正则只认单引号标题，
而 J03 的标题 `postMessage 目标 origin 通配` 用的是双引号。
于是它一直能扫、能报，但不在注册表里：没有 fixture 覆盖统计、
没有 eval、item-index 取不到它的判据。
更麻烦的是 `--check` 用**同一条正则**算「扫描器现有规则」，
两边一起漏，所以它永远报「一致」。

**tp**：`postMessage(payload, '*')` —— 目标 origin 通配。
**fp**：`postMessage(payload, ORIGIN)` —— 指定了具体 origin，不是通配。
