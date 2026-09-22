// 普通一次性赋值，不在兜底语境，也不是要被主题覆盖的
export function highlight(row: HTMLElement): void {
    row.style.opacity = '0.5';
}
