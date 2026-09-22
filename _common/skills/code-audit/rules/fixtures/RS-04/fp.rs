pub async fn tick(state: Arc<tokio::sync::Mutex<Counter>>) {
    let mut g = state.lock().await;
    g.inc();
}
