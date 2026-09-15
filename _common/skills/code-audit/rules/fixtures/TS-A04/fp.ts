export class Stat {
  private _hp = 0;
  tick(d: number) {
    if (!Number.isFinite(d)) {
      return;
    }
    this._hp += d;
  }
}
