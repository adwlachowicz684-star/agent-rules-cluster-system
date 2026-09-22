export class Bus {
    handlers: Function[] = [];

    subscribe(handler: Function): void {
        this.handlers.push(buildHandler(handler));
    }
}
