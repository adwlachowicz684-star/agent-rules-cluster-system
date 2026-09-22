export class NodePool {
  private free: any[] = [];

  prewarm(n: number) {
    for (let i = 0; i < n; i++) {
      this.free.push({});
    }
  }
}
