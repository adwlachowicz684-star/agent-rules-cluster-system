const BAD = ['__proto__', 'constructor', 'prototype'];

export function setByPath(obj: any, path: string, v: any) {
  const seg = path.split('.');
  if (seg.some((s) => BAD.includes(s))) {
    return;
  }
  let cur = obj;
  for (let i = 0; i < seg.length - 1; i++) {
    cur = cur[seg[i]];
  }
  cur[seg[seg.length - 1]] = v;
}
