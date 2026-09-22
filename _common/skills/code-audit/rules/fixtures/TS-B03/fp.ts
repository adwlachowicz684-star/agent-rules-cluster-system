export function walk(node: any, seen: Set<any>) {
  if (seen.has(node)) {
    return;
  }
  seen.add(node);
  walk(node.next, seen);
}
