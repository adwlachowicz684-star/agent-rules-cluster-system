// 函数体内有正则字面量，花括号破坏配平 → 不能因 body 过短就判"未使用"
export function scopeCss(css, scope) {
  return css.replace(/(^|\})([^{}@]+)\{/g, (m, brace, selector) => {
    return `${brace}${scope} ${selector}{`;
  });
}
