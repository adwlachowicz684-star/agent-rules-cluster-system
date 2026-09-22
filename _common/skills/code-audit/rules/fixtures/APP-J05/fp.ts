export function mount(el: HTMLElement): void {
    const h = (e: Event) => onData(e);
    el.addEventListener('click', h);
    el.removeEventListener('click', h);
}
