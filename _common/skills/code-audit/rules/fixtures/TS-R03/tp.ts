function parsePath(p: string) {
  return p.split('.');
}

export function applyPatch(root: any, path: string, v: any) {
  const seg = parsePath(path);
  let cur = root;
  for (const s of seg) {
    cur = cur[s];
  }
  return v;
}
