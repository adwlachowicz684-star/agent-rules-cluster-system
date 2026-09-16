# K-15 · 缺口补齐

对应判据条目：**K-15**

**tp**：声明的 content-length 直接进 `Vec::with_capacity`——声明 10GB 就申请 10GB。
**fp**：`.min(MAX_BODY)` 收口。

**为什么是文件级而不是单行正则**：`let n = req.content_length();` 与
`Vec::with_capacity(n)` 通常分处两行，`[^\n]` 跨不过换行，单行正则抓不到。
改成文件级：先确认文件里确实读了声明长度，再看分配处有没有收口——
少了前半个条件，任何 `Vec::with_capacity` 都会被报，误报不可接受。
