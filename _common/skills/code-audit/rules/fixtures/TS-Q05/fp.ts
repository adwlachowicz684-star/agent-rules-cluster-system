export function maxOf(values: number[]): number {
    return values.reduce((a, b) => (a > b ? a : b), 0);
}
