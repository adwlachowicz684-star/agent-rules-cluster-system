pub fn push(state: &Shared, v: u32) {
    let mut g = state.lock().unwrap_or_else(|e| e.into_inner());
    g.push(v);
}
