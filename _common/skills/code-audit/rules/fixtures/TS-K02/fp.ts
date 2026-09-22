export class Store {
    private _map = new Map<string, number>();
    private _cache = new Map<string, number>();

    clear(): void {
        this._map.clear();
        this._cache.clear();
    }
}
