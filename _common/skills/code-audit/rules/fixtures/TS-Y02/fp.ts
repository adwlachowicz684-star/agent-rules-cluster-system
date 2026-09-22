export class Comp {
    private out: number[] = [];

    update(dt: number): void {
        this.out.length = 0;
        for (const e of this.list) this.out.push(e);
    }
}
