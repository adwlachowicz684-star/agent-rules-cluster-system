export class Emitter {
    constructor() {
        this._queue = [];
    }

    emit(e: string): void {
        this._queue.push(e);
        if (this._queue.length > 64) this._queue.shift();
    }
}
