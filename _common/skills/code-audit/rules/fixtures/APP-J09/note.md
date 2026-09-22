# APP-J09

只注册不注销 —— **清空后重建不是泄漏，但不能无条件降级**。

- `tp.js` —— **必须命中**：`renderPanel()` 里有 `box.innerHTML = ''`，
  却把监听注册在 `window` 上。window 永远不会被 innerHTML 清空带走 → 真泄漏
- `fp.js` —— **必须不命中**：`renderList()` 里 `list.innerHTML = ''`，
  监听注册在**本作用域 createElement 出来的 btn** 上，btn 随容器一起丢弃 → 不泄漏

## 判据（三个条件同时满足才降级）

1. 接收者是本作用域 `document.createElement` 出来的**局部变量**
2. 文件里确有清空操作（`innerHTML = ''` / `replaceChildren()` / `.remove()`）
3. 该变量没被 `push(...)` 到外部持有

## 另外两条静态扫不出、必须人工看的

- **一次性上下文**：`init` / `boot` / 顶层 IIFE 里的 `window.addEventListener` 是正常用法，
  不是泄漏 —— 规则按缩进找外层函数，命中一次性名单则不报
  （nexus-panel `shell.js:476` 曾因此误报，上方紧邻的是**平级**的
  `const runShellShortcut = ...`，必须按缩进找外层、不能只找最近的）
- **节点被外部持有**（`/tmp/leaktest/mod/d.js`）：注册在新建节点上、但节点被
  `cache.push(card)` 持有 → 节点不回收、监听也不回收。静态扫不出，需人工看

## 来源

2026-09-14 nexus-panel。作者用 `sidebar-listener-test.mjs` 实证
`renderSidebar` 的监听器不泄漏，推翻了我上一轮的静态推断。
但推广成"有清空就不报"会漏掉上述三类真泄漏，故改为受限定降级。
