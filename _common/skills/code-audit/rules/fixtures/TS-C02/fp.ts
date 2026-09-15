export function tally(ids: string[]): Map<string, number> {
    const count = new Map<string, number>();
    for (const id of ids) {
        count.set(id, (count.get(id) ?? 0) + 1);
    }
    return count;
}
