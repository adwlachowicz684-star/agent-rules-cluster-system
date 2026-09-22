export class Store {
  private _m = new Map<string, number>();

  importState(data: any) {
    for (const k of Object.keys(data)) {
      this._m.set(k, data[k]);
    }
  }
}
