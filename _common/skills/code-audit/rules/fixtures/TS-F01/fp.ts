export class Store {
  private _m = new Map<string, number>();

  importState(data: any) {
    for (const k of Object.keys(data)) {
      this.put(k, data[k]);
    }
  }

  private put(k: string, v: number) {
    if (typeof v !== 'number') {
      return;
    }
    this._m.set(k, v);
  }
}
