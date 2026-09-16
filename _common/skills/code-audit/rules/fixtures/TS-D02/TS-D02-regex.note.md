# TS-D02 正则字面量兜底用例

函数体里的**正则字面量**含花括号（如 `/(^|\})([^{}@]+)\{/g`）会让 `_body_of`
配平提前结束，body 被截成 27 字符 → 后半段用到的参数被误判为"未使用"。

实测 nexus-panel `js/plugin-sdk.js:673` `scopeCss(css, scope)`：
`scope` 明明在 `${scope}` 里用了，仍报未使用。

- `fp.ts` —— **必须不命中**（body 过短时走全文计数兜底）
