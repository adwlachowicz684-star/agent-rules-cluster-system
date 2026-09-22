use std::thread;
use std::time::Duration;

pub fn poll() {
    loop {
        thread::sleep(Duration::from_millis(100));
    }
}
