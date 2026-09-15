export function dispatch(name: string): void {
    handlers[name]();
}
