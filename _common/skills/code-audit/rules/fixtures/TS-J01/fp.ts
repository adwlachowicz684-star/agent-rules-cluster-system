export function buy(p: any) {
  try { p.spend(10); p.addItem('sword'); } catch (e) { p.refund(10); }
}
