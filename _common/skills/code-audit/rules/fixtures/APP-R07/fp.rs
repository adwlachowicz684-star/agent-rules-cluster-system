pub fn poll(events: &EventQueue) {
    for _e in events.wait() {
        handle();
    }
}
