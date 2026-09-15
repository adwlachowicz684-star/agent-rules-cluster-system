const TABLE: Record<string, number> = { a: 1 };

export function get(k: string) {
  return TABLE[k];
}
