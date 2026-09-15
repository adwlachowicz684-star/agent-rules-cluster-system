export class Comp {
    step(): void { }

    mount(bus: Bus): void {
        bus.on('tick', this.step);
    }
}
