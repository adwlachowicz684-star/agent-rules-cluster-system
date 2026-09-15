export function watch(bus: Bus): void {
    bus.on('tick', () => {
        step();
    });
}
