export class LazyHeap {
    private _removed: any = new Set();

    get size(): number {
        return 0;
    }

    remove(x) {
        this._removed.add(x);
    }
}
