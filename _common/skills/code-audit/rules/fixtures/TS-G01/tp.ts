export class Bus {
    onChange: Function | null = null;

    subscribe(handler: Function): void {
        this.onChange = handler;
    }
}
