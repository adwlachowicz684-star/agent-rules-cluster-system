export function run(m: Mutex): void {
    m.lock();
    try {
        doWork();
    } finally {
        m.unlock();
    }
}
