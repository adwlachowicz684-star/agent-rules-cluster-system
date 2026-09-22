type Sub = { fn: Function };
const seen = new Set<Function>();
export const list: Sub[] = [];

export function off(fn: Function): void {
    seen.delete(fn);
    list.filter((l) => !seen.has(l.fn));
}
