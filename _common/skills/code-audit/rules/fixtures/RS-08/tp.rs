use std::rc::Rc;

pub fn spawn_workers(v: String) {
    let shared = Rc::new(v);
    for _ in 0..4 {
        let c = shared.clone();
        std::thread::spawn(move || {
            println!("{}", c);
        });
    }
}
