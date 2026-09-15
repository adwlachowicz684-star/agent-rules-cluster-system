export function apply(op: string, p: any) {
  switch (op) {
    case 'add':
      if (typeof value !== 'number') {
        return;
      }
      p.value += getValue(value);
      break;
  }
}
