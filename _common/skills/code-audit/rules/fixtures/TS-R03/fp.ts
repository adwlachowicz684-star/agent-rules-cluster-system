export function applyPatch(root: any, key: string, v: any) {
  root[key] = v;
  return v;
}
