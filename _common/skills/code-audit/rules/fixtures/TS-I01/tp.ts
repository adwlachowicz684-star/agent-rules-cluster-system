export class Recorder {
    constructor() {
        this._log = [];
    }

    push(s: string): void {
        this._log.push(s);
    }
}
