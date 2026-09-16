# K-36 错误分类用宽泛子串 + 丢弃原文

- **TP 必须命中**：命中词语义模糊（一词覆盖多因）；或分类后丢弃原始 message
- **TP2 必须命中**：只丢弃原文
- **FP 必须不命中**：命中词唯一且保留原文

实测来源：某推送工具 `_NEED_UPDATE_HINTS` 含 `not mergeable` 与
`Required status check`；已合并 PR 重跑撞 405，被判 `need_update`
→ 提示「去网页点 Update branch」，而 PR 已合并，该按钮不存在。
