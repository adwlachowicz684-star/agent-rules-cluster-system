export function setByPath(obj: any, path: string, v: any) {
  const seg = path.split('.');
  let cur = obj;
  for (let i = 0; i < seg.length - 1; i++) {
    cur = cur[seg[i]];
  }
  cur[seg[seg.length - 1]] = v;
}
