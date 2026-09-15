export function listen(): void {
    window.addEventListener('message', (e) => {
        handle(e.data);
    });
}
