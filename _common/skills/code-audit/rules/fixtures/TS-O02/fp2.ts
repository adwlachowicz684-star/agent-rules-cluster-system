export function pace(distance: number, step: number): number {
    if (step === 0) return 0;
    return distance / step;
}
