#[tauri::command]
pub async fn never_registered() -> String { String::new() }
