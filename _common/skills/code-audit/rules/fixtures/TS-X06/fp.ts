export class Comp {
    step(): void { }

    mount(bus: Bus): void {
        bus.on('tick', this.step);
    }

    unmount(bus: Bus): void {
        bus.off('tick', this.step);   // 成对注销
    }
}
