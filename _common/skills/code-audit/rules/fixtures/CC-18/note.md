# CC-18 · UI性能

修改 `Label.string` 但全文无 `cacheMode` —— 高频更新时缓存模式不匹配。

**fp 关键**：规则判据是「有 .string= 且全文无 cacheMode」，
所以 fp 必须在同文件里出现 cacheMode 才会被放过。
