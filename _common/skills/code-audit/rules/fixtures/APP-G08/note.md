# APP-G08 重复 import 同一模块

- **TP 必须命中**：同一 spec 被 import 两次（具名 + 命名空间，或两次具名）
- **FP 必须不命中**：同一模块只 import 一次（多个具名合并进同一条）

为什么 fp 重要：把「一次 import 多个名字」误判成重复是最典型的误伤。
实测来源：某项目 `theme-normalizer.js` 与 `plugin-config.js` 各被导入两次。
