export function run(m: Mutex): void {
    m.lock();
    doWork();
}
