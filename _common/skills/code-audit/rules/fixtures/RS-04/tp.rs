pub async fn tick(state: Arc<Mutex<Counter>>) {
    let mut g = state.lock().unwrap();
    fetch_remote().await;
    g.inc();
}
