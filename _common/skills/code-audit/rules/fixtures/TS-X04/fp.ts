export function playFx(node: any) {
  node.runAction(repeatForever(rotate()));
  onDestroy(() => node.stopAllActions());
}
