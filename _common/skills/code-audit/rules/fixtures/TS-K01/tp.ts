export class Guard {
    private _degraded = false;

    degrade(): void {
        this._degraded = true;
    }
}
