export class NodePool {
  private free: any[] = [];

  prewarm(n: number) {
    const c = Math.min(n, 1024);
    for (let i = 0; i < c; i++) {
      this.free.push({});
    }
  }
}
