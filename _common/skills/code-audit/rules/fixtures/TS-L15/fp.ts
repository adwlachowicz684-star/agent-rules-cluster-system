export class Pending {
    private _pending = new Map<string, number>();

    submit(id: string, v: number): void {
        this._pending.set(id, v);
    }

    resolve(id: string): void {
        this._pending.delete(id);
    }
}
