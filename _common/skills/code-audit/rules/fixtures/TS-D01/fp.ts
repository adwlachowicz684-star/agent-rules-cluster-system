export interface Cfg {
  readonly usedField: number;
}

export function apply(c: Cfg) {
  return c.usedField;
}
