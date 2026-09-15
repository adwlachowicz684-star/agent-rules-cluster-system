const ORIGIN = 'https://example.com';
export function broadcast(win: Window, payload: unknown): void {
    win.postMessage(payload, ORIGIN);
}
