export class Index {
    private _buckets: Map<string, Set<string>> = new Map();

    drop(key: string): void {
        this._buckets.delete(key);
    }
}
