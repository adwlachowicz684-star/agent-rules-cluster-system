export class Store {
  private _m = new Map<string, number>();

  importState(data: any) {
    this._m.clear();          // 全量替换：先清再灌，避免只增不减
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
