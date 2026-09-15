export class Stat {
  private _hp = 0;
  tick(d: number) {
    this._hp += d;
  }
}
