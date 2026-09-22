export function tally(ids: string[]): Record<string, number> {
    const count = {};
    for (const id of ids) {
        count[id] = (count[id] ?? 0) + 1;
    }
    return count;
}
