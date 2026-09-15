export function mount(el: HTMLElement): void {
    el.addEventListener('click', (e) => onData(e));
    el.removeEventListener('click', onData);
}
