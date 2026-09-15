export class Emitter {
    constructor() {
        this._queue = [];
    }

    emit(e: string): void {
        this._queue.push(e);
    }
}
