export function listen(trusted: string): void {
    window.addEventListener('message', (e) => {
        if (e.origin !== trusted) return;
        handle(e.data);
    });
}
