export class Bus {
    private _map: Map<string, number> = new Map();
    private _queue: Map<string, number> = new Map();

    clear(): void {
        this._map.clear();
    }
}
