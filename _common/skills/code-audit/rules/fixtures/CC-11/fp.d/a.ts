export class A {
  onLoad() { this.node.on('click', this.h, this); }
  onDestroy() { this.node.off('click', this.h, this); }
}
