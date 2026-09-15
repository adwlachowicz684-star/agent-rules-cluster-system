export class Bag {
    private _items: number[] = [];

    dump(): number[] {
        return this._items.slice();
    }
}
