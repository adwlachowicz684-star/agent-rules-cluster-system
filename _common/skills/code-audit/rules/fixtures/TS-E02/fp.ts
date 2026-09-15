const seen = new Set<string>();

export function off(key: string): void {
    seen.delete(key);
}
