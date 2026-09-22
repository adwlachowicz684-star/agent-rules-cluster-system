export class Recorder {
    constructor() {
        this._log = [];
    }

    push(s: string): void {
        this._log.push(s);
        if (this._log.length > 100) this._log.shift();
    }
}
