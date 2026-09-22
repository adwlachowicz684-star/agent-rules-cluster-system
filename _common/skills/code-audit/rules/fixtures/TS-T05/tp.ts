// 首屏兜底：内联样式优先级最高，后续主题系统写 CSS 变量覆盖不住
export function applyFallback(root: HTMLElement): void {
    root.style.backgroundColor = '#1a1a1a';
}
