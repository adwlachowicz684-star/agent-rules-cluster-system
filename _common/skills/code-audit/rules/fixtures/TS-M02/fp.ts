let balance = 0;

export function canAfford(cost: number) {
  if (!Number.isFinite(cost) || !Number.isFinite(balance)) {
    return false;
  }
  return cost <= balance;
}
