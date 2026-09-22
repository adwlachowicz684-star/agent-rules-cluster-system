export function norm(a:number){ const r = a % (Math.PI*2); return r<0 ? r+Math.PI*2 : r; }
