// 前置 isNaN 已挡住 NaN，Math.max 拿到的一定是有限数 → 不是问题
export function getHueShift() {
    const n = parseInt(localStorage.getItem('k') || '0', 10);
    return isNaN(n) ? 0 : Math.max(-180, Math.min(180, n));
}
