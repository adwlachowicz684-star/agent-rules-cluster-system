export function walk(node: any) {
  walk(node.next);
}
