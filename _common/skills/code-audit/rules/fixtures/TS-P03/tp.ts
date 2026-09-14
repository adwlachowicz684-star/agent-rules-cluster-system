export function clampHue(n: number) {
    return Math.max(-180, Math.min(180, n));
}
