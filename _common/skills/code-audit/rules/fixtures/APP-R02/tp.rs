pub fn push(state: &Shared, v: u32) {
    let mut g = state.lock().unwrap();
    g.push(v);
}
