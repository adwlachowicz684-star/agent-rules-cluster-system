export function pick(cached: any): any {
    if (cached !== undefined) {
        refresh(cached);
        return cached;
    }
}
