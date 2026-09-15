export function start(): number {
    const id = setInterval(tick, 1000);
    return id;
}

export function stop(): void {
    clearInterval(start());
}
