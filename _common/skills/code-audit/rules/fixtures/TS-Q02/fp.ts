export class Stack {
    private _items: any[] = [];

    get size(): number {
        return this._items.length;
    }

    remove(x: any): void {
        this._items.pop();
    }
}
