use std::sync::Arc;

pub fn spawn_workers(v: String) {
    let shared = Arc::new(v);
    for _ in 0..4 {
        let c = shared.clone();
        std::thread::spawn(move || {
            println!("{}", c);
        });
    }
}
