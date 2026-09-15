export class Guard {
    private _degraded = false;

    degrade(): void {
        this._degraded = true;
    }

    reset(): void {
        this._degraded = false;
    }
}
