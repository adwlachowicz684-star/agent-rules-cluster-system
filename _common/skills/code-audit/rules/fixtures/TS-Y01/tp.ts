export class Comp {
    update(dt: number): void {
        const node = find('Root/Player');
        node.x += dt;
    }
}
