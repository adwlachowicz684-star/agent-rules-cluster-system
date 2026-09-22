const TABLE: Record<string, number> = { a: 1 };

export function get(k: string) {
  if (!Object.prototype.hasOwnProperty.call(TABLE, k)) {
    return 0;
  }
  return TABLE[k];
}
