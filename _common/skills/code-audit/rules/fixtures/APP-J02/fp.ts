export function dispatch(name: string): void {
    handlers.run(name);
}
