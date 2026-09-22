export class Comp {
    private node: any = null;

    init(): void {
        this.node = find('Root/Player');
    }

    update(dt: number): void {
        this.node.x += dt;
    }
}
